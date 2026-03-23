"""Typer CLI entrypoint for cross-harness."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import typer

from cross_harness.broker import Broker
from cross_harness.broker.lock import LockManager
from cross_harness.broker.state_manager import StateManager
from cross_harness.workspace import ensure_workflow_exists, init_workflow

app = typer.Typer(add_completion=False, no_args_is_help=True)


def _project_root(path: Path | None) -> Path:
    return (path or Path.cwd()).resolve()


def _configure_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


@app.command()
def init(
    path: Path = typer.Argument(Path("."), exists=False, file_okay=False, dir_okay=True),
):
    """Initialize .workflow and .cross-harness directories."""
    project_root = _project_root(path)
    workflow_dir = init_workflow(project_root)
    typer.echo(f"Initialized cross-harness workspace in {workflow_dir}")


@app.command()
def broker(
    path: Path = typer.Option(Path("."), "--path", file_okay=False, dir_okay=True),
    config: Path | None = typer.Option(None, "--config"),
    once: bool = typer.Option(False, "--once", help="Process current inbox files and exit."),
    verbose: bool = typer.Option(False, "--verbose"),
):
    """Run the single-writer broker."""
    _configure_logging(verbose)
    project_root = _project_root(path)
    broker_runtime = Broker(project_root=project_root, config_path=config)
    if once:
        stats = broker_runtime.run_once()
        typer.echo(
            json.dumps(
                {
                    "processed": stats.processed,
                    "skipped_duplicates": stats.skipped_duplicates,
                    "moved_to_dead_letter": stats.moved_to_dead_letter,
                }
            )
        )
        raise typer.Exit(code=0)
    broker_runtime.run_forever()


@app.command()
def status(
    path: Path = typer.Option(Path("."), "--path", file_okay=False, dir_okay=True),
):
    """Show current workflow status."""
    project_root = _project_root(path)
    workflow_dir = ensure_workflow_exists(project_root)
    lock_manager = LockManager(workflow_dir)
    state = StateManager(workflow_dir / "state.json").load()

    typer.echo(f"workflow_status: {state.workflow_status}")
    typer.echo(f"event_count: {state.event_count}")
    typer.echo(f"last_event_id: {state.last_event_id or '-'}")
    if lock_manager.is_locked():
        typer.echo(f"lock: {json.dumps(lock_manager.read_lock(), ensure_ascii=False)}")
    else:
        typer.echo("lock: none")
    for name, agent in state.agents.items():
        typer.echo(
            f"agent {name}: status={agent.status} dispatch={agent.current_dispatch or '-'} "
            f"session={agent.session_id or '-'}"
        )


@app.command()
def unlock(
    path: Path = typer.Option(Path("."), "--path", file_okay=False, dir_okay=True),
    force: bool = typer.Option(False, "--force", help="Remove lock without PID check."),
):
    """Remove a stale workflow lock."""
    project_root = _project_root(path)
    workflow_dir = ensure_workflow_exists(project_root)
    lock_manager = LockManager(workflow_dir)
    if not lock_manager.is_locked():
        typer.echo("No lock present.")
        raise typer.Exit(code=0)

    if force:
        lock_manager.release()
        typer.echo("Lock removed.")
        raise typer.Exit(code=0)

    if lock_manager.check_stale():
        typer.echo("Stale lock removed.")
        raise typer.Exit(code=0)

    typer.echo("Active lock is still held; use --force to remove it.", err=True)
    raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
