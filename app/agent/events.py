"""In-process pub/sub broker that fans agent events out to SSE subscribers.

Each run gets a channel that buffers every event it emits. New subscribers replay
the buffer first (so a page reload or a late connection still sees the whole run),
then receive live events. Channels are evicted a short while after the run ends; any
reconnect after that falls back to replaying persisted steps from the database.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass
class _Channel:
    events: list[dict] = field(default_factory=list)
    subscribers: set[asyncio.Queue] = field(default_factory=set)
    closed: bool = False
    stopped: bool = False


class RunBroker:
    def __init__(self) -> None:
        self._channels: dict[str, _Channel] = {}

    def _chan(self, run_id: str) -> _Channel:
        chan = self._channels.get(run_id)
        if chan is None:
            chan = _Channel()
            self._channels[run_id] = chan
        return chan

    def has_channel(self, run_id: str) -> bool:
        return run_id in self._channels

    async def publish(self, run_id: str, event: dict) -> None:
        chan = self._chan(run_id)
        chan.events.append(event)
        for queue in list(chan.subscribers):
            queue.put_nowait(event)

    def subscribe(self, run_id: str) -> tuple[list[dict], asyncio.Queue]:
        chan = self._chan(run_id)
        queue: asyncio.Queue = asyncio.Queue()
        chan.subscribers.add(queue)
        return list(chan.events), queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue) -> None:
        chan = self._channels.get(run_id)
        if chan is not None:
            chan.subscribers.discard(queue)

    def request_stop(self, run_id: str) -> None:
        self._chan(run_id).stopped = True

    def is_stopped(self, run_id: str) -> bool:
        chan = self._channels.get(run_id)
        return bool(chan and chan.stopped)

    def close(self, run_id: str) -> None:
        chan = self._channels.get(run_id)
        if chan is not None:
            chan.closed = True

    def evict(self, run_id: str) -> None:
        self._channels.pop(run_id, None)


broker = RunBroker()
