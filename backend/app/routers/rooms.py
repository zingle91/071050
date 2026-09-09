"""Room/membership/message API with soft-leave and system notifications."""
import re
import uuid
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_user
from app.database import SessionLocal, get_db
from app.models import Employee, Room, RoomMember, Message
from app.schemas import (
    RoomCreate,
    RoomOut,
    RoomMemberOut,
    MessageCreate,
    MessageOut,
    InviteBotRequest,
    RoomInviteRequest,
    RoomDisplayNameUpdate,
    UnreadUserOut,
    RoomKickRequest,
)

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


def _has_batchim(name: str) -> bool:
    if not name:
        return False
    ch = name[-1]
    code = ord(ch)
    if 0xAC00 <= code <= 0xD7A3:
        return (code - 0xAC00) % 28 != 0
    return False


def _iga(name: str) -> str:
    """name + 이/가"""
    return f"{name}{'이' if _has_batchim(name) else '가'}"


def _eulreul(name: str) -> str:
    """name + 을/를"""
    return f"{name}{'을' if _has_batchim(name) else '를'}"


def _user_room_ids(db: Session, user_id: int) -> set[int]:
    """Rooms the user still has a membership row for (active or soft-left)."""
    rows = db.query(RoomMember.room_id).filter(RoomMember.employee_id == user_id).all()
    return {r[0] for r in rows}


def _membership(db: Session, room_id: int, user_id: int) -> RoomMember | None:
    return (
        db.query(RoomMember)
        .filter(RoomMember.room_id == room_id, RoomMember.employee_id == user_id)
        .first()
    )


def _active_membership(db: Session, room_id: int, user_id: int) -> RoomMember | None:
    m = _membership(db, room_id, user_id)
    if m and m.status == "active":
        return m
    return None


def _unread_count(db: Session, room_id: int, user_id: int, last_read_at: datetime | None) -> int:
    q = db.query(func.count(Message.id)).filter(
        Message.room_id == room_id,
        Message.sender_id != user_id,
        Message.is_system == False,  # noqa: E712
    )
    if last_read_at is not None:
        q = q.filter(Message.created_at > last_read_at)
    return int(q.scalar() or 0)


def _batch_unread_counts(
    db: Session, user_id: int, room_ids: set[int] | list[int]
) -> dict[int, int]:
    """One GROUP BY room_id unread query for a user's rooms (avoids N+1 on list)."""
    if not room_ids:
        return {}
    rows = (
        db.query(Message.room_id, func.count(Message.id))
        .join(
            RoomMember,
            and_(
                RoomMember.room_id == Message.room_id,
                RoomMember.employee_id == user_id,
                RoomMember.status == "active",
            ),
        )
        .filter(
            Message.room_id.in_(list(room_ids)),
            Message.sender_id != user_id,
            Message.is_system == False,  # noqa: E712
            or_(
                RoomMember.last_read_at.is_(None),
                Message.created_at > RoomMember.last_read_at,
            ),
        )
        .group_by(Message.room_id)
        .all()
    )
    return {int(rid): int(cnt) for rid, cnt in rows}


def _advance_last_read(db: Session, membership: RoomMember, room_id: int) -> datetime:
    """Advance last_read_at monotonically to cover all messages currently in the room.

    Never rewinds (concurrent mark-read / send races). Uses max(now, latest message)
    so a mark-read that lands just after an insert still clears that message.
    """
    latest = (
        db.query(func.max(Message.created_at))
        .filter(Message.room_id == room_id)
        .scalar()
    )
    now = datetime.utcnow()
    stamp = now if latest is None else max(now, latest)
    prev = membership.last_read_at
    if prev is None or stamp > prev:
        membership.last_read_at = stamp
    return membership.last_read_at  # type: ignore[return-value]


def _load_room_members(db: Session, room_id: int, *, active_only: bool = True) -> list[RoomMember]:
    q = (
        db.query(RoomMember)
        .options(joinedload(RoomMember.employee))
        .filter(RoomMember.room_id == room_id)
    )
    if active_only:
        q = q.filter(RoomMember.status == "active")
    return q.all()


def _member_has_read(member: RoomMember, msg: Message) -> bool:
    """Read only if last_read_at is set and >= message time. NULL = never accessed = unread."""
    if member.last_read_at is None:
        return False
    return member.last_read_at >= msg.created_at


def _iter_unreader_members(members: list[RoomMember], msg: Message) -> list[RoomMember]:
    """Active non-bot members except sender who have not read msg."""
    out: list[RoomMember] = []
    for m in members:
        if getattr(m, "status", "active") != "active":
            continue
        if m.employee_id == msg.sender_id:
            continue
        emp = m.employee
        if emp is not None and emp.is_bot:
            continue
        if _member_has_read(m, msg):
            continue
        out.append(m)
    return out


def _message_unread_count(members: list[RoomMember], msg: Message) -> int:
    if msg.is_system:
        return 0
    return len(_iter_unreader_members(members, msg))


def _employees_by_ids(db: Session, ids: set[int] | list[int]) -> dict[int, Employee]:
    """Single IN query → id→Employee map (create_room / invite / notes)."""
    id_list = list({i for i in ids if i is not None})
    if not id_list:
        return {}
    rows = db.query(Employee).filter(Employee.id.in_(id_list)).all()
    return {e.id: e for e in rows}


def _emp_names_map(db: Session, ids: set[int] | list[int]) -> dict[int, str]:
    """Preload id→name for system-message rendering (no per-call DB)."""
    return {eid: emp.name for eid, emp in _employees_by_ids(db, ids).items()}


def _name_from_map(names: dict[int, str], emp_id: int | None) -> str:
    if not emp_id:
        return "누군가"
    return names.get(emp_id, "누군가")


def _render_system_content(msg: Message, viewer_id: int, names: dict[int, str]) -> str:
    """Personalize system notification text for the viewing user (map only)."""
    actor_name = _name_from_map(names, msg.system_actor_id)
    target_name = _name_from_map(names, msg.system_target_id)
    event = msg.system_event or ""
    if event == "leave":
        if msg.system_actor_id == viewer_id:
            return "당신은 나갔습니다."
        return f"{_iga(actor_name)} 나갔습니다."
    if event == "kick":
        if msg.system_target_id == viewer_id:
            return f"{_iga(actor_name)} 당신을 내보냈습니다."
        return f"{_iga(actor_name)} {_eulreul(target_name)} 내보냈습니다."
    return msg.content


def _system_name_ids(*msgs: Message) -> set[int]:
    ids: set[int] = set()
    for msg in msgs:
        if not msg or not msg.is_system:
            continue
        if msg.system_actor_id:
            ids.add(msg.system_actor_id)
        if msg.system_target_id:
            ids.add(msg.system_target_id)
    return ids


def _message_out(
    msg: Message,
    members: list[RoomMember],
    viewer_id: int | None = None,
    db: Session | None = None,
    name_map: dict[int, str] | None = None,
) -> MessageOut:
    base = MessageOut.model_validate(msg)
    content = msg.content
    if msg.is_system and viewer_id is not None:
        names = name_map
        if names is None and db is not None:
            names = _emp_names_map(db, _system_name_ids(msg))
        content = _render_system_content(msg, viewer_id, names or {})
    return base.model_copy(
        update={
            "content": content,
            "unread_count": _message_unread_count(members, msg),
            "is_system": bool(msg.is_system),
            "system_event": msg.system_event,
            "system_actor_id": msg.system_actor_id,
            "system_target_id": msg.system_target_id,
        }
    )


def _room_out(
    room: Room,
    user_id: int,
    db: Session,
    last_message_at: datetime | None = None,
    unread_count: int | None = None,
) -> RoomOut:
    membership = next((m for m in room.members if m.employee_id == user_id), None)
    display_name = membership.display_name if membership else None
    status = (membership.status if membership else "active") or "active"
    left_at = membership.left_at if membership else None
    # Only active members appear in the participant list
    active_members = [m for m in room.members if (m.status or "active") == "active"]
    unread = 0
    if membership and status == "active":
        if unread_count is not None:
            unread = unread_count
        else:
            unread = _unread_count(db, room.id, user_id, membership.last_read_at)
    if last_message_at is None:
        last_message_at = (
            db.query(func.max(Message.created_at))
            .filter(Message.room_id == room.id)
            .scalar()
        )
    return RoomOut(
        id=room.id,
        public_id=room.public_id,
        name=room.name,
        room_type=room.room_type,
        created_at=room.created_at,
        members=[RoomMemberOut.model_validate(m) for m in active_members],
        display_name=display_name,
        unread_count=unread,
        membership_status=status,
        left_at=left_at,
        last_message_at=last_message_at or room.created_at,
    )


def _load_room(db: Session, room_id: int) -> Room:
    return (
        db.query(Room)
        .options(
            joinedload(Room.members).joinedload(RoomMember.employee).joinedload(Employee.department)
        )
        .filter(Room.id == room_id)
        .one()
    )


def _soft_remove(membership: RoomMember, status: str, removed_by_id: int | None) -> None:
    membership.status = status
    membership.left_at = datetime.utcnow()
    membership.removed_by_id = removed_by_id


def _create_system_message(
    db: Session,
    room_id: int,
    *,
    sender_id: int,
    event: str,
    actor_id: int,
    target_id: int | None,
    public_content: str,
) -> Message:
    msg = Message(
        room_id=room_id,
        sender_id=sender_id,
        content=public_content,
        is_system=True,
        system_event=event,
        system_actor_id=actor_id,
        system_target_id=target_id,
    )
    db.add(msg)
    db.flush()
    return msg


async def _broadcast_read_update(
    db: Session, room_id: int, user_id: int, last_read_at: datetime
):
    """Notify room members that a peer marked messages as read (live unread digits)."""
    from app.ws_manager import manager

    event = {
        "type": "read_update",
        "room_id": room_id,
        "user_id": user_id,
        "last_read_at": last_read_at.isoformat() if last_read_at else None,
    }
    member_ids = [
        m.employee_id
        for m in db.query(RoomMember)
        .filter(RoomMember.room_id == room_id, RoomMember.status == "active")
        .all()
    ]
    if member_ids:
        await manager.notify_users(member_ids, event)


async def _broadcast_membership_change(
    room_id: int,
    action: str,
    actor_id: int,
    removed_ids: list[int],
    notify_user_ids: list[int],
    room_payload: dict | None = None,
    removed_room_payloads: dict[int, dict] | None = None,
    system_messages: list[dict] | None = None,
):
    """Notify sidebars of leave/kick. Soft-left users keep the room in a left state."""
    from app.ws_manager import manager

    event = {
        "type": "membership_change",
        "room_id": room_id,
        "action": action,  # leave | kick
        "actor_id": actor_id,
        "removed_ids": removed_ids,
        "room": room_payload,
        "removed_rooms": removed_room_payloads or {},
        "system_messages": system_messages or [],
    }
    targets = list({*notify_user_ids, *removed_ids})
    if targets:
        await manager.notify_users(targets, event)


async def _broadcast_system_messages(
    db: Session,
    room_id: int,
    msgs: list[Message],
    notify_user_ids: list[int],
):
    """Send system messages personalized per recipient (including soft-left users)."""
    from app.ws_manager import manager

    active_members = _load_room_members(db, room_id, active_only=True)
    name_map = _emp_names_map(db, _system_name_ids(*msgs))
    deliveries: list[tuple[int, dict]] = []
    for uid in notify_user_ids:
        for msg in msgs:
            payload = _message_out(
                msg, active_members, viewer_id=uid, name_map=name_map
            ).model_dump(mode="json")
            deliveries.append(
                (
                    uid,
                    {
                        "type": "message",
                        "room_id": room_id,
                        "unread_delta": 0,
                        "data": payload,
                    },
                )
            )
    await manager.notify_personalized(deliveries)


async def _broadcast_new_message(db: Session, room_id: int, msg: Message, sender_id: int):
    """Fan-out via /ws/user only (active members; left/kicked get no new chat traffic)."""
    from app.ws_manager import manager

    members = _load_room_members(db, room_id, active_only=True)
    member_ids = [m.employee_id for m in members]
    if not member_ids:
        return

    name_map = _emp_names_map(db, _system_name_ids(msg)) if msg.is_system else {}
    deliveries: list[tuple[int, dict]] = []
    if msg.is_system:
        for uid in member_ids:
            personalized = _message_out(
                msg, members, viewer_id=uid, name_map=name_map
            ).model_dump(mode="json")
            deliveries.append(
                (
                    uid,
                    {
                        "type": "message",
                        "room_id": room_id,
                        "unread_delta": 0,
                        "data": personalized,
                    },
                )
            )
    else:
        # Shared payload; per-user unread_delta (0 for sender)
        payload = _message_out(
            msg, members, viewer_id=sender_id, name_map=name_map
        ).model_dump(mode="json")
        for uid in member_ids:
            deliveries.append(
                (
                    uid,
                    {
                        "type": "message",
                        "room_id": room_id,
                        "unread_delta": 0 if uid == sender_id else 1,
                        "data": payload,
                    },
                )
            )
    await manager.notify_personalized(deliveries)


@router.get("", response_model=list[RoomOut])
def list_rooms(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Employee, Depends(get_current_user)],
):
    room_ids = _user_room_ids(db, current_user.id)
    if not room_ids:
        return []
    last_msg_sq = (
        db.query(
            Message.room_id.label("room_id"),
            func.max(Message.created_at).label("last_at"),
        )
        .group_by(Message.room_id)
        .subquery()
    )
    rows = (
        db.query(Room, last_msg_sq.c.last_at)
        .outerjoin(last_msg_sq, Room.id == last_msg_sq.c.room_id)
        .options(
            joinedload(Room.members)
            .joinedload(RoomMember.employee)
            .joinedload(Employee.department)
        )
        .filter(Room.id.in_(room_ids))
        .order_by(func.coalesce(last_msg_sq.c.last_at, Room.created_at).desc())
        .all()
    )
    unread_map = _batch_unread_counts(db, current_user.id, room_ids)
    return [
        _room_out(
            room,
            current_user.id,
            db,
            last_message_at=last_at,
            unread_count=unread_map.get(room.id, 0),
        )
        for room, last_at in rows
    ]


@router.post("", response_model=RoomOut)
def create_room(
    body: RoomCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Employee, Depends(get_current_user)],
):
    if body.room_type not in ("direct", "group"):
        raise HTTPException(status_code=400, detail="room_type은 direct 또는 group 이어야 합니다")

    member_ids = set(body.member_ids)
    member_ids.add(current_user.id)

    if body.room_type == "direct":
        if len(member_ids) != 2:
            raise HTTPException(status_code=400, detail="1:1 채팅은 상대 1명만 지정하세요")
        other_id = next(i for i in member_ids if i != current_user.id)
        existing = (
            db.query(Room)
            .options(joinedload(Room.members))
            .filter(Room.room_type == "direct")
            .all()
        )
        for room in existing:
            ids = {m.employee_id for m in room.members}
            if ids == member_ids:
                # Reactivate soft-left memberships if reopening DM
                for m in room.members:
                    if m.employee_id in member_ids and m.status != "active":
                        m.status = "active"
                        m.left_at = None
                        m.removed_by_id = None
                db.commit()
                return _room_out(_load_room(db, room.id), current_user.id, db)
        emps = _employees_by_ids(db, member_ids)
        other = emps.get(other_id)
        name = f"{current_user.name} ↔ {other.name if other else other_id}"
    else:
        # Group display names are NOT unique. Identity is Room.public_id (UUID).
        # Duplicate names are allowed; clients/joins that need a stable id must use public_id.
        name = body.name or "그룹 채팅"
        emps = _employees_by_ids(db, member_ids)

    room = Room(
        name=name,
        room_type=body.room_type,
        created_by=current_user.id,
        public_id=str(uuid.uuid4()),
    )
    db.add(room)
    db.flush()
    for mid in member_ids:
        if mid not in emps:
            raise HTTPException(status_code=400, detail=f"존재하지 않는 직원 id: {mid}")
        db.add(
            RoomMember(
                room_id=room.id,
                employee_id=mid,
                last_read_at=None,
                status="active",
            )
        )
    db.commit()
    return _room_out(_load_room(db, room.id), current_user.id, db)


@router.patch("/{room_id}/display-name", response_model=RoomOut)
def update_display_name(
    room_id: int,
    body: RoomDisplayNameUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Employee, Depends(get_current_user)],
):
    membership = _membership(db, room_id, current_user.id)
    if not membership:
        raise HTTPException(status_code=403, detail="해당 채팅방 권한이 없습니다")
    raw = body.display_name
    if raw is None or not str(raw).strip():
        membership.display_name = None
    else:
        membership.display_name = str(raw).strip()[:200]
    db.commit()
    return _room_out(_load_room(db, room_id), current_user.id, db)


@router.post("/{room_id}/read", response_model=RoomOut)
async def mark_room_read(
    room_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Employee, Depends(get_current_user)],
):
    membership = _membership(db, room_id, current_user.id)
    if not membership:
        raise HTTPException(status_code=403, detail="해당 채팅방 권한이 없습니다")
    # Soft-left users may view history but should not affect others' unread.
    # Monotonic advance covers concurrent inserts and overlapping mark-read calls.
    _advance_last_read(db, membership, room_id)
    db.commit()
    db.refresh(membership)
    if membership.status == "active" and membership.last_read_at is not None:
        await _broadcast_read_update(db, room_id, current_user.id, membership.last_read_at)
    return _room_out(_load_room(db, room_id), current_user.id, db)


@router.get("/{room_id}/messages", response_model=list[MessageOut])
def list_messages(
    room_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Employee, Depends(get_current_user)],
):
    if room_id not in _user_room_ids(db, current_user.id):
        raise HTTPException(status_code=403, detail="해당 채팅방 권한이 없습니다")
    members = _load_room_members(db, room_id, active_only=True)
    msgs = (
        db.query(Message)
        .options(joinedload(Message.sender))
        .filter(Message.room_id == room_id)
        .order_by(Message.created_at.asc())
        .limit(500)
        .all()
    )
    name_map = _emp_names_map(db, _system_name_ids(*msgs))
    return [
        _message_out(m, members, viewer_id=current_user.id, name_map=name_map)
        for m in msgs
    ]


@router.get(
    "/{room_id}/messages/{msg_id}/unreaders",
    response_model=list[UnreadUserOut],
)
def list_unreaders(
    room_id: int,
    msg_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Employee, Depends(get_current_user)],
):
    """People who have not yet read this message (for the unread-count popup)."""
    membership = _membership(db, room_id, current_user.id)
    if not membership:
        raise HTTPException(status_code=403, detail="해당 채팅방 권한이 없습니다")
    msg = (
        db.query(Message)
        .filter(Message.id == msg_id, Message.room_id == room_id)
        .first()
    )
    if not msg:
        raise HTTPException(status_code=404, detail="메시지를 찾을 수 없습니다")
    members = _load_room_members(db, room_id, active_only=True)
    unreaders = _iter_unreader_members(members, msg)
    result: list[UnreadUserOut] = []
    for m in unreaders:
        emp = m.employee
        if not emp:
            continue
        result.append(
            UnreadUserOut(
                id=emp.id,
                employee_id=emp.employee_id,
                name=emp.name,
                is_bot=bool(emp.is_bot),
            )
        )
    return result



# Chat message content limits / light hardening (never auto-append room history)
_MESSAGE_MAX_LEN = 4000
_DEDUPE_WINDOW_SEC = 3
# Reject note-style multi-speaker history dumps pasted as a single chat message
_HISTORY_DUMP_RE = re.compile(
    r"(?m)^\s*-\s*.{0,40}:\s+.+$",
)


def _normalize_message_content(raw: str) -> str:
    """Store only the intended utterance: trim; do not prefix room history."""
    content = (raw or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="메시지 내용이 비어 있습니다")
    if len(content) > _MESSAGE_MAX_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"메시지는 {_MESSAGE_MAX_LEN}자를 넘을 수 없습니다",
        )
    # Note-summary dumps: several "- role: text" lines → reject (do not silently mash)
    hist_lines = _HISTORY_DUMP_RE.findall(content)
    if len(hist_lines) >= 3:
        raise HTTPException(
            status_code=400,
            detail="채팅 메시지에 대화 이력 요약 형식을 넣을 수 없습니다. 한 문장/한 발화만 전송하세요",
        )
    return content


def _find_by_client_message_id(
    db: Session, room_id: int, sender_id: int, client_message_id: str
) -> Message | None:
    return (
        db.query(Message)
        .options(joinedload(Message.sender))
        .filter(
            Message.room_id == room_id,
            Message.sender_id == sender_id,
            Message.client_message_id == client_message_id,
        )
        .first()
    )


def _find_recent_duplicate(
    db: Session, room_id: int, sender_id: int, content: str, window_sec: int = _DEDUPE_WINDOW_SEC
) -> Message | None:
    """Same sender+room+identical body within a short window (retry / double-submit)."""
    since = datetime.utcnow() - timedelta(seconds=window_sec)
    return (
        db.query(Message)
        .options(joinedload(Message.sender))
        .filter(
            Message.room_id == room_id,
            Message.sender_id == sender_id,
            Message.content == content,
            Message.is_system == False,  # noqa: E712
            Message.created_at >= since,
        )
        .order_by(Message.created_at.desc())
        .first()
    )


async def _generate_and_persist_bot_reply(
    room_id: int,
    bot_id: int,
    user_content: str,
    room_name: str,
) -> None:
    """Await LLM without a request-scoped DB session; persist with SessionLocal."""
    from app.llm import generate_reply

    try:
        reply_text = await generate_reply(user_content, room_name)
    except Exception:
        return

    db = SessionLocal()
    try:
        bot_msg = Message(room_id=room_id, sender_id=bot_id, content=reply_text)
        db.add(bot_msg)
        db.commit()
        bot_msg = (
            db.query(Message)
            .options(joinedload(Message.sender))
            .filter(Message.id == bot_msg.id)
            .one()
        )
        await _broadcast_new_message(db, room_id, bot_msg, bot_id)
    except Exception:
        db.rollback()
    finally:
        db.close()


@router.post("/{room_id}/messages", response_model=MessageOut)
async def post_message(
    room_id: int,
    body: MessageCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Employee, Depends(get_current_user)],
    background_tasks: BackgroundTasks,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    """Create a chat message.

    Stores only the request content/body string (trimmed). Never appends room
    history or other users' utterances. Supports idempotency via
    ``client_message_id`` / ``Idempotency-Key`` and a short identical-body window.
    Bot LLM replies run in a background task with a fresh DB session so the
    request-scoped session is not held open across the LLM await.
    """
    membership = _active_membership(db, room_id, current_user.id)
    if not membership:
        # Distinguish soft-left vs never a member
        any_m = _membership(db, room_id, current_user.id)
        if any_m:
            raise HTTPException(status_code=403, detail="이미 나간 채팅방에서는 메시지를 보낼 수 없습니다")
        raise HTTPException(status_code=403, detail="해당 채팅방 권한이 없습니다")

    content = _normalize_message_content(body.resolved_content())
    client_key = (body.client_message_id or idempotency_key or "").strip() or None
    if client_key and len(client_key) > 64:
        raise HTTPException(status_code=400, detail="client_message_id / Idempotency-Key는 64자 이하여야 합니다")

    members = _load_room_members(db, room_id, active_only=True)

    # 1) Explicit idempotency key → return existing row
    if client_key:
        existing = _find_by_client_message_id(db, room_id, current_user.id, client_key)
        if existing:
            return _message_out(existing, members, viewer_id=current_user.id, db=db)

    # 2) Short-window dedupe (retry / double-click without a key)
    dup = _find_recent_duplicate(db, room_id, current_user.id, content)
    if dup:
        return _message_out(dup, members, viewer_id=current_user.id, db=db)

    msg = Message(
        room_id=room_id,
        sender_id=current_user.id,
        content=content,  # exact intended string only — no history concat
        client_message_id=client_key,
    )
    db.add(msg)
    db.flush()  # assign msg.created_at before advancing read cursor
    _advance_last_read(db, membership, room_id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Concurrent retry with same client_message_id
        if client_key:
            existing = _find_by_client_message_id(db, room_id, current_user.id, client_key)
            if existing:
                return _message_out(existing, members, viewer_id=current_user.id, db=db)
        dup = _find_recent_duplicate(db, room_id, current_user.id, content, window_sec=10)
        if dup:
            return _message_out(dup, members, viewer_id=current_user.id, db=db)
        raise HTTPException(status_code=409, detail="메시지 저장 충돌이 발생했습니다. 다시 시도하세요")

    db.refresh(msg)
    msg = (
        db.query(Message)
        .options(joinedload(Message.sender))
        .filter(Message.id == msg.id)
        .one()
    )
    await _broadcast_new_message(db, room_id, msg, current_user.id)
    await _broadcast_read_update(db, room_id, current_user.id, membership.last_read_at)

    schedule_bot_reply = False
    bot_id: int | None = None
    room_name = ""
    bot = db.query(Employee).filter(Employee.is_bot == True).first()  # noqa: E712
    if bot:
        bot_in_room = (
            db.query(RoomMember)
            .filter(
                RoomMember.room_id == room_id,
                RoomMember.employee_id == bot.id,
                RoomMember.status == "active",
            )
            .first()
        )
        should_reply = bot_in_room and (
            "@AI" in content or "@ai" in content or "AI 도우미" in content or content.startswith("?")
        )
        if should_reply and current_user.id != bot.id:
            room = db.query(Room).filter(Room.id == room_id).first()
            schedule_bot_reply = True
            bot_id = bot.id
            room_name = room.name if room else ""

    members = _load_room_members(db, room_id, active_only=True)
    out = _message_out(msg, members, viewer_id=current_user.id, db=db)

    if schedule_bot_reply and bot_id is not None:
        # Do not await LLM on the request session; persist reply with SessionLocal.
        background_tasks.add_task(
            _generate_and_persist_bot_reply,
            room_id,
            bot_id,
            content,
            room_name,
        )

    return out


@router.post("/{room_id}/members", response_model=RoomOut)
def invite_members(
    room_id: int,
    body: RoomInviteRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Employee, Depends(get_current_user)],
):
    if not _active_membership(db, room_id, current_user.id):
        raise HTTPException(status_code=403, detail="해당 채팅방 권한이 없습니다")
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="채팅방을 찾을 수 없습니다")
    if room.room_type == "direct":
        raise HTTPException(status_code=400, detail="1:1 채팅에는 멤버를 추가할 수 없습니다")
    if not body.member_ids:
        raise HTTPException(status_code=400, detail="초대할 직원을 선택하세요")

    existing = {
        m.employee_id: m
        for m in db.query(RoomMember).filter(RoomMember.room_id == room_id).all()
    }
    emp_map = {
        e.id: e
        for e in db.query(Employee)
        .filter(Employee.id.in_(list(body.member_ids)), Employee.is_active == True)  # noqa: E712
        .all()
    }
    for mid in body.member_ids:
        emp = emp_map.get(mid)
        if not emp:
            raise HTTPException(status_code=400, detail=f"존재하지 않는 직원 id: {mid}")
        prev = existing.get(mid)
        if prev:
            if prev.status != "active":
                prev.status = "active"
                prev.left_at = None
                prev.removed_by_id = None
                prev.joined_at = datetime.utcnow()
                prev.last_read_at = None
            continue
        db.add(RoomMember(room_id=room_id, employee_id=mid, last_read_at=None, status="active"))
    db.commit()
    return _room_out(_load_room(db, room_id), current_user.id, db)


@router.post("/{room_id}/leave", response_model=RoomOut)
async def leave_room(
    room_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Employee, Depends(get_current_user)],
):
    """Soft-leave: keep membership + history; append system notification."""
    membership = _active_membership(db, room_id, current_user.id)
    if not membership:
        raise HTTPException(status_code=403, detail="해당 채팅방 권한이 없습니다")

    before = (
        db.query(RoomMember).filter(RoomMember.room_id == room_id).all()
    )
    notify_ids = [m.employee_id for m in before]

    _soft_remove(membership, "left", current_user.id)
    public = f"{_iga(current_user.name)} 나갔습니다."
    sys_msg = _create_system_message(
        db,
        room_id,
        sender_id=current_user.id,
        event="leave",
        actor_id=current_user.id,
        target_id=current_user.id,
        public_content=public,
    )
    db.commit()

    sys_msg = (
        db.query(Message)
        .options(joinedload(Message.sender))
        .filter(Message.id == sys_msg.id)
        .one()
    )

    room = _load_room(db, room_id)
    leaver_out = _room_out(room, current_user.id, db)
    remaining_active = [m for m in room.members if m.status == "active"]
    room_payload = None
    if remaining_active:
        room_payload = _room_out(room, remaining_active[0].employee_id, db).model_dump(mode="json")

    active_members = _load_room_members(db, room_id, active_only=True)
    leave_names = _emp_names_map(db, _system_name_ids(sys_msg))
    sys_payloads = [
        _message_out(sys_msg, active_members, viewer_id=uid, name_map=leave_names).model_dump(
            mode="json"
        )
        for uid in notify_ids
    ]

    await _broadcast_system_messages(db, room_id, [sys_msg], notify_ids)
    await _broadcast_membership_change(
        room_id=room_id,
        action="leave",
        actor_id=current_user.id,
        removed_ids=[current_user.id],
        notify_user_ids=notify_ids,
        room_payload=room_payload,
        removed_room_payloads={current_user.id: leaver_out.model_dump(mode="json")},
        system_messages=sys_payloads[:1],  # public-ish; clients also get personalized WS message
    )
    return leaver_out


@router.post("/{room_id}/kick", response_model=RoomOut)
async def kick_members(
    room_id: int,
    body: RoomKickRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Employee, Depends(get_current_user)],
):
    """Soft-kick members. MVP: any active non-bot member may kick others (not self)."""
    if current_user.is_bot:
        raise HTTPException(status_code=403, detail="봇은 멤버를 내보낼 수 없습니다")
    membership = _active_membership(db, room_id, current_user.id)
    if not membership:
        raise HTTPException(status_code=403, detail="해당 채팅방 권한이 없습니다")
    if not body.member_ids:
        raise HTTPException(status_code=400, detail="내보낼 멤버를 선택하세요")

    kick_ids = list(dict.fromkeys(body.member_ids))
    if current_user.id in kick_ids:
        raise HTTPException(status_code=400, detail="자신은 내보내기로 제거할 수 없습니다. 나가기를 사용하세요")

    before = _load_room_members(db, room_id, active_only=False)
    notify_ids = [m.employee_id for m in before]
    existing = {m.employee_id: m for m in before if m.status == "active"}

    removed: list[int] = []
    sys_msgs: list[Message] = []
    for mid in kick_ids:
        target = existing.get(mid)
        if not target:
            raise HTTPException(status_code=400, detail=f"채팅방에 없는 멤버 id: {mid}")
        target_emp = target.employee or db.query(Employee).filter(Employee.id == mid).first()
        target_name = target_emp.name if target_emp else str(mid)
        _soft_remove(target, "kicked", current_user.id)
        public = f"{_iga(current_user.name)} {_eulreul(target_name)} 내보냈습니다."
        sys_msgs.append(
            _create_system_message(
                db,
                room_id,
                sender_id=current_user.id,
                event="kick",
                actor_id=current_user.id,
                target_id=mid,
                public_content=public,
            )
        )
        removed.append(mid)

    if not removed:
        raise HTTPException(status_code=400, detail="내보낼 멤버가 없습니다")

    db.commit()

    loaded_sys: list[Message] = []
    for sm in sys_msgs:
        loaded_sys.append(
            db.query(Message)
            .options(joinedload(Message.sender))
            .filter(Message.id == sm.id)
            .one()
        )

    room = _load_room(db, room_id)
    out = _room_out(room, current_user.id, db)
    removed_payloads = {
        rid: _room_out(room, rid, db).model_dump(mode="json") for rid in removed
    }

    await _broadcast_system_messages(db, room_id, loaded_sys, notify_ids)
    await _broadcast_membership_change(
        room_id=room_id,
        action="kick",
        actor_id=current_user.id,
        removed_ids=removed,
        notify_user_ids=notify_ids,
        room_payload=out.model_dump(mode="json"),
        removed_room_payloads=removed_payloads,
        system_messages=[
            _message_out(m, _load_room_members(db, room_id), viewer_id=current_user.id, db=db).model_dump(
                mode="json"
            )
            for m in loaded_sys
        ],
    )
    return out


@router.delete("/{room_id}/members/{employee_id}", response_model=RoomOut)
async def kick_member(
    room_id: int,
    employee_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Employee, Depends(get_current_user)],
):
    """Kick a single member (same policy as POST /kick)."""
    return await kick_members(
        room_id,
        RoomKickRequest(member_ids=[employee_id]),
        db,
        current_user,
    )


@router.delete("/{room_id}/history")
async def dismiss_history(
    room_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Employee, Depends(get_current_user)],
):
    """Permanently remove left/kicked room from this user's list (hard delete membership)."""
    membership = _membership(db, room_id, current_user.id)
    if not membership:
        raise HTTPException(status_code=404, detail="채팅방 이력을 찾을 수 없습니다")
    if membership.status == "active":
        raise HTTPException(status_code=400, detail="참여 중인 채팅방은 이력 삭제 대신 나가기를 사용하세요")
    db.delete(membership)
    db.commit()

    from app.ws_manager import manager

    event = {
        "type": "membership_change",
        "room_id": room_id,
        "action": "dismiss_history",
        "actor_id": current_user.id,
        "removed_ids": [current_user.id],
        "room": None,
    }
    await manager.notify_users([current_user.id], event)
    return {"ok": True, "room_id": room_id}


@router.post("/invite-bot", response_model=RoomOut)
def invite_bot(
    body: InviteBotRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Employee, Depends(get_current_user)],
):
    if not _active_membership(db, body.room_id, current_user.id):
        raise HTTPException(status_code=403, detail="해당 채팅방 권한이 없습니다")
    bot = db.query(Employee).filter(Employee.is_bot == True).first()  # noqa: E712
    if not bot:
        raise HTTPException(status_code=404, detail="AI 봇이 없습니다")
    existing = (
        db.query(RoomMember)
        .filter(RoomMember.room_id == body.room_id, RoomMember.employee_id == bot.id)
        .first()
    )
    if existing:
        if existing.status != "active":
            existing.status = "active"
            existing.left_at = None
            existing.removed_by_id = None
            db.commit()
    else:
        db.add(
            RoomMember(
                room_id=body.room_id,
                employee_id=bot.id,
                last_read_at=None,
                status="active",
            )
        )
        db.commit()
    return _room_out(_load_room(db, body.room_id), current_user.id, db)
