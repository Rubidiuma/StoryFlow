# AGENT_LOG.md — 智能体协作过程日志

> 按时间顺序记录每个 subagent 任务、使用的 Superpowers 技能、关键 prompt、输出片段、人工干预、学到的教训。

---

## 日志维护规则

- **何时更新：** 每完成一个 task（T01～T24），立即记录本项
- **记录内容：** 时间 + task ID + 技能 + prompt 关键词 + subagent 输出摘要 + 人工修改 + 教训
- **保留证据：** commit hash、测试红绿结果、关键代码片段
- **隐私处理：** 不记录真实 API Key，仅记录模板版本、请求长度、错误码

---

## 冷启动验证 (CS-01)

**日期：** 2026-08-07（精确起止时刻与总耗时未被可靠保留）
**Agent 类型：** general-purpose  
**任务：** 从 T02 或 T04 中选择 1～2 个任务推进，验证 SPEC / PLAN 清晰度  
**Worktree：** `.claude/worktrees/coldstart-validation`  
**Branch：** `coldstart/spec-plan-validation`  
**状态：** ✅ **完成 - SPEC 清晰度验证通过**

**Superpowers 技能：** 无（冷启动是初期验证，不用技能框架）

**关键指令：**
```
从 PLAN 的 T02 或 T04 中选择 1～2 个任务推进。
先写失败测试，确认失败，再实现最少代码使其通过。
遇到不确定处立即暂停提问，不要自行补充产品规则。
```

**实际执行：**

1. **选定任务：** T02（领域模型与状态机）
2. **执行方式：** 严格 TDD
   - 编写 29 个测试（13 个状态机 + 16 个模型验证）
   - 首次 RED 在测试收集阶段因 import/module 缺失中止，个别测试尚未运行；不能表述为 28 或 29 个测试分别失败
   - 实现最少代码：5 个枚举类 + 12 个 Pydantic 模型 + 状态转换表
   - 所有 29 个测试通过；精确测试耗时未被可靠保留

3. **停留需求证据：** 最终报告未列出阻塞性规约歧义；完整对话与暂停轨迹未被可靠保留，不能据此断言暂停或提问次数

**产出清单：**

✅ 修改的文件：
```
src/storyflow/domain/
├── __init__.py
├── enums.py (StoryStatus, ChoiceFrequency, Genre, StoryStructure, ChoiceType)
├── models.py (StoryConfig, CustomAction, ChoiceOption, ChoicePoint, StoryBible,
│              CharacterState, Story, StoryArc, StorySegment, Branch,
│              MemorySnapshot, GenerationEvent)
└── state_machine.py (转换表、非法转换拒绝)

tests/unit/
├── test_state_machine.py (13 个转换测试)
└── test_domain_models.py (16 个模型验证测试)
```

✅ RED 证据说明：首次运行在测试收集阶段因 `ModuleNotFoundError` 中止，个别测试尚未运行；原始完整输出未被可靠保留，因此不补写相似失败数或其他缺失输出。

✅ 绿色测试输出：
```
================================= 29 passed =================================

Category: State Transitions (13/13)
  - test_draft_to_planning_rejected
  - test_waiting_choice_to_planning_rejected
  - test_streaming_to_committing_allowed
  - [10 more]

Category: Domain Validation (16/16)
  - test_story_config_total_length_limit
  - test_choice_point_must_have_three_options
  - test_choice_point_options_must_be_unique
  - [13 more]
```

✅ SPEC / PLAN 问题列表：
- **清晰度评级：** 优秀 (9/10)
- **发现的缺陷数：** 0 个阻塞性缺陷
- **非阻塞注记数：** 2 个（都已记录到 SPEC_PROCESS.md）
  - PLAN.md worktree 路径不匹配（在本次 PR-01 过程文档对账中纠正）
  - 自定义行动解析策略延迟到服务层（有意设计，已确认理解）

**人工干预：** 

1. **文档对账（2026-08-07）**
   - 修改：`../storyflow-coldstart` → `.claude/worktrees/coldstart-validation`。
   - 原因：实际 worktree 路径与历史文档不符；此前“已修正”的记录不准确。
   - 同时更正证据谱系：隔离分支仍指向 `010c021`，而冷启动代码提交 `9bc5df8` 位于 main 谱系；不能称其由隔离分支提交。

2. **无代码修改需求**
   - SPEC.md：无修订（清晰度已验证）
   - Agent 的代码可直接移用于 T01～T03

**教训：**

1. **SPEC 清晰度的实证价值**
   - 最终报告未列出阻塞性歧义，支持 T02 规约可执行的结论
   - 完整对话与暂停轨迹未保留，不能据此证明不存在任何隐性假设
   - TDD 强制能够立即暴露规约问题（这里暴露 0 个）

2. **Task 颗粒度合理**
   - T02 预算为 60～75 分钟；实际总耗时未被可靠保留
   - 已保留完成产物与测试结果，但不以无法核验的时长评价任务颗粒度

3. **陌生 Agent 的评审价值**
   - 用 general-purpose（非 Claude Code）避免了共享隐性上下文
   - 冷启动强制了"规约本身要清楚，不靠口头补充"的原则
   - 这是单人项目中最接近"同侪评审"的内部机制

4. **Superpowers TDD 的威力**
   - 没有技能框架的强制，也能自发地做 TDD（先红后绿）
   - 说明课程对工程纪律的要求已内化到 Agent 行为

**信心指标：**
- ✅ SPEC 清晰度：9/10（高）
- ✅ PLAN 可执行性：8/10（高，有 2 处小路径不匹配）
- ✅ 可启动正式实现：是
- ✅ 建议下一步：立即启动 T01（项目骨架）

**Commit 记录（证据更正）：** 冷启动练习产出的代码为 `9bc5df8`，但它提交在 main 谱系；隔离分支 `coldstart/spec-plan-validation` 仍为 `010c021`。正式分支上的 T02 接纳提交为 `8bd1174`。这是 worktree/提交谱系偏差，已由正式接纳恢复过程可追溯性，并非产品缺陷。
**推荐下一步：** 启动 PR-01（T01～T03），Agent 可复用冷启动的 domain 代码

---

## 正式实现工作区

### Phase 1：Project Bootstrap & Domain (PR-01)

#### T01 - 项目骨架与质量门禁

**时间：** 2026-08-07（任务报告未保留精确时分）
**Agent 类型：** subagent
**分支：** `feature/bootstrap-domain`  
**Worktree：** `.worktrees/feature-bootstrap-domain`
**依赖：** CS-01 完成  

**技能/工作流：** `using-git-worktrees`、`subagent-driven-development`、`test-driven-development`、`requesting-code-review`、`verification-before-completion`；仅在初始 broken-import/环境设置诊断中使用 `systematic-debugging`。

**RED → GREEN：** 首个健康检查因 `ModuleNotFoundError: storyflow.main` 失败；实现最小 FastAPI 应用后目标测试 `1 passed`。最终 `make test` 为 30 passed，`make lint` 与 `make typecheck` 均通过。

**评审与修复：** 两轮独立评审修复质量门禁范围问题，并撤回越过 T01 范围的 T02 文件修改；最终无未解决发现。

**提交：** `471b4ee` / `ba878d9` / `5a7b02f`。

**控制器介入：** 使用精确 brief `.superpowers/sdd/PLAN/task-1-brief.md` 派发任务。subagent 遇到 Git index-lock sandbox 权限后，控制器仅对已产出的改动执行机械性暂存/提交；没有人类编写代码的声明。

**教训：** 质量门禁必须覆盖声明的完整范围，同时须守住已有任务文件的边界。

---

#### T02 - 领域模型与状态机

**时间：** 2026-08-07（任务报告未保留精确时分）
**Agent 类型：** subagent
**分支：** `feature/bootstrap-domain`（同 T01）  
**Worktree：** `.worktrees/feature-bootstrap-domain`
**依赖：** T01 完成  

**技能/工作流：** `using-git-worktrees`、`subagent-driven-development`、`test-driven-development`、`requesting-code-review`、`verification-before-completion`。

**RED → GREEN：** 在冷启动原型 29 个通过测试的基线之上，五组缺口测试分别暴露缺少纯 `transition`、6,000 字符聚合限制、`ScenePlan`、SPEC §8 关系字段、空白/规范化唯一性校验；最小实现后领域测试 41 passed，完整回归 42 passed，lint/typecheck 均通过。

**评审与修复：** 独立 SPEC/质量评审 Approved；没有记录需另行修复的发现。

**提交：** `9bc5df8`（冷启动领域原型，main 谱系）/ `8bd1174`（正式接纳）。

**控制器介入：** 使用精确 brief `.superpowers/sdd/PLAN/task-2-brief.md` 派发任务。subagent 遇到 Git index-lock sandbox 权限后，控制器仅对已产出的改动执行机械性暂存/提交；没有人类编写代码的声明。

**教训：** 冷启动原型必须经正式的、可追溯的契约缺口测试和独立评审后，才能作为任务完成接纳。

---

#### T03 - SQLite schema 与仓储

**时间：** 2026-08-07（任务报告未保留精确时分）
**Agent 类型：** subagent
**分支：** `feature/bootstrap-domain`  
**Worktree：** `.worktrees/feature-bootstrap-domain`
**依赖：** T02 完成  

**技能/工作流：** `using-git-worktrees`、`subagent-driven-development`、`test-driven-development`、`requesting-code-review`、`verification-before-completion`。

**RED → GREEN：** 三个 TDD 切片先后暴露缺失 `storyflow.db`、`create_branch`、路径/快照读取；修复后集成测试变绿。评审补充了关系外键、读连接关闭和非弃用 UTC 回归测试，最终 `make test` 为 52 passed、0 warning，lint/typecheck 均通过。

**评审与修复：** 两轮独立评审；第一轮修复三项持久化完整性问题，第二轮恢复 T02 的 naive-UTC 兼容语义，最终无未解决发现。

**提交：** `8250a44` / `d565c96` / `4797f91`。

**控制器介入：** 使用精确 brief `.superpowers/sdd/PLAN/task-3-brief.md` 派发任务。subagent 遇到 Git index-lock sandbox 权限后，控制器仅对已产出的改动执行机械性暂存/提交；没有人类编写代码的声明。

**教训：** 持久化层既要以关系约束保护一致性，也要用回归测试保护既有序列化语义。

---

## PR-01 对账指标（2026-08-07）

- CS-01、T01、T02、T03：已完成；T04 及后续任务仍未开始。
- 当前完整测试：67 passed，0 warning；T01～T03 与最终修复波次均保存了 RED/GREEN 证据。
- PR-01 最终评审提出的 Critical/Important/指定 Minor 已在单次整分支修复波次中处理；最终复审批准仍待控制器确认。
- PR-01 整分支最终复审：**待完成**，本日志不将其标记为已批准或已完成。

#### PR-01 最终评审修复波次

**日期：** 2026-08-07
**Agent 类型：** 单一 final-fix subagent
**范围：** 同 Story/路径持久化完整性、父节点环检测、StoryConfig 完整性与选择频率一致性、冷启动证据准确性、测试读连接关闭。

**TDD 证据：** 持久化初始 RED 为 7 failed / 10 passed，修复后 17 passed；同 Story 兄弟路径补充 RED 为 1 failed，修复后相关 3 passed。环检测的最终有效 RED 覆盖 Pydantic、自引用 SQL 与多节点环，修复后 3 passed。StoryConfig/Story 频率 RED 为 4 failed，修复后 4 passed。

**最终门禁：** 目标领域/仓储测试 51 passed；完整测试 67 passed；`make lint`、`make typecheck`、`git diff --check` 均通过且无 warning。

**证据文件：** `.superpowers/sdd/PLAN/final-fix-report.md`
**状态：** 修复实现与本地门禁完成；PR-01 最终复审批准待控制器处理。

---

### Phase 2：LLM & Bible (PR-02)

#### T04 - LLM 抽象与 fake LLM

**时间：** TBD  
**Agent 类型：** TBD  
**分支：** `feature/llm-bible`  
**依赖：** PR-01 完成  

**Superpowers 技能：**
- `test-driven-development`

**关键 Prompt：** [TBD]

**失败测试覆盖：**
- 按脚本返回 JSON、流式文本
- 模拟超时、非法 JSON
- 模拟流中断和 partial text
- 请求上下文记录

**预期完成：** [TBD]

**实际输出：** [待启动]

**Commit Hash：** —

**教训：** [待总结]

---

#### T05 - 故事创建与故事圣经

**时间：** TBD  
**Agent 类型：** TBD  
**分支：** `feature/llm-bible`  
**依赖：** T04 完成  

**Superpowers 技能：**
- `test-driven-development`
- `requesting-code-review`

**关键 Prompt：** [TBD]

**失败测试覆盖：**
- 未确认 Bible 不能生成正文
- 非法结构重试一次
- 两次失败不留半成品
- 输入校验

**预期完成：** [TBD]

**实际输出：** [待启动]

**Commit Hash：** —

**教训：** [待总结]

---

### Phase 3：Choice & Context (PR-03)

#### T06 - 选择点策略

**时间：** TBD  
**Agent 类型：** TBD  
**分支：** `feature/choice-context`  
**依赖：** PR-01 完成  

**Superpowers 技能：**
- `test-driven-development`

**预期完成：** [TBD]

**实际输出：** [待启动]

**Commit Hash：** —

**教训：** [待总结]

---

#### T07 - 上下文预算与分层记忆

**时间：** TBD  
**Agent 类型：** TBD  
**分支：** `feature/choice-context`  
**依赖：** T03 完成  

**Superpowers 技能：**
- `test-driven-development`

**预期完成：** [TBD]

**实际输出：** [待启动]

**Commit Hash：** —

**教训：** [待总结]

---

### Phase 4～8：生成、选择、UI、安全、发布

#### T08～T24

**记录模板（待每个 Task 启动时填充）：**

```markdown
#### TXX - [Task 名]

**时间：** TBD  
**Agent 类型：** TBD  
**分支：** `feature/...`  
**依赖：** [Task]  

**Superpowers 技能：**
- [技能列表]

**关键 Prompt：**
```
[核心指令]
```

**失败测试（红色）：** [Agent 确认失败的输出]

**实现（绿色）：** [修改文件、通过测试的结果]

**两阶段评审：**
- SPEC 合规：[评审结果]
- 代码质量：[评审结果]

**Commit Message：** [建议 commit 信息]

**Commit Hash：** [合并后的真实 hash]

**人工修改：** [如有，记录修改内容和理由]

**教训：**
- 什么有效：[...]
- 什么低效或需改进：[...]
```

---

## 重点关注事项

### TDD 强制执行检查表

- [ ] **红色失败：** 每个 task 必须有"运行失败测试，看到红色"的证据（输出截图或日志）
- [ ] **绿色通过：** 实现后"运行测试，全部通过"的证据
- [ ] **重构：** 仅在绿色之后进行，测试保持通过
- [ ] **回归：** 相关回归测试全部通过

### Prompt & Context Engineering 记录

记录有效的 prompt 模式：

- [ ] "先写失败测试"显著减少实现偏离
- [ ] "不要自行扩大范围"防止 scope creep
- [ ] "遇到不确定立即暂停"确保规约问题尽早暴露
- [ ] [更多关键 prompt 模式待总结]

### 人工干预事件

按 task 记录：

- 类型：Bug fix / 规约澄清 / 重构建议 / 进度调整
- 理由：[具体说明为什么人工介入]
- 修改文件：[变更清单]
- 对后续 task 的影响

---

## 关键指标汇总

（待实现工作完成后填充）

| 指标 | 目标 | 实际 | 备注 |
|------|------|------|------|
| 冷启动暴露的 SPEC 问题数 | ≥ 3 | TBD | — |
| 规约修订轮次 | ≤ 2 | TBD | — |
| Task 完成进度（Day 10） | 100% | TBD | 包含 P0 和 P1 |
| TDD 遵守率 | 100% | TBD | 每个 task 都有红→绿 |
| Critical issue 比例 | 0% | TBD | 两阶段评审通过率 |

---

## 日志查询指南

**按阶段查找：** 搜索 `### Phase N`  
**按 Task 查找：** 搜索 `#### TXX`  
**按人工干预查找：** 搜索 `**人工修改**`  
**按教训查找：** 搜索 `**教训**`  

---

*日志维护：主开发 Claude（Claude Code）*  
*初始化：2026-08-07*  
*持续更新中...*
