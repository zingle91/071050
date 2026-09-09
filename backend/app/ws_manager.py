import asyncio
import json
from collections import defaultdict
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.room_connections: dict[int, set[WebSocket]] = defaultdict(set)
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


manager = ConnectionManager()
