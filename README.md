# Cross Harness

> Semi-Autonomous Cross-Model Collaboration System
> Human-in-the-Loop 기반 멀티 AI CLI 협업 플랫폼

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

---

## 개요

Cross Harness는 여러 AI CLI 도구(Claude, Codex, Gemini)를 하나의 소프트웨어 프로젝트에서 조율하는 **반자동 협업 시스템**이다.

사람이 모든 단계 전환의 게이트키퍼 역할을 하면서, 각 에이전트의 강점을 조합하여 구현 → 리뷰 → 수정 사이클을 효율적으로 운영한다.

### 왜 필요한가

| 문제 | Cross Harness의 해결 |
|------|---------------------|
| AI CLI 도구들이 각각 독립 동작 | Hub-and-Spoke로 중앙 조율 |
| 수동 CLI 전환 + 복사/붙여넣기 | Broker가 자동 dispatch + artifact 전달 |
| 완전 자동화는 잘못된 방향으로 연쇄 진행 | 사람이 매 단계 승인 (Human-in-the-Loop) |
| 모델 간 충돌/무한 루프 | 직접 통신 금지, 모든 흐름은 사람 경유 |
| 디버깅/재현 어려움 | 모든 이벤트/결정이 artifact로 기록 |

### 핵심 가치

| 가치 | 설명 |
|------|------|
| **가시성** | 누가 뭘 하고 있는지, 어느 단계인지, 왜 넘어가는지가 항상 보인다 |
| **제어권** | 사람이 모든 단계 전환의 게이트키퍼 |
| **안정성** | 모델 간 직접 대화 없음 — 충돌/루프 방지 |
| **재현성** | 모든 이벤트/의견/결정이 artifact로 기록 |
| **단순성** | 공유 디렉터리에서 순차 작업 — sync 오버헤드 없음 |

---

## 아키텍처

```
┌─────────────────────────────────────────────────────────────────────┐
│                          tmux session                                │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │  Pane 0      │  │  Pane 1      │  │  Pane 2      │              │
│  │  claude      │  │  codex       │  │  gemini      │              │
│  │  (interactive│  │  (interactive│  │  (interactive│              │
│  │   CLI 대기)  │  │   CLI 대기)  │  │   CLI 대기)  │              │
│  └──────────────┘  └──────────────┘  └──────────────┘              │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  Pane 3: Human Control Console (TUI)                        │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘

                    ┌─────────────────────────┐
                    │   Broker (single-writer) │
                    │  Event Ingestion         │
                    │  State Manager           │
                    │  Dispatch Engine         │
                    └────────────┬────────────┘
                                 │
            ┌────────────────────┼────────────────────┐
            ▼                    ▼                    ▼
     claude -p ...        codex exec ...        gemini -p ...
     (subprocess)         (subprocess)          (subprocess)
```

### 컴포넌트

| 컴포넌트 | 역할 |
|---------|------|
| **Broker** | 이벤트/상태의 유일한 writer. inbox 감시, atomic write, dispatch 실행 |
| **Human Control Console** | TUI 중앙 관제판. 이벤트 표시, 사용자 결정 수신, 상태 대시보드 |
| **Agent Adapter** | CLI별 차이 추상화. 비대화형 호출, 세션 관리, read-only 강제, profile 주입 |
| **Dispatch Engine** | 프롬프트 생성, subprocess 실행, HEAD 비교 commit 감지, dirty tree 검증 |
| **Skill/MCP Registry** | 선언형 Skill/MCP 관리. registry → lock → vendor → generated profile |

### 실행 경로 (자동 + 수동 공존)

| 경로 | 방식 | 언제 |
|------|------|------|
| **자동** | Broker → 비대화형 subprocess (pane 밖) | Console에서 승인 시 |
| **수동** | 사람이 pane에서 직접 타이핑 | 직접 개입하고 싶을 때 |

- Broker working 중에는 `.workflow/lock`으로 수동 commit 차단 (pre-commit hook)
- 수동 작업도 1급 경로: `cross-harness begin` → 작업 → `cross-harness done`

---

## 빠른 시작

### 사전 요구사항

- Python 3.11+
- tmux
- AI CLI 도구 (하나 이상): `claude`, `codex`, `gemini`

### 설치

```bash
# (구현 예정)
pip install cross-harness
```

### 시작

```bash
cd your-project/

# 워크플로우 초기화 + Broker 시작 + tmux 4-pane 실행
cross-harness-start.sh
```

시작하면 tmux 4-pane 레이아웃이 열린다:

```
┌────────────────────────┬────────────────────────┐
│  claude (interactive)  │  codex (interactive)   │
├────────────────────────┼────────────────────────┤
│  gemini (interactive)  │  Human Control Console │
└────────────────────────┴────────────────────────┘
```

- Pane 0~2: 에이전트 interactive CLI (사람이 직접 타이핑 가능)
- Pane 3: Human Control Console (TUI) — 이벤트 피드, 결정 프롬프트, 상태 대시보드

---

## 사용법

### 기본 워크플로우: 구현 → 리뷰 → 수정

```
[Console에서]
1. Claude에게 구현 지시
2. Claude 완료 → Console에 결과 표시
3. "Codex 리뷰로" 선택
4. Codex 리뷰 완료 → finding 표시
5. "Claude에게 수정 보내기" 선택
6. 수정 완료 → 승인
```

모든 에이전트가 **같은 프로젝트 디렉터리**에서 작업하므로 sync가 필요 없다. Codex는 Claude의 commit을 바로 볼 수 있고, Claude는 Codex의 리뷰 결과(`.workflow/outputs/`)를 바로 참조한다.

### Auto Loop: 자동 반복 리파인먼트

사람이 매번 승인하지 않아도 되는 반복 개선 모드.

```bash
cross-harness loop \
  --worker claude \
  --reviewer codex \
  --judge claude \
  --max-iterations 3 \
  --prompt "auth phase 1: login endpoint + JWT 구현"
```

**구조**:

```
Worker (Claude) ──구현──▶ Reviewer (Codex) ──리뷰──▶ Judge (Claude, fresh session)
       ▲                                                      │
       └──────────── continue / stop / escalate ◀─────────────┘
```

- **Worker**: 코드 작업 (pane 세션과 별도)
- **Reviewer**: 결과 검증 (항상 fresh 세션)
- **Judge**: 수렴 판정만 수행 (항상 fresh new 세션, artifact만 보고 판단)

**자동 정지 규칙** (무한 핑퐁 방지):

| 규칙 | 조건 |
|------|------|
| 수렴 | `high=0 and medium<=1` |
| 정체 | 같은 finding 2회 연속 반복 |
| 무변화 | finding 수/심각도 2회 연속 변화 없음 |
| 한도 | `max_iterations` 도달 → 사람에게 넘김 |

Judge 판정: `continue` (계속) / `stop` (수렴 종료) / `escalate` (사람에게 넘김)

### 수동 개입

pane에서 직접 작업할 때:

```bash
# 1. dispatch 등록 (인과 추적 연결)
cross-harness begin --agent claude --type impl --task-id task_001

# 2. pane에서 직접 작업...

# 3a. 코드 변경 → git commit (post-commit hook이 자동으로 이벤트 발행)
# 3b. 비코드 작업 → done으로 완료
cross-harness done --dispatch-id dsp_002 --type review --summary "LGTM"
```

---

## CLI 명령어

### 오케스트레이션

| 명령 | 설명 |
|------|------|
| `cross-harness loop` | 자동 반복 루프 (Worker → Reviewer → Judge) |
| `cross-harness begin` | 수동 작업 dispatch 등록 |
| `cross-harness done` | 수동 비코드 작업 완료 |
| `cross-harness status` | 현재 상태 조회 (agent, dispatch, lock) |
| `cross-harness unlock [--force]` | stale lock 수동 제거 |
| `cross-harness broker` | Broker 프로세스 시작 |
| `cross-harness console` | Human Control Console TUI 시작 |

### Skill/MCP 관리

| 명령 | 설명 |
|------|------|
| `cross-harness skill add/enable/disable/remove/list` | Skill 관리 |
| `cross-harness mcp add/enable/disable/remove/list` | MCP 서버 관리 |
| `cross-harness sync [--prune]` | registry → lock → vendor → generated 동기화 |
| `cross-harness plan-sync` | dry-run: 변경 계획만 표시 |
| `cross-harness doctor skills/mcps` | 무결성/healthcheck 검사 |
| `cross-harness gc` | cache/staging 정리 |

---

## 설정

### .workflow/config.yaml

```yaml
project:
  name: "my-project"
  repo: "."

agents:
  claude:
    argv_base: ["claude", "-p"]
    cli_interactive: "claude"
    readonly_flags: ["--permission-mode", "plan"]
    roles: [impl, fix, refactor]
  codex:
    argv_base: ["codex", "exec"]
    cli_interactive: "codex"
    readonly_flags: []                   # exec review는 기본 read-only
    roles: [review, test]                # research 제외 (exec review는 코드 리뷰 전용)
  gemini:
    argv_base: ["gemini", "-p"]
    cli_interactive: "gemini"
    readonly_flags: ["--approval-mode", "plan"]
    roles: [research, review]

workflow:
  approval_mode: "manual"                # manual | auto | conditional

broker:
  inbox_poll_ms: 500
  subprocess_timeout_s: 600
  max_retries: 2

tmux:
  session_name: "cross-harness"
  layout: "tiled"
  pane_mode: "interactive"
```

### Skill/MCP Registry

```yaml
# .cross-harness/registry/skills.yaml
skills:
  - id: repo-review
    enabled: true
    source:
      type: git
      url: https://github.com/acme/agent-assets
      ref: v1.2.0
      path: skills/repo-review
    targets: [claude, codex, gemini]
    bundles: [base, review]

# .cross-harness/registry/mcps.yaml
mcps:
  - id: github
    enabled: true
    transport: stdio
    launcher:
      command: npx
      args: ["-y", "@modelcontextprotocol/server-github"]
      env:
        GITHUB_TOKEN: ${env:GITHUB_TOKEN}  # 평문 금지
    targets: [claude, codex]
    permissions:
      network: true
      read_paths: []
      write_paths: []
```

---

## 디렉터리 구조

### 런타임 (.workflow/)

Broker가 관리하는 오케스트레이션 상태. 변경 빈도 높음.

```
.workflow/
├── config.yaml              # 워크플로우 설정
├── events.jsonl             # 이벤트 로그 (append-only, Broker만 write)
├── state.json               # 현재 상태 (atomic rename)
├── inbox/                   # 이벤트 발행 요청 drop-box
├── tasks/                   # 태스크 정의
├── prompts/                 # dispatch별 프롬프트
├── outputs/                 # 에이전트 출력 artifact (리뷰/리서치 결과)
├── human-notes/             # 인간 의견 기록
├── lock                     # Broker working 중 존재
├── manual_dispatch.{agent}  # 수동 작업 dispatch (agent별)
└── processed_keys.json      # idempotency key 기록
```

### Skill/MCP 설정 (.cross-harness/)

선언형 설정. 변경 빈도 낮음. 사람은 `registry/`만 수정.

```
.cross-harness/
├── registry/                # 사람이 수정하는 source of truth
│   ├── skills.yaml
│   ├── mcps.yaml
│   └── bundles.yaml
├── lock/                    # resolve 결과 고정 (재현성)
├── vendor/                  # 외부 artifact 캐시
├── generated/               # CLI별 주입 설정 (자동 생성, 수정 금지)
├── runtime/                 # session/profile/lease 상태
└── locks/                   # management lock
```

### 소스코드

```
cross_harness/
├── src/cross_harness/
│   ├── cli.py               # CLI 엔트리포인트 (typer)
│   ├── broker/              # Broker (event_store, state_manager, inbox, idempotency)
│   ├── console/             # Human Control Console TUI (textual)
│   ├── dispatch/            # Dispatch Engine (engine, templates)
│   ├── adapters/            # Agent Adapters (base, claude, codex, gemini)
│   ├── workspace/           # 작업 디렉터리 관리
│   ├── events/              # 이벤트 데이터 모델 (pydantic)
│   ├── config/              # 설정 로더 (pydantic)
│   └── tmux/                # tmux 세션 관리
├── scripts/
│   ├── cross-harness-start.sh
│   └── post-commit-hook.sh
└── tests/
```

---

## 이벤트 시스템

모든 상태 변화는 이벤트로 기록된다. `dispatch_id` / `causation_id` / `attempt`로 인과 체인을 추적한다.

### 이벤트 타입

| Type | Source | 설명 |
|------|--------|------|
| `task_complete` | agent | 코드 변경 완료 (commit 있음) |
| `review_complete` | agent | 리뷰 완료 (output artifact) |
| `research_complete` | agent | 리서치 완료 (output artifact) |
| `task_failed` | agent | 작업 실패 |
| `task_needs_decision` | agent | 결과 모호, 사용자 판단 필요 |
| `human_decision` | human | 사용자 결정 |
| `human_note` | human | 사용자 의견 추가 |
| `task_dispatched` | human/system | 에이전트에게 task 전달 |
| `loop_started` | human | auto loop 시작 |
| `loop_verdict` | agent | Judge 판정 (continue/stop/escalate) |
| `loop_stopped` | system | 루프 종료 |

### source 규칙

- `agent` (claude/codex/gemini): 실제 작업 수행 주체
- `human`: 사용자의 결정/의견
- `system`: auto-approve 등 자동화된 결정

> Broker는 events.jsonl의 writer이지 source가 아니다.

### 완료 시그널 이원화

| 작업 유형 | 코드 변경 | 완료 시그널 |
|-----------|---------|-----------|
| impl, fix, refactor, test | O | git commit |
| review, research | X | `.workflow/outputs/` artifact |

---

## 세션 메모리 전략

CLI의 세션 메모리(대화 문맥)를 전략적으로 활용하되, artifact를 source of truth로 유지한다.

| 상황 | 세션 모드 |
|------|----------|
| 첫 dispatch | `new` (새 세션) |
| 같은 에이전트 연속 dispatch | `resume` (기본) |
| task_type 변경 / 이전 실패 / 사용자 요청 | `new` |
| Codex review | 항상 `new` (exec review가 resume 미지원) |
| Gemini | 항상 `new` (MVP, index drift 위험) |

**resume 시에도 항상 주입하는 explicit context**:
1. 이전 dispatch 요약
2. 관련 commit / output artifact
3. human note
4. 현재 목표와 종료 조건

> 세션 메모리는 편리하지만 불투명하다. artifact가 항상 source of truth이다.

### CLI별 실행 방식

| CLI | 비대화형 실행 | 세션 재개 | Read-only | MCP 주입 |
|-----|-------------|----------|-----------|---------|
| Claude | `claude -p` | `--resume <id>` | `--permission-mode plan` | `--mcp-config` (CLI 인자) |
| Codex | `codex exec` / `exec resume` / `exec review` | `exec resume <id>` | `exec review` (기본 read-only) | per-dispatch sandbox + HOME override |
| Gemini | `gemini -p` | MVP 미지원 | `--approval-mode plan` | per-dispatch sandbox + HOME override |

---

## 주요 설계 결정 (ADR 요약)

| # | 결정 | 핵심 이유 |
|---|------|----------|
| 001 | 공유 worktree 기본 | 사람이 게이트키퍼 → 순차 작업 → sync 불필요 |
| 002 | 완료 시그널 이원화 | 리뷰/리서치는 코드 변경 없음 → git history 오염 방지 |
| 003 | Single-Writer Broker | append 경쟁, last-write-wins 방지 |
| 004 | subprocess dispatch + interactive pane | 신뢰성 + 수동 개입 즉시 가능 |
| 009 | Repo lock | Broker working 중 수동 commit 차단 |
| 014 | resume + artifact 주입 | 문맥 유지 + source of truth 보장 |
| 015 | Registry-driven Skill/MCP | 선언형 설정, CLI별 generated config |
| 017 | MCP least privilege | bundle 기반 allowlist로 필요한 MCP만 |
| 019 | Auto loop Judge는 fresh new 세션 | 독립 관점에서 수렴 판정 |

> 전체 19건의 ADR은 [docs/HLD.md](docs/HLD.md)에서 확인.

---

## 기술 스택

| 컴포넌트 | 기술 |
|---------|------|
| Broker | Python 3.11+ / asyncio |
| Human Console | Python 3.11+ / textual |
| Event Bus | File-based (fswatch + jsonl + inbox) |
| Agent Adapter | Python (subprocess) |
| Layout Manager | tmux + bash |
| Config | YAML (PyYAML / pydantic) |

---

## 로드맵

### Phase 1: MVP

- [x] 설계 문서 (SRS / HLD / LLD)
- [ ] .workflow 구조 초기화, typer CLI skeleton
- [ ] Broker (single-writer): inbox, events.jsonl, state.json
- [ ] 비대화형 Dispatch: adapter, subprocess, 결과 캡처
- [ ] Human Console 기본 TUI
- [ ] tmux 4-pane + 통합 테스트
- [ ] Auto Loop (Claude ↔ Codex)

### Phase 2: 고도화

- 병렬 코드 수정 (임시 worktree)
- 자동 승인 규칙 엔진
- 커스텀 워크플로우 YAML
- Skill native materialization
- Gemini session resume
- 데스크톱 알림

### Phase 3: 확장

- 웹 대시보드
- Slack/Discord 연동
- 에이전트 플러그인 시스템
- 멀티 프로젝트 관리

### Phase 4: 지능화

- 에이전트 자동 선택
- 자연어 워크플로우 정의
- ML 기반 auto-approve 신뢰도

---

## 설계 문서

| 문서 | 내용 |
|------|------|
| [docs/SRS.md](docs/SRS.md) | 소프트웨어 요구사항 명세서 |
| [docs/HLD.md](docs/HLD.md) | 고수준 설계 — 아키텍처, 컴포넌트, ADR 19건 |
| [docs/LLD.md](docs/LLD.md) | 저수준 설계 — 스키마, 알고리즘, CLI 명령, Auto Loop |
| [docs/DESIGN.md](docs/DESIGN.md) | 아카이브 — v0.1~v0.8 설계 발전 이력 |

---

## 라이선스

MIT
