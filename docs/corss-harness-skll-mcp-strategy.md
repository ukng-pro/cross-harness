# Cross Harness — Skill / MCP Strategy

> Cross Harness에서 Skill과 MCP를 선언형으로 관리하기 위한 전략 문서
> 목적: 추가/비활성화/제거/동기화/활성화/정리 전 과정을 재현 가능하게 설계

**버전**: 1.0.0  
**작성일**: 2026-03-23  
**관련 문서**: [SRS.md](./SRS.md) · [HLD.md](./HLD.md) · [LLD.md](./LLD.md)

---

## 목차

1. [문서 목적](#1-문서-목적)
2. [핵심 설계 결정](#2-핵심-설계-결정)
3. [디렉터리 구조](#3-디렉터리-구조)
4. [데이터 모델](#4-데이터-모델)
5. [CLI별 적용 전략](#5-cli별-적용-전략)
6. [명령 계약](#6-명령-계약)
7. [핵심 알고리즘](#7-핵심-알고리즘)
8. [동시성 및 복구 전략](#8-동시성-및-복구-전략)
9. [보안 및 정책](#9-보안-및-정책)
10. [운영 예시](#10-운영-예시)
11. [불변식](#11-불변식)

---

## 1. 문서 목적

이 문서는 Cross Harness에서 다음 두 대상을 어떻게 관리할지 정의한다.

- **Skill**: 에이전트에게 특정 작업 방식을 주입하는 재사용 가능한 지식 패키지
- **MCP**: 에이전트가 외부 도구/데이터 소스와 통신하기 위한 Model Context Protocol 서버 설정

여기서 중요한 점은:

- Skill/MCP의 **source of truth**는 개별 CLI 폴더가 아니다
- source of truth는 **Cross Harness registry manifest**다
- Claude / Codex / Gemini는 이 source of truth를 각자 이해 가능한 형식으로 **generated config**를 받아 쓴다

즉, 이 전략은 다음 질문에 답한다.

1. Skill을 어떻게 추가하는가
2. MCP를 어떻게 추가하는가
3. 제거/비활성화는 어떻게 하는가
4. CLI별 설정 파일은 누가 언제 생성하는가
5. 실행 중인 dispatch를 깨지 않으면서 prune은 어떻게 하는가

---

## 2. 핵심 설계 결정

### 2.1 Registry-Driven

사람은 Claude/Codex/Gemini 전용 폴더를 직접 수정하지 않는다.

- 사람이 수정하는 파일: `registry/*.yaml`
- Harness가 생성하는 파일: `generated/*`
- 실제 설치 캐시: `vendor/*`
- 재현성 보장: `lock/*.yaml`

### 2.2 Skill은 Harness 추상화다

Skill은 각 CLI의 native 개념과 1:1 대응하지 않는다.

- Claude: skill/plugin/prompt module 중 하나로 materialize
- Codex: native skill 개념을 가정하지 않고 prompt module로 materialize
- Gemini: native skill/extension을 우선, 없으면 prompt module fallback

즉, Skill은 **Cross Harness 내부의 공통 추상화**이고, 실제 투영 방식은 agent adapter가 결정한다.

### 2.3 MCP는 Least Privilege

모든 agent에 모든 MCP를 항상 열어두지 않는다.

- task type
- agent
- approval mode
- bundle policy

위 4가지에 따라 필요한 MCP만 allowlist로 주입한다.

### 2.4 Disable First, Prune Later

삭제는 2단계다.

1. registry에서 `enabled: false`
2. `sync --prune` 시 실제 generated/vendor 제거

이유:

- active session이 아직 참조 중일 수 있음
- active dispatch가 old profile을 lease 중일 수 있음
- 즉시 삭제보다 단계적 제거가 안전함

### 2.5 Atomic Generation

generated config는 in-place 수정하지 않는다.

- staging 디렉터리에 새 profile 생성
- health check / validation 통과 후 atomic swap
- active runtime lease가 없는 이전 profile만 prune

---

## 3. 디렉터리 구조

```text
.cross-harness/
├── registry/
│   ├── skills.yaml
│   ├── mcps.yaml
│   └── bundles.yaml
├── lock/
│   ├── skills.lock.yaml
│   ├── mcps.lock.yaml
│   └── bundles.lock.yaml
├── vendor/
│   ├── skills/
│   │   └── <skill-id>@<resolved-version>/
│   └── mcps/
│       └── <mcp-id>@<resolved-version>/
├── generated/
│   ├── claude/
│   │   └── profiles/<profile-hash>/
│   ├── codex/
│   │   └── profiles/<profile-hash>/
│   └── gemini/
│       └── profiles/<profile-hash>/
├── runtime/
│   ├── sessions.json
│   ├── leases.json
│   ├── active_profiles.json
│   └── sync-state.json
├── cache/
│   └── downloads/
├── logs/
│   └── sync.log
└── locks/
    └── registry.lock
```

### 3.1 역할 분리

| 경로 | 역할 |
|------|------|
| `registry/` | 사람이 선언하는 source of truth |
| `lock/` | resolve 결과를 고정하는 재현성 파일 |
| `vendor/` | 외부 artifact 캐시 |
| `generated/` | CLI별 실제 주입 설정 |
| `runtime/` | 현재 session/profile/lease 상태 |
| `locks/` | sync/prune 중 상호배제 |

---

## 4. 데이터 모델

### 4.1 `skills.yaml`

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
    compatibility:
      claude: native_or_prompt
      codex: prompt_only
      gemini: native_or_prompt
    materialization:
      preferred: auto           # auto | native | prompt
    checksum: null              # optional human-pinned integrity
```

### 4.2 Skill Package 규약

`vendor/skills/<skill>/` 아래의 최소 규약:

```text
skill-root/
├── SKILL.yaml
├── SKILL.md
├── prompts/
│   ├── shared.md
│   ├── claude.md
│   ├── codex.md
│   └── gemini.md
├── assets/
└── adapters/
    ├── claude/
    ├── codex/
    └── gemini/
```

`SKILL.yaml` 최소 필드:

```yaml
id: repo-review
version: 1.2.0
entrypoint: SKILL.md
provides:
  - review-checklist
  - risk-analysis
agent_overrides:
  claude:
    mode: native_or_prompt
  codex:
    mode: prompt_only
  gemini:
    mode: native_or_prompt
```

### 4.3 `mcps.yaml`

```yaml
mcps:
  - id: github
    enabled: true
    transport: stdio            # stdio | http
    launcher:
      command: npx
      args: ["-y", "@modelcontextprotocol/server-github"]
      env:
        GITHUB_TOKEN: ${env:GITHUB_TOKEN}
    bundles: [base, review]
    targets: [claude, codex]
    permissions:
      network: true
      read_paths: []
      write_paths: []
    healthcheck:
      type: process_start
      timeout_s: 10

  - id: docs
    enabled: true
    transport: stdio
    launcher:
      command: uvx
      args: ["internal-docs-mcp"]
      env: {}
    bundles: [research]
    targets: [gemini, codex]
    permissions:
      network: false
      read_paths: ["./docs"]
      write_paths: []
    healthcheck:
      type: process_start
      timeout_s: 5
```

### 4.4 `bundles.yaml`

Bundle은 dispatch 시 어떤 skill/MCP 세트를 활성화할지 결정하는 정책 단위다.

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

  by_mode:
    manual: []
    auto: []
```

### 4.5 `skills.lock.yaml`

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
    targets: [claude, codex, gemini]
```

### 4.6 `mcps.lock.yaml`

```yaml
generated_at: "2026-03-23T20:00:00Z"
entries:
  github:
    launcher_resolved:
      command: npx
      args: ["-y", "@modelcontextprotocol/server-github"]
    config_hash: "abc123"
    healthcheck:
      status: ok
      checked_at: "2026-03-23T20:00:02Z"
```

### 4.7 `runtime/leases.json`

Generated profile을 prune하기 전에 참조 여부를 확인하기 위한 lease 테이블.

```jsonc
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

### 4.8 `runtime/active_profiles.json`

```jsonc
{
  "claude": {
    "profile_id": "claude_f83d12",
    "session_id": "session-123",
    "session_mode": "resume"
  },
  "codex": {
    "profile_id": "codex_118ac9",
    "session_id": "session-456",
    "session_mode": "resume"
  },
  "gemini": {
    "profile_id": "gemini_91f0de",
    "session_id": "session-789",
    "session_mode": "resume"
  }
}
```

---

## 5. CLI별 적용 전략

### 5.1 Claude

Cross Harness adapter가 사용할 수 있는 경로:

- `--settings`
- `--mcp-config`
- `--plugin-dir`
- `--add-dir`
- `--system-prompt`

Skill 적용 전략:

1. native skill/plugin materialization 가능하면 우선 사용
2. 불가하면 prompt fragment로 compile

MCP 적용 전략:

- generated profile 아래 `mcp.json` 생성
- dispatch 실행 시 `--mcp-config <generated>` 주입

### 5.2 Codex

Codex는 native skill abstraction을 전제로 두지 않는다.

Skill 적용 전략:

- 항상 prompt module 또는 generated system prompt fragment로 materialize
- `argv_base`와 별도로 `prompt prelude`를 생성해 prepend

MCP 적용 전략:

- generated config/profile 또는 per-run override로 주입
- dispatch 시 `argv_base + config_overrides` 형태로 합성

### 5.3 Gemini

Gemini는 skill/extension/mcp 개념을 상대적으로 직접 지원한다.

Skill 적용 전략:

1. native skill/extension으로 materialize 가능하면 우선
2. fallback은 prompt module

MCP 적용 전략:

- generated MCP config
- allowed MCP server names allowlist 동시 생성

### 5.4 공통 규칙

모든 agent adapter는 동일한 공통 contract를 따른다.

- 입력: selected bundle set
- 출력: generated profile directory
- 부작용: 없음
- generated profile ID는 내용 hash 기반

---

## 6. 명령 계약

### 6.1 Skill 명령

```bash
cross-harness skill add <id> --git <url> --ref <ref> --path <subdir> --target claude,codex
cross-harness skill add <id> --local <path> --target gemini

cross-harness skill enable <id>
cross-harness skill disable <id>
cross-harness skill remove <id>

cross-harness skill list
cross-harness skill sync
```

### 6.2 MCP 명령

```bash
cross-harness mcp add <id> \
  --command npx \
  --args '["-y","@modelcontextprotocol/server-github"]' \
  --target claude,codex

cross-harness mcp enable <id>
cross-harness mcp disable <id>
cross-harness mcp remove <id>

cross-harness mcp list
cross-harness mcp sync
```

### 6.3 공통 명령

```bash
cross-harness sync
cross-harness sync --prune
cross-harness plan-sync
cross-harness doctor skills
cross-harness doctor mcps
cross-harness gc
```

### 6.4 사람 기준 권장 운영

1. 추가: `add`
2. 적용: `sync`
3. 비활성화: `disable`
4. 실제 제거: `sync --prune`

---

## 7. 핵심 알고리즘

### 7.1 Add Skill 알고리즘

입력:

- `id`
- `source`
- `targets`
- `bundles`

출력:

- `registry/skills.yaml` 갱신
- optional `sync` 트리거

```python
def add_skill(spec):
    acquire_registry_lock()
    manifest = load_yaml("registry/skills.yaml")

    assert_unique_id(manifest.skills, spec.id)
    validate_targets(spec.targets)
    validate_source(spec.source)

    normalized = normalize_skill_spec(spec)
    manifest.skills.append(normalized)

    atomic_write_yaml("registry/skills.yaml", manifest)
    release_registry_lock()

    return normalized.id
```

### 7.2 Disable Skill / MCP 알고리즘

삭제 대신 먼저 disable한다.

```python
def disable_entry(kind, entry_id):
    acquire_registry_lock()
    manifest = load_registry(kind)
    entry = find_entry(manifest, entry_id)
    entry.enabled = False
    atomic_write_registry(kind, manifest)
    release_registry_lock()
```

효과:

- 다음 `sync`부터 generated profile에 포함되지 않음
- 기존 active lease가 끝날 때까지 vendor cache는 유지 가능

### 7.3 Remove 알고리즘

`remove`는 registry에서 선언을 제거하지만, 실제 artifact 삭제는 prune 단계에서 수행한다.

```python
def remove_entry(kind, entry_id):
    acquire_registry_lock()
    manifest = load_registry(kind)
    manifest.entries = [e for e in manifest.entries if e.id != entry_id]
    atomic_write_registry(kind, manifest)
    release_registry_lock()
```

### 7.4 Sync Plan 계산 알고리즘

`sync`는 즉시 mutate하지 않고 먼저 plan을 계산한다.

```python
def plan_sync():
    desired = resolve_desired_state()
    current = load_lock_state()
    runtime = load_runtime_state()

    return diff_states(
        desired=desired,
        current=current,
        active_leases=runtime.leases,
    )
```

plan이 포함해야 하는 항목:

- download / clone 대상
- update 대상
- healthcheck 대상
- generated profile 생성 대상
- prune 후보
- active lease 때문에 보류된 prune 후보

### 7.5 Desired State Resolve 알고리즘

```python
def resolve_desired_state():
    skills = load_enabled_skills()
    mcps = load_enabled_mcps()
    bundles = load_bundles()

    desired = {}
    for agent in ["claude", "codex", "gemini"]:
        selected = resolve_bundles_for_agent(agent, bundles)
        desired[agent] = {
            "skills": dedupe(resolve_skills(selected, agent, skills)),
            "mcps": dedupe(resolve_mcps(selected, agent, mcps)),
        }
    return desired
```

#### Bundle 선택 순서

```python
def resolve_bundles_for_dispatch(agent, task_type, mode):
    result = []
    result += policy.defaults
    result += policy.by_agent.get(agent, [])
    result += policy.by_task_type.get(task_type, [])
    result += policy.by_mode.get(mode, [])
    return stable_dedupe(result)
```

정렬 규칙:

- 선언 순서 유지
- 동일 ID 중복 제거
- higher priority skill이 뒤에서 override 가능

### 7.6 Skill Materialization 알고리즘

```python
def materialize_skill(skill_entry):
    if skill_entry.source.type == "git":
        repo = clone_or_fetch(skill_entry.source.url)
        commit = resolve_ref(repo, skill_entry.source.ref)
        path = checkout_subpath(repo, commit, skill_entry.source.path)
    elif skill_entry.source.type == "local":
        path = resolve_local_path(skill_entry.source.path)
        commit = "local"
    else:
        raise UnsupportedSourceType()

    verify_skill_layout(path)
    sha = compute_sha256(path)

    vendor_path = vendor_dir / f"{skill_entry.id}@{commit}"
    if not vendor_path.exists():
        copytree_atomic(path, vendor_path)

    return {
        "id": skill_entry.id,
        "commit": commit,
        "sha256": sha,
        "vendor_path": str(vendor_path),
    }
```

### 7.7 MCP Resolve / Health Check 알고리즘

```python
def materialize_mcp(mcp_entry):
    launcher = normalize_launcher(mcp_entry.launcher)
    env = resolve_env_refs(launcher.env)

    health = run_healthcheck(
        command=launcher.command,
        args=launcher.args,
        env=env,
        timeout_s=mcp_entry.healthcheck.timeout_s,
    )

    if not health.ok:
        raise MCPHealthcheckFailed(mcp_entry.id)

    return {
        "id": mcp_entry.id,
        "launcher": launcher,
        "health": health,
    }
```

### 7.8 Generated Profile 생성 알고리즘

generated profile은 agent별 selected skills/MCP의 **내용 hash**로 식별한다.

```python
def build_profile(agent, desired_entry):
    payload = {
        "agent": agent,
        "skills": serialize_ids_and_versions(desired_entry.skills),
        "mcps": serialize_ids_and_versions(desired_entry.mcps),
    }
    profile_hash = sha256(json.dumps(payload, sort_keys=True))
    profile_id = f"{agent}_{profile_hash[:8]}"

    profile_dir = generated_dir / agent / "profiles" / profile_id
    staging = mktemp_dir()

    render_agent_profile(agent, desired_entry, staging)
    validate_generated_profile(agent, staging)

    atomic_replace_dir(profile_dir, staging)
    return profile_id, profile_dir
```

생성물 예시:

```text
generated/claude/profiles/claude_f83d12/
├── prompt-prelude.md
├── mcp.json
├── settings.json
└── plugins/
```

### 7.9 Dispatch Activation 알고리즘

dispatch 시점에는 manifest를 다시 읽지 않고 generated profile을 사용한다.

```python
def activate_profile_for_dispatch(dispatch):
    desired = resolve_for_dispatch(
        agent=dispatch.agent,
        task_type=dispatch.task_type,
        mode=dispatch.mode,
    )

    profile_id = ensure_profile_exists(dispatch.agent, desired)

    acquire_lease(
        dispatch_id=dispatch.dispatch_id,
        agent=dispatch.agent,
        profile_id=profile_id,
    )

    runtime.active_profiles[dispatch.agent] = {
        "profile_id": profile_id,
        "session_id": runtime.active_profiles[dispatch.agent].get("session_id"),
        "session_mode": "resume",
    }
    atomic_write_runtime()

    return profile_id
```

### 7.10 Resume 세션과 Skill/MCP 적용 규칙

기본 정책:

- 첫 dispatch: `new`
- 두 번째 이후: `resume`
- 항상 `resume + explicit generated context`

즉, resume 세션을 쓰더라도 generated profile을 생략하지 않는다.

```python
def build_agent_command(agent, profile, session_state):
    cmd = list(agent.argv_base)
    cmd += adapter.profile_args(profile)

    if session_state.exists:
        cmd += adapter.resume_args(session_state.session_id)
    else:
        cmd += adapter.new_session_args()

    return cmd
```

### 7.11 Sync 알고리즘

```python
def sync(prune=False):
    acquire_management_lock(".cross-harness/locks/registry.lock")
    try:
        validate_manifests()
        plan = plan_sync()

        materialized_skills = [materialize_skill(s) for s in plan.skills_to_install]
        materialized_mcps = [materialize_mcp(m) for m in plan.mcps_to_install]

        desired_state = resolve_desired_state()
        generated_profiles = {}
        for agent, desired_entry in desired_state.items():
            generated_profiles[agent] = build_profile(agent, desired_entry)

        write_skill_lock(materialized_skills, desired_state)
        write_mcp_lock(materialized_mcps, desired_state)
        write_bundle_lock(desired_state)
        update_sync_state(plan, generated_profiles)

        if prune:
            prune_orphans()
    finally:
        release_management_lock()
```

### 7.12 Prune 알고리즘

prune는 active lease를 절대 깨면 안 된다.

```python
def prune_orphans():
    referenced_vendor = compute_vendor_references_from_lock()
    referenced_profiles = compute_profile_references_from_runtime()

    for path in vendor_paths():
        if path not in referenced_vendor:
            safe_delete(path)

    for profile in generated_profiles():
        if profile.id not in referenced_profiles:
            safe_delete(profile.path)
```

### 7.13 Garbage Collection 알고리즘

`gc`는 prune보다 더 공격적이지만 여전히 lease-aware여야 한다.

```python
def gc():
    acquire_management_lock()
    leases = load_leases()
    remove_expired_download_cache()
    remove_broken_staging_dirs()
    remove_orphan_vendor_without_active_lease(leases)
    remove_orphan_profiles_without_active_lease(leases)
    release_management_lock()
```

### 7.14 Rollback 알고리즘

sync 실패 시 generated/lock/vendor를 partial state로 남기면 안 된다.

```python
def rollback_sync(snapshot):
    restore_lock_files(snapshot.lock_files)
    restore_generated_symlink(snapshot.generated_pointer)
    cleanup_temp_dirs(snapshot.temp_dirs)
```

rollback 전략:

- lock file은 temp에 쓰고 rename
- generated profile은 versioned dir 생성 후 pointer swap
- vendor는 content-addressed이므로 partially downloaded dir만 cleanup

---

## 8. 동시성 및 복구 전략

### 8.1 Management Lock

`sync`, `prune`, `gc`, `skill add`, `mcp add`는 동시에 실행되면 안 된다.

```text
.cross-harness/locks/registry.lock
```

lock 내용:

```json
{
  "pid": 12345,
  "command": "cross-harness sync --prune",
  "started_at": "2026-03-23T20:30:00Z"
}
```

### 8.2 Stale Management Lock

Broker lock과 같은 방식으로 stale lock 정리가 필요하다.

알고리즘:

1. lock 파일 존재 확인
2. pid 생존 여부 확인
3. dead면 stale로 간주
4. 자동 삭제 또는 `cross-harness unlock-registry --force`

### 8.3 Active Lease 보호

lease가 존재하면 아래 작업을 금지한다.

- active profile 디렉터리 삭제
- active vendor dependency 삭제
- session이 사용 중인 generated config overwrite

### 8.4 Manual Edit 금지

다음 경로는 generated artifact이므로 직접 수정 금지:

- `.cross-harness/generated/`
- `.cross-harness/vendor/`
- `.cross-harness/lock/`

사람이 수정하는 경로는 오직:

- `.cross-harness/registry/skills.yaml`
- `.cross-harness/registry/mcps.yaml`
- `.cross-harness/registry/bundles.yaml`

---

## 9. 보안 및 정책

### 9.1 Secret Injection

secret은 manifest에 평문 저장 금지.

허용:

```yaml
env:
  GITHUB_TOKEN: ${env:GITHUB_TOKEN}
```

금지:

```yaml
env:
  GITHUB_TOKEN: ghp_xxx_plaintext
```

### 9.2 MCP 권한 정책

모든 MCP는 다음 3축을 명시해야 한다.

- network 필요 여부
- read path
- write path

write path가 필요한 MCP는 기본 bundle에 넣지 않는다.

### 9.3 Skill 신뢰도 정책

`source.type=git` skill은 가능한 경우 pinned ref를 사용한다.

- 권장: tag + lock에서 commit 고정
- 금지: floating branch를 lock 없이 production에서 사용

### 9.4 Integrity 검증

가능한 경우 sha256 기록:

- local snapshot hash
- git commit tree hash
- archive checksum

---

## 10. 운영 예시

### 10.1 Skill 추가

```bash
cross-harness skill add repo-review \
  --git https://github.com/acme/agent-assets \
  --ref v1.2.0 \
  --path skills/repo-review \
  --target claude,codex,gemini

cross-harness sync
```

결과:

1. `registry/skills.yaml`에 선언 추가
2. git ref resolve
3. `vendor/skills/repo-review@<commit>/` 생성
4. `skills.lock.yaml` 갱신
5. `generated/<agent>/profiles/*` 재생성

### 10.2 MCP 추가

```bash
cross-harness mcp add github \
  --command npx \
  --args '["-y","@modelcontextprotocol/server-github"]' \
  --target claude,codex

cross-harness sync
```

결과:

1. `registry/mcps.yaml` 갱신
2. launcher healthcheck
3. `mcps.lock.yaml` 갱신
4. Claude/Codex generated profile 갱신

### 10.3 Disable 후 Prune

```bash
cross-harness skill disable repo-review
cross-harness sync
cross-harness sync --prune
```

결과:

- sync: generated profile에서 제거
- prune: active lease가 없으면 vendor/profile 제거

### 10.4 Dispatch 실행 시 Bundle 선택

예: `codex`, `review`, `auto`

1. defaults = `[base]`
2. by_agent.codex = `[review]`
3. by_task_type.review = `[review]`
4. by_mode.auto = `[]`
5. stable dedupe 결과 = `[base, review]`

결과:

- selected skills: `repo-review`
- selected mcps: `github`
- profile id 생성: `codex_118ac9`
- lease 획득 후 dispatch 실행

---

## 11. 불변식

다음은 구현이 항상 지켜야 하는 invariant다.

1. 사람이 직접 수정하는 truth는 `registry/*.yaml`뿐이다.
2. `lock/*.yaml`은 resolve 결과를 재현 가능하게 고정한다.
3. `generated/*`는 in-place 수정하지 않고 새 profile version으로 생성한다.
4. active lease가 있는 profile/vendor는 prune하지 않는다.
5. disable과 remove는 즉시 물리 삭제를 의미하지 않는다.
6. `source`는 CLI별 native 개념이 아니라 Cross Harness 추상화다.
7. MCP는 기본 deny, 명시적 allowlist로만 열어준다.
8. resume 세션을 써도 generated profile 주입은 생략하지 않는다.
9. sync 실패 시 lock/generated/vendor는 atomic rollback 가능해야 한다.
10. agent adapter는 같은 desired input에 대해 같은 generated profile hash를 만들어야 한다.

---

## 부록 A. 추천 구현 순서

1. `registry/skills.yaml`, `registry/mcps.yaml`, `registry/bundles.yaml` 파서 구현
2. `skills.lock.yaml`, `mcps.lock.yaml` writer 구현
3. vendor materializer 구현
4. generated profile renderer 구현
5. `cross-harness sync` 구현
6. `cross-harness skill add/disable/remove` 구현
7. `cross-harness mcp add/disable/remove` 구현
8. lease-aware prune 구현
9. dispatch 시 profile activation 연동
10. session resume 정책 연동

## 부록 B. 최소 MVP 범위

MVP에서는 다음만 먼저 구현해도 된다.

- source type: `git`, `local`
- MCP transport: `stdio`
- bundle policy: `defaults`, `by_agent`, `by_task_type`
- generated profile: prompt prelude + mcp config
- commands: `skill add`, `mcp add`, `sync`, `sync --prune`

Phase 2 이후:

- native skill materialization 고도화
- multi-profile cache optimization
- remote skill registry
- signed package verification
- lease-aware hot swap
