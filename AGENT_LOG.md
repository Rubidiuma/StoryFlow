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

**时间：** 2026-08-07 08:35～09:50 UTC  
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
   - 先写 29 个失败测试（13 个状态机 + 16 个模型验证）
   - 确认测试失败（import/module 缺失）
   - 实现最少代码：5 个枚举类 + 11 个 Pydantic 模型 + 状态转换表
   - 所有 29 个测试通过（耗时 0.04s）

3. **停留需求：** 零次暂停，零个问题提出
   - 没有遇到规约歧义
   - 没有找不到的说明
   - 自主完成 100%

**产出清单：**

✅ 修改的文件：
```
src/storyflow/domain/
├── __init__.py
├── enums.py (StoryStatus, ChoiceFrequency, ConfigGenre, ConfigStructure, ForeshadowingStatus)
├── models.py (Story, StoryConfig, StoryBible, CharacterState, StoryArc, StorySegment, ChoicePoint, ChoiceOption, Branch, MemorySnapshot)
└── state_machine.py (转换表、非法转换拒绝)

tests/unit/
├── test_state_machine.py (13 个转换测试)
└── test_domain_models.py (16 个模型验证测试)
```

✅ 红色测试输出：
```
FAILED src/storyflow/domain/__init__.py - ModuleNotFoundError: No module named 'storyflow.domain.enums'
[28 more similar failures]
```

✅ 绿色测试输出：
```
================================= 29 passed in 0.04s =================================

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
  - PLAN.md worktree 路径不匹配（已人工纠正）
  - 自定义行动解析策略延迟到服务层（有意设计，已确认理解）

**人工干预：** 

1. **PLAN.md 修正**
   - 修改：`../storyflow-coldstart` → `.claude/worktrees/coldstart-validation`
   - 原因：实际 worktree 路径与文档不符
   - 文件：PLAN.md §3 CS-01 的 **工作区** 字段

2. **SPEC_PROCESS.md 补充**
   - 记录了 Agent 的完成情况、测试结果、SPEC 验证分析
   - 将冷启动从"待完成"更新为"✅ 通过"

3. **无代码修改需求**
   - SPEC.md：无修订（清晰度已验证）
   - Agent 的代码可直接移用于 T01～T03

**教训：**

1. **SPEC 清晰度的实证价值**
   - Agent 零停留完成 T02，证明了规约写得充分
   - 没有隐性假设或模棱两可的地方
   - TDD 强制能够立即暴露规约问题（这里暴露 0 个）

2. **Task 颗粒度合理**
   - T02 预算 60～75 分钟，实际耗时 35 分钟
   - 说明任务分解足够细，Agent 能快速推进
   - 时间余量可用于 T03（SQLite + 仓储）

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

**Commit 记录（冷启动 Agent 在隔离环境）：** `9bc5df8`  
**推荐下一步：** 启动 PR-01（T01～T03），Agent 可复用冷启动的 domain 代码

---

## 正式实现工作区（待启动）

### Phase 1：Project Bootstrap & Domain (PR-01)

#### T01 - 项目骨架与质量门禁

**时间：** TBD  
**Agent 类型：** TBD（取决于冷启动结果）  
**分支：** `feature/bootstrap-domain`  
**依赖：** CS-01 完成  

**Superpowers 技能：**
- `writing-plans`：确认任务细分
- `test-driven-development`：强制 TDD
- `requesting-code-review`：两阶段评审

**关键 Prompt：**
```
[待 Task 启动时记录]
你负责 PLAN.md 中的 T01（项目骨架与质量门禁）。
1. 先写测试（`GET /health` 返回结构化状态）；
2. 确认测试失败；
3. 实现最少代码使测试通过；
4. 运行 ruff、mypy 等质量门禁；
5. 报告修改文件、红绿结果和 commit message。
```

**预期完成条件：**
- [ ] `make test` 通过健康检查测试
- [ ] `make lint` 和 `make typecheck` 通过
- [ ] `.gitignore` 包含 Python、数据库、编辑器规则
- [ ] 两阶段评审（SPEC 合规 + 代码质量）无 Critical issue

**实际输出：** [待启动]

**Commit Hash：** —

**人工修改：** [待记录]

**教训：** [待总结]

---

#### T02 - 领域模型与状态机

**时间：** TBD  
**Agent 类型：** TBD  
**分支：** `feature/bootstrap-domain`（同 T01）  
**依赖：** T01 完成  

**Superpowers 技能：**
- `test-driven-development`

**关键 Prompt：** [TBD]

**失败测试覆盖：**
- `DRAFT → PLANNING` 被拒绝
- `WAITING_CHOICE → PLANNING` 被拒绝
- `STREAMING → COMMITTING → IDLE/WAITING_CHOICE` 合法
- 配置边界校验（自定义行动长度、选项数量等）

**预期完成：** [TBD]

**实际输出：** [待启动]

**Commit Hash：** —

**教训：** [待总结]

---

#### T03 - SQLite schema 与仓储

**时间：** TBD  
**Agent 类型：** TBD  
**分支：** `feature/bootstrap-domain`  
**依赖：** T02 完成  

**Superpowers 技能：**
- `test-driven-development`

**失败测试覆盖：**
- 幂等键防止重复片段
- 事务失败不产生半场景
- 外键约束
- 路径遍历恢复

**预期完成：** [TBD]

**实际输出：** [待启动]

**Commit Hash：** —

**教训：** [待总结]

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
