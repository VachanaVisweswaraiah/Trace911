"""In-process pub/sub for WebSocket fan-out.

The DB is the source of truth for state; this is the live notification channel.
Restart-tolerant clients can re-fetch the snapshot via REST then re-subscribe.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any


class Broker:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._t0: dict[str, datetime] = {}

    def register_call(self, call_id: str, started_at: datetime) -> None:
        self._t0[call_id] = started_at

    def t_for(self, call_id: str) -> float:
        t0 = self._t0.get(call_id)
        if t0 is None:
            return 0.0
        return (datetime.now(timezone.utc) - t0).total_seconds()

    def subscribe(self, call_id: str) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        self._subs[call_id].add(q)
        return q

    def unsubscribe(self, call_id: str, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subs[call_id].discard(q)
        if not self._subs[call_id]:
            self._subs.pop(call_id, None)

    async def publish(self, call_id: str, event_type: str, payload: Any) -> None:
        msg = {"type": event_type, "t": self.t_for(call_id), "payload": payload}
        for q in list(self._subs.get(call_id, ())):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                # Slow consumer — drop. UI can recover by re-fetching the snapshot.
                pass


broker = Broker()
