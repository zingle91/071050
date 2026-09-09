from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_user
from app.database import get_db
from app.models import Employee, Note
from app.schemas import NoteCreate, NoteOut

router = APIRouter(prefix="/api/notes", tags=["notes"])


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


@router.post("", response_model=NoteOut)
def send_note(
    body: NoteCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Employee, Depends(get_current_user)],
):
    recipient = db.query(Employee).filter(Employee.id == body.recipient_id).first()
    if not recipient or recipient.is_bot:
        raise HTTPException(status_code=404, detail="수신자를 찾을 수 없습니다")
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="쪽지 내용이 비어 있습니다")
    note = Note(
        sender_id=current_user.id,
        recipient_id=body.recipient_id,
        subject=body.subject or "(제목 없음)",
        content=body.content.strip(),
    )
    db.add(note)
    db.commit()
    return (
        db.query(Note)
        .options(joinedload(Note.sender), joinedload(Note.recipient))
        .filter(Note.id == note.id)
        .one()
    )


@router.post("/{note_id}/read", response_model=NoteOut)
def mark_read(
    note_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Employee, Depends(get_current_user)],
):
    note = db.query(Note).filter(Note.id == note_id, Note.recipient_id == current_user.id).first()
    if not note:
        raise HTTPException(status_code=404, detail="쪽지를 찾을 수 없습니다")
    note.is_read = True
    db.commit()
    return (
        db.query(Note)
        .options(joinedload(Note.sender), joinedload(Note.recipient))
        .filter(Note.id == note.id)
        .one()
    )
