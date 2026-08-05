# 进阶 Lab 项目需求：AI4Coding AgentOS 实验工作台

## 1. 项目定位

原来的“知识体导航器”适合课堂展示和带做，应继续保留。它的优点是范围小、节奏稳，适合在 3 小时实践课中快速走完 Spec / Checklist / OpenCode / Gate 闭环。

本文件设计的是**课后挑战项目**，不是替换课堂 Lab。它的复杂度更高，用来让学生在课后验证：当项目变成多文件、多视图、多状态、多证据时，PE / CE / HE 为什么会从“技巧”变成“必要工程”。

课后挑战项目命名为：

**AI4Coding AgentOS 实验工作台**

它是一个本地运行的静态 Web 应用，用来管理 AI4Coding 课程中的概念、Lab、阶段合同、Gate 证据和 AgentOS 分层映射。项目仍然不接后端、不接真实模型 API，但通过多文件、多视图、本地状态、证据记录和权限边界，让学生必须分阶段使用 PE / CE / HE 才能稳定完成。

## 2. 用户与场景

- 学生：查看 PE / CE / HE / MCP / Skill / Hook / Gate 等知识点，按 Lab 0-12 完成作业，记录每阶段证据。
- 教师 / 助教：检查学生是否写清 Spec、Checklist、context-pack、Gate 证据和日志。
- Agent：在 OpenCode 中根据阶段 Spec、上下文包和权限边界，分阶段实现功能。

## 3. 核心功能

### 3.1 概念图谱

- 展示 AgentOS 五层：Human、Client、Agent Program、Runtime、Infrastructure。
- 展示关键概念：Spec、Checklist、Gate、OpenCode、PE、CE、HE、MCP、Skill、Hook、LambdAgentPaaS、K8s / CI。
- 支持按关键词、层次、Lab 编号过滤概念。
- 点击概念后显示定义、对应 Lab、验收点和相关概念。

### 3.2 Lab 看板

- 展示 Lab 0-12，每个 Lab 有状态：`todo`、`doing`、`blocked`、`pass`。
- 每个 Lab 显示应交文件、文件基本内容、关联知识点和通过标志。
- 支持切换状态，并把状态保存到 `localStorage`。
- 支持按状态过滤 Lab。

### 3.3 阶段合同面板

- 每个开发阶段都有一个 Stage Contract：阶段目标、输入文件、禁止事项、Checklist、退出条件。
- 支持选择阶段：项目初始化、全局 Spec、全局 Checklist、上下文包、MVP、Gate 放行、日志摘要、选做扩展。
- 选择阶段后，页面展示本阶段建议给 OpenCode 的 Prompt。

### 3.4 Gate 证据记录

- 每个 Lab 至少可以添加一条证据记录：证据类型、检查命令或观察方式、结果、人工决定。
- 没有证据时，Lab 不能直接标记为 `pass`，只能是 `todo`、`doing` 或 `blocked`。
- 证据保存在 `localStorage`，刷新页面后仍可查看。
- 支持导出证据 JSON，便于提交或粘贴到 `AGENT_LOG.md`。

### 3.5 权限与风险面板

- 展示 OpenCode 课堂默认权限：read allow、edit ask、bash ask/allowlist、webfetch deny、secret deny。
- 展示常见高风险动作：读 `.env`、删除文件、联网、部署、强推、安装未知依赖。
- 每个风险动作都要显示建议策略：allow、ask、deny。

## 4. 文件结构建议

```text
ai4coding-agentos-lab/
  index.html
  assets/
    styles.css
    app.js
  data/
    concepts.js
    labs.js
    stages.js
    policies.js
  SPEC.md
  CHECKLIST.md
  context-pack.md
  gate-checklist.md
  AGENT_LOG.md
  context-snapshot.md
  prompts/
    stage-template.md
  skills/
    lab-stage-check/
      SKILL.md
  hooks/
    pre-commit.sample
  agentpack-draft/
    manifest.yml
    agents/
      gate-checker.yml
```

## 5. 为什么它能验证 PE / CE / HE

### PE 的意义

这个项目包含概念图谱、Lab 看板、阶段合同、证据记录、权限面板。若只说“帮我做一个实验工作台”，Agent 很容易一次性混改数据结构、视图和状态逻辑。学生必须把任务切成阶段 Prompt，例如：

- 本阶段只做 Lab 看板，不做证据记录。
- 本阶段只增加 Gate 放行规则，不改概念图谱。
- 本阶段只把状态保存到 localStorage，不做导出。

### CE 的意义

不同阶段需要不同上下文。实现 Lab 看板时，主要需要 `data/labs.js`、`assets/app.js`、`CHECKLIST.md`；实现权限面板时，主要需要 `data/policies.js` 和 `SPEC.md`；实现 Gate 证据时，需要 `data/labs.js`、`assets/app.js`、`gate-checklist.md`。如果把全部 Lecture、全部历史聊天和所有文件都塞给 Agent，很容易出现上下文腐烂、重复实现和旧决策污染。

### HE 的意义

项目涉及多文件写入、状态持久化、证据导出和提交前检查，因此必须设置工具边界：

- 允许读项目文件、运行 `node --check`、查看 `git status`。
- 编辑文件必须 ask。
- 删除文件、读取 `.env`、联网部署、强推必须 deny。
- Gate 未过不能进入下一功能阶段。

## 6. Lab 0-12 对应关系

| Lab | 新项目中的任务 | 主要验证点 |
| --- | --- | --- |
| 0 | 初始化 OpenCode、权限、AGENTS.md、项目目录 | HE：工具边界和项目地图 |
| 1 | 写全局 SPEC：定义实验工作台的用户、模块、非目标 | Spec：复杂需求边界 |
| 2 | 写全局 CHECKLIST：功能、状态、证据、安全、体验 | Gate：可观察验收 |
| 3 | 写 context-pack：为“Lab 看板 MVP”选择上下文 | CE：选择与隔离上下文 |
| 4 | 写 stage-template：阶段 Prompt 模板 | PE：单阶段委托 |
| 5 | 生成 MVP：概念图谱 + Lab 看板静态展示 | Stage：多数据源 MVP |
| 6 | 增加状态与 Gate 证据：localStorage + pass 限制 | PE / CE / Gate：功能切片 |
| 7 | 写 gate-checklist 并检查失败项 | Gate / Evidence：证据驱动退出 |
| 8 | 写 AGENT_LOG 和 snapshot | CE / Memory：阶段交接 |
| 9 | 手动模拟或接入 Browser MCP 检查状态持久化 | MCP：外部观察能力 |
| 10 | 写 lab-stage-check Skill | Skill：复用检查套路 |
| 11 | 写 pre-commit Hook：密钥、Gate 文件、数据语法检查 | Hook / HE：确定性防线 |
| 12 | 设计 GateChecker AgentPack | LambdAgentPaaS：runtime 与 trace |

## 7. 最小可完成范围

三小时实践中，学生最低完成：

1. 概念图谱静态展示。
2. Lab 看板静态展示。
3. Lab 状态切换并保存到 `localStorage`。
4. 至少一条 Gate 证据记录。
5. 没有证据不能标记 `pass`。
6. 完成 `SPEC.md`、`CHECKLIST.md`、`context-pack.md`、`gate-checklist.md`、`AGENT_LOG.md`。

## 8. 选做增强

- 导出 / 导入证据 JSON。
- 按 AgentOS 层过滤概念。
- Lab 与概念的双向高亮。
- 权限风险面板。
- Browser MCP 检查脚本。
- `lab-stage-check` Skill。
- `pre-commit.sample` Hook。
- `GateChecker` AgentPack 草案。
