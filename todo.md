# Cross Harness TODO

Derived from:
- `docs/SRS.md`
- `docs/HLD.md`
- `docs/LLD.md`
- `docs/corss-harness-skll-mcp-strategy.md`

Snapshot date: 2026-03-24

## Legend

- `[x]` done
- `[~]` partially done / local WIP exists
- `[ ]` not started

## Current Status

### Done So Far

- `[x]` Requirements and design docs split into `SRS/HLD/LLD`
- `[x]` Skill/MCP strategy document added
- `[x]` README localized with English as the primary entrypoint
- `[~]` Local Python package scaffold exists (`pyproject.toml`, `src/cross_harness/...`)
- `[~]` Local broker/storage primitives exist: event store, lock manager, state manager, idempotency store
- `[~]` Local workspace initializer exists for `.workflow/`

### Still Missing or Incomplete

- `[ ]` `cross_harness.cli` Typer entrypoint implementation
- `[ ]` Broker runtime loop
- `[ ]` Agent adapters for Claude / Codex / Gemini
- `[ ]` Dispatch engine and subprocess execution flow
- `[ ]` Human Console TUI
- `[ ]` Git hook installation and runtime integration
- `[ ]` tmux launcher and 4-pane orchestration
- `[ ]` Skill/MCP registry runtime
- `[ ]` Auto loop controller
- `[ ]` Test suite

### Local WIP Note

The current workspace contains untracked implementation files under `src/` and `pyproject.toml`.
This TODO reflects that local snapshot, not only the last pushed code.

## Phase 1: MVP Delivery

The MVP scope comes from `docs/SRS.md` section 9 and `docs/HLD.md` section 9.

### M1. Project Frame + CLI Skeleton

- `[~]` Add Python package scaffold
- `[ ]` Implement `cross_harness.cli` with Typer app
- `[ ]` Add CLI commands:
  - `init`
  - `broker`
  - `console`
  - `begin`
  - `done`
  - `unlock`
  - `loop`
  - `skill ...`
  - `mcp ...`
  - `sync`
  - `plan-sync`
  - `doctor`
  - `gc`
- `[~]` Initialize `.workflow/`
- `[ ]` Initialize `.cross-harness/`
- `[ ]` Create `.workflow/sandbox/` and other runtime subdirectories required by the docs
- `[ ]` Validate config loading from `.workflow/config.yaml`
- `[ ]` Wire package entrypoint so `cross-harness` actually runs after install

### M2. Broker (Single-Writer Core)

- `[~]` `events.jsonl` append store exists
- `[~]` `state.json` manager exists
- `[~]` `processed_keys.json` idempotency store exists
- `[~]` `.workflow/lock` manager exists
- `[ ]` Implement broker main loop to poll `.workflow/inbox/`
- `[ ]` Add inbox validation and dead-letter handling
- `[ ]` Enforce single writer for all state/event mutations
- `[ ]` Strengthen atomic write guarantees:
  - `fsync` for state temp file before rename
  - `fsync` for idempotency file before rename
  - atomic lock acquisition instead of `exists()` then write
- `[ ]` Update `dispatch_index` on dispatch lifecycle transitions
- `[ ]` Persist `active_loop` state
- `[ ]` Add stale lock recovery on broker startup
- `[ ]` Add structured broker logging

### M3. Non-Interactive Dispatch

- `[ ]` Define `AgentAdapter` base interface
- `[ ]` Implement Claude adapter
- `[ ]` Implement Codex adapter
- `[ ]` Implement Gemini adapter
- `[ ]` Implement session mode resolution:
  - Claude: `new` / `resume`
  - Codex review: always fresh
  - Gemini: always new in MVP
- `[ ]` Build final subprocess command per CLI
- `[ ]` Capture stdout / stderr / exit code / duration
- `[ ]` Detect commits using `pre_head` vs `post_head`
- `[ ]` Detect `commit_count > 1` and emit `task_needs_decision`
- `[ ]` Parse session IDs from CLI output where supported
- `[ ]` Enforce read-only flags for review / research dispatches
- `[ ]` Create per-dispatch sandbox and `HOME` override for Codex / Gemini
- `[ ]` Inject explicit artifact context on every automatic dispatch
- `[ ]` Perform post-run dirty tree verification before final event write

### M4. Human Console (TUI)

- `[ ]` Build Textual app skeleton
- `[ ]` Show latest events and current agent status
- `[ ]` Show lock state and active dispatch
- `[ ]` Prompt for human decision / human note
- `[ ]` Show pending `task_needs_decision`
- `[ ]` Show auto-loop iteration trend and verdict summary
- `[ ]` Support pause / abort actions for active auto loop
- `[ ]` Display broker/recovery warnings clearly

### M5. tmux Layout + End-to-End Integration

- `[ ]` Implement `cross-harness-start.sh`
- `[ ]` Start 4 panes:
  - Claude interactive pane
  - Codex interactive pane
  - Gemini interactive pane
  - Human Control Console
- `[ ]` Export `CROSS_HARNESS_AGENT` correctly per pane
- `[ ]` Keep pane sessions interactive and separate from auto-dispatch subprocesses
- `[ ]` Verify manual typing does not interfere with broker-owned dispatch
- `[ ]` Run one full end-to-end flow:
  - Claude impl
  - Codex review
  - Human decision
  - Claude fix

### MVP Cross-Cutting TODO

#### Manual Path

- `[ ]` Implement `cross-harness begin`
- `[ ]` Write agent-scoped `manual_dispatch.{agent}`
- `[ ]` Implement post-commit hook generation/install
- `[ ]` Implement pre-commit hook generation/install
- `[ ]` Implement `cross-harness done --dispatch-id ...`
- `[ ]` Ensure inbox write succeeds before manual dispatch cleanup

#### Event / State Schema Alignment

- `[~]` Core event/state models exist
- `[ ]` Tighten model validation to match documented schema
- `[ ]` Add missing loop-related state fields
- `[ ]` Add event builder helpers for all event types
- `[ ]` Guarantee `source`, `type`, `task_type` use strict enums/contracts

#### Session Memory Strategy

- `[~]` Basic session fields exist in local state model
- `[ ]` Persist session state through real dispatch execution
- `[ ]` Resume Claude sessions after first automatic dispatch
- `[ ]` Re-inject summary/artifacts/human notes on resume
- `[ ]` Expose session override controls in Console

#### Skill / MCP Registry (MVP subset)

- `[ ]` Create `.cross-harness/registry/{skills,mcps,bundles}.yaml`
- `[ ]` Create lock files and generated profile directories
- `[ ]` Implement manifest validation
- `[ ]` Implement resolve/materialize/build-profile pipeline
- `[ ]` Implement lease tracking in `.cross-harness/runtime/leases.json`
- `[ ]` Implement `sync`, `sync --prune`, `plan-sync`
- `[ ]` Implement `skill add/enable/disable/remove/list`
- `[ ]` Implement `mcp add/enable/disable/remove/list`
- `[ ]` Implement prompt-module materialization only
- `[ ]` Implement least-privilege bundle selection

#### Auto Loop MVP

- `[ ]` Implement `cross-harness loop`
- `[ ]` Support MVP pair only:
  - worker = Claude
  - reviewer = Codex
  - judge = Claude or Codex
- `[ ]` Persist `active_loop` in `state.json`
- `[ ]` Emit loop events:
  - `loop_started`
  - `loop_iteration`
  - `loop_verdict`
  - `loop_stopped`
  - `loop_max_reached`
  - `loop_paused`
  - `loop_aborted`
- `[ ]` Implement early stop rules:
  - `high == 0 and medium <= 1`
  - same findings repeated
  - no progress for 2 consecutive comparisons
  - max iterations reached
- `[ ]` Implement reviewer JSON output contract and parsing
- `[ ]` Guard parse failures so they escalate to Judge instead of auto-stop
- `[ ]` Show finding trend in Console

#### Tests and Verification

- `[ ]` Add pytest test suite
- `[ ]` Add `pytest-asyncio` if `asyncio_mode = auto` remains
- `[ ]` Add unit tests for:
  - event store append/read
  - state manager atomic save
  - idempotency store
  - lock stale detection
  - session mode resolution
  - CLI command building
  - finding parser / early stop rules
- `[ ]` Add integration tests for:
  - `init`
  - manual path (`begin -> commit -> hook`)
  - broker inbox processing
  - auto loop
  - stale lock recovery

## Phase 2: Hardening and Advanced Workflow

- `[ ]` Conditional auto-approve rules engine
- `[ ]` Custom workflow YAML definition and execution
- `[ ]` Temporary git worktree support for parallel code modification
- `[ ]` Parallel dispatch orchestration
- `[ ]` Agent performance / quality metrics collection
- `[ ]` Desktop notifications
- `[ ]` Native skill materialization where stable
- `[ ]` Bundle `by_mode` policy axis
- `[ ]` Revisit multi-session / fork state if needed
- `[ ]` Revisit Gemini resume when stable UUID-based resume exists

## Phase 3: Expansion

- `[ ]` Web dashboard
- `[ ]` Slack / Discord integration
- `[ ]` Agent plugin system
- `[ ]` Workflow template library
- `[ ]` Multi-project management

## Phase 4: Intelligence

- `[ ]` Automatic agent selection
- `[ ]` Natural-language workflow definition
- `[ ]` Learning-based auto-approve confidence tuning
- `[ ]` Cross-model output quality comparison and analytics

## Recommended Implementation Order

1. Finish M1 so the declared CLI actually runs.
2. Finish M2 broker loop and make file durability match the design.
3. Finish M3 adapters and dispatch flow.
4. Implement manual path (`begin`, hooks, `done`) before full Console polish.
5. Implement M4 Console and decision handling.
6. Implement M5 tmux bootstrap and end-to-end MVP flow.
7. Implement Skill/MCP registry MVP.
8. Implement Auto loop MVP.
9. Add tests and release checklist.

## Release Readiness Checklist

- `[ ]` `cross-harness init` works in a clean repo
- `[ ]` `cross-harness broker` runs and processes inbox events
- `[ ]` `cross-harness console` shows live state
- `[ ]` Manual code path works with hooks
- `[ ]` Automatic Claude dispatch works
- `[ ]` Automatic Codex review works
- `[ ]` Automatic Gemini research works
- `[ ]` Skill/MCP sync works for MVP prompt-module flow
- `[ ]` Auto loop works for Claude impl ↔ Codex review
- `[ ]` Stale lock recovery works
- `[ ]` Dirty tree protection works
- `[ ]` README quickstart matches actual commands
- `[ ]` Tests pass in CI
