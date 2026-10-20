import asyncio
from collections import defaultdict

from fastapi import WebSocket, WebSocketDisconnect

class ConnectionManager:
    def __init__(self):
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, device_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            if len(self._connections.get(device_id, set())) >= 3:
                await websocket.close(code=1008, reason='Too many device connections')
                raise WebSocketDisconnect(code=1008)
            await websocket.accept()
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
                await asyncio.wait_for(socket.send_json(message), timeout=1.5)
                delivered = True
            except Exception:
                await self.disconnect(device_id, socket)
        
        return delivered

manager = ConnectionManager()
