"""WSS channel fanout.

Multiple sockets attached to one channel through different grants receive
identical frames with identical event ids and message ids (spec/03), so a
frame is built exactly once and broadcast to every registered socket.
The registry is the in-process ephemeral store (ADR hum-4q8k).
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict

from starlette.websockets import WebSocket


class ChannelRegistry:
    def __init__(self) -> None:
        self._channels: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def register(self, channel: str, socket: WebSocket) -> None:
        async with self._lock:
            self._channels[channel].add(socket)

    async def unregister(self, channel: str, socket: WebSocket) -> None:
        async with self._lock:
            self._channels[channel].discard(socket)
            if not self._channels[channel]:
                self._channels.pop(channel, None)

    async def broadcast(self, channel: str, frame: dict) -> None:
        """Serialize once; send to every socket, dropping dead ones quietly."""
        async with self._lock:
            sockets = list(self._channels.get(channel, ()))
        if not sockets:
            return
        text = json.dumps(frame, separators=(",", ":"), ensure_ascii=False)
        for socket in sockets:
            try:
                await socket.send_text(text)
            except Exception:
                await self.unregister(channel, socket)


registry = ChannelRegistry()
