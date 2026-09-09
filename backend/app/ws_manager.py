import asyncio
import json
from collections import defaultdict
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        # user_id -> websockets (personal channel: messages + unread + notes)
        self.user_connections: dict[int, set[WebSocket]] = defaultdict(set)
        self.lock = asyncio.Lock()

    async def connect_user(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        async with self.lock:
            self.user_connections[user_id].add(websocket)

    async def disconnect_user(self, user_id: int, websocket: WebSocket):
        async with self.lock:
            self.user_connections[user_id].discard(websocket)
            if not self.user_connections[user_id]:
                del self.user_connections[user_id]

    async def notify_users(self, user_ids: list[int], message: dict):
        """Push the same event to each listed user's personal WebSocket connections."""
        if not user_ids:
            return
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

    async def notify_personalized(self, deliveries: list[tuple[int, dict]]):
        """Push possibly different payloads per user in one lock + send batch.

        Each item is (user_id, message_dict). JSON is encoded once per delivery
        entry; sockets are collected under a single lock acquisition.
        """
        if not deliveries:
            return
        encoded: list[tuple[int, str]] = [
            (uid, json.dumps(message, ensure_ascii=False, default=str))
            for uid, message in deliveries
        ]
        async with self.lock:
            targets: list[tuple[int, WebSocket, str]] = []
            for uid, data in encoded:
                for ws in self.user_connections.get(uid, set()):
                    targets.append((uid, ws, data))
        dead: list[tuple[int, WebSocket]] = []
        for uid, ws, data in targets:
            try:
                await ws.send_text(data)
            except Exception:
                dead.append((uid, ws))
        for uid, ws in dead:
            await self.disconnect_user(uid, ws)


manager = ConnectionManager()
