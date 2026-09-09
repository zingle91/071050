from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.orm import Session

from app.auth import get_user_from_token
from app.database import SessionLocal
from app.models import RoomMember
from app.ws_manager import manager

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/rooms/{room_id}")
async def room_ws(websocket: WebSocket, room_id: int, token: str = Query(...)):
    db: Session = SessionLocal()
    try:
        user = get_user_from_token(token, db)
        if not user:
            await websocket.close(code=4401)
            return
        membership = (
            db.query(RoomMember)
            .filter(RoomMember.room_id == room_id, RoomMember.employee_id == user.id)
            .first()
        )
        if not membership:
            await websocket.close(code=4403)
            return
    finally:
        db.close()

    await manager.connect(room_id, websocket)
    try:
        while True:
            # Keepalive / client can send ping
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(room_id, websocket)


@router.websocket("/ws/user")
async def user_ws(websocket: WebSocket, token: str = Query(...)):
    """Personal channel: live message events for all rooms (unread badges)."""
    db: Session = SessionLocal()
    try:
        user = get_user_from_token(token, db)
        if not user:
            await websocket.close(code=4401)
            return
        user_id = user.id
    finally:
        db.close()

    await manager.connect_user(user_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect_user(user_id, websocket)
