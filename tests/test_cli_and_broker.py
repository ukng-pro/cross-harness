from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from cross_harness.broker.runtime import Broker
from cross_harness.cli import app
from cross_harness.workspace import init_workflow


def test_init_creates_documented_layout(tmp_path: Path):
    runner = CliRunner()
    result = runner.invoke(app, ["init", str(tmp_path)])

    assert result.exit_code == 0
    assert (tmp_path / ".workflow" / "inbox").is_dir()
    assert (tmp_path / ".workflow" / "dead-letter").is_dir()
    assert (tmp_path / ".workflow" / "sandbox").is_dir()
    assert (tmp_path / ".workflow" / "events.jsonl").exists()
    assert (tmp_path / ".workflow" / "state.json").exists()
    assert (tmp_path / ".cross-harness" / "registry" / "skills.yaml").exists()
    assert (tmp_path / ".cross-harness" / "registry" / "mcps.yaml").exists()
    assert (tmp_path / ".cross-harness" / "registry" / "bundles.yaml").exists()
    assert (tmp_path / ".cross-harness" / "runtime" / "leases.json").exists()


def test_broker_processes_dispatch_event_and_updates_state(tmp_path: Path):
    init_workflow(tmp_path)
    inbox_path = tmp_path / ".workflow" / "inbox" / "evt_001.json"
    inbox_path.write_text(
        json.dumps(
            {
                "source": "human",
                "type": "task_dispatched",
                "dispatch_id": "dsp_001",
                "idempotency_key": "dispatch_dsp_001",
                "payload": {
                    "task_id": "task_001",
                    "task_type": "impl",
                    "target_agent": "claude",
                    "summary": "implement auth",
                },
            }
        )
    )

    broker = Broker(tmp_path)
    stats = broker.run_once()

    assert stats.processed == 1
    state = json.loads((tmp_path / ".workflow" / "state.json").read_text())
    assert state["event_count"] == 1
    assert state["agents"]["claude"]["status"] == "working"
    assert state["agents"]["claude"]["current_dispatch"] == "dsp_001"
    assert state["dispatch_index"]["dsp_001"]["agent"] == "claude"
    assert state["dispatch_index"]["dsp_001"]["status"] == "active"
    events = (tmp_path / ".workflow" / "events.jsonl").read_text().strip().splitlines()
    assert len(events) == 1


def test_broker_skips_duplicate_idempotency_keys(tmp_path: Path):
    init_workflow(tmp_path)
    inbox_dir = tmp_path / ".workflow" / "inbox"
    for name in ("a.json", "b.json"):
        (inbox_dir / name).write_text(
            json.dumps(
                {
                    "source": "human",
                    "type": "task_dispatched",
                    "dispatch_id": f"dsp_{name[0]}",
                    "idempotency_key": "duplicate_key",
                    "payload": {
                        "task_id": "task_001",
                        "task_type": "impl",
                        "target_agent": "claude",
                    },
                }
            )
        )

    broker = Broker(tmp_path)
    stats = broker.run_once()

    assert stats.processed == 1
    assert stats.skipped_duplicates == 1
    events = (tmp_path / ".workflow" / "events.jsonl").read_text().strip().splitlines()
    assert len(events) == 1
