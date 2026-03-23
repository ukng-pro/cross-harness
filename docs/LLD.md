# Cross Harness — 저수준 설계 (LLD)

> Semi-Autonomous Cross-Model Collaboration System
> 구현 상세: 스키마, 인터페이스, 알고리즘, CLI 명령, Git Hooks, Config

**버전**: 1.0.0
**작성일**: 2026-03-23
**관련 문서**: [SRS.md](./SRS.md) · [HLD.md](./HLD.md)

---

## 목차

1. [이벤트 스키마](#1-이벤트-스키마)
2. [데이터 구조 (Config / Task / State)](#2-데이터-구조)
3. [Agent Adapter 인터페이스](#3-agent-adapter-인터페이스)
4. [CLI 실행 예시](#4-cli-실행-예시)
5. [CLI 명령 (cross-harness)](#5-cli-명령)
6. [Dispatch 알고리즘](#6-dispatch-알고리즘)
7. [Broker 내부 구현](#7-broker-내부-구현)
8. [Git Hooks](#8-git-hooks)
9. [프롬프트 템플릿](#9-프롬프트-템플릿)
10. [tmux 세션 초기화](#10-tmux-세션-초기화)
11. [에러 복구 구현](#11-에러-복구-구현)
12. [설정 스키마 상세](#12-설정-스키마-상세)
13. [Skill/MCP Registry 구현](#13-skillmcp-registry-구현)
14. [Auto Loop 구현](#14-auto-loop-구현)

---

## 1. 이벤트 스키마

### 1.1 전체 JSON 스키마

```jsonc
{
  // 공통 필드 (Broker가 부여)
  "id": "evt_20260323_185500_001",       // 유니크 이벤트 ID
  "timestamp": "2026-03-23T18:55:00Z",   // ISO 8601
  "source": "claude",                     // 실제 작업 주체: claude | codex | gemini | human | system
  "type": "task_complete",                // 이벤트 타입

  // 인과 추적 필드
  "dispatch_id": "dsp_20260323_185000_002",  // 이 이벤트를 유발한 dispatch의 ID (nullable)
  "causation_id": "evt_20260323_185000_001", // 직접 원인이 된 이벤트 ID (nullable)
  "attempt": 1,                              // 재시도 횟수 (1 = 첫 시도)

  // 중복 제거
  "idempotency_key": "claude_task001_commit_abc1234",  // inbox 경유 시 사용

  // 타입별 페이로드
  "payload": {
    "task_id": "task_001",
    "task_type": "impl",                  // impl | fix | refactor | test | review | research
    "commit": "abc1234",                  // 코드 변경 작업에만 존재
    "branch": "feature/auth",
    "cwd": ".",                           // 작업 디렉터리 (기본: ".", 병렬 시: 임시 worktree 경로)
    "summary": "auth phase 1: login endpoint + JWT generation",
    "files_changed": ["src/auth/login.ts", "src/auth/jwt.ts"],
    "output_artifact": null,              // 비코드 작업 시 결과 파일 경로
    "exit_code": 0,
    "suggested_next": "codex_review"
  }
}
```

### 1.2 source 필드 규칙

`source`는 항상 실제 작업을 수행하거나 결정을 내린 주체를 가리킨다.

| source 값 | 의미 | 예시 |
|-----------|------|------|
| `claude` / `codex` / `gemini` | 해당 에이전트가 수행한 작업 | task_complete, review_complete |
| `human` | 사용자의 결정/의견 | human_decision, human_note |
| `system` | auto-approve 규칙 등 자동화된 오케스트레이션 결정 | task_dispatched (auto-approve 경로) |

> Broker는 writer이지 source가 아니다. `system`은 사람이 아닌 규칙 엔진이 결정을 내린 경우에 사용한다.

### 1.3 인과 추적 필드

| 필드 | 용도 | 예시 |
|------|------|------|
| `dispatch_id` | 어떤 dispatch의 결과인가 | review_complete가 어떤 dispatch에서 나왔는지 |
| `causation_id` | 직접적인 원인 이벤트 | human_decision → task_dispatched 체인 |
| `attempt` | 같은 dispatch에 대한 몇 번째 시도인가 | 재시도 시 attempt=2 |
| `idempotency_key` | 같은 이벤트의 중복 발행 방지 | inbox 경유 시에만 사용 |

---

## 2. 데이터 구조

### 2.1 config.yaml

```yaml
project:
  name: "my-project"
  repo: "."

agents:
  claude:
    argv_base: ["claude", "-p"]          # 비대화형 호출 (토큰 배열)
    cli_interactive: "claude"            # tmux pane에 띄울 interactive CLI
    readonly_flags: ["--permission-mode", "plan"]
    roles: [impl, fix, refactor]
  codex:
    argv_base: ["codex", "exec"]
    cli_interactive: "codex"
    readonly_flags: []              # exec review는 기본 read-only, 별도 플래그 불필요
    roles: [review, test]           # research 제외: exec review는 코드 리뷰 전용
  gemini:
    argv_base: ["gemini", "-p"]
    cli_interactive: "gemini"
    readonly_flags: ["--approval-mode", "plan"]
    roles: [research, review]

workflow:
  approval_mode: "manual"                # manual | auto | conditional
  auto_approve_rules:
    - condition: "review_result == 'pass' and error_count == 0"
      action: "auto_approve"
    - condition: "task_type == 'research'"
      action: "auto_approve"

broker:
  inbox_poll_ms: 500
  subprocess_timeout_s: 600
  max_retries: 2

parallel:
  worktree_dir: ".worktrees"
  merge_strategy: "cherry-pick"
  enforce_single_commit: true            # dispatch당 1 commit 강제 (다수면 squash)

tmux:
  session_name: "cross-harness"
  layout: "tiled"
  pane_mode: "interactive"               # interactive (기본) | log-tail

notifications:
  desktop: true
  sound: true
  slack_webhook: null
  idle_timeout_minutes: 10
```

### 2.2 Task 정의

```yaml
# .workflow/tasks/task_001.yaml
id: task_001
title: "Implement auth phase 1"
description: "Login endpoint + JWT token generation"
status: completed                  # pending | in_progress | completed | failed
assigned_to: claude
created_at: "2026-03-23T18:00:00Z"
completed_at: "2026-03-23T18:55:00Z"
commit: "abc1234"
branch: "feature/auth"
dispatches:
  - dispatch_id: "dsp_001"
    attempt: 1
    result: "completed"
human_notes:
  - "세션 만료 edge case도 확인 필요"
next_suggested: codex_review
depends_on: []
```

### 2.3 state.json

```jsonc
{
  "workflow_status": "active",
  "current_phase": "review",
  "last_updated": "2026-03-23T19:05:00Z",
  "last_writer": "broker",

  "agents": {
    "claude": {
      "status": "idle",
      "current_dispatch": null,
      "last_activity": "2026-03-23T18:55:00Z",
      "subprocess_pid": null,
      "session_id": "ses_claude_20260323_180000",    // CLI 세션 ID (resume용)
      "session_mode": "resume",                       // new | resume
      "last_session_used_at": "2026-03-23T18:55:00Z"
    },
    "codex": {
      "status": "working",
      "current_dispatch": "dsp_002",
      "last_activity": "2026-03-23T19:01:00Z",
      "subprocess_pid": 12345,
      "session_id": "ses_codex_20260323_190100",
      "session_mode": "resume",
      "last_session_used_at": "2026-03-23T19:01:00Z"
    },
    "gemini": {
      "status": "idle",
      "current_dispatch": null,
      "last_activity": "2026-03-23T18:30:00Z",
      "subprocess_pid": null,
      "session_id": null,                             // 아직 실행된 적 없음
      "session_mode": "new",                             // Gemini: MVP에서 항상 new
      "last_session_used_at": null                       //   (resume은 Phase 2)
    }
  },

  // dispatch → agent 역조회 인덱스 (done 명령 등에서 사용)
  // 불변식: 모든 활성/완료 dispatch는 이 인덱스에 존재한다
  "dispatch_index": {
    "dsp_001": {"agent": "claude", "task_id": "task_001", "status": "completed", "session_id": "ses_claude_20260323_180000"},
    "dsp_002": {"agent": "codex", "task_id": "task_002", "status": "active", "session_id": "ses_codex_20260323_190100"}
  },

  "pending_decisions": [],
  "event_count": 42,
  "last_event_id": "evt_20260323_190100_042"
}
```

---

## 3. Agent Adapter 인터페이스

```python
class AgentAdapter:
    """CLI별 비대화형 호출을 추상화하는 어댑터."""

    name: str              # "claude" | "codex" | "gemini"
    project_root: Path     # 프로젝트 디렉터리 (공유)
    argv_base: list[str]   # 비대화형 호출 토큰 배열 (예: ["claude", "-p"])
    readonly_flags: list[str]  # read-only 모드 플래그

    def resolve_session_mode(self, agent_state: dict, task_type: str,
                             prev_task_type: str | None) -> str:
        """
        세션 모드를 결정한다 (new | resume).

        - session_id가 None → "new"
        - task_type이 이전과 크게 다름 (impl→review 등) → "new"
        - 이전 dispatch가 task_failed → "new"
        - 사용자가 Console에서 "fresh session" 요청 → "new"
        - 그 외 → "resume"

        ※ fork는 MVP에서 지원하지 않는다. "새 canonical session이 필요한 상황"은
          모두 new로 처리한다. fork(기존 세션을 복제하여 분기)는 CLI별 지원 여부가
          불명확하며, state에 agent당 session_id가 하나이므로 분기 세션의 수명/소유
          관리가 복잡해진다. Phase 2에서 multi-session state 도입 시 재검토.
        """
        ...

    def build_command(self, task_type: str, prompt: str,
                      profile_dir: Path,
                      session_mode: str, session_id: str | None) -> list[str]:
        """
        세션 + 프로필 + read-only를 모두 반영한 최종 커맨드를 구성한다.
        CLI별로 인자 위치/호환성이 다르므로 각 어댑터가 직접 구현.

        2026-03-24 기준 CLI별 차이:
          Claude: --resume <id>, --verbose + --output-format stream-json 필수
          Codex:  exec resume <id> <prompt> (impl/fix/refactor/test)
                  exec review <prompt> (review, 항상 fresh, resume 미지원)
                  research는 Codex 타겟에서 제외
          Gemini: MVP에서 resume 비지원 (항상 new, artifact 주입으로 보상)
        """
        ...

    def extract_session_id(self, stdout: str) -> str | None:
        """subprocess stdout에서 session_id를 추출한다. CLI별로 구현."""
        ...

    def execute(self, prompt: str, dispatch_id: str,
                task_type: str,
                profile_dir: Path,
                session_mode: str = "resume",
                session_id: str | None = None,
                cwd: Path | None = None) -> ExecutionResult:
        """
        비대화형으로 에이전트를 실행하고 결과를 반환한다.

        1. clean tree 확인 (git status --porcelain, 비어있지 않으면 거부)
        2. pre_head = git rev-parse HEAD
        3. .workflow/lock 생성 (수동 commit 차단)
        4. 프롬프트 생성 (artifact 요약 + human note + 목표/종료 조건 주입)
        5. 커맨드 구성: adapter.build_command() 호출
           - CLI별로 세션/프로필/read-only 인자를 직접 조립 (§4.2~4.4)
        6. subprocess 실행 (Popen, cwd=project_root 또는 임시 worktree)
           - env에 CROSS_HARNESS_BROKER=1 설정 (post-commit hook skip용)
        7. stdout/stderr 캡처
        8. exit code 확인
        9. post_head = git rev-parse HEAD
        10. (lock 유지 상태에서) dirty tree 검증
        11. commit_count = git rev-list --count pre_head..post_head
            - 0: commit 없음 (비코드 작업)
            - 1: 정상 코드 변경
            - >1: 공유 dir이면 경고, 임시 worktree면 squash
        12. ExecutionResult 반환 (Broker가 이벤트 기록 후 lock 삭제)
        """
        ...


@dataclass
class ExecutionResult:
    exit_code: int
    stdout: str
    stderr: str
    pre_head: str
    post_head: str
    has_new_commit: bool      # pre_head != post_head
    commit_count: int         # git rev-list --count pre..post
    commit: str | None        # 최종 commit hash (squash 후일 수도 있음)
    files_changed: list[str]  # git diff --name-only pre..post
    duration_s: float
    session_id: str | None    # CLI가 반환한 세션 ID (다음 resume용)
```

---

## 4. CLI 실행 예시

> CLI별 디렉터리 옵션이 다르므로 프로세스 수준 cwd(`subprocess.Popen(cwd=...)`)를 사용한다.
> 모든 예시는 session + profile + readonly를 통합한 실제 실행 경로를 보여준다.

### 4.1 통합 커맨드 구성

```python
def build_full_command(adapter, task_type, prompt, profile_dir, session_state):
    """
    세션 + 프로필 + read-only를 모두 반영한 최종 커맨드를 구성한다.
    CLI별 인자 위치/호환성이 다르므로 각 adapter.build_command()에 위임한다.
    """
    return adapter.build_command(
        task_type=task_type,
        prompt=prompt,
        profile_dir=profile_dir,
        session_mode=session_state.mode,
        session_id=session_state.session_id,
    )
```

> 공통 build_full_command는 adapter.build_command()로 위임만 한다. CLI마다 인자 위치, resume 구문, read-only 플래그 호환성이 달라서 공통 조립 로직으로 통일할 수 없다.

### 4.2 Claude 실행 예시

```python
class ClaudeAdapter(AgentAdapter):
    # argv_base = ["claude", "-p"]

    def build_command(self, task_type, prompt, profile_dir,
                      session_mode, session_id):
        cmd = ["claude", "-p", prompt]
        # 세션 재개
        if session_mode == "resume" and session_id:
            cmd += ["--resume", session_id]
        # MCP 프로필
        mcp = profile_dir / "mcp.json"
        if mcp.exists():
            cmd += ["--mcp-config", str(mcp)]
        # read-only
        if task_type in ("review", "research"):
            cmd += ["--permission-mode", "plan"]
        # session_id 추출을 위해 stream-json + verbose 필수
        cmd += ["--output-format", "stream-json", "--verbose"]
        return cmd
```

```python
# Claude — impl, resume 세션
subprocess.Popen(
    ["claude", "-p", prompt,
     "--resume", session_id,
     "--mcp-config", str(profile_dir / "mcp.json"),
     "--output-format", "stream-json", "--verbose"],      # --verbose 필수
    cwd=PROJECT_ROOT,
    env={**os.environ, "CROSS_HARNESS_BROKER": "1"},
    stdout=PIPE, stderr=subprocess.STDOUT,
)
```

> **--verbose 필수**: 2026-03 기준 Claude는 `-p` 모드에서 `--output-format stream-json` 사용 시 `--verbose`도 함께 요구한다. 없으면 session_id가 출력되지 않아 다음 dispatch가 항상 new로 떨어진다.

### 4.3 Codex 실행 예시

Codex는 서브커맨드별 인자 구조가 다르므로 **task_type + session_mode 조합에 따라 경로를 분기**한다.

> 2026-03-24 기준: `--json`은 `codex exec review`에서만 지원. `codex review`(단독)는 `--json` 미지원. MCP/profile 주입은 `--config` 플래그가 아닌 환경변수 또는 설정 파일 경로 방식.

```python
class CodexAdapter(AgentAdapter):
    # argv_base = ["codex", "exec"]

    def build_command(self, task_type, prompt, profile_dir,
                      session_mode, session_id):
        if task_type == "review":
            # read-only 코드 리뷰: codex exec review (--json 지원)
            # exec review는 항상 fresh (세션 resume 없음)
            cmd = ["codex", "exec", "review", prompt, "--json"]
        elif session_mode == "resume" and session_id:
            # resume 경로: codex exec resume <session_id> <prompt>
            cmd = ["codex", "exec", "resume", session_id, prompt, "--json"]
        else:
            # new 경로: codex exec <prompt>
            cmd = ["codex", "exec", prompt, "--json"]

        return cmd

    def inject_profile(self, profile_dir, dispatch_sandbox):
        """
        Codex는 CLI 인자로 MCP/Skill config를 받지 않음.
        per-dispatch sandbox에 설정 배치 + HOME override로 격리.

        2026-03-24 기준: Codex는 ~/.codex/ 아래 설정을 읽는다.
        HOME을 sandbox로 바꾸면 sandbox/.codex/가 설정 디렉터리가 된다.
        """
        # 1. sandbox 안에 Codex가 실제로 읽는 경로 구조 생성
        codex_config = dispatch_sandbox / ".codex"
        codex_config.mkdir(parents=True, exist_ok=True)
        # 2. 기존 사용자 설정(~/.codex/config.toml 등)을 sandbox에 복사
        real_codex = Path.home() / ".codex"
        if (real_codex / "config.toml").exists():
            shutil.copy(real_codex / "config.toml", codex_config / "config.toml")
        # 3. generated MCP 설정을 sandbox에 merge/추가
        if (profile_dir / "mcp.json").exists():
            shutil.copy(profile_dir / "mcp.json", codex_config / "mcp.json")
        # 4. prompt-prelude 내용은 프롬프트 텍스트에 prepend (build_command에서 처리)
        # 5. HOME override → Codex가 sandbox/.codex/를 읽음
        return {"HOME": str(dispatch_sandbox)}
```

```python
# Codex — review (read-only, codex exec review, --json 지원)
subprocess.Popen(
    ["codex", "exec", "review", prompt, "--json"],
    cwd=PROJECT_ROOT,
    env={**os.environ, "CROSS_HARNESS_BROKER": "1",
         "HOME": str(dispatch_sandbox)},            # sandbox/.codex/를 읽음
    stdout=PIPE, stderr=subprocess.STDOUT,
)
```

```python
# Codex — impl, resume 세션
subprocess.Popen(
    ["codex", "exec", "resume", session_id, prompt, "--json"],
    cwd=PROJECT_ROOT,
    env={**os.environ, "CROSS_HARNESS_BROKER": "1",
         "HOME": str(dispatch_sandbox)},
    stdout=PIPE, stderr=subprocess.STDOUT,
)
```

> **Codex review는 항상 fresh 세션**: `codex exec review`는 resume을 지원하지 않으므로 매번 새 세션이다. 이것은 의도된 설계 — 코드 리뷰는 이전 리뷰 문맥에 오염되지 않는 fresh 관점이 바람직하다.

> **Codex는 research 타겟에서 제외**: `codex exec review`는 저장소 코드 리뷰 전용 명령이다. 외부 조사/연구 성격의 research task를 여기에 태우면 의미가 맞지 않는다. **research task의 Codex 할당을 금지한다.** config의 `roles`에서도 research를 제거한다.

### 4.4 Gemini 실행 예시

```python
class GeminiAdapter(AgentAdapter):
    # argv_base = ["gemini", "-p"]

    def build_command(self, task_type, prompt, profile_dir,
                      session_mode, session_id):
        cmd = ["gemini", "-p", prompt]
        # MVP: Gemini resume 비지원 — 항상 new 세션
        # 이전 문맥은 프롬프트의 artifact 주입으로 보상
        # read-only
        if task_type in ("review", "research"):
            cmd += ["--approval-mode", "plan"]
        return cmd

    def inject_profile(self, profile_dir, dispatch_sandbox):
        """
        Gemini도 CLI 인자로 MCP config를 받지 않음.
        per-dispatch sandbox에 설정 배치 + HOME override로 격리.

        2026-03-24 기준: Gemini는 $HOME/.gemini/settings.json 계열을 읽는다.
        GEMINI_HOME 같은 전용 변수는 무시됨 — HOME 자체를 바꿔야 설정 경로가 바뀐다.
        """
        # 1. sandbox 안에 Gemini가 실제로 읽는 경로 구조 생성
        gemini_config = dispatch_sandbox / ".gemini"
        gemini_config.mkdir(parents=True, exist_ok=True)
        # 2. 기존 사용자 설정을 sandbox에 복사
        real_gemini = Path.home() / ".gemini"
        if (real_gemini / "settings.json").exists():
            shutil.copy(real_gemini / "settings.json", gemini_config / "settings.json")
        # 3. generated MCP 설정을 sandbox에 merge/추가
        if (profile_dir / "mcp.json").exists():
            shutil.copy(profile_dir / "mcp.json", gemini_config / "mcp.json")
        # 4. HOME override → Gemini가 sandbox/.gemini/를 읽음
        return {"HOME": str(dispatch_sandbox)}

```

> **Gemini resume: MVP에서 비지원 (항상 new 세션)**
>
> Gemini `--resume`은 세션 index를 입력으로 받는데, interactive pane에서 생성된 세션이 index를 밀어버리므로 adapter가 관리하는 index와 실제 Gemini index가 drift할 수 있다. Gemini CLI에 sessions 조회 API도 없고, "latest"는 pane 세션과 혼동 위험이 있다.
>
> 따라서 **MVP에서 Gemini resume을 지원하지 않는다**. 모든 Gemini dispatch는 새 세션이며, 이전 문맥은 프롬프트의 explicit artifact 주입으로 보상한다. Gemini CLI가 안정적인 session UUID 기반 resume을 지원하게 되면 Phase 2에서 재활성화한다.

> **Codex/Gemini MCP 주입 전략: per-dispatch sandbox** (기본 설정 위치 덮어쓰기 아님):

두 CLI 모두 MCP config를 CLI 인자로 받지 않는다. **기본 설정 위치를 직접 덮어쓰면 interactive pane 세션에 설정이 새어 들어가고 crash 시 원복 누락이 생긴다.**

대신 **per-dispatch sandbox + HOME override**를 사용한다:

```
1. dispatch마다 임시 sandbox 디렉터리 생성
   .workflow/sandbox/dsp_001/

2. adapter.inject_profile()로 sandbox에 설정 구조 생성
   - 기존 사용자 설정(~/.codex/config.toml 등)을 sandbox에 복사
   - generated MCP config를 sandbox에 추가
   → sandbox/.codex/ 또는 sandbox/.gemini/ 구조

3. subprocess 실행 시 HOME을 sandbox로 override
   env = {HOME: sandbox_path}
   → CLI가 sandbox/.codex/ 또는 sandbox/.gemini/를 읽음
   → interactive pane(원래 HOME)의 설정에 영향 없음

4. dispatch 완료 후 sandbox 디렉터리 삭제
   (crash 시에도 orphan sandbox만 남고, 기본 설정은 무사)
```

이 방식의 장점:
- interactive pane 세션과 완전 격리
- crash 시 기본 설정 오염 없음 (orphan sandbox만 GC 대상)
- 병렬 dispatch 시에도 각자 별도 sandbox

### 4.5 Session ID 추출 규약

각 CLI에서 subprocess 완료 후 session_id를 추출하는 방법은 CLI마다 다르다. 이것은 adapter 구현의 핵심 계약이다.

| CLI | 출력 모드 강제 | session_id 추출 위치 | 파싱 방법 | 비고 |
|-----|--------------|---------------------|----------|------|
| Claude | `--output-format stream-json --verbose` | stdout JSON stream | 마지막 `result` 이벤트의 `session_id` | `--verbose` 없으면 미출력 |
| Codex | `--json` (`exec`, `exec resume`, `exec review`) | stdout JSON stream | `thread.started` 이벤트의 `thread_id` | `exec review`는 항상 fresh (resume 없음) |
| Gemini | JSON 출력 모드 | stdout JSON | 최종 응답의 `session_id` | MVP: resume 비지원 (추출은 하되 저장만, resume에 사용 안 함) |

```python
class ClaudeAdapter(AgentAdapter):
    def extract_session_id(self, stdout: str) -> str | None:
        """
        stream-json + --verbose 출력에서 session_id를 추출.
        --verbose 없으면 session_id가 출력되지 않을 수 있음.
        """
        for line in reversed(stdout.strip().splitlines()):
            try:
                event = json.loads(line)
                if "session_id" in event:
                    return event["session_id"]
            except json.JSONDecodeError:
                continue
        return None

class CodexAdapter(AgentAdapter):
    def extract_session_id(self, stdout: str) -> str | None:
        """--json 출력에서 thread.started.thread_id를 추출."""
        for line in stdout.strip().splitlines():
            try:
                event = json.loads(line)
                if event.get("type") == "thread.started":
                    return event.get("thread_id")
            except json.JSONDecodeError:
                continue
        return None

class GeminiAdapter(AgentAdapter):
    def extract_session_id(self, stdout: str) -> str | None:
        """JSON 출력에서 session_id를 추출. resume 시에는 별도 token 변환 필요."""
        for line in reversed(stdout.strip().splitlines()):
            try:
                data = json.loads(line)
                if "session_id" in data:
                    return data["session_id"]
            except json.JSONDecodeError:
                continue
        return None
```

> **Fallback 규칙**: 추출 실패 시 `session_id=None` → 다음 dispatch는 자동으로 new 세션.

---

## 5. CLI 명령 (cross-harness)

### 5.1 `cross-harness begin` — 수동 작업 진입

```bash
# 기존 dispatch takeover
cross-harness begin --takeover dsp_002

# 새 수동 dispatch 생성
cross-harness begin --agent claude --type impl --task-id task_001
# → dispatch_id 발급됨 (예: dsp_003)
# → .workflow/manual_dispatch.claude 생성
```

동작:
1. dispatch_id 발급 (또는 takeover)
2. agent별 `.workflow/manual_dispatch.{agent}` 파일 생성
3. task_dispatched 이벤트를 inbox에 drop

**agent-scoped 파일로 pane 간 오귀속 방지**:
```
.workflow/manual_dispatch.claude   ← Claude pane의 begin 결과
.workflow/manual_dispatch.codex    ← Codex pane의 begin 결과
```

**자동 정리 (삭제는 항상 이벤트 파일 생성 성공 후)**:
- `cross-harness done`: inbox에 이벤트 파일 write 성공 후 해당 agent의 파일 삭제
- post-commit hook: inbox에 이벤트 파일 write 성공 후 해당 agent의 파일 삭제 (1 dispatch = 1 commit)
- `begin`이 이미 해당 agent에 active dispatch 있으면: 기존 것을 먼저 닫을지 물음

> inbox write가 실패하면 manual_dispatch 파일이 남아있으므로 재시도가 가능하다.

### 5.2 `cross-harness done` — 수동 비코드 작업 완료

```bash
# --dispatch-id 필수
cross-harness done --dispatch-id dsp_002 --type review \
  --summary "input validation 누락, 2건 warning"

# 파일로 결과 전달
cross-harness done --dispatch-id dsp_002 --type review --file /tmp/my_review.md

# dispatch_id 모르겠으면
cross-harness status   # 현재 활성 dispatch 목록
```

동작:
1. `dispatch_id` 유효성 검증 (`state.json`의 `dispatch_index`에 존재 확인)
2. `dispatch_index[dispatch_id]`에서 `agent`, `task_id` 역조회
3. 결과를 `.workflow/outputs/{dispatch_id}.md`에 저장
4. inbox에 이벤트 drop (dispatch_id/causation_id/task_id 포함)
5. inbox write 성공 후 `.workflow/manual_dispatch.{agent}` 삭제

```jsonc
// done이 inbox에 drop하는 이벤트
{
  "source": "codex",                                     // dispatch_id에서 agent 역조회
  "type": "review_complete",
  "dispatch_id": "dsp_002",
  "causation_id": "evt_003",                             // dispatch를 유발한 이벤트
  "attempt": 1,
  "idempotency_key": "manual_codex_dsp_002",
  "payload": {
    "task_type": "review",
    "task_id": "task_002",
    "output_artifact": ".workflow/outputs/dsp_002.md",
    "summary": "input validation 누락, 2건 warning",
    "manual": true
  }
}
```

### 5.3 `cross-harness unlock` — Stale lock 수동 제거

```bash
cross-harness unlock          # lock 파일의 PID 확인 후 삭제
cross-harness unlock --force  # PID 확인 없이 강제 삭제
```

### 5.4 `cross-harness status` — 현재 상태 조회

현재 활성 dispatch, agent 상태, lock 여부를 표시한다.

---

## 6. Dispatch 알고리즘

```
Human Decision
  → dispatch_id 발급

  세션 모드 결정 (new | resume, fork는 MVP 미지원):
    agent_state = state.json["agents"][agent]
    session_id = agent_state["session_id"]
    session_mode = adapter.resolve_session_mode(agent_state, task_type, prev_task_type)
      - session_id == null → "new"
      - task_type이 이전과 크게 다름 → "new"
      - 이전 dispatch가 task_failed → "new"
      - 사용자가 Console에서 "fresh session" 요청 → "new"
      - Codex review → 항상 "new" (exec review가 resume 미지원)
      - Gemini → 항상 "new" (MVP에서 resume 비지원)
      - 그 외 → "resume"

  Profile activation (§13.9):
    bundles = resolve_bundles_for_dispatch(agent, task_type)
    profile_id, profile_dir = activate_profile_for_dispatch(dispatch)
    dispatch_sandbox = create_sandbox(dispatch_id)  # per-dispatch 격리 디렉터리
    env_overrides = adapter.inject_profile(profile_dir, dispatch_sandbox)  # Codex/Gemini: HOME override

  → 프롬프트 생성 (.workflow/prompts/{dispatch_id}.md)
    - resume이어도 항상 주입: 이전 dispatch 요약, commit/artifact, human note, 목표/종료 조건
    - generated profile의 prompt-prelude.md 내용 포함
  → clean tree 확인 (git status --porcelain → 비어있지 않으면 거부)
  → pre_head = git rev-parse HEAD
  → .workflow/lock 생성
  → review/research면 read-only 플래그 추가
  → subprocess 실행:
      cmd = adapter.build_command(task_type, prompt, profile_dir, session_mode, session_id)
      env = {**os.environ, "CROSS_HARNESS_BROKER": "1", **env_overrides}
      Popen(cmd, cwd=PROJECT_ROOT, env=env)
    - 병렬 코드 수정이면: 임시 worktree 생성 후 그 경로를 cwd로
  → stdout/stderr 캡처 → .workflow/outputs/{dispatch_id}.md
  → post_head = git rev-parse HEAD

  ── lock 유지 상태에서 검증 + 이벤트 기록 ──

  post-run dirty tree 검증:
    git status --porcelain → 비어있지 않으면 task_failed (외부 수정 감지)

  코드 변경 판정:
    pre_head == post_head → commit 없음 → output artifact로 처리
    pre_head != post_head →
      commit_count = git rev-list --count pre_head..post_head
      commit_count == 1 → task_complete (post_head를 기준 commit으로 기록)
      commit_count > 1 →
        공유 디렉터리:
          → task_needs_decision 이벤트
          → Console에 "N개 commit 생성됨. 수용/squash/실패 선택" 표시
          → 사용자 결정 전까지 downstream 진행 안 함 (lock도 유지)
        임시 worktree:
          → 자동 squash (git reset --soft pre_head && git commit)
          → squash된 단일 commit을 cherry-pick

  → 완료 이벤트 기록 (dispatch_id로 귀속, 기준 commit 명시)
  → state.json 갱신: agents[agent].session_id = result.session_id
  → dispatch_index[dispatch_id].session_id = result.session_id
  → profile lease 해제 (dispatch 완료)
  → 병렬이었다면: 임시 worktree 결과를 메인으로 merge 후 worktree 정리
  → .workflow/lock 삭제 (모든 검증 + 이벤트 기록 완료 후)
```

---

## 7. Broker 내부 구현

### 7.1 Inbox 처리

```bash
# 이벤트 발행 요청 예시: 어댑터 → inbox
cat > .workflow/inbox/evt_$(date +%s%N).json << 'EOF'
{
  "source": "claude",
  "type": "task_complete",
  "idempotency_key": "claude_task001_commit_abc1234",
  "payload": { ... }
}
EOF
```

```
Broker 처리 흐름:
  inbox/ 파일 감지 (fswatch 또는 polling)
  → JSON 파싱 및 검증
  → idempotency_key 중복 체크 (이미 처리한 키면 skip)
  → 이벤트 ID/timestamp 부여
  → events.jsonl에 append (write + fsync)
  → state.json atomic update (write to .tmp → rename)
  → inbox 파일 삭제 (처리 완료)
  → Console에 알림
```

### 7.2 Post-run Dirty Tree 검증

```python
dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True).stdout.strip()
if dirty:
    emit_event(type="task_failed",
               reason="dirty_tree_after_run",
               detail=f"Untracked/modified files detected: {dirty}")
```

### 7.3 Stale Lock 복구

```python
# Broker 시작 시
if lock_file_exists():
    lock = read_lock()
    if not pid_is_alive(lock["pid"]):
        log.warning(f"Stale lock detected (pid {lock['pid']} dead), removing")
        remove_lock()
    else:
        log.info(f"Active lock found (pid {lock['pid']}), keeping")
```

### 7.4 Repo Lock 흐름

```
Broker subprocess 시작:
  → .workflow/lock 생성: {"agent": "claude", "dispatch_id": "dsp_001", "pid": 12345}
  → pre-commit hook이 lock 감지 → 수동 commit 차단

Broker subprocess 종료:
  → (lock 유지 상태)
  → post-run dirty tree 검증
  → 코드 변경 판정 (pre_head/post_head, commit_count)
  → 최종 이벤트 기록 (task_complete / task_failed / task_needs_decision)
  → .workflow/lock 삭제 (모든 검증 + 기록 완료 후)
```

---

## 8. Git Hooks

### 8.1 pre-commit hook — Broker working 중 commit 차단

```bash
#!/bin/bash
# .git/hooks/pre-commit

WORKFLOW_DIR="$(git rev-parse --show-toplevel)/.workflow"
LOCK_FILE="$WORKFLOW_DIR/lock"

if [ -f "$LOCK_FILE" ]; then
  AGENT=$(python3 -c "import json; print(json.load(open('$LOCK_FILE'))['agent'])" 2>/dev/null)
  DSP=$(python3 -c "import json; print(json.load(open('$LOCK_FILE'))['dispatch_id'])" 2>/dev/null)
  echo "cross-harness: Broker가 ${AGENT} 작업 중 (${DSP}). 완료 후 다시 시도하세요." >&2
  exit 1
fi
```

### 8.2 post-commit hook — 수동 코드 변경 이벤트 발행

`cross-harness begin` 후 commit한 경우에 동작한다.
agent별 `manual_dispatch.{agent}` 파일에서 인과 추적 정보를 읽어 이벤트에 포함한다.

```bash
#!/bin/bash
# .git/hooks/post-commit

# Broker subprocess에서는 skip
if [ -n "$CROSS_HARNESS_BROKER" ]; then
  exit 0
fi

WORKFLOW_DIR="$(git rev-parse --show-toplevel)/.workflow"
COMMIT_HASH=$(git log -1 --pretty=%h)
COMMIT_MSG=$(git log -1 --pretty=%B)
AGENT_NAME="${CROSS_HARNESS_AGENT:-unknown}"
IDEMP_KEY="commit_${COMMIT_HASH}"

# agent별 manual_dispatch 파일에서 인과 추적 정보 읽기
MANUAL_DSP="$WORKFLOW_DIR/manual_dispatch.${AGENT_NAME}"
if [ -f "$MANUAL_DSP" ]; then
  # 파일의 agent와 현재 pane의 agent 일치 확인
  FILE_AGENT=$(python3 -c "import json; print(json.load(open('$MANUAL_DSP'))['agent'])" 2>/dev/null)
  if [ "$FILE_AGENT" != "$AGENT_NAME" ]; then
    echo "cross-harness: 경고 — manual_dispatch agent 불일치 ($FILE_AGENT != $AGENT_NAME)" >&2
    DISPATCH_ID="null"; TASK_ID="null"; CAUSATION_ID="null"
  else
    DISPATCH_ID=$(python3 -c "import json; print(json.load(open('$MANUAL_DSP'))['dispatch_id'])" 2>/dev/null)
    TASK_ID=$(python3 -c "import json; print(json.load(open('$MANUAL_DSP'))['task_id'])" 2>/dev/null)
    CAUSATION_ID=$(python3 -c "import json; print(json.load(open('$MANUAL_DSP'))['causation_id'])" 2>/dev/null)
    SHOULD_CLEANUP_MANUAL=1
  fi
else
  # cross-harness begin 없이 commit됨 → 비추적 commit
  DISPATCH_ID="null"; TASK_ID="null"; CAUSATION_ID="null"
  echo "cross-harness: 경고 — begin 없이 commit됨. 'cross-harness begin'으로 dispatch를 먼저 등록하세요." >&2
fi

# inbox에 이벤트 파일 생성
EVT_FILE="$WORKFLOW_DIR/inbox/evt_$(date +%s%N).json"
cat > "$EVT_FILE" << EOF
{
  "source": "${AGENT_NAME}",
  "type": "task_complete",
  "dispatch_id": ${DISPATCH_ID:+\"$DISPATCH_ID\"}${DISPATCH_ID:-null},
  "causation_id": ${CAUSATION_ID:+\"$CAUSATION_ID\"}${CAUSATION_ID:-null},
  "idempotency_key": "${IDEMP_KEY}",
  "payload": {
    "task_id": ${TASK_ID:+\"$TASK_ID\"}${TASK_ID:-null},
    "commit": "${COMMIT_HASH}",
    "message": "${COMMIT_MSG}",
    "manual": true
  }
}
EOF

# inbox write 성공 후에만 manual_dispatch 정리 (실패 시 재시도 가능하도록)
if [ -f "$EVT_FILE" ] && [ -n "$SHOULD_CLEANUP_MANUAL" ]; then
  rm -f "$MANUAL_DSP"
fi
```

---

## 9. 프롬프트 템플릿

Dispatch 시 `.workflow/prompts/{dispatch_id}.md`로 저장 후 전달:

```markdown
## Task: {task_type}

### Context
- Dispatch: {dispatch_id} (attempt: {attempt})
- Session: {session_mode} ({session_id})
- Previous agent: {source_agent}
- Previous dispatch: {previous_dispatch_id}
- Branch: {branch}

### Previous Dispatch Summary
{previous_dispatch_summary}

### Relevant Artifacts
{commit_hashes_and_output_artifact_content}

### Human Notes
{human_notes}

### Your Assignment
{generated_instruction}

### Goal and Exit Criteria
{goal_description}
{exit_criteria}

### Files to Focus On
{files_list}

### Completion
- For code changes: commit with descriptive message (single commit per dispatch)
- For review/research: write your findings to stdout
```

> **resume이어도 위 내용을 항상 주입한다.** CLI의 내부 세션 메모리는 불투명하므로, artifact 기반 explicit context가 source of truth이다.

---

## 10. tmux 세션 초기화

```bash
#!/bin/bash
# cross-harness-start.sh

set -euo pipefail

SESSION="cross-harness"
REPO_DIR="$(pwd)"
WORKFLOW_DIR="$REPO_DIR/.workflow"

# ─── Step 1: 워크플로우 디렉터리 초기화 ───
mkdir -p "$WORKFLOW_DIR"/{inbox,tasks,prompts,outputs,human-notes}

# ─── Step 2: Broker 시작 (백그라운드) ───
cross-harness broker --config "$WORKFLOW_DIR/config.yaml" &
BROKER_PID=$!
echo "Broker started (PID: $BROKER_PID)"

# ─── Step 3: tmux 세션 생성 ───
tmux new-session -d -s $SESSION -n main

# 4개 패널 생성
tmux split-window -h -t $SESSION:main
tmux split-window -v -t $SESSION:main.0
tmux split-window -v -t $SESSION:main.1

# 레이아웃 적용
tmux select-layout -t $SESSION:main tiled

# 에이전트 interactive CLI (사람이 직접 조작 가능)
tmux send-keys -t $SESSION:main.0 \
  "cd $REPO_DIR && export CROSS_HARNESS_AGENT=claude && claude" Enter
tmux send-keys -t $SESSION:main.1 \
  "cd $REPO_DIR && export CROSS_HARNESS_AGENT=codex && codex" Enter
tmux send-keys -t $SESSION:main.2 \
  "cd $REPO_DIR && export CROSS_HARNESS_AGENT=gemini && gemini" Enter

# Human Control Console (TUI)
tmux send-keys -t $SESSION:main.3 \
  "cross-harness console --config $WORKFLOW_DIR/config.yaml" Enter

# 패널 이름 설정
tmux select-pane -t $SESSION:main.0 -T "Claude"
tmux select-pane -t $SESSION:main.1 -T "Codex"
tmux select-pane -t $SESSION:main.2 -T "Gemini"
tmux select-pane -t $SESSION:main.3 -T "Human Control"

tmux set -t $SESSION pane-border-status top
tmux set -t $SESSION pane-border-format "#{pane_title}"

# 세션 연결
tmux attach -t $SESSION
```

### 수동 조작 주의사항

pane에 interactive CLI가 이미 떠 있으므로 별도 전환 없이 바로 타이핑 가능.

**Broker working 중에는 commit이 차단된다** (pre-commit hook의 lock 체크):

```
Console 표시 예시:
  ● Claude   idle          ← 수동 조작 + commit 가능
  ◉ Codex    working 🔒    ← subprocess 실행 중, commit 차단됨
  ○ Gemini   idle          ← 수동 조작 + commit 가능
```

수동 비코드 작업 완료 시:
```bash
cross-harness done --dispatch-id dsp_002 --type review --summary "LGTM, 이슈 없음"
```

---

## 11. 에러 복구 구현

### 11.1 Broker 재시작 복구

1. `.workflow/lock` 존재 시: lock의 PID 생존 확인 → dead면 stale lock 삭제
2. state.json을 읽어 마지막 상태 복원
3. events.jsonl에서 마지막 이벤트 ID 확인
4. 실행 중이던 subprocess가 있으면 PID로 상태 확인
5. inbox에 미처리 파일이 있으면 순차 처리

### 11.2 이벤트 리플레이

- events.jsonl은 append-only이므로 전체 히스토리 보존
- `dispatch_id` + `causation_id`로 인과 체인 재구성 가능
- 특정 dispatch부터 재시도 가능 (attempt 증가)

### 11.3 Idempotency 보장

- 같은 `idempotency_key`를 가진 이벤트는 한 번만 기록
- Broker 재시작 후 inbox 재처리 시에도 중복 없음

---

## 12. 설정 스키마 상세

### 12.1 에이전트 추가 예시

```yaml
# 새 에이전트 추가: Copilot CLI
agents:
  copilot:
    argv_base: ["gh", "copilot", "suggest"]
    cli_interactive: "gh copilot"
    readonly_flags: []
    roles: [impl, fix]
```

### 12.2 커스텀 워크플로우

```yaml
# .workflow/workflows/impl-review-fix.yaml
name: "Implementation → Review → Fix"
steps:
  - agent: claude
    task_type: impl
    on_complete:
      suggest: codex_review

  - agent: codex
    task_type: review           # review → output artifact, git commit 아님
    on_complete:
      if_pass: suggest_merge
      if_fail: suggest_claude_fix

  - agent: claude
    task_type: fix
    on_complete:
      suggest: codex_review
```

### 12.3 Auto-Approve 규칙

```yaml
auto_approve_rules:
  - name: "Auto-approve passing reviews"
    condition:
      event_type: review_complete
      exit_code: 0
      output_contains: "no errors found"
    action: auto_dispatch
    target: merge

  - name: "Auto-dispatch research"
    condition:
      event_type: research_complete
    action: auto_dispatch
    target: human_review
```

### 12.4 알림 설정

```yaml
notifications:
  desktop: true
  sound: true
  slack_webhook: null
  idle_timeout_minutes: 10
```

---

## 13. Skill/MCP Registry 구현

### 13.1 Registry 스키마

**skills.yaml**:

```yaml
skills:
  - id: repo-review
    enabled: true
    source:
      type: git                 # git | local
      url: https://github.com/acme/agent-assets
      ref: v1.2.0
      path: skills/repo-review
    targets: [claude, codex, gemini]
    bundles: [base, review]
    priority: 50
    materialization:
      preferred: prompt         # MVP: prompt 전용. Phase 2: auto | native | prompt
```

**mcps.yaml**:

```yaml
mcps:
  - id: github
    enabled: true
    transport: stdio
    launcher:
      command: npx
      args: ["-y", "@modelcontextprotocol/server-github"]
      env:
        GITHUB_TOKEN: ${env:GITHUB_TOKEN}   # 평문 금지, 환경변수 참조만 허용
    bundles: [base, review]
    targets: [claude, codex]
    permissions:
      network: true
      read_paths: []
      write_paths: []           # write path 있으면 base bundle에 넣지 않음
    healthcheck:
      type: process_start
      timeout_s: 10
```

**bundles.yaml** (MVP: defaults + by_agent + by_task_type만):

```yaml
bundles:
  base:
    skills: [repo-review]
    mcps: [github]
  impl:
    skills: []
    mcps: []
  review:
    skills: [repo-review]
    mcps: [github]
  research:
    skills: []
    mcps: [docs]

policy:
  defaults: [base]
  by_agent:
    claude: [impl]
    codex: [review]
    gemini: [research]
  by_task_type:
    impl: [impl]
    fix: [impl]
    refactor: [impl]
    review: [review]
    research: [research]
  # by_mode: Phase 2
```

### 13.2 Skill Package 규약

```text
vendor/skills/<skill-id>@<commit>/
├── SKILL.yaml       # id, version, entrypoint, provides, agent_overrides
├── SKILL.md         # 메인 프롬프트 (entrypoint)
├── prompts/
│   ├── shared.md    # 공통 프롬프트 fragment
│   ├── claude.md    # Claude 전용 (optional)
│   ├── codex.md     # Codex 전용 (optional)
│   └── gemini.md    # Gemini 전용 (optional)
└── assets/          # 참조 파일
```

### 13.3 Lock 파일

**skills.lock.yaml** (재현성):

```yaml
generated_at: "2026-03-23T20:00:00Z"
entries:
  repo-review:
    source_resolved:
      type: git
      url: https://github.com/acme/agent-assets
      commit: 8b4d9f1
      subpath: skills/repo-review
    integrity:
      sha256: "..."
    materialized_path: ".cross-harness/vendor/skills/repo-review@8b4d9f1"
```

### 13.4 Generated Profile

내용 hash로 식별되는 agent별 주입 설정:

```text
generated/claude/profiles/claude_f83d12/
├── prompt-prelude.md    # Skill prompt fragment 결합
├── mcp.json             # MCP 서버 설정
└── settings.json        # CLI 오버라이드 설정
```

### 13.5 Runtime Lease

dispatch가 profile을 사용 중일 때 prune을 방지하는 lease:

```jsonc
// .cross-harness/runtime/leases.json
{
  "leases": [
    {
      "dispatch_id": "dsp_001",
      "agent": "claude",
      "profile_id": "claude_f83d12",
      "acquired_at": "2026-03-23T20:10:00Z"
    }
  ]
}
```

### 13.6 CLI 명령

```bash
# Skill 관리
cross-harness skill add <id> --git <url> --ref <ref> --path <subdir> --target claude,codex
cross-harness skill add <id> --local <path> --target gemini
cross-harness skill enable <id>
cross-harness skill disable <id>
cross-harness skill remove <id>
cross-harness skill list

# MCP 관리
cross-harness mcp add <id> --command npx --args '["-y","@mcp/server-github"]' --target claude,codex
cross-harness mcp enable <id>
cross-harness mcp disable <id>
cross-harness mcp remove <id>
cross-harness mcp list

# 동기화
cross-harness sync                 # registry → lock → vendor → generated
cross-harness sync --prune         # + orphan 제거 (lease-aware)
cross-harness plan-sync            # dry-run: 변경 계획만 표시
cross-harness doctor skills        # skill 무결성 검사
cross-harness doctor mcps          # MCP healthcheck
cross-harness gc                   # cache/staging 정리
```

### 13.7 Bundle 선택 알고리즘

```python
def resolve_bundles_for_dispatch(agent, task_type):
    """dispatch 시 활성화할 bundle 목록을 결정한다."""
    result = []
    result += policy.defaults                         # [base]
    result += policy.by_agent.get(agent, [])          # [review] (codex)
    result += policy.by_task_type.get(task_type, [])  # [review] (review)
    return stable_dedupe(result)                      # [base, review]
```

### 13.8 Profile 생성 알고리즘

```python
def build_profile(agent, desired_skills, desired_mcps):
    """agent별 generated profile을 생성한다."""
    payload = {
        "agent": agent,
        "skills": serialize_ids_and_versions(desired_skills),
        "mcps": serialize_ids_and_versions(desired_mcps),
    }
    profile_hash = sha256(json.dumps(payload, sort_keys=True))
    profile_id = f"{agent}_{profile_hash[:8]}"

    profile_dir = generated_dir / agent / "profiles" / profile_id
    staging = mktemp_dir()

    # prompt-prelude.md: skill prompt fragments 결합
    render_prompt_prelude(agent, desired_skills, staging)
    # mcp.json: MCP 서버 설정
    render_mcp_config(agent, desired_mcps, staging)
    # settings.json: CLI 오버라이드
    render_agent_settings(agent, staging)

    validate_generated_profile(agent, staging)
    atomic_replace_dir(profile_dir, staging)

    return profile_id, profile_dir
```

### 13.9 Dispatch 시 Profile Activation

```python
def activate_profile_for_dispatch(dispatch):
    """dispatch 시 generated profile을 활성화하고 lease를 획득한다."""
    bundles = resolve_bundles_for_dispatch(dispatch.agent, dispatch.task_type)
    desired_skills = resolve_skills(bundles, dispatch.agent)
    desired_mcps = resolve_mcps(bundles, dispatch.agent)

    profile_id, profile_dir = ensure_profile_exists(dispatch.agent, desired_skills, desired_mcps)

    # lease 획득 (prune 보호)
    acquire_lease(dispatch.dispatch_id, dispatch.agent, profile_id)

    return profile_id, profile_dir
```

Adapter의 커맨드 구성은 §4.1의 `build_full_command()` → `adapter.build_command()`를 사용한다. CLI별 인자 구조가 다르므로 각 adapter가 직접 커맨드를 조립한다 (§4.2~4.4 참조).

### 13.10 Sync 알고리즘

```python
def sync(prune=False):
    acquire_management_lock(".cross-harness/locks/registry.lock")
    try:
        validate_manifests()
        plan = plan_sync()

        # 1. vendor materialization (git clone/fetch, local copy)
        materialized_skills = [materialize_skill(s) for s in plan.skills_to_install]
        materialized_mcps = [materialize_mcp(m) for m in plan.mcps_to_install]

        # 2. generated profile 생성 (content hash 기반, atomic swap)
        desired = resolve_desired_state()
        for agent, entry in desired.items():
            build_profile(agent, entry.skills, entry.mcps)

        # 3. lock 파일 갱신
        write_skill_lock(materialized_skills)
        write_mcp_lock(materialized_mcps)

        # 4. prune (요청 시, lease-aware)
        if prune:
            prune_orphans()
    finally:
        release_management_lock()

def prune_orphans():
    """active lease가 없는 vendor/profile만 삭제한다."""
    active_leases = load_leases()
    referenced_profiles = {l["profile_id"] for l in active_leases}

    for profile in all_generated_profiles():
        if profile.id not in referenced_profiles:
            safe_delete(profile.path)
```

### 13.11 Adapter Profile 주입 (CLI별)

Claude만 CLI 인자로 profile을 주입. Codex/Gemini는 per-dispatch sandbox + HOME override.

```python
class ClaudeAdapter(AgentAdapter):
    def inject_profile(self, profile_dir, dispatch_sandbox):
        # Claude는 CLI 인자로 주입 가능 → sandbox 불필요, env override 없음
        return {}  # HOME은 바꾸지 않음

    def build_command(self, task_type, prompt, profile_dir,
                      session_mode, session_id):
        cmd = ["claude", "-p", prompt]
        # profile 인자 (Claude만 CLI 인자 지원)
        mcp = profile_dir / "mcp.json"
        if mcp.exists():
            cmd += ["--mcp-config", str(mcp)]
        # session
        if session_mode == "resume" and session_id:
            cmd += ["--resume", session_id]
        # read-only
        if task_type in ("review", "research"):
            cmd += ["--permission-mode", "plan"]
        cmd += ["--output-format", "stream-json", "--verbose"]
        return cmd

class CodexAdapter(AgentAdapter):
    # inject_profile: §4.3 참조 — sandbox/.codex/ 생성 + HOME override
    # build_command: §4.3 참조 — exec/exec resume/exec review 분기
    ...

class GeminiAdapter(AgentAdapter):
    # inject_profile: §4.4 참조 — sandbox/.gemini/ 생성 + HOME override
    # build_command: §4.4 참조 — MVP에서 항상 new 세션
    ...
```

> **Profile 주입 방식 요약**:
> - **Claude**: CLI 인자 (`--mcp-config`, `--system-prompt`). sandbox 불필요.
> - **Codex/Gemini**: per-dispatch sandbox + `HOME` override. 기본 설정 위치를 직접 수정하지 않으므로 interactive pane과 격리 (§4.3, §4.4 참조).

### 13.12 불변식

1. 사람이 직접 수정하는 truth는 `registry/*.yaml`뿐이다
2. `generated/*`는 in-place 수정 금지, 새 profile version으로 생성
3. active lease가 있는 profile/vendor는 prune하지 않는다
4. resume 세션을 써도 generated profile 주입은 생략하지 않는다
5. MCP는 기본 deny, 명시적 allowlist로만 열어준다
6. sync 실패 시 lock/generated/vendor는 atomic rollback 가능해야 한다
7. agent adapter는 같은 desired input에 대해 같은 profile hash를 만들어야 한다

---

## 14. Auto Loop 구현

### 14.1 CLI 명령

```bash
cross-harness loop \
  --worker claude \
  --reviewer codex \
  --judge claude \
  --task-type impl \
  --task-id task_001 \
  --max-iterations 3 \
  --prompt "auth phase 1: login endpoint + JWT 구현"
```

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `--worker` | 작업 수행 에이전트 (pane 세션과 별도) | 필수 |
| `--reviewer` | 검증 에이전트 (항상 fresh 세션) | 필수 |
| `--judge` | 수렴 판정 CLI (항상 fresh new 세션, 판정만 수행) | `--worker`와 동일 |
| `--task-type` | 작업 유형 (impl/fix/refactor) | `impl` |
| `--task-id` | 연결할 task | 자동 생성 |
| `--max-iterations` | 최대 반복 횟수 (초과 시 사람에게 넘김) | 3 |
| `--prompt` | 초기 작업 프롬프트 | 필수 |

> **MVP 제한**: Worker=Claude, Reviewer=Codex 한 쌍만 먼저 지원. Judge는 Claude 또는 Codex 중 선택.

### 14.2 데이터 모델

**Loop 정의** (state.json 확장):

```jsonc
{
  // 기존 state.json에 추가
  "active_loop": {
    "loop_id": "loop_20260324_100000",
    "worker": "claude",
    "reviewer": "codex",
    "judge": "claude",
    "task_type": "impl",
    "task_id": "task_001",
    "max_iterations": 10,
    "current_iteration": 3,
    "status": "running",          // running | paused | stopped | aborted | max_reached | escalated
    "iterations": [
      {
        "iteration": 1,
        "worker_dispatch": "dsp_010",
        "review_dispatch": "dsp_011",
        "judge_dispatch": "dsp_012",
        "judge_verdict": "continue",
        "finding_count": 5
      },
      {
        "iteration": 2,
        "worker_dispatch": "dsp_013",
        "review_dispatch": "dsp_014",
        "judge_dispatch": "dsp_015",
        "judge_verdict": "continue",
        "finding_count": 2
      },
      {
        "iteration": 3,
        "worker_dispatch": "dsp_016",
        "review_dispatch": "dsp_017",
        "judge_dispatch": null,       // 아직 판정 전
        "judge_verdict": null,
        "finding_count": null
      }
    ]
  }
}
```

### 14.3 이벤트 타입

| Type | Source | 설명 |
|------|--------|------|
| `loop_started` | human | auto loop 시작 (loop_id, worker, reviewer, judge) |
| `loop_iteration` | system | iteration N 시작 |
| `loop_verdict` | agent (judge) | Judge가 `continue`/`stop`/`escalate` 판정 |
| `loop_stopped` | system | stop 판정 또는 early stop으로 루프 종료 |
| `loop_max_reached` | system | max_iterations 도달로 루프 종료 |
| `loop_paused` | human | 사용자가 루프 일시 중지 |
| `loop_aborted` | human | 사용자가 루프 중단 |

### 14.4 Loop Controller 알고리즘

```python
class LoopController:
    """Broker 내부 컴포넌트. Auto loop를 관리한다."""

    def run_loop(self, config: LoopConfig):
        loop_id = generate_loop_id()
        emit_event(type="loop_started", payload=config)
        finding_history = []     # 각 iteration의 findings 기록

        for iteration in range(1, config.max_iterations + 1):
            # 사용자 중단 확인
            if self.check_pause_or_abort(loop_id):
                break

            emit_event(type="loop_iteration", payload={"iteration": iteration})

            # ── Phase 1: Worker 실행 (pane과 별도 세션) ──
            if iteration == 1:
                worker_prompt = config.prompt
            else:
                worker_prompt = self.build_fix_prompt(
                    original_prompt=config.prompt,
                    review_output=prev_review_output,
                    judge_output=prev_judge_output,
                    iteration=iteration,
                )

            worker_result = dispatch_and_wait(
                agent=config.worker,
                task_type=config.task_type,
                prompt=worker_prompt,
                loop_id=loop_id,
                iteration=iteration,
            )

            if worker_result.exit_code != 0:
                emit_event(type="loop_aborted", reason="worker_failed")
                break

            # ── Phase 2: Reviewer 실행 (항상 fresh 세션) ──
            review_result = dispatch_and_wait(
                agent=config.reviewer,
                task_type="review",
                prompt=self.build_review_prompt(worker_result, iteration),
                loop_id=loop_id,
                iteration=iteration,
                force_new_session=True,
            )

            prev_review_output = review_result

            # ── Phase 2.5: 정량적 early stop 확인 (Judge 호출 전) ──
            findings = self.parse_findings(review_result.stdout)
            finding_history.append(findings)

            early_stop = self.check_early_stop(finding_history)
            if early_stop:
                emit_event(type="loop_stopped", payload={
                    "loop_id": loop_id,
                    "total_iterations": iteration,
                    "reason": early_stop.reason,
                })
                break

            # ── Phase 3: Judge 판정 (별도 new 세션, 판정만) ──
            # Judge는 구현/리뷰를 직접 하지 않음.
            # artifact + diff + finding summary만 보고 continue/stop/escalate 결정.
            judge_result = dispatch_and_wait(
                agent=config.judge,
                task_type="review",
                prompt=self.build_judge_prompt(
                    review_output=review_result,
                    finding_history=finding_history,
                    iteration=iteration,
                    max_iterations=config.max_iterations,
                ),
                loop_id=loop_id,
                iteration=iteration,
                force_new_session=True,       # 항상 fresh new 세션
            )

            verdict = self.parse_verdict(judge_result.stdout)
            prev_judge_output = judge_result

            emit_event(type="loop_verdict", payload={
                "iteration": iteration,
                "verdict": verdict.decision,
                "finding_count": findings.total,
                "high": findings.high,
                "medium": findings.medium,
                "reasoning": verdict.reasoning,
            })

            self.record_iteration(loop_id, iteration, worker_result,
                                  review_result, judge_result, verdict)

            if verdict.decision == "stop":
                emit_event(type="loop_stopped", payload={
                    "loop_id": loop_id,
                    "total_iterations": iteration,
                    "reason": verdict.reasoning,
                })
                break

            if verdict.decision == "escalate":
                emit_event(type="loop_paused", payload={
                    "loop_id": loop_id,
                    "reason": "judge_escalated",
                })
                break  # 사람에게 넘김

        else:
            # max_iterations 도달 → 사람에게 넘김
            emit_event(type="loop_max_reached", payload={
                "loop_id": loop_id,
                "max_iterations": config.max_iterations,
            })

    def check_early_stop(self, finding_history: list) -> EarlyStop | None:
        """
        Judge 호출 전에 정량적 규칙으로 조기 종료를 판단한다.
        이 규칙들은 Judge의 판정보다 우선한다 (비용 절약).
        """
        current = finding_history[-1]

        # Guard: 파싱 실패 시 early stop 판단 불가 → Judge에게 위임
        if not current.parsed:
            return None

        # Rule 1: high=0 and medium<=1 → 종료
        if current.high == 0 and current.medium <= 1:
            return EarlyStop(reason=f"high=0, medium={current.medium}")

        # Rule 2: 같은 finding이 2회 연속 반복 → 종료 (개선 정체)
        if len(finding_history) >= 2:
            prev = finding_history[-2]
            if self.same_findings(prev, current):
                return EarlyStop(reason="same_findings_repeated")

        # Rule 3: finding 수/심각도가 2회 연속 변화 없음 → 종료 (정체)
        if len(finding_history) >= 3:
            prev1 = finding_history[-2]
            prev2 = finding_history[-3]
            if (current.high == prev1.high == prev2.high
                    and current.medium == prev1.medium == prev2.medium
                    and current.total == prev1.total == prev2.total):
                return EarlyStop(reason="no_progress_2_consecutive")

        return None

    @staticmethod
    def same_findings(a, b) -> bool:
        """두 iteration의 finding이 실질적으로 동일한지 비교."""
        return (a.high == b.high and a.medium == b.medium
                and a.finding_ids == b.finding_ids)

    def parse_findings(self, review_stdout: str) -> "Findings":
        """
        Reviewer 출력에서 finding 목록을 구조화한다.

        Reviewer 프롬프트에서 구조화된 JSON 출력을 강제한다 (§14.10 참조).
        Reviewer가 자유 텍스트로 답하면 파싱 실패 → finding_ids 비어있음 →
        반복 감지 불가 → Judge에게 위임 (graceful degradation).
        """
        try:
            data = json.loads(review_stdout.strip().splitlines()[-1])
            findings = data.get("findings", [])
            return Findings(
                high=sum(1 for f in findings if f["severity"] == "high"),
                medium=sum(1 for f in findings if f["severity"] == "medium"),
                low=sum(1 for f in findings if f["severity"] == "low"),
                total=len(findings),
                finding_ids=sorted(f["id"] for f in findings),
                parsed=True,
            )
        except (json.JSONDecodeError, KeyError, IndexError):
            # 구조화 파싱 실패 → early stop 제외, Judge에게 판정 위임
            return Findings(high=0, medium=0, low=0, total=0,
                            finding_ids=[], parsed=False)


@dataclass
class Findings:
    high: int
    medium: int
    low: int
    total: int
    finding_ids: list[str]    # finding 식별자 (반복 감지용, 정규화된 짧은 ID)
    parsed: bool              # True: 구조화 파싱 성공, False: 파싱 실패 → early stop 제외

@dataclass
class EarlyStop:
    reason: str
```

### 14.5 Judge 프롬프트 템플릿

```markdown
## Task: Auto Loop Convergence Judgment

### Context
- Loop: {loop_id}, Iteration: {iteration}/{max_iterations}
- Worker: {worker_agent}, Reviewer: {reviewer_agent}

### Current Review Output
{review_output}

### Finding History
- Iteration 1: {finding_count_1} findings
- Iteration 2: {finding_count_2} findings
- Iteration {N}: {finding_count_N} findings

### Your Assignment
당신은 구현/리뷰를 직접 수행하지 않습니다.
위 artifact, diff, finding summary만 보고 다음 중 하나를 판정하세요:

1. **continue** — 의미 있는 finding이 남아있고, 다음 iteration에서 개선 가능
2. **stop** — finding이 충분히 수렴하여 루프를 종료해도 됨
3. **escalate** — 자동 해결이 어려운 문제 발견, 사람에게 넘김

판정 기준:
- severity=high가 0이고 medium<=1이면 stop
- 같은 finding이 이전 iteration과 동일하게 반복되면 stop (개선 정체)
- finding 수가 줄어들고 있고 high가 남아있으면 continue
- 아키텍처 수준 변경이 필요하거나 자동 수정이 위험하면 escalate

### Output Format
반드시 아래 JSON 형식으로만 답하세요:
{"decision": "continue" | "stop" | "escalate", "finding_count": N, "high": N, "medium": N, "reasoning": "이유"}
```

### 14.6 dispatch_and_wait 통합

기존 Dispatch Engine을 확장하여 loop context를 지원한다.

```python
def dispatch_and_wait(agent, task_type, prompt, loop_id, iteration,
                      force_new_session=False):
    """동기적으로 dispatch 실행 후 결과를 반환한다."""
    dispatch_id = generate_dispatch_id()

    # 세션 모드 결정
    if force_new_session:
        session_mode = "new"
        session_id = None
    else:
        session_mode, session_id = resolve_session(agent, task_type)

    # 기존 dispatch 흐름 (§6) 그대로 실행
    result = execute_dispatch(
        agent=agent,
        task_type=task_type,
        prompt=prompt,
        dispatch_id=dispatch_id,
        session_mode=session_mode,
        session_id=session_id,
    )

    # 이벤트 payload에 loop context 추가
    result.event_payload["loop_id"] = loop_id
    result.event_payload["loop_iteration"] = iteration

    return result
```

### 14.7 Console에서의 Loop 제어

```
Console 표시 예시:
  🔄 Auto Loop: loop_20260324_100000
     Worker: Claude | Reviewer: Codex | Judge: Claude
     Iteration: 3/10 | Status: running
     Finding trend: 5 → 2 → ?

  [p] Pause loop    [a] Abort loop    [s] Skip to next iteration
```

사용자가 `p` (pause)를 누르면:
1. 현재 진행 중인 dispatch는 완료까지 실행
2. 완료 후 다음 iteration을 시작하지 않음
3. `loop_paused` 이벤트 기록
4. Console에서 `r` (resume)로 재개 가능

### 14.8 이벤트 스키마 확장

기존 이벤트 payload에 optional `loop_id` + `loop_iteration` 필드 추가:

```jsonc
{
  // 기존 필드...
  "payload": {
    // 기존 필드...
    "loop_id": "loop_20260324_100000",      // auto loop 소속 시에만 존재
    "loop_iteration": 3                      // auto loop iteration 번호
  }
}
```

### 14.10 Reviewer 출력 규약 (finding_id 추출용)

Auto loop의 반복 감지(`same_findings()`)가 동작하려면, Reviewer 출력이 구조화되어야 한다.

**Reviewer 프롬프트에 추가되는 출력 요구**:

```markdown
### Output Format (auto loop mode)
리뷰 본문 뒤에 반드시 아래 JSON을 마지막 줄로 출력하세요:
{"findings": [
  {"id": "missing-input-validation", "severity": "high", "summary": "..."},
  {"id": "unused-import", "severity": "low", "summary": "..."}
]}

finding.id 규칙:
- kebab-case, 영문, 짧고 안정적인 식별자
- 같은 문제는 iteration이 바뀌어도 같은 id를 사용
- 예: "missing-input-validation", "session-expiry-edge-case"
```

**파싱 실패 시 graceful degradation**: Reviewer가 구조화 JSON을 출력하지 않으면 `finding_ids`가 비어있게 되고, `same_findings()` 비교가 수치만으로 이루어진다. 정확한 반복 감지는 불가능하지만 수치 기반 정체 감지는 동작한다.

### 14.11 불변식

1. Worker/Reviewer/Judge 모두 interactive pane 세션과 분리된 별도 세션으로 실행
2. Judge는 판정만 수행 — 구현/리뷰를 직접 하지 않음, artifact + finding summary만 입력
3. Judge dispatch는 항상 `force_new_session=True` (fresh 판정, 문맥 오염 방지)
4. 정량적 early stop이 Judge 호출보다 우선 (비용 절약)
5. Loop 내 모든 dispatch는 `loop_id`로 귀속 추적 가능
6. max_iterations 도달 시 무조건 루프 종료 → 사람에게 넘김 (무한 핑퐁 방지)
7. 사용자는 Console에서 언제든 pause/abort 가능 (human oversight 유지)
8. Loop 내 dispatch도 기존 dispatch와 동일한 lock/dirty-tree/commit 규칙을 따른다
9. 같은 finding 2회 반복 또는 meaningful diff 없이 2회 연속이면 강제 종료 (정체 감지)
