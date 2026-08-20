"""Delivery scheduler (spec/06 §Turn-taking and WSS).

Publishes each reply group as the exact N+3 sequence: typing true, one
message per scheduled entry in position order at its deliver_at, typing
false. Delivery message ids are fresh UUIDs distinct from schedule ids;
request metadata is copied to every bubble (null when omitted). Pending
schedules are recovered from durable state after restart (spec/06
§Reliability and scaling).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from . import metrics
from .db import session
from .fanout import registry
from .ids import event_id, new_uuid
from .storage import Outbox, Schedule, loads
from .timefmt import ts, utcnow


def _typing_frame(channel: str, thread_id: str, typing: bool) -> dict:
    return {
        "id": event_id(),
        "type": "turn_taking.typing",
        "channel": channel,
        "ts": ts(utcnow()),
        "data": {"thread_id": thread_id, "typing": typing},
    }


def _message_frame(channel: str, thread_id: str, content: str, position: int,
                   metadata) -> dict:
    now = utcnow()
    return {
        "id": event_id(),
        "type": "turn_taking.message",
        "channel": channel,
        "ts": ts(now),
        "data": {
            "message_id": new_uuid(),
            "thread_id": thread_id,
            "content": content,
            "position": position,
            "sent_at": ts(now),
            "metadata": metadata,
        },
    }


def _aware(when: datetime) -> datetime:
    """SQLite round-trips naive datetimes; normalize to UTC-aware."""
    return when if when.tzinfo is not None else when.replace(tzinfo=timezone.utc)


async def _sleep_until(when: datetime) -> None:
    delay = (_aware(when) - utcnow()).total_seconds()
    if delay > 0:
        await asyncio.sleep(delay)


async def _deliver_group(channel: str, thread_id: str,
                         entries: list[dict]) -> None:
    """entries: [{id, content, position, deliver_at(datetime), metadata}]"""
    await registry.broadcast(channel, _typing_frame(channel, thread_id, True))
    for entry in sorted(entries, key=lambda e: e["position"]):
        await _sleep_until(entry["deliver_at"])
        metrics.record_schedule_lateness(
            (utcnow() - _aware(entry["deliver_at"])).total_seconds() * 1000.0)
        await registry.broadcast(channel, _message_frame(
            channel, thread_id, entry["content"], entry["position"], entry["metadata"]))
        metrics.record_ws_frame("turn_taking.message")
        with session() as s:
            row = s.get(Schedule, entry["id"])
            if row is not None:
                row.status = "delivered"
                row.updated_at = utcnow()
    await registry.broadcast(channel, _typing_frame(channel, thread_id, False))


class DeliveryScheduler:
    def __init__(self) -> None:
        self._tasks: set[asyncio.Task] = set()

    def schedule_group(self, channel: str, thread_id: str, entries: list[dict]) -> None:
        task = asyncio.create_task(_deliver_group(channel, thread_id, entries))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def recover(self) -> int:
        """Re-arm undelivered schedules from durable state after restart."""
        with session() as s:
            rows = s.execute(
                select(Schedule).where(Schedule.status == "scheduled")
                .order_by(Schedule.reply_group, Schedule.position)
            ).scalars().all()
        groups: dict[str, list[Schedule]] = {}
        for row in rows:
            groups.setdefault(row.reply_group, []).append(row)
        for group_rows in groups.values():
            first = group_rows[0]
            channel = f"turn-taking-thread/{first.thread_id}"
            self.schedule_group(channel, first.thread_id, [
                {
                    "id": row.id,
                    "content": row.content,
                    "position": row.position,
                    "deliver_at": row.deliver_at,
                    "metadata": loads(row.metadata_json),
                }
                for row in group_rows
            ])
        # Close the outbox loop: any deliver_reply left unprocessed by a crash
        # has now been re-armed from durable schedule state.
        with session() as s:
            rows = s.execute(
                select(Outbox).where(Outbox.kind == "deliver_reply",
                                     Outbox.processed_at.is_(None))
            ).scalars().all()
            for row in rows:
                row.processed_at = utcnow()
        return len(groups)


scheduler = DeliveryScheduler()
