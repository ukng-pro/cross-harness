"""Broker runtime loop and inbox processing."""

from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from cross_harness.broker.event_store import EventStore
from cross_harness.broker.idempotency import IdempotencyStore
from cross_harness.broker.lock import LockManager
from cross_harness.broker.state_manager import StateManager
from cross_harness.config.loader import CrossHarnessConfig, load_config
from cross_harness.config.state import ActiveLoopState, DispatchIndexEntry, WorkflowState
from cross_harness.events.models import Event, EventPayload, EventType, SourceType
from cross_harness.workspace import ensure_workflow_exists, generate_event_id

log = logging.getLogger(__name__)


@dataclass
class BrokerRunStats:
    processed: int = 0
    skipped_duplicates: int = 0
    moved_to_dead_letter: int = 0


class Broker:
    """Single-writer broker for inbox -> events/state processing."""

    def __init__(self, project_root: Path, config_path: Path | None = None):
        self.project_root = project_root
        self.workflow_dir = ensure_workflow_exists(project_root)
        self.config_path = config_path or self.workflow_dir / "config.yaml"
        self.config: CrossHarnessConfig = load_config(self.config_path)
        self.inbox_dir = self.workflow_dir / "inbox"
        self.dead_letter_dir = self.workflow_dir / "dead-letter"
        self.event_store = EventStore(self.workflow_dir / "events.jsonl")
        self.state_manager = StateManager(self.workflow_dir / "state.json")
        self.idempotency = IdempotencyStore(self.workflow_dir / "processed_keys.json")
        self.lock_manager = LockManager(self.workflow_dir)

    def recover(self) -> bool:
        """Recover stale lock state at startup."""
        return self.lock_manager.check_stale()

    def run_forever(self, poll_ms: int | None = None):
        interval_ms = poll_ms or self.config.broker.inbox_poll_ms
        self.recover()
        while True:
            self.run_once()
            time.sleep(interval_ms / 1000)

    def run_once(self) -> BrokerRunStats:
        stats = BrokerRunStats()
        self.recover()
        for path in sorted(self.inbox_dir.glob("*.json")):
            result = self._process_inbox_file(path)
            if result == "processed":
                stats.processed += 1
            elif result == "duplicate":
                stats.skipped_duplicates += 1
            elif result == "dead-letter":
                stats.moved_to_dead_letter += 1
        return stats

    def _process_inbox_file(self, path: Path) -> str:
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            self._move_to_dead_letter(path)
            log.warning("Invalid inbox JSON moved to dead-letter: %s", path.name)
            return "dead-letter"

        idempotency_key = data.get("idempotency_key")
        if idempotency_key and self.idempotency.has_key(idempotency_key):
            path.unlink(missing_ok=True)
            return "duplicate"

        try:
            event = self._build_event(data)
        except Exception:
            self._move_to_dead_letter(path)
            log.exception("Inbox event validation failed: %s", path.name)
            return "dead-letter"

        state = self.state_manager.load()
        state = self._apply_event(state, event)
        self.event_store.append(event)
        self.state_manager.save(state)
        if idempotency_key:
            self.idempotency.add_key(idempotency_key)
        path.unlink(missing_ok=True)
        return "processed"

    def _build_event(self, data: dict) -> Event:
        payload = EventPayload.model_validate(data.get("payload") or {})
        event_data = {
            "id": data.get("id") or generate_event_id(),
            "source": data["source"],
            "type": data["type"],
            "dispatch_id": data.get("dispatch_id"),
            "causation_id": data.get("causation_id"),
            "attempt": data.get("attempt", 1),
            "idempotency_key": data.get("idempotency_key"),
            "payload": payload,
        }
        if data.get("timestamp"):
            event_data["timestamp"] = data["timestamp"]
        return Event(
            **event_data,
        )

    def _apply_event(self, state: WorkflowState, event: Event) -> WorkflowState:
        state = self.state_manager.increment_event_count(state, event.id)
        agent_names = set(state.agents)
        event_type = event.type.value
        source = event.source.value

        if event_type == EventType.TASK_DISPATCHED.value and event.dispatch_id:
            target_agent = event.payload.target_agent
            if target_agent and target_agent in agent_names:
                state = self.state_manager.update_agent(
                    state,
                    target_agent,
                    status="working",
                    current_dispatch=event.dispatch_id,
                    last_activity=event.timestamp,
                )
                state.dispatch_index[event.dispatch_id] = DispatchIndexEntry(
                    agent=target_agent,
                    task_id=event.payload.task_id,
                    status="active",
                )
                state.current_phase = (
                    event.payload.task_type.value if event.payload.task_type else state.current_phase
                )

        if event_type in {
            EventType.TASK_COMPLETE.value,
            EventType.REVIEW_COMPLETE.value,
            EventType.RESEARCH_COMPLETE.value,
            EventType.TASK_FAILED.value,
            EventType.TASK_NEEDS_DECISION.value,
        }:
            if source in agent_names:
                next_status = "error" if event_type == EventType.TASK_FAILED.value else "idle"
                state = self.state_manager.update_agent(
                    state,
                    source,
                    status=next_status,
                    current_dispatch=None,
                    last_activity=event.timestamp,
                )
            if event.dispatch_id:
                entry = state.dispatch_index.get(event.dispatch_id)
                if entry is None and source in agent_names:
                    entry = DispatchIndexEntry(agent=source, task_id=event.payload.task_id)
                if entry is not None:
                    entry.status = {
                        EventType.TASK_COMPLETE.value: "completed",
                        EventType.REVIEW_COMPLETE.value: "reviewed",
                        EventType.RESEARCH_COMPLETE.value: "researched",
                        EventType.TASK_FAILED.value: "failed",
                        EventType.TASK_NEEDS_DECISION.value: "needs_decision",
                    }[event_type]
                    state.dispatch_index[event.dispatch_id] = entry
            if event_type == EventType.TASK_NEEDS_DECISION.value and event.dispatch_id:
                if event.dispatch_id not in state.pending_decisions:
                    state.pending_decisions.append(event.dispatch_id)

        if event_type == EventType.HUMAN_DECISION.value and event.dispatch_id:
            state.pending_decisions = [
                dispatch_id
                for dispatch_id in state.pending_decisions
                if dispatch_id != event.dispatch_id
            ]

        if event_type == EventType.WORKFLOW_PAUSE.value:
            state.workflow_status = "paused"
        elif event_type == EventType.WORKFLOW_RESUME.value:
            state.workflow_status = "active"

        state = self._apply_loop_event(state, event)
        return state

    def _apply_loop_event(self, state: WorkflowState, event: Event) -> WorkflowState:
        event_type = event.type.value
        if event_type == EventType.LOOP_STARTED.value:
            loop_id = event.payload.loop_id or event.dispatch_id or event.id
            state.active_loop = ActiveLoopState(
                loop_id=loop_id,
                worker=event.payload.extra.get("worker", ""),
                reviewer=event.payload.extra.get("reviewer", ""),
                judge=event.payload.extra.get("judge", ""),
                task_type=(
                    event.payload.task_type.value
                    if event.payload.task_type is not None
                    else event.payload.extra.get("task_type", "impl")
                ),
                task_id=event.payload.task_id,
                max_iterations=int(event.payload.extra.get("max_iterations", 3)),
                current_iteration=0,
                status="running",
            )
        elif state.active_loop is not None:
            if event.payload.loop_iteration is not None:
                state.active_loop.current_iteration = event.payload.loop_iteration
            if event_type == EventType.LOOP_PAUSED.value:
                state.active_loop.status = "paused"
            elif event_type == EventType.LOOP_ABORTED.value:
                state.active_loop.status = "aborted"
            elif event_type == EventType.LOOP_MAX_REACHED.value:
                state.active_loop.status = "max_reached"
            elif event_type == EventType.LOOP_STOPPED.value:
                state.active_loop.status = "stopped"
        return state

    def _move_to_dead_letter(self, path: Path):
        target = self.dead_letter_dir / path.name
        if target.exists():
            target = self.dead_letter_dir / f"{path.stem}.{int(time.time() * 1000)}.json"
        shutil.move(str(path), str(target))
