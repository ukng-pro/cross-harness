"""Core event and execution data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class EventType(StrEnum):
    TASK_COMPLETE = "task_complete"
    REVIEW_COMPLETE = "review_complete"
    RESEARCH_COMPLETE = "research_complete"
    TASK_FAILED = "task_failed"
    TASK_NEEDS_DECISION = "task_needs_decision"
    HUMAN_DECISION = "human_decision"
    HUMAN_NOTE = "human_note"
    TASK_DISPATCHED = "task_dispatched"
    MERGE_COMPLETE = "merge_complete"
    WORKFLOW_PAUSE = "workflow_pause"
    WORKFLOW_RESUME = "workflow_resume"
    LOOP_STARTED = "loop_started"
    LOOP_ITERATION = "loop_iteration"
    LOOP_VERDICT = "loop_verdict"
    LOOP_STOPPED = "loop_stopped"
    LOOP_MAX_REACHED = "loop_max_reached"
    LOOP_PAUSED = "loop_paused"
    LOOP_ABORTED = "loop_aborted"


class TaskType(StrEnum):
    IMPL = "impl"
    FIX = "fix"
    REFACTOR = "refactor"
    TEST = "test"
    REVIEW = "review"
    RESEARCH = "research"


class SourceType(StrEnum):
    CLAUDE = "claude"
    CODEX = "codex"
    GEMINI = "gemini"
    HUMAN = "human"
    SYSTEM = "system"


class AgentStatus(StrEnum):
    IDLE = "idle"
    WORKING = "working"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Event payload
# ---------------------------------------------------------------------------

class EventPayload(BaseModel):
    task_id: str | None = None
    task_type: TaskType | None = None
    commit: str | None = None
    branch: str | None = None
    cwd: str = "."
    summary: str | None = None
    files_changed: list[str] = Field(default_factory=list)
    output_artifact: str | None = None
    exit_code: int | None = None
    suggested_next: str | None = None
    manual: bool = False
    # Human decision fields
    target_agent: str | None = None
    prompt: str | None = None
    note: str | None = None
    # Loop fields
    loop_id: str | None = None
    loop_iteration: int | None = None
    # Catch-all for extensibility
    extra: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------

class Event(BaseModel):
    id: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: SourceType
    type: EventType
    dispatch_id: str | None = None
    causation_id: str | None = None
    attempt: int = 1
    idempotency_key: str | None = None
    payload: EventPayload = Field(default_factory=EventPayload)

    def to_jsonl(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_jsonl(cls, line: str) -> Event:
        return cls.model_validate_json(line)


# ---------------------------------------------------------------------------
# Execution result (returned by adapter.execute)
# ---------------------------------------------------------------------------

@dataclass
class ExecutionResult:
    exit_code: int
    stdout: str
    stderr: str
    pre_head: str
    post_head: str
    has_new_commit: bool
    commit_count: int
    commit: str | None
    files_changed: list[str] = field(default_factory=list)
    duration_s: float = 0.0
    session_id: str | None = None
