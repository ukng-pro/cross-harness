# Cross Harness — 소프트웨어 요구사항 명세서 (SRS)

> Semi-Autonomous Cross-Model Collaboration System
> Human-in-the-Loop 기반 멀티 AI CLI 협업 플랫폼

**버전**: 1.0.0
**작성일**: 2026-03-23
**관련 문서**: [HLD.md](./HLD.md) · [LLD.md](./LLD.md)

---

## 목차

1. [프로젝트 개요](#1-프로젝트-개요)
2. [설계 원칙 (요구사항 수준)](#2-설계-원칙)
3. [기능 요구사항](#3-기능-요구사항)
4. [워크플로우 유스케이스](#4-워크플로우-유스케이스)
5. [Human Control Console 요구사항](#5-human-control-console-요구사항)
6. [설정 및 확장 요구사항](#6-설정-및-확장-요구사항)
7. [에러 처리 요구사항](#7-에러-처리-요구사항)
8. [비기능 요구사항 및 제약](#8-비기능-요구사항-및-제약)
9. [MVP 범위](#9-mvp-범위)
10. [향후 로드맵](#10-향후-로드맵)
11. [용어 정의](#11-용어-정의)

---

## 1. 프로젝트 개요

### 1.1 문제 정의

현재 AI CLI 도구(Claude CLI, Codex CLI, Gemini CLI)는 각각 독립적으로 동작한다. 하나의 소프트웨어 프로젝트에서 여러 모델의 강점을 조합하려면, 사람이 수동으로 각 CLI를 전환하며 결과를 복사/붙여넣기하는 방식에 의존해야 한다.

완전 자동화(fully autonomous) 방식은 다음 문제를 갖는다:

- 잘못된 방향으로 연쇄적으로 진행될 위험
- 모델 간 출력 충돌을 자동 해결하기 어려움
- 불필요한 토큰/시간 낭비
- 디버깅 및 재현이 어려움

### 1.2 해결 방안

**Human-in-the-Loop Semi-Autonomous** 방식을 채택한다.

- 모든 에이전트가 **같은 프로젝트 디렉터리**에서 순차적으로 작업 수행
- 작업 완료 시 **Broker**가 이벤트를 감지하여 **Human Control Console**에 전달
- 사람이 **승인/보류/수정/라우팅** 결정
- 결정에 따라 Broker가 다음 에이전트를 **비대화형(subprocess)으로 실행**
- 병렬 코드 수정이 필요한 예외 경우에만 **임시 git worktree** 생성

### 1.3 핵심 가치

| 가치 | 설명 |
|------|------|
| **가시성** | 누가 뭘 하고 있는지, 어느 단계인지, 왜 넘어가는지가 항상 보임 |
| **제어권** | 사람이 모든 단계 전환의 게이트키퍼 |
| **안정성** | 모델 간 직접 대화 없음 → 충돌/루프 방지 |
| **재현성** | 모든 이벤트/의견/결정이 artifact로 기록됨 |
| **단순성** | 공유 디렉터리에서 순차 작업 → sync 오버헤드 없음 |

---

## 2. 설계 원칙

### 2.1 Hub-and-Spoke 토폴로지

```
모델 간 직접 통신 금지.
모든 흐름은 Broker + Human Control Console을 경유한다.

  Claude ──┐
  Codex  ──┼──▶ Broker ──▶ Human Control Console ◀── 사용자
  Gemini ──┘   (single    (중앙 관제판)
                writer)
```

- Claude ↔ Codex 직접 대화 **X**
- Claude → Broker → Human Control → Broker → Codex **O**

### 2.2 공유 Worktree 기본, 임시 Worktree 예외

모든 에이전트가 같은 프로젝트 디렉터리에서 순차적으로 작업한다.
사람이 게이트키퍼이므로 한 번에 하나의 에이전트만 작업한다.

| 비교 | 공유 worktree | 분리 worktree |
|------|:---:|:---:|
| 순차 작업 (기본 흐름) | 자연스러움 | 매번 sync 필요 |
| 리뷰/리서치 (읽기 전용) | 문제없음 | 불필요한 복사 |
| 이전 작업 참조 | 즉시 가능 | sync 후에만 가능 |
| 병렬 코드 수정 (예외) | 충돌 위험 | 필요 |
| 복잡도 | 낮음 | 높음 |

병렬 코드 수정이 필요한 드문 경우에만 임시 worktree를 생성한다.

### 2.3 완료 시그널 이원화

| 작업 유형 | 코드 변경 여부 | 완료 시그널 | 저장 위치 |
|-----------|--------------|-----------|----------|
| `impl` | O | git commit | 프로젝트 디렉터리 (공유) |
| `fix` | O | git commit | 프로젝트 디렉터리 (공유) |
| `refactor` | O | git commit | 프로젝트 디렉터리 (공유) |
| `test` | O | git commit | 프로젝트 디렉터리 (공유) |
| `review` | X (보통) | orchestration artifact | `.workflow/outputs/` |
| `research` | X | orchestration artifact | `.workflow/outputs/` |

### 2.4 기본 사람 승인, 옵션 자동 승인

- 기본 모드: 사람 승인 필요 (safe mode)
- 옵션 모드: auto-approve (신뢰도 높은 반복 작업용, task 유형별 세밀 설정)

### 2.5 모든 인간 의견은 Artifact로 남긴다

사람의 의견/결정은 반드시 이벤트 로그 또는 별도 파일로 저장하여 재현성을 확보한다.

### 2.6 CLI 세션 메모리 전략

에이전트 CLI의 세션 메모리(대화 문맥)를 활용하되, artifact를 source of truth로 유지한다.

| 경로 | 세션 정책 |
|------|----------|
| interactive pane | CLI의 native 세션 메모리 유지 (사람이 직접 관리) |
| 자동 dispatch (첫 실행) | 새 세션 생성 (`new`), session_id 저장 |
| 자동 dispatch (2회 이후) | 기본 resume + artifact 재주입 |
| 예외 (작업 종류 변경, 세션 오염, fresh review 필요) | 새 세션 (`new`) |

**핵심 원칙**:
- resume만 믿지 않는다. 내부 세션 메모리는 불투명하므로, 자동 dispatch 시 항상 다음을 명시적으로 주입한다:
  - 이전 dispatch 요약
  - 관련 commit / output artifact
  - human note
  - 현재 목표와 종료 조건
- artifact가 항상 source of truth이다.

### 2.7 Single-Writer Broker

events.jsonl과 state.json에 대한 쓰기 권한은 Broker 프로세스만 갖는다.
이 규칙이 없으면 append 경쟁, last-write-wins, replay 비결정성이 생긴다.

---

## 3. 기능 요구사항

### 3.1 이벤트 시스템

시스템은 다음 이벤트 타입을 지원해야 한다:

| Type | Source | 설명 |
|------|--------|------|
| `task_complete` | agent | 코드 변경 작업 완료 (commit 있음) |
| `review_complete` | agent | 리뷰 완료 (output artifact) |
| `research_complete` | agent | 리서치 완료 (output artifact) |
| `task_failed` | agent | 에이전트 작업 실패 (exit code != 0, dirty tree 감지 등) |
| `task_needs_decision` | agent | 작업 결과가 모호하여 사용자 판단 필요 (예: commit_count > 1) |
| `human_decision` | human | 사용자가 다음 액션 결정 |
| `human_note` | human | 사용자가 추가 의견 입력 |
| `task_dispatched` | human / system | 에이전트에게 task 전달됨 |
| `merge_complete` | human / system | 임시 worktree 결과를 메인 repo에 merge |
| `workflow_pause` | human | 워크플로우 일시 중지 |
| `workflow_resume` | human | 워크플로우 재개 |

`source`는 실제 작업 주체를 나타낸다:
- `agent`: 해당 에이전트 (claude, codex, gemini)
- `human`: 사용자
- `system`: auto-approve 규칙 등 자동화된 결정

### 3.2 인과 추적

모든 이벤트는 `dispatch_id`, `causation_id`, `attempt` 필드를 통해 인과 관계를 추적해야 한다. 수동 경로(pane에서 직접 작업)도 1급 작업 경로로서 동일한 인과 추적이 적용된다.

### 3.3 Repo Lock

Broker가 subprocess를 실행 중일 때 수동 commit을 차단해야 한다 (pre-commit hook). Lock은 subprocess 종료 후 dirty tree 검증, commit 판정, 최종 이벤트 기록 완료 시까지 유지해야 한다.

### 3.4 수동 작업 경로

- **코드 변경**: `cross-harness begin`으로 dispatch 등록 후 pane에서 작업 → post-commit hook이 인과 추적 포함 이벤트 발행
- **비코드 작업**: `cross-harness done --dispatch-id <id>`로 결과를 오케스트레이션에 반환
- 수동 dispatch 컨텍스트는 agent별로 격리 (`manual_dispatch.{agent}`)

### 3.5 병렬 Read-Only 강제

review/research를 병렬 실행 시, CLI별 read-only 플래그를 강제 부여해야 한다.

### 3.6 세션 관리

- 에이전트별 session_id를 추적하여 같은 에이전트에 대한 연속 dispatch는 기존 세션을 resume한다.
- resume 시에도 최신 artifact 요약, human note, 목표/종료 조건을 프롬프트에 재주입한다.
- 작업 종류가 크게 바뀌거나 세션이 오염된 경우 새 세션(new)을 사용한다.
- 세션 모드 결정은 Broker가 자동 판단하되, 사용자가 Console에서 override 가능하다.
- **CLI별 예외**: Codex review는 항상 fresh 세션 (exec review가 resume 미지원). Gemini는 MVP에서 resume 비지원 (항상 new, artifact 주입으로 보상).

### 3.7 Auto Loop Mode

사용자가 지정한 에이전트 조합으로 **자동 반복 루프**를 실행할 수 있어야 한다. 이것은 기존 3개 pane의 연장이 아니라 **별도 auto-loop 실행 단위**다.

**3가지 역할**:
- **Worker**: 코드 작업 수행 (impl/fix/refactor). pane 세션과 별도 세션.
- **Reviewer**: 결과 검증 (review). 항상 fresh 세션.
- **Judge** (Loop Controller): 수렴 판정만 수행. 항상 fresh new 세션. 구현/리뷰를 직접 하지 않고, artifact + diff + finding summary만 보고 continue/stop/escalate만 결정.

**정량적 stop condition** (모호한 "finding이 거의 없을 때"를 대체):
- `high=0 and medium<=1` → 종료
- 같은 finding이 2회 연속 반복 → 종료 (개선 정체)
- finding 수/심각도가 2회 연속 변화 없음 → 종료 (정체)
- `max_iterations` (기본 3) 도달 → 무조건 종료, 사람에게 넘김

**핑퐁 방지**:
- 같은 두 모델이 서로 핑퐁하면서 비용만 쓰는 루프를 방지하기 위해 stop condition을 정량화
- Judge는 worker/reviewer와 독립된 fresh 관점에서 판정
- MVP `max_iterations`는 3~5 권장

**기타 요구사항**:
- 사용자는 Console에서 언제든 루프를 중단(pause/abort)할 수 있다
- 루프의 모든 iteration은 개별 dispatch로 기록되며 인과 추적이 유지된다
- Worker/Reviewer/Judge 모두 interactive pane 세션과 분리된 별도 세션
- Judge는 artifact만 보고 판단 (pane 세션 메모리에 의존하지 않음)

### 3.8 Skill 관리

- **Skill**은 에이전트에게 특정 작업 방식을 주입하는 재사용 가능한 지식 패키지다.
- Skill은 Cross Harness의 공통 추상화이며, CLI별 native 개념과 1:1 대응하지 않는다.
- Source of truth는 `registry/skills.yaml`이며, CLI별 설정 파일은 registry로부터 자동 생성(generated)된다.
- 사람은 registry만 수정한다. generated 파일을 직접 수정하지 않는다.
- Skill 삭제는 2단계: disable(generated에서 제외) → prune(물리 삭제). active dispatch가 참조 중인 리소스는 삭제하지 않는다.

### 3.8 MCP 관리

- **MCP**(Model Context Protocol)는 에이전트가 외부 도구/데이터 소스와 통신하기 위한 서버 설정이다.
- 모든 에이전트에 모든 MCP를 열어두지 않는다. task_type과 agent에 따라 필요한 MCP만 allowlist로 주입한다 (Least Privilege).
- MCP 서버의 healthcheck를 sync 시 수행한다.
- Secret(토큰 등)은 registry에 평문 저장 금지. 환경변수 참조(`${env:GITHUB_TOKEN}`)만 허용한다.
- MCP 권한은 network/read_paths/write_paths 3축을 명시해야 한다.

### 3.9 Bundle 정책

- **Bundle**은 dispatch 시 어떤 Skill/MCP 세트를 활성화할지 결정하는 정책 단위다.
- agent + task_type 조합에 따라 bundle이 선택된다.
- 같은 Skill/MCP도 bundle에 따라 포함 여부가 달라질 수 있다.

### 3.10 코드 변경 감지

`pre_head != post_head` (HEAD 비교)로 코드 변경을 판정한다. `git rev-list --count`로 commit 수를 판정하고, >1이면 `task_needs_decision` 이벤트를 발행한다.

---

## 4. 워크플로우 유스케이스

### 4.1 기본: 구현 → 리뷰 → 수정

```
[1] 사용자가 Console에서 Claude 구현 지시
[2] Broker가 Claude subprocess 실행 (같은 디렉터리)
[3] Claude 구현 완료 → exit(0) + git commit
[4] Broker 감지 → Console에 표시
[5] 사용자 결정: Codex 리뷰로 / 의견 추가 후 / Claude 수정 / 보류
[6] Codex 리뷰 실행 (같은 디렉터리, sync 불필요)
[7] Codex 리뷰 완료 → stdout 캡처 → output artifact (git commit 아님)
[8] 사용자 결정: Claude 수정 / Gemini 리서치 / 승인 / 보류
```

### 4.2 병렬: 동시 리뷰 + 리서치

- 리뷰/리서치는 읽기 전용이므로 같은 디렉터리에서 병렬 실행 가능
- CLI별 read-only 플래그 강제
- 병렬 코드 수정 시에만 임시 worktree 생성 (dispatch당 1 commit 강제)

### 4.3 Auto Loop: 설계 → 리뷰 자동 반복

```
[1] 사용자가 Console에서 auto loop 시작:
    cross-harness loop --worker claude --reviewer codex --judge claude --max-iterations 3
[2] Broker가 Claude(new session)에게 설계 dispatch (iteration 1)
[3] Claude 완료 → Broker가 Codex(fresh session)에게 review dispatch
[4] Codex 리뷰 결과: high=2, medium=3
[5] Judge(Claude, fresh new session)가 artifact만 보고 판정:
    high>0 → "continue"
[6] Iteration 2: Broker가 Claude에게 수정 dispatch (리뷰 결과 + finding 포함)
[7] Claude 완료 → Codex 리뷰 결과: high=0, medium=1
[8] Judge: high=0, medium<=1 → "stop"
[9] 루프 종료 → Console에 최종 결과 표시 + 사람에게 최종 승인 요청
```

**MVP 제한**: Claude impl ↔ Codex review 한 쌍만 먼저 지원. Judge는 Claude 또는 Codex 중 선택. `max_iterations` 기본 3.

### 4.4 에스컬레이션: 에러 처리

에이전트 실패 시 Console에 재시도/전환/수동개입/중단 선택지 제시.

---

## 5. Human Control Console 요구사항

### 5.1 화면 요소

```
┌─────────────────────────────────────────────────────────────┐
│  Cross Harness Control                          ⏱ 19:05:32 │
├──────────────────────────────┬──────────────────────────────┤
│  Agent Status                │  Event Feed                  │
│  ● Claude   idle             │  (실시간 이벤트 스트림)       │
│  ◉ Codex    working [dsp002] │                              │
│  ○ Gemini   idle             │                              │
├──────────────────────────────┴──────────────────────────────┤
│  [EVENT] 상세 정보 + dispatch/causation 추적                │
│  선택지: [1] ... [2] ... [c] Custom [n] Note [h] History    │
│  Choice: █                                                  │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 기능 목록

1. **이벤트 피드**: 실시간 에이전트 이벤트 표시
2. **결정 프롬프트**: 다음 액션 선택지 제시 (Quick Action 1~9)
3. **의견 입력**: 자유 텍스트 추가 지시사항 입력
4. **상태 대시보드**: 에이전트별 상태 + lock 표시
5. **히스토리 뷰**: 이벤트/결정 이력 + 인과 체인 시각화
6. **Custom Action**: 대상 에이전트 선택 + 자유 프롬프트
7. **Pane 전환**: tmux 단축키로 에이전트 pane 진입 (interactive CLI 대기 중)

---

## 6. 설정 및 확장 요구사항

### 6.1 에이전트 추가/제거

config에 에이전트를 추가하면 pane이 자동 생성되어야 한다.

### 6.2 커스텀 워크플로우

반복되는 워크플로우를 YAML로 사전 정의할 수 있어야 한다.

### 6.3 Auto-Approve 규칙

이벤트 타입, exit_code, 출력 내용에 따른 조건부 자동 승인을 지원해야 한다.

### 6.4 알림

데스크톱 알림, 사운드, Slack webhook, idle timeout 경고를 지원해야 한다.

---

## 7. 에러 처리 요구사항

| 시나리오 | 기대 대응 |
|---------|----------|
| subprocess 실패 (exit != 0) | task_failed → Console에 재시도/전환 옵션 |
| subprocess timeout | SIGTERM → Console 경고 |
| dispatch 전 dirty tree | dispatch 거부 + 사용자에게 clean 요청. 자동 stash 금지 |
| post-run dirty tree (외부 수정) | task_failed (reason: dirty_tree_after_run) |
| commit_count > 1 | task_needs_decision → 사용자 판단 (수용/squash/실패) |
| Stale lock | Broker 시작 시 PID 확인 → dead면 자동 삭제. `cross-harness unlock` 지원 |
| Broker 크래시 | 자동 재시작 + stale lock 정리 |
| events.jsonl 손상 | 손상 줄 skip + 경고 |
| inbox 파싱 실패 | dead-letter 이동 + 경고 |
| 임시 worktree merge 충돌 | Console에 충돌 표시 + 수동 해결 안내 |

---

## 8. 비기능 요구사항 및 제약

| 항목 | 요구사항 |
|------|---------|
| 런타임 | Python 3.11+ |
| 플랫폼 | macOS (darwin), Linux 호환 목표 |
| 터미널 | tmux 필수 |
| TUI 프레임워크 | textual |
| 이벤트 저장 | 파일 기반 (jsonl), 별도 DB 불필요 |
| CLI 도구 | claude, codex, gemini (비대화형 모드 지원 필수) |

---

## 9. MVP 범위

**포함**:
- 공유 프로젝트 디렉터리에서 순차 에이전트 실행
- Broker (single-writer): inbox 감시 + events.jsonl + state.json
- 비대화형 dispatch: `claude -p`, `codex exec`, `gemini -p`
- Human Control Console (기본 TUI)
- 완료 시그널 이원화
- 이벤트 인과 추적
- tmux 4-pane 레이아웃 (interactive CLI)
- 기본 config.yaml

**미포함 (Phase 2 이후)**:
- 병렬 코드 수정용 임시 worktree
- 자동 승인 규칙 엔진
- 커스텀 워크플로우 정의
- Skill native materialization (MVP는 prompt module 전용)
- Bundle by_mode 축 (MVP는 defaults + by_agent + by_task_type만)
- 데스크톱 알림
- 웹 대시보드
- Slack 연동

---

## 10. 향후 로드맵

### Phase 2: 고도화
- 조건부 자동 승인 엔진
- 커스텀 워크플로우 YAML 정의/실행
- 병렬 코드 수정용 임시 worktree 자동 생성/merge/cleanup
- 병렬 dispatch
- 에이전트별 성능/품질 메트릭 수집
- 데스크톱 알림

### Phase 3: 확장
- 웹 기반 대시보드
- Slack/Discord 연동
- 에이전트 플러그인 시스템
- 워크플로우 템플릿 라이브러리
- 멀티 프로젝트 관리

### Phase 4: 지능화
- 에이전트 자동 선택
- 자연어 워크플로우 정의
- 학습 기반 auto-approve 신뢰도 조정
- cross-model 출력 품질 비교 분석

---

## 11. 용어 정의

| 용어 | 정의 |
|------|------|
| Agent | AI CLI 도구 (Claude, Codex, Gemini 등) |
| Worktree | 병렬 코드 수정 시에만 생성되는 임시 git 작업 디렉터리 |
| Broker | 이벤트/상태의 유일한 writer 프로세스 |
| Dispatch | 에이전트에게 비대화형으로 작업을 전달하는 행위 |
| dispatch_id | 개별 dispatch를 식별하는 유니크 ID |
| Inbox | 이벤트 발행 요청을 drop하는 디렉터리 |
| Human Note | 사람이 추가한 의견/지시사항 |
| Output Artifact | 비코드 작업(리뷰/리서치)의 결과 파일 |
| Hub | Human Control Console (중앙 관제점) |
