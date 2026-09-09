from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_user
from app.database import get_db
from app.models import Employee, Note
from app.schemas import EmployeeOut, NoteCreate, NoteOut, NotesUnreadCount
from app.ws_manager import manager

router = APIRouter(prefix="/api/notes", tags=["notes"])


def _load_note(db: Session, note_id: int) -> Note:
    return (
        db.query(Note)
        .options(joinedload(Note.sender), joinedload(Note.recipient))
        .filter(Note.id == note_id)
        .one()
    )


def _resolve_recipients(body: NoteCreate) -> list[int]:
    ids: list[int] = []
    if body.recipient_ids:
        ids.extend(body.recipient_ids)
    if body.recipient_id is not None:
        ids.append(body.recipient_id)
    # unique preserve order
    seen: set[int] = set()
    out: list[int] = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def _resolve_subject(body: NoteCreate) -> str:
    title = (body.title if body.title is not None else body.subject) or ""
    title = title.strip()
    return title or "(제목 없음)"


def _resolve_content(body: NoteCreate) -> str:
    raw = body.body if body.body is not None else body.content
    return (raw or "").strip()


async def _notify_note_received(recipient_id: int, note: Note, unread_count: int):
    payload = NoteOut.model_validate(note).model_dump(mode="json")
    await manager.notify_users(
        [recipient_id],
        {
            "type": "note",
            "action": "received",
            "unread_count": unread_count,
            "data": payload,
        },
    )


async def _notify_note_read(user_id: int, note: Note, unread_count: int):
    payload = NoteOut.model_validate(note).model_dump(mode="json")
    await manager.notify_users(
        [user_id],
        {
            "type": "note",
            "action": "read",
            "unread_count": unread_count,
            "data": payload,
        },
    )



def _batch_recipient_employees(db: Session, note: Note) -> list[Employee]:
    """Find co-recipients of the same multi-send batch (same sender/subject/content ~time)."""
    window_start = note.created_at - timedelta(seconds=3)
    window_end = note.created_at + timedelta(seconds=3)
    peers = (
        db.query(Note)
        .options(joinedload(Note.recipient))
        .filter(
            Note.sender_id == note.sender_id,
            Note.subject == note.subject,
            Note.content == note.content,
            Note.created_at >= window_start,
            Note.created_at <= window_end,
        )
        .all()
    )
    seen: set[int] = set()
    out: list[Employee] = []
    for peer in peers:
        r = peer.recipient
        if r is None or r.id in seen:
            continue
        seen.add(r.id)
        out.append(r)
    if not out and note.recipient is not None:
        out.append(note.recipient)
    return out


def _note_out_with_recipients(db: Session, note: Note) -> NoteOut:
    payload = NoteOut.model_validate(note)
    payload.recipients = [
        EmployeeOut.model_validate(e) for e in _batch_recipient_employees(db, note)
    ]
    return payload


def _unread_count_for(db: Session, user_id: int) -> int:
    return (
        db.query(Note)
        .filter(Note.recipient_id == user_id, Note.is_read.is_(False))
        .count()
    )


def _mark_note_read(db: Session, note: Note) -> bool:
    """Mark as read; return True if state changed."""
    if note.is_read:
        return False
    note.is_read = True
    note.read_at = datetime.utcnow()
    return True


@router.get("/inbox", response_model=list[NoteOut])
def inbox(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Employee, Depends(get_current_user)],
):
    return (
        db.query(Note)
        .options(joinedload(Note.sender), joinedload(Note.recipient))
        .filter(Note.recipient_id == current_user.id)
        .order_by(Note.created_at.desc())
        .all()
    )


@router.get("/sent", response_model=list[NoteOut])
def sent(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Employee, Depends(get_current_user)],
):
    return (
        db.query(Note)
        .options(joinedload(Note.sender), joinedload(Note.recipient))
        .filter(Note.sender_id == current_user.id)
        .order_by(Note.created_at.desc())
        .all()
    )


@router.get("/unread-count", response_model=NotesUnreadCount)
def unread_count(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Employee, Depends(get_current_user)],
):
    return NotesUnreadCount(count=_unread_count_for(db, current_user.id))


@router.get("/{note_id}", response_model=NoteOut)
async def get_note(
    note_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Employee, Depends(get_current_user)],
):
    """Open note detail. Recipient opening marks it as read."""
    note = (
        db.query(Note)
        .options(joinedload(Note.sender), joinedload(Note.recipient))
        .filter(Note.id == note_id)
        .first()
    )
    if not note:
        raise HTTPException(status_code=404, detail="쪽지를 찾을 수 없습니다")
    if note.recipient_id != current_user.id and note.sender_id != current_user.id:
        raise HTTPException(status_code=403, detail="쪽지를 볼 권한이 없습니다")

    if note.recipient_id == current_user.id and _mark_note_read(db, note):
        db.commit()
        note = _load_note(db, note.id)
        count = _unread_count_for(db, current_user.id)
        await _notify_note_read(current_user.id, note, count)
    return _note_out_with_recipients(db, note)


@router.post("", response_model=list[NoteOut])
async def send_note(
    body: NoteCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Employee, Depends(get_current_user)],
):
    recipient_ids = _resolve_recipients(body)
    if not recipient_ids:
        raise HTTPException(status_code=400, detail="수신자를 선택하세요")
    content = _resolve_content(body)
    if not content:
        raise HTTPException(status_code=400, detail="쪽지 내용이 비어 있습니다")
    subject = _resolve_subject(body)

    emp_map = {
        e.id: e
        for e in db.query(Employee).filter(Employee.id.in_(recipient_ids)).all()
    }
    created_ids: list[int] = []
    for rid in recipient_ids:
        recipient = emp_map.get(rid)
        if not recipient or recipient.is_bot:
            raise HTTPException(status_code=404, detail="수신자를 찾을 수 없습니다")
        if rid == current_user.id:
            raise HTTPException(status_code=400, detail="본인에게는 쪽지를 보낼 수 없습니다")
        note = Note(
            sender_id=current_user.id,
            recipient_id=rid,
            subject=subject,
            content=content,
        )
        db.add(note)
        db.flush()
        created_ids.append(note.id)

    db.commit()

    results: list[Note] = []
    for nid in created_ids:
        note = _load_note(db, nid)
        results.append(note)
        count = _unread_count_for(db, note.recipient_id)
        await _notify_note_received(note.recipient_id, note, count)

    return results


@router.post("/{note_id}/read", response_model=NoteOut)
async def mark_read(
    note_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Employee, Depends(get_current_user)],
):
    note = (
        db.query(Note)
        .filter(Note.id == note_id, Note.recipient_id == current_user.id)
        .first()
    )
    if not note:
        raise HTTPException(status_code=404, detail="쪽지를 찾을 수 없습니다")
    if _mark_note_read(db, note):
        db.commit()
    note = _load_note(db, note.id)
    count = _unread_count_for(db, current_user.id)
    await _notify_note_read(current_user.id, note, count)
    return note
