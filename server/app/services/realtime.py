import asyncio
from collections import defaultdict

from fastapi import WebSocket

class ConnectionManager:
    def __init__(self):
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, device_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[device_id].add(websocket)

    async def disconnect(self, device_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            group = self._connections.get(device_id)
            if group:
                group.discard(websocket)
                if not group:
                    self._connections.pop(device_id, None)

    async def send(self, device_id: str, message: dict) -> bool:
        async with self._lock:
            sockets = list(self._connections.get(device_id, set()))

        delivered = False
        for socket in sockets:
            try:
                await socket.send_json(message)
                delivered = True
            except Exception:
                await self.disconnect(device_id, socket)
        
        return delivered

manager = ConnectionManager()
