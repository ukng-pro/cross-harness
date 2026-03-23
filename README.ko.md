# Cross Harness

[English](README.md) | [中文](README.zh.md) | [한국어](README.ko.md)

> 사람을 게이트로 두는 AI CLI용 반자동 멀티모델 협업 시스템.

![License](https://img.shields.io/badge/license-MIT-blue.svg)

## 현재 상태

이 저장소는 현재 구현보다 설계 문서가 중심이다.

- 구현은 아직 완료되지 않았다.
- 현재의 source of truth는 [`docs/SRS.md`](docs/SRS.md), [`docs/HLD.md`](docs/HLD.md), [`docs/LLD.md`](docs/LLD.md) 이다.
- README는 출시된 제품 설명이 아니라 현재 설계 방향과 목표 시스템을 설명한다.

## Cross Harness란

Cross Harness는 Claude, Codex, Gemini 같은 여러 AI CLI를 하나의 소프트웨어 프로젝트 위에서 조율하되, 모델끼리 직접 대화하지 않도록 설계된 시스템이다.

구조는 hub-and-spoke다.

- Broker가 이벤트와 상태를 단일 writer로 기록한다.
- Human Control Console이 모든 단계 전환의 중앙 관제판 역할을 한다.
- 기본적으로 같은 프로젝트 디렉터리에서 순차 작업한다.
- review / research 결과는 artifact로 저장한다.
- 코드 변경은 commit으로 저장한다.

목표는 멀티모델 협업의 장점은 살리면서, 조용한 방향 이탈, 무한 핑퐁, 재현 불가능한 자동화를 줄이는 것이다.

## 왜 필요한가

여러 AI CLI를 한 프로젝트에서 같이 쓰면 보통 수동 복사/붙여넣기, 임시 라우팅, 낮은 추적성에 의존하게 된다. 완전 자동화는 멋져 보이지만 실제로는 문제가 많다.

- 잘못된 방향으로 계속 진행될 수 있다
- 모델 간 충돌을 자동으로 풀기 어렵다
- 토큰과 시간이 과도하게 소모될 수 있다
- 디버깅과 재현이 어렵다

Cross Harness의 핵심 원칙은 단순하다. 사람을 게이트키퍼로 남기고, 모든 단계를 보이게 만든다.

## 핵심 아이디어

### 1. Human-in-the-loop 오케스트레이션

기본 흐름은 다음과 같다.

1. 한 에이전트가 작업을 끝낸다
2. Broker가 결과를 기록한다
3. Human Control Console이 다음 액션을 묻는다
4. 사람의 결정 후에만 다음 에이전트가 실행된다

### 2. 기본은 공유 worktree

일반적인 순차 흐름은 같은 프로젝트 디렉터리를 쓴다.

- 구현
- 리뷰
- 수정
- 승인

그래서 reviewer는 최신 commit을 바로 볼 수 있고, worker는 reviewer artifact를 바로 참조할 수 있다. 임시 git worktree는 병렬 코드 수정 같은 예외 상황에서만 사용한다.

### 3. interactive pane와 subprocess의 공존

목표 UI는 4-pane `tmux` 세션이다.

- `claude`
- `codex`
- `gemini`
- Human Control Console

이 pane들은 사람이 언제든 직접 개입할 수 있도록 유지되지만, 자동 실행은 Broker가 관리하는 별도 비대화형 subprocess에서 수행된다. 즉 사람의 live pane 세션을 오염시키지 않는다.

### 4. artifact 중심 메모리 전략

세션 메모리는 유용하지만, 그것 자체를 source of truth로 보지 않는다.

Cross Harness가 canonical로 보는 것은 다음이다.

- commits
- review artifacts
- research artifacts
- human notes
- event logs

resume이 가능한 CLI는 세션을 재개할 수 있어도, 매 dispatch마다 명시적 context를 다시 주입한다.

### 5. hard stop rule이 있는 auto loop

설계에는 자동 반복 개선 모드도 포함된다. 예를 들면:

- Worker: Claude
- Reviewer: Codex
- Judge: Claude 또는 Codex

Judge는 구현이나 리뷰를 직접 하지 않는다. artifact, diff, finding summary만 보고 `continue`, `stop`, `escalate`를 결정한다.

무한 루프를 막기 위해 다음 같은 명시적 stop rule을 둔다.

- `high=0 and medium<=1`
- 같은 finding 반복
- 연속 iteration에서 진전 없음
- 최대 iteration 수 도달

## 아키텍처 요약

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

핵심 제약은 다음과 같다.

- 모델 간 직접 대화 금지
- 기본은 하나의 공유 프로젝트 디렉터리
- `events.jsonl`, `state.json`은 Broker만 쓴다
- 수동 개입도 허용하지만 반드시 추적된다
- Broker 실행 중에는 repo lock으로 수동 commit을 막는다

## 저장소 구조

현재 저장소에는 다음이 있다.

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

문서 역할은 다음과 같다.

- [`docs/SRS.md`](docs/SRS.md): 요구사항과 제품 동작
- [`docs/HLD.md`](docs/HLD.md): 아키텍처, 컴포넌트, ADR
- [`docs/LLD.md`](docs/LLD.md): 스키마, 알고리즘, 명령 계약
- [`docs/DESIGN.md`](docs/DESIGN.md): 설계 발전 이력 아카이브
- [`docs/corss-harness-skll-mcp-strategy.md`](docs/corss-harness-skll-mcp-strategy.md): Skill/MCP 상세 전략

## 설계가 다루는 범위

현재 설계 패키지는 다음을 포함한다.

- Broker 기반 single-writer 오케스트레이션
- TUI Console을 통한 사람 승인과 라우팅
- interactive pane + subprocess 공존 구조
- 인과 추적이 유지되는 수동 takeover 경로
- CLI별 session memory 정책
- registry 기반 Skill/MCP 관리와 generated profile
- Judge가 수렴을 판단하는 auto-loop

## 추천 읽기 순서

처음 보는 사람이라면:

1. [`docs/SRS.md`](docs/SRS.md)
2. [`docs/HLD.md`](docs/HLD.md)
3. [`docs/LLD.md`](docs/LLD.md)

Skill/MCP만 보고 싶다면 [`docs/corss-harness-skll-mcp-strategy.md`](docs/corss-harness-skll-mcp-strategy.md)부터 읽으면 된다.

## 현재 범위와 주의점

이 저장소는 아직 production-ready CLI 구현으로 보면 안 된다.

특히:

- 예전 초안에 있던 설치 명령은 현재 저장소에 포함되어 있지 않다
- `tmux` 오케스트레이션 흐름은 설계되어 있지만 완전 구현되지는 않았다
- README는 여러 차례 리뷰를 거친 현재 설계 방향을 반영한다

## License

MIT
