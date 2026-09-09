"""Room/membership/message API with soft-leave and system notifications."""
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_user
from app.database import get_db
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


def _emp_name(db: Session, emp_id: int | None) -> str:
    if not emp_id:
        return "누군가"
    emp = db.query(Employee).filter(Employee.id == emp_id).first()
    return emp.name if emp else "누군가"


def _render_system_content(msg: Message, viewer_id: int, db: Session) -> str:
    """Personalize system notification text for the viewing user."""
    actor_name = _emp_name(db, msg.system_actor_id)
    target_name = _emp_name(db, msg.system_target_id)
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


def _message_out(msg: Message, members: list[RoomMember], viewer_id: int | None = None, db: Session | None = None) -> MessageOut:
    base = MessageOut.model_validate(msg)
    content = msg.content
    if msg.is_system and viewer_id is not None and db is not None:
        content = _render_system_content(msg, viewer_id, db)
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
) -> RoomOut:
    membership = next((m for m in room.members if m.employee_id == user_id), None)
    display_name = membership.display_name if membership else None
    status = (membership.status if membership else "active") or "active"
    left_at = membership.left_at if membership else None
    # Only active members appear in the participant list
    active_members = [m for m in room.members if (m.status or "active") == "active"]
    unread = 0
    if membership and status == "active":
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
    await manager.broadcast(room_id, event)
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
    await manager.broadcast(room_id, event)
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
    for uid in notify_user_ids:
        for msg in msgs:
            payload = _message_out(msg, active_members, viewer_id=uid, db=db).model_dump(mode="json")
            event = {
                "type": "message",
                "room_id": room_id,
                "unread_delta": 0,
                "data": payload,
            }
            await manager.notify_users([uid], event)


async def _broadcast_new_message(db: Session, room_id: int, msg: Message, sender_id: int):
    """Fan-out to active members only (left/kicked users do not get new chat traffic)."""
    from app.ws_manager import manager

    members = _load_room_members(db, room_id, active_only=True)
    # Use sender as viewer for public content; clients with system meta can re-render if needed
    payload = _message_out(msg, members, viewer_id=sender_id, db=db).model_dump(mode="json")
    event = {
        "type": "message",
        "room_id": room_id,
        "unread_delta": 0 if msg.is_system else 1,
        "data": payload,
    }
    await manager.broadcast(room_id, event)

    member_ids = [m.employee_id for m in members]
    if member_ids:
        # Personalize system content per user when needed
        if msg.is_system:
            for uid in member_ids:
                personalized = _message_out(msg, members, viewer_id=uid, db=db).model_dump(mode="json")
                await manager.notify_users(
                    [uid],
                    {
                        "type": "message",
                        "room_id": room_id,
                        "unread_delta": 0,
                        "data": personalized,
                    },
                )
        else:
            await manager.notify_users(member_ids, event)


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
    return [
        _room_out(room, current_user.id, db, last_message_at=last_at)
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
        other = db.query(Employee).filter(Employee.id == other_id).first()
        name = f"{current_user.name} ↔ {other.name if other else other_id}"
    else:
        # Group display names are NOT unique. Identity is Room.public_id (UUID).
        # Duplicate names are allowed; clients/joins that need a stable id must use public_id.
        name = body.name or "그룹 채팅"

    room = Room(
        name=name,
        room_type=body.room_type,
        created_by=current_user.id,
        public_id=str(uuid.uuid4()),
    )
    db.add(room)
    db.flush()
    for mid in member_ids:
        if not db.query(Employee).filter(Employee.id == mid).first():
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
    # Soft-left users may view history but should not affect others' unread
    membership.last_read_at = datetime.utcnow()
    db.commit()
    db.refresh(membership)
    if membership.status == "active":
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
    return [_message_out(m, members, viewer_id=current_user.id, db=db) for m in msgs]


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


@router.post("/{room_id}/messages", response_model=MessageOut)
async def post_message(
    room_id: int,
    body: MessageCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Employee, Depends(get_current_user)],
):
    from app.llm import generate_reply

    membership = _active_membership(db, room_id, current_user.id)
    if not membership:
        # Distinguish soft-left vs never a member
        any_m = _membership(db, room_id, current_user.id)
        if any_m:
            raise HTTPException(status_code=403, detail="이미 나간 채팅방에서는 메시지를 보낼 수 없습니다")
        raise HTTPException(status_code=403, detail="해당 채팅방 권한이 없습니다")
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="메시지 내용이 비어 있습니다")

    msg = Message(room_id=room_id, sender_id=current_user.id, content=body.content.strip())
    db.add(msg)
    membership.last_read_at = datetime.utcnow()
    db.commit()
    db.refresh(msg)
    msg = (
        db.query(Message)
        .options(joinedload(Message.sender))
        .filter(Message.id == msg.id)
        .one()
    )
    await _broadcast_new_message(db, room_id, msg, current_user.id)
    await _broadcast_read_update(db, room_id, current_user.id, membership.last_read_at)

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
        text = body.content
        should_reply = bot_in_room and (
            "@AI" in text or "@ai" in text or "AI 도우미" in text or text.strip().startswith("?")
        )
        if should_reply and current_user.id != bot.id:
            room = db.query(Room).filter(Room.id == room_id).first()
            reply_text = await generate_reply(text, room.name if room else "")
            bot_msg = Message(room_id=room_id, sender_id=bot.id, content=reply_text)
            db.add(bot_msg)
            db.commit()
            bot_msg = (
                db.query(Message)
                .options(joinedload(Message.sender))
                .filter(Message.id == bot_msg.id)
                .one()
            )
            await _broadcast_new_message(db, room_id, bot_msg, bot.id)

    members = _load_room_members(db, room_id, active_only=True)
    return _message_out(msg, members, viewer_id=current_user.id, db=db)


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
    for mid in body.member_ids:
        emp = db.query(Employee).filter(Employee.id == mid, Employee.is_active == True).first()  # noqa: E712
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
    sys_payloads = [
        _message_out(sys_msg, active_members, viewer_id=uid, db=db).model_dump(mode="json")
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
