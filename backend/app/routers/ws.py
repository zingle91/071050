from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.orm import Session

from app.auth import get_user_from_token
from app.database import SessionLocal
from app.ws_manager import manager

router = APIRouter(tags=["websocket"])


async def _ws_keepalive(websocket: WebSocket):
    """Receive client pings; reply pong to JSON ping; ignore plain text ping."""
    while True:
        raw = await websocket.receive_text()
        text = (raw or "").strip()
        if text.lower() == "ping":
            try:
                await websocket.send_text('{"type":"pong"}')
            except Exception:
                return
            continue
        if text.startswith("{"):
            try:
                import json

                msg = json.loads(text)
                if msg.get("type") == "ping":
                    await websocket.send_text('{"type":"pong"}')
            except Exception:
                pass


@router.websocket("/ws/user")
async def user_ws(websocket: WebSocket, token: str = Query(...)):
    """Personal channel: live message events for all rooms (center + unread badges)."""
    db: Session = SessionLocal()
    try:
        user = get_user_from_token(token, db)
        if not user or not user.is_active:
            await websocket.close(code=4401)
            return
        user_id = user.id
    finally:
        db.close()

    await manager.connect_user(user_id, websocket)
    try:
        await _ws_keepalive(websocket)
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect_user(user_id, websocket)
