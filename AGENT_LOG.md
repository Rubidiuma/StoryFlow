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

**时间：** 2026-08-07 08:35～估计 10:35 UTC  
**Agent 类型：** general-purpose  
**任务：** 从 T02 或 T04 中选择 1～2 个任务推进，验证 SPEC / PLAN 清晰度  
**Worktree：** `.claude/worktrees/coldstart-validation`  
**Branch：** `coldstart/spec-plan-validation`

**Superpowers 技能：** 无（冷启动是初期验证，不用技能框架）

**关键指令：**
```
从 PLAN 的 T02 或 T04 中选择 1～2 个任务推进。
先写失败测试，确认失败，再实现最少代码使其通过。
遇到不确定处立即暂停提问，不要自行补充产品规则。
```

**预期输出：**
- 修改的文件清单
- 红色测试输出（失败原因）
- 绿色测试通过结果
- 遇到的 SPEC / PLAN 问题列表

**实际输出：** [待 Agent 完成]

**人工干预：** [待评估冷启动结果后记录]

**教训：** [待总结]

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
