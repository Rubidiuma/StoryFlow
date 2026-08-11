# Codex + Claude 协作计划

**状态：** 🚀 现在启动  
**目标：** 在 10 天内完成 24 个任务 + 1 个冷启动验证  
**当前进度：** 7/24 完成（29%），需要 17 个任务在 ~7 天内完成

---

## 📋 当前状态（2026-08-11 14:30 UTC）

### 🎉 PR-04 完成并合并到 main
- ✅ **PR-04（T08-T10）完成** - Codex 交付
  - **T08：** 事务性场景协调器（生成请求处理）
  - **T09：** 版本化 SSE 流式生成端点
  - **T10：** 并发恢复保障 + 幂等生成
  - 提交：`1c62e99`（merge commit），包含 Codex 的 9 个主要提交

### 🎉 PR-05 完成并提交
- ✅ **PR-01～PR-05 全部稳定** - 221 个测试全部通过
- ✅ **PR-05（T11-T13）完成** - Claude 交付
  - **T11：** 预设与自定义选择（9 测试）
  - **T12：** 分支与记忆快照恢复（6 测试）
  - **T13：** 动态故事弧与摘要（20 测试）
  - 提交：`e7b6fab` (feature/choice-branch)

### ✅ 已解决的问题
- ✅ PR-04 与 main 的合并冲突（Makefile、pyproject.toml、domain/__init__.py、PLAN.md）
- ✅ Python 3.9 兼容性（datetime.UTC、类型注解、generic syntax）
- ✅ `transition` 函数导出
- ✅ 所有测试恢复通过（186/186 ✓）

### 待做工作
- **PR-05 merge 到 main** → 当前在 `feature/choice-branch`，需人工 merge
- **PR-06 实现（T14-T16）** → Web UI [Codex 可从 main 合并 PR-05 后启动]
- **PR-07 实现（T17-T20）** → 安全、脱敏、导出
- **PR-08 完成（T21-T24）** → 测试、Docker、CI/CD、部署

---

## 🤝 分工建议

### Option A：串行协作（推荐）
**模式：** Codex 完成当前 PR，Claude 处理下一个 PR（不冲突）

| PR | 任务 | Codex | Claude | 时间 |
|----|------|-------|--------|------|
| PR-04 | T08-T10 生成流 | 🚧 进行 | 🔄 待命 | Day 1 |
| PR-05 | T11-T13 选择分支 | 📋 待启 | 🚀 启动 | Day 2 |
| PR-06 | T14-T16 Web UI | 📋 待启 | 🚀 启动 | Day 3 |
| PR-07 | T17-T20 安全导出 | 📋 待启 | 🚀 启动 | Day 4 |
| PR-08 | T21-T24 测试发布 | 📋 待启 | 🚀 启动 | Day 5+ |

**优点：**
- 无分支冲突，清晰的所有制
- 每个 PR 由一个 Agent 完成，保持代码风格一致
- 时间充足，可以完成高质量的两阶段评审

**流程：**
1. Codex 完成 PR-04 → merge 到 main
2. Claude 从 main 创建 PR-05 worktree
3. Codex 稍后从 main（包含 PR-05 的 commits）创建 PR-06

---

### Option B：并行协作（快速但有风险）
**模式：** Codex 继续 PR-04，Claude 同时开启 PR-05（需要定期合并）

**风险：** 分支冲突、集成复杂，不推荐单人项目

---

## 📍 立即行动

### 对 Codex 的建议
```
你目前在 PR-04 (T08-T10) 的 feature/generation-streaming 分支。
下一步：
1. 完成 T08（生成协调器）的失败测试编写
2. 实现最少代码使其通过
3. 完成 T09（流式生成接口）
4. 完成 T10（幂等、断线与恢复）
5. 通过两阶段评审（SPEC 合规 + 代码质量）
6. 发起 PR 合并到 main

时间预算：2～3 天（总计 4-6 小时）
```

### 对 Claude 的行动
```
1. 等待 Codex 完成 PR-04 并合并到 main（~24 小时）
2. 从 main 创建新 worktree：feature/choice-branch（对应 PR-05）
3. 启动 T11-T13（选择与分支管理）
   - T11：预设与自定义选择
   - T12：分支与记忆快照恢复
   - T13：动态故事弧与摘要

并行：Claude 可在 main 保留，进行代码评审、文档、或其他任务
```

---

## 🔄 协调机制

### 每日同步点
- **Codex 完成一个 PR** → 发送 PR merge 通知
- **Claude 启动新 PR** → 在此文件中更新进度
- **遇到阻塞** → 在 AGENT_LOG.md 中记录，等待对方支持

### 代码评审流程
每个 PR 合并前需要：
1. **SPEC 合规评审**（15 分钟）
   - 功能对应 SPEC 条款？
   - 所有失败测试已变绿？
   - 相关回归测试通过？

2. **代码质量评审**（15 分钟）
   - 代码是否清晰、可维护？
   - 有无 Critical bug？
   - 测试覆盖是否足够？

3. **合并与部署**
   - 更新 PLAN.md 中的任务状态
   - 更新 AGENT_LOG.md 记录
   - 创建 commit 并推送到 main

---

## ⏱️ 时间预算

| 阶段 | 任务 | 预算 | Agent | 状态 |
|------|------|------|-------|------|
| Day 1 | PR-04 (T08-T10) | 6-8h | Codex | 🚧 |
| Day 2 | PR-05 (T11-T13) | 6-8h | Claude | 📋 |
| Day 3 | PR-06 (T14-T16) | 8-10h | Codex or Claude | 📋 |
| Day 4 | PR-07 (T17-T20) | 6-8h | Codex or Claude | 📋 |
| Day 5+ | PR-08 (T21-T24) | 8-10h | Codex or Claude | 📋 |

**总计：** ~34-46 小时 = ~4.5 小时/天 × 7 天（充足）

---

## 🎯 成功标准

**全部 24 个任务完成时的终止条件：**
- [ ] 所有 P0 任务完成（20 个）
- [ ] 所有 P1 任务完成（4 个）
- [ ] 所有任务都有红→绿测试证据
- [ ] 两阶段评审通过，0 个 Critical issue
- [ ] PLAN.md 中所有任务标记为 `[x]`
- [ ] AGENT_LOG.md 完整记录了每个 task 的过程
- [ ] 代码推送到 main，可部署

---

## 📞 协作频道

**更新此文件：** 当开启新 PR、遇到阻塞、或完成重要里程碑时
**AGENT_LOG.md：** 每个 task 完成时，记录时间、技能、prompt、输出、修改
**Git Commits：** 每个 PR merge 时，更新 PLAN.md 和 AGENT_LOG.md

---

*初始化于：2026-08-11*  
*Codex（已启动）+ Claude（现在启动）*  
*目标：10 天内上线 StoryFlow*
