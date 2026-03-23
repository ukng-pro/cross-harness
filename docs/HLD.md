# Cross Harness — 고수준 설계 (HLD)

> Semi-Autonomous Cross-Model Collaboration System
> Human-in-the-Loop 기반 멀티 AI CLI 협업 플랫폼

**버전**: 1.0.0
**작성일**: 2026-03-23
**관련 문서**: [SRS.md](./SRS.md) · [LLD.md](./LLD.md)

---

## 목차

1. [시스템 아키텍처](#1-시스템-아키텍처)
2. [컴포넌트 책임](#2-컴포넌트-책임)
3. [이벤트 시스템 설계](#3-이벤트-시스템-설계)
4. [데이터 흐름](#4-데이터-흐름)
5. [디렉터리 레이아웃](#5-디렉터리-레이아웃)
6. [워크플로우 패턴 (아키텍처 관점)](#6-워크플로우-패턴)
7. [기술 스택](#7-기술-스택)
8. [소스코드 구조](#8-소스코드-구조)
9. [MVP 마일스톤](#9-mvp-마일스톤)
10. [설계 결정 기록 (ADR)](#10-설계-결정-기록)

---

## 1. 시스템 아키텍처

### 1.1 전체 구조도

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
                    │                         │
                    │  ┌───────────────────┐  │
                    │  │ Event Ingestion   │  │  ← 이벤트 수신, 검증, 중복 제거
                    │  ├───────────────────┤  │
                    │  │ State Manager     │  │  ← state.json atomic update
                    │  ├───────────────────┤  │
                    │  │ Dispatch Engine   │  │  ← 비대화형 subprocess 실행
                    │  └───────────────────┘  │
                    └────────────┬────────────┘
                                 │
            ┌────────────────────┼────────────────────┐
            ▼                    ▼                    ▼
  ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
  │ claude -p ...    │ │ codex exec ...   │ │ gemini -p ...    │
  │ (subprocess)     │ │ (subprocess)     │ │ (subprocess)     │
  │  순차: 공유 dir  │ │  순차: 공유 dir  │ │  순차: 공유 dir  │
  │  병렬: 임시 wt   │ │  병렬: 임시 wt   │ │  병렬: 임시 wt   │
  └──────────────────┘ └──────────────────┘ └──────────────────┘

                    모든 에이전트의 작업 디렉터리:
                    ┌──────────────────────┐
                    │  project-root/       │  ← 공유 (기본)
                    │  ├── src/            │
                    │  ├── .workflow/       │  ← 오케스트레이션 (Broker만 쓰기)
                    │  └── .worktrees/      │  ← 병렬 코드 수정 시에만 임시 생성
                    └──────────────────────┘
```

### 1.2 계층 구조

```
Layer 5: Human Control Console (TUI)     ← 사용자 인터페이스
Layer 4: Broker (single-writer)          ← 이벤트 관리 + 상태 관리
Layer 3: Dispatch Engine                 ← 비대화형 subprocess 실행
Layer 2: Agent Adapters                  ← CLI별 호출 규격 추상화
Layer 1: AI CLI Tools                    ← claude -p, codex exec, gemini -p
Layer 0: Shared Project Dir              ← 공유 작업 공간 (병렬 시 임시 worktree)
```

### 1.3 tmux pane의 이중 역할

3개 pane에는 처음부터 interactive CLI가 떠 있다. 자동 dispatch(Broker subprocess)와 수동 조작(pane)이 공존한다.

| 경로 | 방식 | 언제 |
|------|------|------|
| **자동** | Broker → 비대화형 subprocess (pane 밖) | Human Console에서 승인 시 |
| **수동** | 사람이 pane에 직접 타이핑 | 사람이 직접 개입하고 싶을 때 |

**Broker working 중 repo lock**: Broker subprocess 실행 중 `.workflow/lock` 존재 → pre-commit hook이 수동 commit 차단. Lock은 모든 검증 + 최종 이벤트 기록 완료 후에만 해제.

---

## 2. 컴포넌트 책임

### 2.1 Broker (Single-Writer)

시스템의 핵심 프로세스. events.jsonl과 state.json에 대한 유일한 writer.

**책임**:
- **이벤트 수신**: inbox 디렉터리 감시, 이벤트 요청 파일 수거
- **검증 및 중복 제거**: idempotency key로 동일 이벤트 재발행 방지
- **이벤트 기록**: events.jsonl에 atomic append
- **상태 갱신**: state.json을 atomic rename으로 갱신
- **Console 알림**: 새 이벤트를 Human Control Console에 push
- **Repo lock 관리**: subprocess 실행 전 lock 생성, 최종 이벤트 기록 후 삭제

**Inbox 패턴**: 외부 컴포넌트는 `.workflow/inbox/`에 JSON 파일을 drop → Broker가 수거 → 검증 → 기록. Broker만 events.jsonl/state.json을 쓰므로 write 경쟁이 없다.

### 2.2 Agent Adapter

각 CLI 도구의 차이를 추상화하는 래퍼 레이어.

**책임**:
- CLI별 비대화형 호출 인터페이스 통일
- 프로세스 수준 cwd로 CLI별 디렉터리 옵션 차이 흡수
- task_type에 따른 read-only 플래그/서브커맨드 자동 부여
- **CLI별 세션 resume 메커니즘 추상화** (CLI마다 resume 인터페이스가 다름)
- **MCP/Skill profile 주입 추상화**: Claude는 CLI 인자, Codex/Gemini는 per-dispatch sandbox + env override

**에이전트 식별**: Broker가 subprocess를 직접 실행하므로 Broker가 어떤 에이전트인지 이미 안다. 수동 개입 시에는 `CROSS_HARNESS_AGENT` 환경변수로 식별.

**완료 감지 (단일 경로)**: Broker가 subprocess를 실행하고 완료를 관찰하므로 별도 감지 메커니즘 불필요. events.jsonl writer는 항상 Broker이며, 중복이 구조적으로 불가능하다.

### 2.3 세션 메모리 모델

에이전트 CLI의 세션 메모리(대화 문맥)를 전략적으로 활용한다.

```
                    ┌─────────────┐
                    │  Artifact   │  ← Source of Truth
                    │  (outputs/, │     (commit, output artifact,
                    │   commits)  │      human note)
                    └──────┬──────┘
                           │ 항상 주입
                           ▼
┌──────────┐      ┌─────────────────┐      ┌──────────┐
│ 이전     │      │   Dispatch      │      │ CLI      │
│ dispatch │─────▶│   프롬프트 생성  │─────▶│ Session  │
│ 요약     │      │   (resume +     │      │ (불투명) │
└──────────┘      │    explicit)    │      └──────────┘
                  └─────────────────┘
```

**세 가지 메모리 경로**:

| 경로 | 세션 관리 | 메모리 소유자 |
|------|----------|-------------|
| interactive pane | CLI의 native 세션 (사람이 관리) | CLI 자체 |
| 자동 dispatch | Broker가 session_id로 resume 관리 | Broker + CLI |
| artifact | `.workflow/outputs/`, git commit | Broker (source of truth) |

**세션 모드 결정 로직** (Broker Dispatch Engine 담당):

```
첫 dispatch (해당 agent에 session_id 없음)
  → mode: new → 새 세션 생성 → session_id 저장

2회 이후 dispatch (session_id 있음)
  → 기본: mode: resume
  → 예외 감지 시 mode: new
    - task_type이 이전과 크게 다름 (impl → review 등)
    - 이전 세션이 task_failed로 끝남
    - 사용자가 Console에서 "fresh session" 요청
    - 수동 개입(begin/done) 후 문맥이 틀어짐

※ fork(기존 세션 복제 후 분기)는 MVP에서 지원하지 않는다.
  state에 agent당 session_id가 하나이므로 분기 세션의 수명 관리가
  복잡해진다. Phase 2에서 multi-session state 도입 시 재검토.

CLI별 resume 예외:
  - Codex review: 항상 fresh (exec review가 resume 미지원, fresh 관점이 리뷰에 바람직)
  - Gemini: MVP에서 resume 비지원 (index 기반 --resume이 pane 세션과 drift 위험)
    → 모든 Gemini dispatch는 new, 이전 문맥은 artifact 주입으로 보상
```

**resume 시에도 항상 주입하는 explicit context**:
1. 이전 dispatch 요약 (무엇을 했고 결과가 무엇이었는지)
2. 관련 commit hash / output artifact 내용
3. human note (사용자가 추가한 의견)
4. 현재 목표와 종료 조건

> 세션 메모리는 편리하지만 불투명하다. artifact가 항상 source of truth이다.

**CLI별 resume 구현은 Adapter 책임**: CLI마다 resume 지원 수준이 다르다. Claude만 `--resume <session_id>`로 안정적으로 resume을 지원한다. Codex review는 항상 fresh, Gemini는 MVP에서 resume 비지원 (항상 new). 설계에서는 resume policy를 정의하고, CLI별 구현과 제약은 adapter가 추상화한다.

### 2.4 Skill/MCP Registry

에이전트에게 주입할 Skill과 MCP를 선언형으로 관리하는 컴포넌트.

**핵심 설계: Registry-Driven**

```
.cross-harness/           ← Skill/MCP 설정 (선언적, .workflow/와 분리)
├── registry/             ← 사람이 수정하는 source of truth
│   ├── skills.yaml
│   ├── mcps.yaml
│   └── bundles.yaml
├── lock/                 ← resolve 결과 고정 (재현성)
├── vendor/               ← 외부 artifact 캐시
├── generated/            ← CLI별 실제 주입 설정 (자동 생성, 수정 금지)
│   ├── claude/profiles/
│   ├── codex/profiles/
│   └── gemini/profiles/
├── runtime/              ← session/profile/lease 상태
└── locks/                ← management lock (sync/prune 상호배제)
```

**`.cross-harness/`와 `.workflow/`의 관계**:

| 디렉터리 | 성격 | 변경 빈도 | 주체 |
|----------|------|----------|------|
| `.cross-harness/` | 선언적 설정 (Skill/MCP registry, profile) | 낮음 (setup/config 시) | 사람 (registry) + sync 명령 (generated) |
| `.workflow/` | 런타임 오케스트레이션 (이벤트, 상태, dispatch) | 높음 (매 dispatch마다) | Broker |

**Skill은 Cross Harness 추상화**:

Skill은 CLI의 native 개념과 1:1 대응하지 않는다. 실제 투영(materialization) 방식은 adapter가 결정한다.

| CLI | Native 지원 | MVP materialization | Phase 2+ |
|-----|------------|-------------------|----------|
| Claude | skill/plugin/prompt module | prompt module | native 우선, prompt fallback |
| Codex | native 개념 미확정 | prompt module | prompt module (당분간) |
| Gemini | skill/extension | prompt module | native 우선, prompt fallback |

> MVP에서는 모든 CLI에 prompt module로 통일한다. native materialization은 CLI별 안정성이 확인된 후 Phase 2에서 도입한다.

**MCP는 Least Privilege**:

dispatch 시 bundle 정책에 따라 필요한 MCP만 allowlist로 주입한다.

```
Bundle 선택 (dispatch 시):
  defaults + by_agent[agent] + by_task_type[task_type]
  → stable dedupe
  → 해당 bundle에 포함된 skills/mcps만 generated profile에 포함
```

**Disable First, Prune Later**:

삭제는 2단계. active dispatch가 참조 중인 리소스를 즉시 삭제하면 안 된다.

```
1. registry에서 enabled: false → 다음 sync부터 generated profile에서 제외
2. sync --prune → active lease가 없는 vendor/profile만 물리 삭제
```

**Profile Activation at Dispatch**:

dispatch 시점에 registry를 다시 읽지 않고, 미리 generated된 profile을 사용한다.

```
Dispatch 시:
  → bundle 선택 (agent + task_type)
  → 해당 bundle의 generated profile 확인 (없으면 build)
  → profile lease 획득 (prune 보호)
  → per-dispatch sandbox 생성
  → adapter.inject_profile(profile_dir, sandbox)로 설정 배치 + env override 획득
  → adapter.build_command()로 최종 커맨드 구성
  → subprocess 실행 (env override 포함)
  → dispatch 완료 시 lease 해제 + sandbox 삭제
```

**Lock 계층 (2개, 독립)**:

| Lock | 위치 | 용도 | 소유자 |
|------|------|------|--------|
| Dispatch lock | `.workflow/lock` | subprocess 실행 중 수동 commit 차단 | Broker |
| Management lock | `.cross-harness/locks/registry.lock` | sync/prune/add 상호배제 | CLI 명령 |

두 lock은 독립이다. sync와 dispatch가 동시에 일어날 수 있지만, sync는 generated profile을 versioned dir로 생성하고 pointer를 swap하므로 running dispatch의 기존 profile을 깨지 않는다.

### 2.5 Human Control Console

시스템의 중앙 관제판. TUI(textual)로 구현.

**책임**:
- events.jsonl과 state.json을 읽기만 함 (Console은 reader)
- 사용자 결정을 Broker에게 요청 (inbox에 human_decision 이벤트 drop)

**기술 스택**: Python textual (MVP 추천)

### 2.6 Dispatch Engine

Broker 내부 컴포넌트.

**책임**:
- 사용자 선택 해석 → 프롬프트 생성 → dispatch_id 발급
- 비대화형 subprocess 실행 (argv_base 토큰 배열 + 프로세스 cwd)
- pre_head/post_head HEAD 비교로 코드 변경 판정
- post-run dirty tree 검증
- 완료 이벤트 기록

---

## 3. 이벤트 시스템 설계

### 3.1 이벤트 스키마 (구조)

모든 이벤트는 다음 구조를 따른다:

| 필드 그룹 | 필드 | 설명 |
|-----------|------|------|
| 공통 | id, timestamp, source, type | 식별 + 분류 |
| 인과 추적 | dispatch_id, causation_id, attempt | 이벤트 간 관계 |
| 중복 제거 | idempotency_key | inbox 경유 시 사용 |
| 페이로드 | payload (타입별 상이) | 작업 결과 상세 |

**source 규칙**: 실제 작업 주체 (agent 이름 / human / system). Broker는 writer이지 source가 아니다.

> 전체 JSON 스키마는 [LLD.md](./LLD.md)에 정의.

### 3.2 인과 체인

```
evt_001 (task_complete, claude impl)
  ↓ causation
evt_002 (human_decision, "send to codex review")
  ↓ causation
evt_003 (task_dispatched, dispatch_id=dsp_001)
  ↓ causation
evt_004 (review_complete, dispatch_id=dsp_001, attempt=1)
```

### 3.3 Atomic Write 규칙

- `events.jsonl`: `open(O_APPEND | O_WRONLY)` → `write(json + "\n")` → `fsync`
- `state.json`: `write("state.json.tmp")` → `fsync` → `rename("state.json.tmp", "state.json")`

---

## 4. 데이터 흐름

### 4.1 시퀀스 다이어그램

```
Broker          Console         User            Claude(subprocess)   Codex(subprocess)
  │                │              │                    │                   │
  │                │  dispatch    │                    │                   │
  │ ◀──────────── │ ◀─── "Claude │                    │                   │
  │  human_decision│    구현해라" │                    │                   │
  │                │              │                    │                   │
  │ ── task_dispatched ──────────────────────────────▶ │                   │
  │    (dsp_001)   │              │  claude -p "..."   │                   │
  │                │              │ (Popen cwd=proj)   │                   │
  │                │              │                    │                   │
  │                │              │              [작업중]                  │
  │                │              │                    │                   │
  │ ◀─────────────────────────── exit(0) + commit ─── │                   │
  │                │              │                    │                   │
  │ task_complete  │              │                    │                   │
  │ (dsp_001) ──▶  │              │                    │                   │
  │                │ [UI 표시]    │                    │                   │
  │                │ "Claude 완료"│                    │                   │
  │                │ "다음 액션?" │                    │                   │
  │                │              │                    │                   │
  │                │ ◀─── User:  │                    │                   │
  │                │ "Codex 리뷰" │                    │                   │
  │ ◀──────────── │              │                    │                   │
  │ human_decision │              │                    │                   │
  │                │              │                    │                   │
  │ ── task_dispatched ─────────────────────────────────────────────────▶ │
  │    (dsp_002)   │              │                    │ codex exec "..."  │
  │                │              │                    │ (Popen cwd=proj)  │
  │                │              │                    │                   │
  │                │              │                    │             [작업중]
  │                │              │                    │                   │
  │ ◀───────────────────────────────────── exit(0) + stdout capture ──── │
  │                │              │                    │                   │
  │ review_complete│              │                    │                   │
  │ (dsp_002) ──▶  │              │                    │                   │
  │                │ [UI 표시]    │                    │                   │
```

---

## 5. 디렉터리 레이아웃

```
project-root/                            # 모든 에이전트가 여기서 순차 작업 (공유)
├── .workflow/                           # 런타임 오케스트레이션 (Broker 관할)
│   ├── config.yaml                      # 워크플로우 설정
│   ├── events.jsonl                     # 이벤트 로그 (append-only, Broker만 write)
│   ├── state.json                       # 현재 상태 (Broker만 atomic rename)
│   ├── inbox/                           # 이벤트 발행 요청 drop-box
│   ├── tasks/                           # 태스크 정의
│   ├── prompts/                         # dispatch별 프롬프트
│   ├── outputs/                         # 에이전트 출력 artifact
│   ├── human-notes/                     # 인간 의견
│   ├── lock                             # Broker working 중 존재 (수동 commit 차단)
│   ├── manual_dispatch.{agent}          # 수동 작업 진입 시 agent별 생성
│   └── processed_keys.json             # Broker idempotency key 기록
│
├── .cross-harness/                      # 선언적 Skill/MCP 설정
│   ├── registry/                        # 사람이 수정하는 source of truth
│   │   ├── skills.yaml
│   │   ├── mcps.yaml
│   │   └── bundles.yaml
│   ├── lock/                            # resolve 결과 고정 (재현성)
│   ├── vendor/                          # 외부 artifact 캐시
│   ├── generated/                       # CLI별 주입 설정 (자동 생성, 수정 금지)
│   │   ├── claude/profiles/
│   │   ├── codex/profiles/
│   │   └── gemini/profiles/
│   ├── runtime/                         # session/profile/lease 상태
│   └── locks/                           # management lock
│
├── .worktrees/                          # 병렬 코드 수정 시에만 임시 생성
│
└── (프로젝트 소스코드)
```

---

## 6. 워크플로우 패턴

### 6.1 순차 작업 (기본)

모든 에이전트가 같은 디렉터리에서 순차 실행. 이전 에이전트의 결과를 다음이 바로 참조.

### 6.2 병렬 읽기 전용 (리뷰 + 리서치)

같은 디렉터리에서 동시 실행. CLI별 read-only 강제로 파일 수정 차단.

### 6.3 병렬 코드 수정 (예외)

임시 worktree에서 실행. dispatch당 1 commit 강제. 완료 후 cherry-pick으로 메인에 merge.

### 6.4 수동 개입

pane의 interactive CLI에서 직접 작업. `cross-harness begin`으로 dispatch 등록, 코드 변경은 post-commit hook, 비코드는 `cross-harness done`으로 완료.

### 6.5 Auto Loop (설계 → 리뷰 자동 반복)

작업자와 검증자 에이전트 쌍으로 finding이 수렴할 때까지 자동 반복하는 모드.

**구조**:

```
                    ┌──────────────────────────────────┐
                    │       Auto Loop Controller       │
                    │       (Broker 내부 컴포넌트)       │
                    └──────────┬───────────────────────┘
                               │
          ┌────────────────────┼────────────────────┐
          ▼                    ▼                    ▼
  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
  │  Worker      │    │  Reviewer    │    │  Judge       │
  │  Agent       │◀──▶│  Agent       │──▶ │  CLI         │
  │  (Claude)    │    │  (Codex)     │    │  (new session)│
  └──────────────┘    └──────────────┘    └──────────────┘
        │                    │                    │
        │   iteration N      │                    │
        ├─── task ──────────▶├─── review ────────▶│
        │                    │                    ├─── continue / stop
        │◀── findings ───────┤                    │
        │                    │                    │
```

**핵심 설계**:

1. **별도 실행 단위**: Auto loop는 기존 3개 pane의 연장이 아님. Worker/Reviewer/Judge 모두 pane 세션과 분리된 별도 세션에서 실행. pane 세션 메모리를 오염시키지 않음

2. **3가지 역할, Judge는 판정만**:
   - Worker: 코드 작업. pane과 별도 세션
   - Reviewer: 결과 검증. 항상 fresh 세션
   - Judge (Loop Controller): **판정만** 수행. 구현/리뷰를 직접 하지 않음. artifact + diff + finding summary만 보고 continue / stop / escalate만 결정. 항상 fresh new 세션

3. **정량적 stop condition** (핑퐁/비용 폭발 방지):
   - `high=0 and medium<=1` → 종료
   - 같은 finding 2회 연속 반복 → 종료 (개선 정체)
   - finding 수/심각도가 2회 연속 변화 없음 → 종료 (정체)
   - max_iterations (MVP 기본 3) → 무조건 사람에게 넘김

4. **Human gate 유지**: 사용자가 Console에서 언제든 pause/abort. Auto loop는 human approval의 자동화이지 human oversight의 제거가 아님. max_iterations 초과 시 자동으로 Human Control 복귀

5. **이벤트 추적**: 각 iteration은 개별 dispatch로 기록. `loop_id`로 묶음. finding 수 trend를 Console에 시각화

---

## 7. 기술 스택

| 컴포넌트 | 기술 |
|---------|------|
| Broker | Python 3.11+ / asyncio |
| Human Control Console | Python 3.11+ / textual |
| Event Bus | File-based (fswatch + jsonl + inbox) |
| Agent Adapter | Python (subprocess) |
| Layout Manager | tmux + bash script |
| Config | YAML (PyYAML / pydantic) |

### 참고 기술

| 기술 | 용도 | 비고 |
|------|------|------|
| git worktree | 병렬 코드 수정 시 임시 격리 | Phase 2 |
| tmux | 터미널 다중화 | interactive CLI pane + Console |
| textual | Python TUI 프레임워크 | Console 구현 |
| fswatch | 파일시스템 감시 (macOS) | inbox/events 감지 |
| claude -p | Claude CLI 비대화형 모드 | primary dispatch |
| codex exec | Codex CLI 비대화형 모드 | primary dispatch |
| gemini -p | Gemini CLI 비대화형 모드 | primary dispatch |

---

## 8. 소스코드 구조

```
cross_harness/
├── pyproject.toml
├── README.md
├── src/
│   └── cross_harness/
│       ├── __init__.py
│       ├── cli.py                # CLI 엔트리포인트 (typer)
│       ├── broker/
│       │   ├── __init__.py
│       │   ├── main.py           # Broker 메인 루프
│       │   ├── inbox.py          # Inbox 감시 + 수거
│       │   ├── event_store.py    # events.jsonl 관리 (single-writer)
│       │   ├── state_manager.py  # state.json atomic update
│       │   └── idempotency.py    # 중복 제거 (processed_keys)
│       ├── console/
│       │   ├── __init__.py
│       │   ├── app.py            # textual App 메인
│       │   ├── widgets.py        # 커스텀 위젯
│       │   └── screens.py        # 화면 정의
│       ├── dispatch/
│       │   ├── __init__.py
│       │   ├── engine.py         # Dispatch Engine (subprocess 실행)
│       │   └── templates.py      # 프롬프트 템플릿
│       ├── adapters/
│       │   ├── __init__.py
│       │   ├── base.py           # AgentAdapter 추상 클래스
│       │   ├── claude.py         # Claude 어댑터
│       │   ├── codex.py          # Codex 어댑터
│       │   └── gemini.py         # Gemini 어댑터
│       ├── workspace/
│       │   ├── __init__.py
│       │   └── manager.py        # 작업 디렉터리 관리 (병렬 시 임시 worktree)
│       ├── events/
│       │   ├── __init__.py
│       │   └── models.py         # 이벤트 데이터 모델 (pydantic)
│       ├── config/
│       │   ├── __init__.py
│       │   └── loader.py         # 설정 로더 (pydantic)
│       └── tmux/
│           ├── __init__.py
│           └── manager.py        # tmux 세션 관리
├── scripts/
│   ├── cross-harness-start.sh    # tmux 세션 시작
│   └── post-commit-hook.sh       # git hook (수동 개입용)
└── tests/
    ├── test_broker.py
    ├── test_dispatch.py
    ├── test_workspace.py
    └── test_events.py
```

---

## 9. MVP 마일스톤

| Phase | 목표 | 산출물 |
|-------|------|--------|
| **M1** | 프로젝트 프레임 + CLI skeleton | .workflow 구조 초기화, typer CLI 엔트리포인트 |
| **M2** | Broker (single-writer) | inbox 감시, events.jsonl, state.json, idempotency |
| **M3** | 비대화형 Dispatch | adapter 구현, subprocess 실행, 결과 캡처 |
| **M4** | Human Console 기본 TUI | 이벤트 표시, 선택 프롬프트, 의견 입력 |
| **M5** | tmux 레이아웃 + 통합 | 4-pane 자동 구성, end-to-end 워크플로우 검증 |

---

## 10. 설계 결정 기록 (ADR)

### ADR-001: 공유 Worktree 기본, 병렬 코드 수정 시에만 임시 Worktree

- **결정**: 모든 에이전트가 같은 프로젝트 디렉터리에서 순차적으로 작업. 병렬 코드 수정 예외 시에만 임시 worktree
- **이유**: 사람이 게이트키퍼이므로 한 번에 하나만 작업. worktree 분리는 매번 sync 오버헤드
- **결과**: 순차 작업 단순화, 병렬 코드 수정은 Phase 2

### ADR-002: 완료 시그널 이원화 (Git Commit vs Artifact)

- **결정**: 코드 변경 작업만 git commit, 리뷰/리서치는 output artifact
- **이유**: 리뷰/리서치는 코드 변경 없음 → 빈 커밋/history 오염
- **결과**: 깨끗한 git history, 오케스트레이션과 코드 레이어 분리

### ADR-003: Single-Writer Broker

- **결정**: events.jsonl/state.json 쓰기 권한은 Broker만 보유
- **이유**: 다중 writer → append 경쟁, last-write-wins, replay 비결정성
- **결과**: 단순한 쓰기 모델, Broker가 SPOF

### ADR-004: 비대화형 Subprocess Dispatch + Interactive Pane 공존

- **결정**: 자동 dispatch는 subprocess, pane은 interactive CLI
- **이유**: send-keys 신뢰성 문제, log tail은 수동 전환 비용
- **결과**: subprocess 신뢰성 + pane 즉시 수동 개입 가능

### ADR-005: Inbox 패턴

- **결정**: 이벤트 발행 요청은 inbox 디렉터리에 파일 drop
- **이유**: Broker가 유일한 writer, 외부는 간접 발행
- **결과**: 파일 기반으로 단순, Broker 재시작 시 재처리 가능

### ADR-006: 프로세스 cwd로 작업 디렉터리 설정

- **결정**: CLI별 `--cwd` 대신 `subprocess.Popen(cwd=...)`
- **이유**: CLI별 옵션 상이 (codex: `-C`, claude/gemini: 미지원)
- **결과**: 프로세스 cwd 통일

### ADR-007: 병렬 read-only 강제

- **결정**: review/research 병렬 시 CLI별 read-only 플래그 강제
- **이유**: 프롬프트 실수로 파일 수정 가능
- **결과**: Claude `--permission-mode plan`, Codex `--sandbox read-only`, Gemini `--approval-mode plan`

### ADR-008: HEAD 비교로 코드 변경 감지

- **결정**: `git diff` 대신 `pre_head != post_head`
- **이유**: commit 후 working tree 깨끗 → git diff 빈 결과
- **결과**: 정확한 commit 감지

### ADR-009: Repo Lock으로 동시 쓰기 방지

- **결정**: Broker working 시 `.workflow/lock`, pre-commit hook으로 차단
- **이유**: pane과 subprocess 동시 writer → 판정 깨짐
- **결과**: lock 기반 상호 배제, idle 시 수동 commit 자유

### ADR-010: 수동 비코드 작업 종료 프로토콜

- **결정**: `cross-harness done --dispatch-id`로 오케스트레이션에 알림
- **이유**: post-commit hook은 commit만 감지, 리뷰/리서치는 commit 없음
- **결과**: 명시적 종료 + 인과 추적 유지

### ADR-011: 다중 Commit 판정

- **결정**: `git rev-list --count pre..post`, >1이면 task_needs_decision
- **이유**: pre_head != post_head만으로 commit 수 구분 불가
- **결과**: 공유 dir >1은 사용자 판단, 임시 worktree >1은 자동 squash

### ADR-012: argv_base 토큰 배열

- **결정**: config의 CLI 명령을 `["claude", "-p"]` 배열로 저장
- **이유**: 문자열 `"claude -p"`를 리스트 원소로 넣으면 실행 파일명으로 인식
- **결과**: 안전한 리스트 결합

### ADR-013: Clean Tree 강제, 자동 Stash 금지

- **결정**: dispatch 전 dirty tree이면 거부, 자동 stash 안 함
- **이유**: 자동 stash는 기준선 오염
- **결과**: 기본 clean tree 강제, 예외 시 stash id를 artifact로 기록

### ADR-014: CLI 세션 메모리 전략 (기본 resume + artifact 주입)

- **결정**: 첫 dispatch는 새 세션(new), 이후는 기본 resume. resume 시에도 artifact 기반 explicit context를 항상 주입. 예외 시 new (fork는 Phase 2)
- **이유**: 세션 메모리는 편리하지만 불투명. resume만 믿으면 세션 내부 상태와 실제 artifact 간 drift 발생. 반대로 매번 new면 이전 문맥 완전 유실
- **대안 검토**: (1) 항상 new → 문맥 유실 (2) 항상 resume → 세션 오염 누적 (3) resume + explicit context (채택) → 양쪽 장점 결합
- **결과**: 연속 작업의 문맥 유지 + artifact source of truth + 예외 시 깨끗한 재시작. CLI별 resume 구현 차이는 adapter가 흡수

### ADR-015: Registry-Driven Skill/MCP 관리

- **결정**: Skill/MCP의 source of truth는 `.cross-harness/registry/*.yaml`. CLI별 설정 파일은 registry로부터 자동 생성(generated)
- **이유**: CLI별 설정 파일을 직접 수정하면 재현성이 깨짐. 3개 CLI의 설정 포맷이 다르므로 공통 registry에서 각각의 generated config를 생성하는 게 맞음
- **대안 검토**: CLI별 설정 직접 관리 → 3벌 유지보수, drift 위험
- **결과**: 선언형 registry + 자동 generated profile. 사람은 registry만 수정

### ADR-016: MVP Skill Materialization은 Prompt Module 전용

- **결정**: MVP에서 모든 Skill은 prompt module(시스템 프롬프트 fragment)로만 materialize
- **이유**: CLI별 native skill/plugin 인터페이스가 아직 불안정하고 상이. prompt module은 모든 CLI에서 동작하는 최소공통분모. native materialization은 CLI 안정성 확인 후 Phase 2에서 도입
- **대안 검토**: native 우선 + prompt fallback → CLI별 경우의 수 폭발, MVP 복잡도 급증
- **결과**: MVP 단순화. Phase 2에서 native 지원 점진 추가

### ADR-017: MCP Least Privilege (Bundle 기반 Allowlist)

- **결정**: 모든 MCP를 항상 열어두지 않고, bundle 정책에 따라 필요한 MCP만 dispatch 시 주입
- **이유**: 불필요한 MCP 노출은 보안 위험 + 토큰 낭비. write path가 있는 MCP가 review 작업에 열리면 의도치 않은 수정 가능
- **결과**: dispatch 시 agent + task_type으로 bundle 선택 → 해당 bundle의 MCP만 generated profile에 포함

### ADR-018: Disable First, Prune Later

- **결정**: Skill/MCP 삭제는 2단계. disable → sync(generated에서 제외) → sync --prune(물리 삭제). active lease가 있는 리소스는 prune하지 않음
- **이유**: active dispatch가 old profile을 참조 중일 수 있음. 즉시 삭제는 running subprocess를 깨뜨림
- **결과**: 안전한 단계적 제거. lease-aware prune

### ADR-019: Auto Loop의 Judge는 별도 New 세션

- **결정**: Auto loop의 수렴 판정(Judge)은 사용자가 선택한 CLI의 **별도 new 세션**으로 실행
- **이유**: interactive pane 세션이나 worker/reviewer 세션을 재사용하면 이전 문맥에 오염된 판정이 나올 수 있음. Judge는 fresh 관점에서 "finding이 충분히 수렴했는가"만 판단해야 함
- **대안 검토**: (1) 사람이 매번 판단 → 자동화 의미 없음 (2) worker/reviewer 세션 재사용 → 문맥 오염 (3) 별도 new 세션 (채택) → 독립적 판정
- **결과**: Judge dispatch는 항상 session_mode="new", review artifact + finding 수/심각도를 프롬프트로 전달, `continue`/`stop`/`escalate`만 반환
