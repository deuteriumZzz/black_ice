import asyncio
import json

from fastapi import WebSocket


class LiveFeed:
    """Broadcasts pipeline decisions to connected netrunner-UI clients. The Kafka
    consumer runs in a plain background thread (I/O-bound poll loop, GIL is fine —
    see spec 3.1), so it hands events to asyncio via run_coroutine_threadsafe."""

    def __init__(self):
        self._clients: set[WebSocket] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    async def _broadcast(self, event: dict) -> None:
        dead = []
        for ws in self._clients:
            try:
                await ws.send_text(json.dumps(event))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    def publish_threadsafe(self, event: dict) -> None:
        """Called from the background Kafka-consumer thread."""
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._broadcast(event), self._loop)


live_feed = LiveFeed()
