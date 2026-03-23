"""Append-only event store backed by events.jsonl."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from cross_harness.events.models import Event

log = logging.getLogger(__name__)


class EventStore:
    def __init__(self, path: Path):
        self._path = path

    def append(self, event: Event):
        line = event.to_jsonl() + "\n"
        fd = os.open(str(self._path), os.O_WRONLY | os.O_APPEND | os.O_CREAT)
        try:
            os.write(fd, line.encode())
            os.fsync(fd)
        finally:
            os.close(fd)

    def read_all(self) -> list[Event]:
        events: list[Event] = []
        if not self._path.exists():
            return events
        with open(self._path) as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(Event.from_jsonl(line))
                except Exception:
                    log.warning("Skipping corrupted event at line %d", lineno)
        return events

    def read_last(self, n: int = 10) -> list[Event]:
        all_events = self.read_all()
        return all_events[-n:]

    def last_event_id(self) -> str | None:
        all_events = self.read_all()
        return all_events[-1].id if all_events else None
