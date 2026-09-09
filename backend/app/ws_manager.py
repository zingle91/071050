import asyncio
import json
from collections import defaultdict
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        # Legacy per-room sockets (optional; primary path is user channel)
        self.room_connections: dict[int, set[WebSocket]] = defaultdict(set)
        # user_id -> websockets (personal channel: messages + unread)
        self.user_connections: dict[int, set[WebSocket]] = defaultdict(set)
        self.lock = asyncio.Lock()

    async def connect(self, room_id: int, websocket: WebSocket):
        await websocket.accept()
        async with self.lock:
            self.room_connections[room_id].add(websocket)

    async def disconnect(self, room_id: int, websocket: WebSocket):
        async with self.lock:
            self.room_connections[room_id].discard(websocket)
            if not self.room_connections[room_id]:
                del self.room_connections[room_id]

    async def connect_user(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        async with self.lock:
            self.user_connections[user_id].add(websocket)

    async def disconnect_user(self, user_id: int, websocket: WebSocket):
        async with self.lock:
            self.user_connections[user_id].discard(websocket)
            if not self.user_connections[user_id]:
                del self.user_connections[user_id]

    async def broadcast(self, room_id: int, message: dict):
        data = json.dumps(message, ensure_ascii=False, default=str)
        async with self.lock:
            sockets = list(self.room_connections.get(room_id, set()))
        dead = []
        for ws in sockets:
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(room_id, ws)

    async def notify_users(self, user_ids: list[int], message: dict):
        """Push an event to each listed user's personal WebSocket connections."""
        data = json.dumps(message, ensure_ascii=False, default=str)
        async with self.lock:
            targets: list[tuple[int, WebSocket]] = []
            for uid in user_ids:
                for ws in self.user_connections.get(uid, set()):
                    targets.append((uid, ws))
        dead: list[tuple[int, WebSocket]] = []
        for uid, ws in targets:
            try:
                await ws.send_text(data)
            except Exception:
                dead.append((uid, ws))
        for uid, ws in dead:
            await self.disconnect_user(uid, ws)


manager = ConnectionManager()
