"""Atomic state.json manager."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from cross_harness.config.state import DispatchIndexEntry, WorkflowState


class StateManager:
    def __init__(self, path: Path):
        self._path = path

    def load(self) -> WorkflowState:
        if not self._path.exists():
            return WorkflowState()
        with open(self._path) as f:
            return WorkflowState.model_validate(json.load(f))

    def save(self, state: WorkflowState):
        state.last_updated = datetime.now(timezone.utc).isoformat()
        state.last_writer = "broker"
        tmp = self._path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(state.model_dump(), f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(self._path)

    def update_agent(self, state: WorkflowState, agent: str, **kwargs) -> WorkflowState:
        if agent in state.agents:
            for k, v in kwargs.items():
                setattr(state.agents[agent], k, v)
        return state

    def update_dispatch_index(
        self, state: WorkflowState, dispatch_id: str, entry: DispatchIndexEntry
    ) -> WorkflowState:
        state.dispatch_index[dispatch_id] = entry
        return state

    def increment_event_count(self, state: WorkflowState, event_id: str) -> WorkflowState:
        state.event_count += 1
        state.last_event_id = event_id
        return state
