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


def _user_room_ids(db: Session, user_id: int) -> set[int]:
    rows = db.query(RoomMember.room_id).filter(RoomMember.employee_id == user_id).all()
    return {r[0] for r in rows}


def _membership(db: Session, room_id: int, user_id: int) -> RoomMember | None:
    return (
        db.query(RoomMember)
        .filter(RoomMember.room_id == room_id, RoomMember.employee_id == user_id)
        .first()
    )


def _unread_count(db: Session, room_id: int, user_id: int, last_read_at: datetime | None) -> int:
    q = db.query(func.count(Message.id)).filter(
        Message.room_id == room_id,
        Message.sender_id != user_id,
    )
    if last_read_at is not None:
        q = q.filter(Message.created_at > last_read_at)
    return int(q.scalar() or 0)


def _load_room_members(db: Session, room_id: int) -> list[RoomMember]:
    return (
        db.query(RoomMember)
        .options(joinedload(RoomMember.employee))
        .filter(RoomMember.room_id == room_id)
        .all()
    )


def _member_has_read(member: RoomMember, msg: Message) -> bool:
    """Read only if last_read_at is set and >= message time. NULL = never accessed = unread."""
    if member.last_read_at is None:
        return False
    return member.last_read_at >= msg.created_at


def _iter_unreader_members(members: list[RoomMember], msg: Message) -> list[RoomMember]:
    """All current non-bot members except sender who have not read msg (NULL last_read_at counts)."""
    out: list[RoomMember] = []
    for m in members:
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
    return len(_iter_unreader_members(members, msg))


def _message_out(msg: Message, members: list[RoomMember]) -> MessageOut:
    base = MessageOut.model_validate(msg)
    return base.model_copy(update={"unread_count": _message_unread_count(members, msg)})


def _room_out(room: Room, user_id: int, db: Session) -> RoomOut:
    membership = next((m for m in room.members if m.employee_id == user_id), None)
    display_name = membership.display_name if membership else None
    last_read = membership.last_read_at if membership else None
    unread = _unread_count(db, room.id, user_id, last_read) if membership else 0
    return RoomOut(
        id=room.id,
        name=room.name,
        room_type=room.room_type,
        created_at=room.created_at,
        members=[RoomMemberOut.model_validate(m) for m in room.members],
        display_name=display_name,
        unread_count=unread,
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
        for m in db.query(RoomMember).filter(RoomMember.room_id == room_id).all()
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
):
    """Notify sidebars that someone left or was kicked.

    Policy note (MVP): any current non-bot member may kick others (not self).
    Self-removal uses leave. removed_ids always receive the event so their UI can drop the room.
    """
    from app.ws_manager import manager

    event = {
        "type": "membership_change",
        "room_id": room_id,
        "action": action,  # leave | kick
        "actor_id": actor_id,
        "removed_ids": removed_ids,
        "room": room_payload,
    }
    await manager.broadcast(room_id, event)
    targets = list({*notify_user_ids, *removed_ids})
    if targets:
        await manager.notify_users(targets, event)


async def _broadcast_new_message(db: Session, room_id: int, msg: Message, sender_id: int):
    """Fan-out to room sockets (legacy) and every member's /ws/user channel.

    User channel is the primary realtime path: active room appends the message;
    inactive rooms bump unread. Sender is included so multi-tab stays in sync.
    """
    from app.ws_manager import manager

    members = _load_room_members(db, room_id)
    payload = _message_out(msg, members).model_dump(mode="json")
    event = {
        "type": "message",
        "room_id": room_id,
        "unread_delta": 1,
        "data": payload,
    }
    await manager.broadcast(room_id, event)

    member_ids = [m.employee_id for m in members]
    if member_ids:
        await manager.notify_users(member_ids, event)


@router.get("", response_model=list[RoomOut])
def list_rooms(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Employee, Depends(get_current_user)],
):
    room_ids = _user_room_ids(db, current_user.id)
    if not room_ids:
        return []
    rooms = (
        db.query(Room)
        .options(joinedload(Room.members).joinedload(RoomMember.employee).joinedload(Employee.department))
        .filter(Room.id.in_(room_ids))
        .order_by(Room.created_at.desc())
        .all()
    )
    return [_room_out(r, current_user.id, db) for r in rooms]


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
            .join(RoomMember)
            .filter(Room.room_type == "direct")
            .all()
        )
        for room in existing:
            ids = {m.employee_id for m in room.members}
            if ids == member_ids:
                return _room_out(_load_room(db, room.id), current_user.id, db)
        other = db.query(Employee).filter(Employee.id == other_id).first()
        name = f"{current_user.name} ↔ {other.name if other else other_id}"
    else:
        name = body.name or "그룹 채팅"

    room = Room(name=name, room_type=body.room_type, created_by=current_user.id)
    db.add(room)
    db.flush()
    for mid in member_ids:
        if not db.query(Employee).filter(Employee.id == mid).first():
            raise HTTPException(status_code=400, detail=f"존재하지 않는 직원 id: {mid}")
        # Never-accessed members must stay unread → last_read_at NULL (do not stamp now)
        db.add(RoomMember(room_id=room.id, employee_id=mid, last_read_at=None))
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
    membership.last_read_at = datetime.utcnow()
    db.commit()
    db.refresh(membership)
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
    members = _load_room_members(db, room_id)
    msgs = (
        db.query(Message)
        .options(joinedload(Message.sender))
        .filter(Message.room_id == room_id)
        .order_by(Message.created_at.asc())
        .limit(500)
        .all()
    )
    return [_message_out(m, members) for m in msgs]


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
    if room_id not in _user_room_ids(db, current_user.id):
        raise HTTPException(status_code=403, detail="해당 채팅방 권한이 없습니다")
    msg = (
        db.query(Message)
        .filter(Message.id == msg_id, Message.room_id == room_id)
        .first()
    )
    if not msg:
        raise HTTPException(status_code=404, detail="메시지를 찾을 수 없습니다")
    members = _load_room_members(db, room_id)
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

    membership = _membership(db, room_id, current_user.id)
    if not membership:
        raise HTTPException(status_code=403, detail="해당 채팅방 권한이 없습니다")
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="메시지 내용이 비어 있습니다")

    msg = Message(room_id=room_id, sender_id=current_user.id, content=body.content.strip())
    db.add(msg)
    # Sender has seen up through this message
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
    # Peers should refresh unread digits when sender's last_read advances too
    await _broadcast_read_update(db, room_id, current_user.id, membership.last_read_at)

    bot = db.query(Employee).filter(Employee.is_bot == True).first()  # noqa: E712
    if bot:
        bot_in_room = (
            db.query(RoomMember)
            .filter(RoomMember.room_id == room_id, RoomMember.employee_id == bot.id)
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

    members = _load_room_members(db, room_id)
    return _message_out(msg, members)


@router.post("/{room_id}/members", response_model=RoomOut)
def invite_members(
    room_id: int,
    body: RoomInviteRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Employee, Depends(get_current_user)],
):
    if room_id not in _user_room_ids(db, current_user.id):
        raise HTTPException(status_code=403, detail="해당 채팅방 권한이 없습니다")
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="채팅방을 찾을 수 없습니다")
    if room.room_type == "direct":
        raise HTTPException(status_code=400, detail="1:1 채팅에는 멤버를 추가할 수 없습니다")
    if not body.member_ids:
        raise HTTPException(status_code=400, detail="초대할 직원을 선택하세요")

    existing_ids = {
        m.employee_id
        for m in db.query(RoomMember).filter(RoomMember.room_id == room_id).all()
    }
    for mid in body.member_ids:
        if mid in existing_ids:
            continue
        emp = db.query(Employee).filter(Employee.id == mid, Employee.is_active == True).first()  # noqa: E712
        if not emp:
            raise HTTPException(status_code=400, detail=f"존재하지 않는 직원 id: {mid}")
        # New invitees have never accessed → NULL so they count as unread for prior msgs too
        db.add(RoomMember(room_id=room_id, employee_id=mid, last_read_at=None))
    db.commit()
    return _room_out(_load_room(db, room_id), current_user.id, db)


@router.post("/{room_id}/leave")
async def leave_room(
    room_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Employee, Depends(get_current_user)],
):
    """Current user leaves the room (self-remove membership)."""
    membership = _membership(db, room_id, current_user.id)
    if not membership:
        raise HTTPException(status_code=403, detail="해당 채팅방 권한이 없습니다")

    remaining_before = (
        db.query(RoomMember).filter(RoomMember.room_id == room_id).all()
    )
    notify_ids = [m.employee_id for m in remaining_before]

    db.delete(membership)
    db.commit()

    # Remaining members (after leave) for sidebar update payload
    remaining = _load_room_members(db, room_id)
    room_payload = None
    if remaining:
        room = _load_room(db, room_id)
        # Use a remaining member as viewer for RoomOut shape; leaver gets room=null via removed_ids
        viewer_id = remaining[0].employee_id
        room_payload = _room_out(room, viewer_id, db).model_dump(mode="json")

    await _broadcast_membership_change(
        room_id=room_id,
        action="leave",
        actor_id=current_user.id,
        removed_ids=[current_user.id],
        notify_user_ids=notify_ids,
        room_payload=room_payload,
    )
    return {"ok": True, "room_id": room_id}


@router.post("/{room_id}/kick", response_model=RoomOut)
async def kick_members(
    room_id: int,
    body: RoomKickRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Employee, Depends(get_current_user)],
):
    """Kick one or more members. MVP: any non-bot member may kick others (not self)."""
    if current_user.is_bot:
        raise HTTPException(status_code=403, detail="봇은 멤버를 내보낼 수 없습니다")
    membership = _membership(db, room_id, current_user.id)
    if not membership:
        raise HTTPException(status_code=403, detail="해당 채팅방 권한이 없습니다")
    if not body.member_ids:
        raise HTTPException(status_code=400, detail="내보낼 멤버를 선택하세요")

    kick_ids = list(dict.fromkeys(body.member_ids))
    if current_user.id in kick_ids:
        raise HTTPException(status_code=400, detail="자신은 내보내기로 제거할 수 없습니다. 나가기를 사용하세요")

    before = _load_room_members(db, room_id)
    notify_ids = [m.employee_id for m in before]
    existing = {m.employee_id: m for m in before}

    removed: list[int] = []
    for mid in kick_ids:
        target = existing.get(mid)
        if not target:
            raise HTTPException(status_code=400, detail=f"채팅방에 없는 멤버 id: {mid}")
        db.delete(target)
        removed.append(mid)

    if not removed:
        raise HTTPException(status_code=400, detail="내보낼 멤버가 없습니다")

    db.commit()
    room = _load_room(db, room_id)
    out = _room_out(room, current_user.id, db)
    await _broadcast_membership_change(
        room_id=room_id,
        action="kick",
        actor_id=current_user.id,
        removed_ids=removed,
        notify_user_ids=notify_ids,
        room_payload=out.model_dump(mode="json"),
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


@router.post("/invite-bot", response_model=RoomOut)
def invite_bot(
    body: InviteBotRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Employee, Depends(get_current_user)],
):
    if body.room_id not in _user_room_ids(db, current_user.id):
        raise HTTPException(status_code=403, detail="해당 채팅방 권한이 없습니다")
    bot = db.query(Employee).filter(Employee.is_bot == True).first()  # noqa: E712
    if not bot:
        raise HTTPException(status_code=404, detail="AI 봇이 없습니다")
    existing = (
        db.query(RoomMember)
        .filter(RoomMember.room_id == body.room_id, RoomMember.employee_id == bot.id)
        .first()
    )
    if not existing:
        db.add(RoomMember(room_id=body.room_id, employee_id=bot.id, last_read_at=None))
        db.commit()
    return _room_out(_load_room(db, body.room_id), current_user.id, db)
