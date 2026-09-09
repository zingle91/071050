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
