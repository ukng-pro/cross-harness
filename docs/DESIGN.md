# Cross Harness — 설계문서 (Archived)

> 이 파일은 v0.1.0 ~ v0.8.0까지의 설계 발전 과정을 담은 아카이브입니다.
> 현재 설계는 아래 3개 문서로 분리되었습니다.

## 현재 설계 문서

| 문서 | 내용 |
|------|------|
| [SRS.md](./SRS.md) | 소프트웨어 요구사항 명세서 — 무엇을, 누구를 위해, 어떤 제약 하에 |
| [HLD.md](./HLD.md) | 고수준 설계 — 아키텍처, 컴포넌트, 데이터 흐름, ADR |
| [LLD.md](./LLD.md) | 저수준 설계 — 스키마, 인터페이스, 알고리즘, CLI, Git Hooks, Config |

## 변경 이력 (아카이브)

| 버전 | 날짜 | 변경 내용 |
|------|------|----------|
| 1.0.0 | 2026-03-23 | SRS/HLD/LLD로 분리, Codex 잔여 fix 3건 반영 |
| 0.8.0 | 2026-03-23 | manual_dispatch agent-scoped + 자동 정리, source에 system 추가, 시퀀스 다이어그램 cwd 정리 |
| 0.7.0 | 2026-03-23 | lock 해제 시점 수정, cross-harness begin 도입, post-commit hook 인과 추적, source 의미 통일 |
| 0.6.0 | 2026-03-23 | post-run dirty tree 검증, stale lock 복구, cross-harness done 인과 추적, commit_count>1 상태 전이 |
| 0.5.0 | 2026-03-23 | Broker working 중 repo lock, argv_base 토큰 배열, 수동 비코드 종료 프로토콜, 다중 commit 판정 |
| 0.4.0 | 2026-03-23 | interactive CLI pane, CLI 호출 규격 실제 옵션, read-only 강제, commit 감지 보정, clean tree 정책 |
| 0.3.0 | 2026-03-23 | 공유 worktree 기본, 병렬 시에만 임시 worktree |
| 0.2.0 | 2026-03-23 | 완료 시그널 이원화, single-writer broker, 비대화형 dispatch, 이벤트 인과 추적 |
| 0.1.0 | 2026-03-23 | 초기 설계 |
