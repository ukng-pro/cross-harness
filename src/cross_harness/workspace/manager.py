"""Workspace initialisation and ID generation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

from cross_harness.config.loader import CrossHarnessConfig, default_config
from cross_harness.config.state import AgentState, WorkflowState

_COUNTER = 0


def _next_counter() -> int:
    global _COUNTER
    _COUNTER += 1
    return _COUNTER


def generate_event_id() -> str:
    now = datetime.now(timezone.utc)
    return f"evt_{now.strftime('%Y%m%d_%H%M%S')}_{_next_counter():03d}"


def generate_dispatch_id() -> str:
    now = datetime.now(timezone.utc)
    return f"dsp_{now.strftime('%Y%m%d_%H%M%S')}_{_next_counter():03d}"


WORKFLOW_SUBDIRS = [
    "inbox",
    "tasks",
    "prompts",
    "outputs",
    "human-notes",
    "dead-letter",
    "sandbox",
]

REGISTRY_FILES = {
    "skills.yaml": {"skills": []},
    "mcps.yaml": {"mcps": []},
    "bundles.yaml": {
        "bundles": {},
        "policy": {"defaults": [], "by_agent": {}, "by_task_type": {}},
    },
}

RUNTIME_FILES = {
    "leases.json": {"leases": []},
}


def _cross_harness_layout(project_root: Path) -> Path:
    return project_root / ".cross-harness"


def init_workflow(project_root: Path, config: CrossHarnessConfig | None = None) -> Path:
    """Create .workflow/ and .cross-harness/ directory trees."""
    config = config or default_config()
    wf = project_root / ".workflow"
    wf.mkdir(parents=True, exist_ok=True)

    for sub in WORKFLOW_SUBDIRS:
        (wf / sub).mkdir(exist_ok=True)

    # config.yaml
    config_path = wf / "config.yaml"
    if not config_path.exists():
        with open(config_path, "w") as f:
            yaml.dump(config.model_dump(), f, default_flow_style=False, allow_unicode=True)

    # events.jsonl
    events_path = wf / "events.jsonl"
    if not events_path.exists():
        events_path.touch()

    # state.json
    state_path = wf / "state.json"
    if not state_path.exists():
        agents = {name: AgentState().model_dump() for name in config.agents}
        initial = WorkflowState(agents=agents)
        with open(state_path, "w") as f:
            json.dump(initial.model_dump(), f, indent=2)

    # processed_keys.json
    keys_path = wf / "processed_keys.json"
    if not keys_path.exists():
        with open(keys_path, "w") as f:
            json.dump([], f)

    ch = _cross_harness_layout(project_root)
    for relative in (
        "registry",
        "lock",
        "vendor",
        "generated/claude/profiles",
        "generated/codex/profiles",
        "generated/gemini/profiles",
        "runtime",
        "locks",
    ):
        (ch / relative).mkdir(parents=True, exist_ok=True)

    registry_dir = ch / "registry"
    for filename, payload in REGISTRY_FILES.items():
        path = registry_dir / filename
        if not path.exists():
            with open(path, "w") as f:
                yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=True)

    runtime_dir = ch / "runtime"
    for filename, payload in RUNTIME_FILES.items():
        path = runtime_dir / filename
        if not path.exists():
            with open(path, "w") as f:
                json.dump(payload, f, indent=2)

    return wf


def ensure_workflow_exists(project_root: Path) -> Path:
    wf = project_root / ".workflow"
    if not wf.is_dir():
        raise FileNotFoundError(f".workflow/ not found in {project_root}. Run 'cross-harness init'.")
    return wf


def ensure_cross_harness_exists(project_root: Path) -> Path:
    ch = _cross_harness_layout(project_root)
    if not ch.is_dir():
        raise FileNotFoundError(
            f".cross-harness/ not found in {project_root}. Run 'cross-harness init'."
        )
    return ch
