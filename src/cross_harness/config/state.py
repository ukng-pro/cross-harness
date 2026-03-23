"""Workflow state model (state.json)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AgentState(BaseModel):
    status: str = "idle"
    current_dispatch: str | None = None
    last_activity: str | None = None
    subprocess_pid: int | None = None
    session_id: str | None = None
    session_mode: str = "new"
    last_session_used_at: str | None = None


class DispatchIndexEntry(BaseModel):
    agent: str
    task_id: str | None = None
    status: str = "active"
    session_id: str | None = None


class LoopIterationState(BaseModel):
    iteration: int
    worker_dispatch: str | None = None
    review_dispatch: str | None = None
    judge_dispatch: str | None = None
    judge_verdict: str | None = None
    finding_count: int | None = None


class ActiveLoopState(BaseModel):
    loop_id: str
    worker: str
    reviewer: str
    judge: str
    task_type: str
    task_id: str | None = None
    max_iterations: int = 3
    current_iteration: int = 0
    status: str = "running"
    iterations: list[LoopIterationState] = Field(default_factory=list)


class WorkflowState(BaseModel):
    workflow_status: str = "active"
    current_phase: str | None = None
    last_updated: str | None = None
    last_writer: str = "broker"
    agents: dict[str, AgentState] = Field(default_factory=dict)
    dispatch_index: dict[str, DispatchIndexEntry] = Field(default_factory=dict)
    pending_decisions: list[str] = Field(default_factory=list)
    active_loop: ActiveLoopState | None = None
    event_count: int = 0
    last_event_id: str | None = None
