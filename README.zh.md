# Cross Harness

[English](README.md) | [中文](README.zh.md) | [한국어](README.ko.md)

> 面向 AI CLI 的半自动多模型协作系统，由人类作为中间闸门。

![License](https://img.shields.io/badge/license-MIT-blue.svg)

## 当前状态

本仓库目前以设计文档为主。

- 实现尚未完成。
- 当前事实来源是 [`docs/SRS.md`](docs/SRS.md)、[`docs/HLD.md`](docs/HLD.md) 和 [`docs/LLD.md`](docs/LLD.md)。
- README 描述的是目标系统和当前设计方向，不代表已经发布的可用产品。

## Cross Harness 是什么

Cross Harness 用来协调 Claude、Codex、Gemini 之类的多个 AI CLI，让它们围绕同一个软件项目协作，但不允许它们彼此直接对话。

系统采用 hub-and-spoke 结构：

- 由单一 Broker 记录事件和状态
- Human Control Console 负责所有阶段切换
- 默认在同一个项目目录中顺序工作
- review / research 结果保存为 artifact
- 代码变更保存为 commit

目标是在保留多模型协作优势的同时，避免静默偏航、无限来回循环，以及难以审计的自动化行为。

## 为什么需要它

在一个项目里同时使用多个 AI CLI，通常意味着手动复制粘贴、临时路由，以及很差的可追踪性。完全自动化看起来很强，但实际会带来问题：

- agent 可能在错误方向上持续推进
- 模型之间的输出冲突很难自动解决
- token 与时间成本容易失控
- 调试与复现困难

Cross Harness 的核心原则很简单：保留人类作为闸门，并让每一步都可见。

## 核心设计

### 1. Human-in-the-loop 编排

默认流程是：

1. 一个 agent 完成工作
2. Broker 记录结果
3. Human Control Console 询问下一步怎么做
4. 在用户决定后再启动下一个 agent

### 2. 默认共享 worktree

常规顺序流程使用同一个项目目录：

- 实现
- 评审
- 修复
- 批准

这样 reviewer 可以立刻看到最新 commit，worker 也可以直接消费 reviewer artifact。只有极少数并行改代码的情况才会启用临时 git worktree。

### 3. interactive pane 与 subprocess 共存

目标 UI 是一个 4-pane 的 `tmux` 会话：

- `claude`
- `codex`
- `gemini`
- Human Control Console

这些 pane 一直可供人工接管，但自动流程通过 Broker 管理的非交互 subprocess 运行，从而避免污染操作者当前的 pane 会话。

### 4. 以 artifact 为中心的记忆策略

会话记忆有价值，但它不是事实来源。

Cross Harness 认为下列内容才是 canonical：

- commits
- review artifacts
- research artifacts
- human notes
- event logs

对于支持稳定 resume 的 CLI，Broker 可以恢复会话，但每次 dispatch 仍会重新注入显式上下文。

### 5. 带硬性停止规则的 auto loop

设计还支持可控的自动迭代，例如：

- Worker: Claude
- Reviewer: Codex
- Judge: Claude 或 Codex

Judge 不负责编码，也不负责 review。它只基于 artifact、diff 和 finding summary 决定 `continue`、`stop` 或 `escalate`。

为防止无限循环，设计中使用了明确的停止条件，例如：

- `high=0 and medium<=1`
- finding 重复
- 连续迭代没有进展
- 最大迭代次数上限

## 架构概览

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

关键约束：

- 模型之间禁止直接对话
- 默认共享同一项目目录
- `events.jsonl` 与 `state.json` 只有 Broker 可以写
- 允许人工接管，但必须可追踪
- Broker 执行期间用 repo lock 阻止手动 commit

## 仓库结构

当前仓库内容：

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

文档职责：

- [`docs/SRS.md`](docs/SRS.md): 需求与产品行为
- [`docs/HLD.md`](docs/HLD.md): 架构、组件、ADR
- [`docs/LLD.md`](docs/LLD.md): schema、算法、命令约定
- [`docs/DESIGN.md`](docs/DESIGN.md): 设计演进归档
- [`docs/corss-harness-skll-mcp-strategy.md`](docs/corss-harness-skll-mcp-strategy.md): Skill/MCP 详细策略

## 计划中的能力

当前设计覆盖的主要范围：

- 基于 Broker 的单写者事件模型
- 通过 TUI Console 进行人工批准与路由
- interactive pane 与 subprocess 并行存在
- 可追踪的人工 takeover 路径
- 按 CLI 区分的 session memory 策略
- 通过 registry 管理 Skill/MCP 并生成 agent profile
- 由 Judge 控制收敛的 auto-loop

## 推荐阅读顺序

如果你第一次接触这个项目：

1. 先读 [`docs/SRS.md`](docs/SRS.md)
2. 再读 [`docs/HLD.md`](docs/HLD.md)
3. 最后读 [`docs/LLD.md`](docs/LLD.md)

如果你只关心 Skill/MCP，直接看 [`docs/corss-harness-skll-mcp-strategy.md`](docs/corss-harness-skll-mcp-strategy.md)。

## 当前范围与注意事项

这个仓库目前还不应被理解为已经完成的生产级 CLI 实现。

特别是：

- 旧草稿里出现过的安装命令并未在本仓库中提供
- `tmux` 编排流程目前是设计而非完整实现
- README 反映的是经过多轮审查后的当前设计方向

## License

MIT
