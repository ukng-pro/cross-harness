# Cross Harness

[English](README.md) | [中文](README.zh.md) | [한국어](README.ko.md)

> Semi-autonomous cross-model collaboration for AI CLIs, with a human gate in the middle.

![License](https://img.shields.io/badge/license-MIT-blue.svg)

## Status

This repository is currently design-first.

- The implementation is not complete yet.
- The source of truth today is the design set in [`docs/SRS.md`](docs/SRS.md), [`docs/HLD.md`](docs/HLD.md), and [`docs/LLD.md`](docs/LLD.md).
- The README describes the intended system and the current design direction, not a released product.

## What Cross Harness Is

Cross Harness coordinates multiple AI CLI agents such as Claude, Codex, and Gemini around one software project without letting them talk to each other directly.

The system uses a hub-and-spoke model:

- A single Broker records events and state.
- A Human Control Console stays in the middle of every transition.
- Agents work on the same project directory by default.
- Reviews and research are captured as artifacts.
- Code changes are captured as commits.

The goal is to keep the strengths of multi-model collaboration while avoiding silent drift, infinite ping-pong, and hard-to-debug autonomous behavior.

## Why It Exists

Using several AI CLIs on one project usually means manual copy/paste, ad-hoc routing, and poor traceability. Full autonomy is attractive, but in practice it creates real problems:

- agents can continue in the wrong direction without a checkpoint
- model-to-model conflicts are difficult to reconcile automatically
- token and time costs can balloon in loops
- decisions become hard to audit and reproduce

Cross Harness is designed around a simpler rule: keep the human as the gatekeeper, and make every step visible.

## Core Ideas

### 1. Human-in-the-loop orchestration

The default flow is:

1. One agent finishes work.
2. The Broker records the result.
3. The Human Control Console asks what should happen next.
4. The next agent runs only after that decision.

This keeps routing explicit and recoverable.

### 2. Shared worktree by default

Agents use the same project directory for the normal sequential flow:

- implementation
- review
- fix
- approval

That means a reviewer can immediately inspect the latest commit, and the worker can immediately consume the reviewer artifact. Temporary git worktrees are reserved for exceptional parallel code-edit cases only.

### 3. Interactive panes plus subprocess dispatch

The intended UI is a 4-pane `tmux` session:

- `claude`
- `codex`
- `gemini`
- Human Control Console

Those panes remain available for manual intervention, but automatic work runs through separate non-interactive subprocesses managed by the Broker. This avoids polluting the operator's live pane sessions.

### 4. Artifact-first memory

Session memory is useful, but it is not trusted as the source of truth.

Cross Harness treats these as canonical:

- commits
- review artifacts
- research artifacts
- human notes
- event logs

For agents that support stable resume, the Broker can resume sessions, but it still reinjects explicit context on every dispatch.

### 5. Auto loop with hard stop rules

The design also supports an auto-loop mode for controlled refinement, for example:

- Worker: Claude
- Reviewer: Codex
- Judge: Claude or Codex

The Judge does not implement or review. It only decides `continue`, `stop`, or `escalate` from artifacts, diffs, and finding summaries.

To avoid infinite loops, the design uses explicit stop rules such as:

- `high=0 and medium<=1`
- repeated findings
- no progress across consecutive iterations
- max iteration cap

## Architecture Summary

```text
Interactive panes (tmux)
  Claude | Codex | Gemini | Human Control Console

                ↓

Broker (single writer)
  - event ingestion
  - state management
  - dispatch engine

                ↓

Agent subprocesses
  - claude -p
  - codex exec / exec review
  - gemini -p
```

Key constraints in the design:

- no direct model-to-model chat
- one shared project directory by default
- Broker is the only writer for `events.jsonl` and `state.json`
- manual intervention is allowed, but still tracked
- repo lock prevents manual commits during Broker-controlled execution

## Repository Layout

Current repository contents:

```text
.
├── README.md
├── README.zh.md
├── README.ko.md
└── docs/
    ├── SRS.md
    ├── HLD.md
    ├── LLD.md
    ├── DESIGN.md
    └── corss-harness-skll-mcp-strategy.md
```

Document roles:

- [`docs/SRS.md`](docs/SRS.md): requirements and product behavior
- [`docs/HLD.md`](docs/HLD.md): architecture, components, ADRs
- [`docs/LLD.md`](docs/LLD.md): schemas, algorithms, command contracts
- [`docs/DESIGN.md`](docs/DESIGN.md): archived design evolution
- [`docs/corss-harness-skll-mcp-strategy.md`](docs/corss-harness-skll-mcp-strategy.md): detailed Skill/MCP strategy

## Planned Capabilities

The current design package covers these major areas:

- Broker-based orchestration with a single-writer event model
- human approval and routing through a TUI console
- interactive pane workflow plus subprocess execution
- manual takeover path with tracked causality
- session-memory policy per CLI
- Skill/MCP registry with generated per-agent profiles
- auto-loop refinement with Judge-controlled convergence

## Recommended Reading Order

If you are new to the project:

1. Read [`docs/SRS.md`](docs/SRS.md) for the product shape.
2. Read [`docs/HLD.md`](docs/HLD.md) for the architecture and design decisions.
3. Read [`docs/LLD.md`](docs/LLD.md) for concrete schemas, commands, and algorithms.

If you only want the Skill/MCP material, go straight to [`docs/corss-harness-skll-mcp-strategy.md`](docs/corss-harness-skll-mcp-strategy.md).

## Current Scope and Caveats

This repository should not yet be read as a production-ready CLI implementation.

In particular:

- install commands shown in older drafts are not shipped here
- the `tmux` orchestration flow is specified, not fully implemented
- the README reflects the current design intent after iterative review

## License

MIT
