from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_user
from app.database import get_db
from app.models import Employee, Room, RoomMember, Message
from app.schemas import RoomCreate, RoomOut, MessageCreate, MessageOut, InviteBotRequest, RoomInviteRequest

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


def _user_room_ids(db: Session, user_id: int) -> set[int]:
    rows = db.query(RoomMember.room_id).filter(RoomMember.employee_id == user_id).all()
    return {r[0] for r in rows}


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
    return rooms


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
        # Reuse existing direct room if present
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
                return (
                    db.query(Room)
                    .options(joinedload(Room.members).joinedload(RoomMember.employee))
                    .filter(Room.id == room.id)
                    .one()
                )
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
        db.add(RoomMember(room_id=room.id, employee_id=mid))
    db.commit()
    return (
        db.query(Room)
        .options(joinedload(Room.members).joinedload(RoomMember.employee))
        .filter(Room.id == room.id)
        .one()
    )


@router.get("/{room_id}/messages", response_model=list[MessageOut])
def list_messages(
    room_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Employee, Depends(get_current_user)],
):
    if room_id not in _user_room_ids(db, current_user.id):
        raise HTTPException(status_code=403, detail="해당 채팅방 권한이 없습니다")
    return (
        db.query(Message)
        .options(joinedload(Message.sender))
        .filter(Message.room_id == room_id)
        .order_by(Message.created_at.asc())
        .limit(500)
        .all()
    )


@router.post("/{room_id}/messages", response_model=MessageOut)
async def post_message(
    room_id: int,
    body: MessageCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Employee, Depends(get_current_user)],
):
    from app.ws_manager import manager
    from app.llm import generate_reply

    if room_id not in _user_room_ids(db, current_user.id):
        raise HTTPException(status_code=403, detail="해당 채팅방 권한이 없습니다")
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="메시지 내용이 비어 있습니다")

    msg = Message(room_id=room_id, sender_id=current_user.id, content=body.content.strip())
    db.add(msg)
    db.commit()
    db.refresh(msg)
    msg = (
        db.query(Message)
        .options(joinedload(Message.sender))
        .filter(Message.id == msg.id)
        .one()
    )
    payload = MessageOut.model_validate(msg).model_dump(mode="json")
    await manager.broadcast(room_id, {"type": "message", "data": payload})

    # AI bot auto-reply if bot is in room and message mentions bot or starts with @AI
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
            bot_payload = MessageOut.model_validate(bot_msg).model_dump(mode="json")
            await manager.broadcast(room_id, {"type": "message", "data": bot_payload})

    return msg




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
        db.add(RoomMember(room_id=room_id, employee_id=mid))
    db.commit()
    return (
        db.query(Room)
        .options(joinedload(Room.members).joinedload(RoomMember.employee))
        .filter(Room.id == room_id)
        .one()
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
        db.add(RoomMember(room_id=body.room_id, employee_id=bot.id))
        db.commit()
    return (
        db.query(Room)
        .options(joinedload(Room.members).joinedload(RoomMember.employee))
        .filter(Room.id == body.room_id)
        .one()
    )
