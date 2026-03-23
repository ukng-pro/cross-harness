"""Configuration loading and validation."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from cross_harness.events.models import TaskType


class AgentConfig(BaseModel):
    argv_base: list[str]
    cli_interactive: str
    readonly_flags: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)


class BrokerConfig(BaseModel):
    inbox_poll_ms: int = 500
    subprocess_timeout_s: int = 600
    max_retries: int = 2


class TmuxConfig(BaseModel):
    session_name: str = "cross-harness"
    layout: str = "tiled"
    pane_mode: str = "interactive"


class ProjectConfig(BaseModel):
    name: str = "project"
    repo: str = "."


class WorkflowConfig(BaseModel):
    approval_mode: str = "manual"


class CrossHarnessConfig(BaseModel):
    project: ProjectConfig = Field(default_factory=ProjectConfig)
    agents: dict[str, AgentConfig] = Field(default_factory=dict)
    workflow: WorkflowConfig = Field(default_factory=WorkflowConfig)
    broker: BrokerConfig = Field(default_factory=BrokerConfig)
    tmux: TmuxConfig = Field(default_factory=TmuxConfig)


def default_config() -> CrossHarnessConfig:
    return CrossHarnessConfig(
        project=ProjectConfig(name="project"),
        agents={
            "claude": AgentConfig(
                argv_base=["claude", "-p"],
                cli_interactive="claude",
                readonly_flags=["--permission-mode", "plan"],
                roles=[TaskType.IMPL, TaskType.FIX, TaskType.REFACTOR],
            ),
            "codex": AgentConfig(
                argv_base=["codex", "exec"],
                cli_interactive="codex",
                readonly_flags=[],
                roles=[TaskType.REVIEW, TaskType.TEST],
            ),
            "gemini": AgentConfig(
                argv_base=["gemini", "-p"],
                cli_interactive="gemini",
                readonly_flags=["--approval-mode", "plan"],
                roles=[TaskType.RESEARCH, TaskType.REVIEW],
            ),
        },
    )


def load_config(path: Path) -> CrossHarnessConfig:
    if not path.exists():
        return default_config()
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return CrossHarnessConfig.model_validate(data)
