# StoryFlow 实现计划

> 对应规约：`SPEC.md`  
> 方法：Superpowers `writing-plans` → 冷启动验证 → worktree + subagent → TDD → 两阶段评审  
> 状态：待冷启动验证  
> 目标周期：10 天

## 1. 计划使用规则

### 1.1 开发纪律

1. 正式实现前，必须先完成本计划第 3 节的冷启动验证，并据此修改 `SPEC.md` / `PLAN.md`。
2. 每个实现任务由一个新鲜 subagent 在对应 worktree 中完成；不得让一个 subagent 连续包办多个独立模块。
3. 每个任务严格执行 TDD：先添加失败测试并确认失败，再写最少实现使测试通过，最后重构。
4. 每个任务完成后依次进行：
   - 第一阶段：SPEC 合规检查；
   - 第二阶段：代码质量检查；
   - Critical issue 修复；
   - 人工复核；
   - commit / PR。
5. 每完成一个任务，在本文件任务索引中将状态改为完成并填写 commit hash。
6. 所有关键 prompt、技能、失败测试、subagent 输出、人工修改和经验写入 `AGENT_LOG.md`。
7. 下文每个编号任务是一组可由单个 subagent 完成的工作；其中每个复选框步骤控制在约 2～5 分钟。

### 1.2 完成标记

- `[ ]` 未开始
- `[-]` 进行中
- `[x]` 已完成
- `[!]` 阻塞

### 1.3 通用完成条件

每个任务只有同时满足以下条件才可标记完成：

- 失败测试的红色结果已记录。
- 最少实现后目标测试变绿。
- 相关回归测试全部通过。
- SPEC 合规评审和代码质量评审均无 Critical issue。
- `AGENT_LOG.md` 已记录过程。
- commit message / PR 描述标注 subagent 与人工修改。
- 本文件已填写 commit hash。

## 2. 目标目录结构

```text
storyflow/
├── src/storyflow/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── domain/
│   │   ├── models.py
│   │   ├── enums.py
│   │   └── state_machine.py
│   ├── db/
│   │   ├── database.py
│   │   ├── schema.sql
│   │   └── repositories.py
│   ├── llm/
│   │   ├── base.py
│   │   ├── fake.py
│   │   └── provider.py
│   ├── prompts/
│   │   ├── bible.py
│   │   ├── director.py
│   │   ├── writer.py
│   │   └── memory.py
│   ├── services/
│   │   ├── bible.py
│   │   ├── choice_policy.py
│   │   ├── context_builder.py
│   │   ├── generation.py
│   │   ├── memory.py
│   │   ├── branches.py
│   │   └── export.py
│   ├── security/
│   │   ├── credentials.py
│   │   ├── redaction.py
│   │   ├── sessions.py
│   │   └── rate_limit.py
│   ├── api/
│   │   ├── dependencies.py
│   │   ├── errors.py
│   │   └── routes/
│   │       ├── stories.py
│   │       ├── generation.py
│   │       ├── choices.py
│   │       └── export.py
│   ├── templates/
│   │   ├── base.html
│   │   ├── index.html
│   │   ├── create.html
│   │   └── reader.html
│   └── static/
│       ├── css/app.css
│       └── js/
│           ├── api.js
│           ├── create.js
│           └── reader.js
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   └── fixtures/
├── scripts/
│   └── demo_seed.py
├── pyproject.toml
├── Makefile
├── Dockerfile
├── .dockerignore
├── .gitignore
├── .gitlab-ci.yml
├── SPEC.md
├── PLAN.md
├── SPEC_PROCESS.md
├── AGENT_LOG.md
├── REFLECTION.md
└── README.md
```

## 3. 正式实现前：冷启动验证

### CS-01 使用陌生 Agent 验证 SPEC / PLAN

**状态：** `[ ]`  
**预计：** 1～2 小时  
**工作区：** `../storyflow-coldstart`  
**分支：** `coldstart/spec-plan-validation`  
**依赖：** 无  
**产物：** `SPEC_PROCESS.md` 中的冷启动记录；必要的 `SPEC.md` / `PLAN.md` 修订

**Agent 选择要求：** 与主开发 Agent 类型不同；启动全新 session；不导入历史会话或 memory。

**仅提供给冷启动 Agent：**

- `SPEC.md`
- `PLAN.md`
- 指令：“从 T02 和 T04 中选择 1～2 个任务推进；遇到任何不确定处立即暂停提问，不得自行补充产品规则。”

**步骤：**

- [ ] 创建独立 worktree 和全新 Agent session。
- [ ] 只向 Agent 提供 `SPEC.md`、`PLAN.md` 和上述指令。
- [ ] 记录 Agent 首次暂停位置和所有问题，不补充口头解释。
- [ ] 记录其对状态机、选择频率或数据结构的不同解读。
- [ ] 对照预期判断问题来自规约缺陷还是 Agent 误读。
- [ ] 保存其失败测试、代码草稿和验证结果作为证据。
- [ ] 在 `SPEC_PROCESS.md` 写入修订前后的关键 diff。
- [ ] 修改 `SPEC.md` / `PLAN.md` 中暴露出的歧义。
- [ ] 丢弃或保留冷启动 worktree，并记录决定和理由。
- [ ] 人工确认规约足以进入正式实现。

**验证：**

```bash
git diff -- SPEC.md PLAN.md SPEC_PROCESS.md
```

**通过标准：** `SPEC_PROCESS.md` 包含暂停点、错误解读、产出差距、修订前后 diff 和人工判断。

## 4. Worktree / PR 与依赖关系

| PR | 分支 | 任务 | 依赖 | 可并行关系 |
| --- | --- | --- | --- | --- |
| PR-01 | `feature/bootstrap-domain` | T01～T03 | CS-01 | 起点 |
| PR-02 | `feature/llm-bible` | T04～T05 | PR-01 | 可与 PR-03 并行 |
| PR-03 | `feature/choice-context` | T06～T07 | PR-01 | 可与 PR-02 并行 |
| PR-04 | `feature/generation-stream` | T08～T10 | PR-02、PR-03 | 主链 |
| PR-05 | `feature/choice-branch` | T11～T13 | PR-04 | 可与 PR-06 的静态 UI 前置并行 |
| PR-06 | `feature/web-ui` | T14～T16 | PR-04，最终联调依赖 PR-05 | 静态壳可提前 |
| PR-07 | `feature/security-export` | T17～T20 | PR-01、PR-05 | 凭据/脱敏可与 PR-06 并行 |
| PR-08 | `feature/release` | T21～T24 | PR-06、PR-07 | 收尾 |

主依赖链：

```text
CS-01 → PR-01 → ┬→ PR-02 ─┐
                 └→ PR-03 ─┴→ PR-04 → PR-05 ─┬→ PR-06 ─┐
                                               └→ PR-07 ─┴→ PR-08
```

## 5. 任务索引

| ID | 任务 | 优先级 | 状态 | Commit |
| --- | --- | --- | --- | --- |
| CS-01 | 冷启动验证 | 必做前置 | `[ ]` | — |
| T01 | 项目骨架与质量门禁 | P0 | `[ ]` | — |
| T02 | 领域模型与状态机 | P0 | `[ ]` | — |
| T03 | SQLite schema 与仓储 | P0 | `[ ]` | — |
| T04 | LLM 抽象与 fake LLM | P0 | `[ ]` | — |
| T05 | 故事创建与故事圣经 | P0 | `[ ]` | — |
| T06 | 选择点策略 | P0 | `[ ]` | — |
| T07 | 上下文预算与分层记忆 | P1 | `[ ]` | — |
| T08 | 生成状态协调器 | P0 | `[ ]` | — |
| T09 | 流式生成接口 | P0 | `[ ]` | — |
| T10 | 幂等、断线与恢复 | P0 | `[ ]` | — |
| T11 | 预设与自定义选择 | P0 | `[ ]` | — |
| T12 | 分支与记忆快照恢复 | P1 | `[ ]` | — |
| T13 | 动态故事弧与摘要 | P1 | `[ ]` | — |
| T14 | 创建向导和书架 | P0 | `[ ]` | — |
| T15 | 流式阅读器和自动续写 | P0 | `[ ]` | — |
| T16 | 选择、暂停、恢复和分支 UI | P0/P1 | `[ ]` | — |
| T17 | 匿名会话隔离 | P0 | `[ ]` | — |
| T18 | 凭据与日志脱敏 | 必做 | `[ ]` | — |
| T19 | 速率、并发和成本护栏 | 必做 | `[ ]` | — |
| T20 | Markdown 导出 | P1 | `[ ]` | — |
| T21 | 端到端测试与演示夹具 | 必做 | `[ ]` | — |
| T22 | Docker 分发 | 必做 | `[ ]` | — |
| T23 | GitLab CI 与 secret scan | 必做 | `[ ]` | — |
| T24 | 部署、README 与最终验收 | 必做 | `[ ]` | — |

## 6. 详细实现任务

## PR-01：项目骨架、领域与持久化

### T01 项目骨架与质量门禁

**目标：** 建立可安装、可启动、可一键测试的最小 FastAPI 项目。  
**文件：** `pyproject.toml`、`src/storyflow/main.py`、`src/storyflow/config.py`、`tests/unit/test_health.py`、`Makefile`、`.gitignore`  
**依赖：** CS-01  
**预计：** 45～60 分钟

**失败测试：** `GET /health` 应返回不含凭据的结构化健康状态；初始因应用不存在而失败。

**步骤：**

- [ ] 创建 `tests/unit/test_health.py`，断言状态码和固定字段。
- [ ] 运行单测并保存 import/route 缺失的红色结果。
- [ ] 创建 `pyproject.toml`，声明 FastAPI、Uvicorn、pytest、httpx、ruff、mypy。
- [ ] 创建 `src/storyflow/main.py` 的应用工厂和 `/health`。
- [ ] 创建最小 `config.py`，只读取非敏感运行配置。
- [ ] 增加 `Makefile` 的 `test`、`lint`、`typecheck`、`run`。
- [ ] 添加 Python、数据库、密钥、编辑器文件的 `.gitignore` 规则。
- [ ] 运行目标测试使其变绿。
- [ ] 运行 ruff 与 mypy，修复最小问题。
- [ ] 两阶段评审并更新日志。

**验证：**

```bash
make test
make lint
make typecheck
```

### T02 领域模型与状态机

**目标：** 用纯领域代码定义故事实体、运行状态和合法状态转换。  
**文件：** `src/storyflow/domain/enums.py`、`src/storyflow/domain/models.py`、`src/storyflow/domain/state_machine.py`、`tests/unit/test_state_machine.py`、`tests/unit/test_domain_models.py`  
**依赖：** T01  
**预计：** 60～75 分钟

**失败测试：**

- `DRAFT → PLANNING` 被拒绝；必须先确认到 `IDLE`。
- `WAITING_CHOICE → PLANNING` 被拒绝。
- `STREAMING → COMMITTING → IDLE/WAITING_CHOICE` 合法。
- 自定义行动长度、选项数量和故事配置边界得到校验。

**步骤：**

- [ ] 先写状态枚举和非法转换测试。
- [ ] 运行测试确认模型/状态机缺失。
- [ ] 实现 `StoryStatus` 与转换表。
- [ ] 写合法转换测试并确认失败。
- [ ] 实现纯函数 `transition(current, event)`。
- [ ] 为故事配置、场景计划、选择点写边界测试。
- [ ] 实现对应 Pydantic 模型和验证器。
- [ ] 增加三个选项必须唯一且 effect 非空的测试。
- [ ] 实现最少校验逻辑。
- [ ] 运行全部领域测试并重构重复 fixture。

**验证：**

```bash
pytest -q tests/unit/test_state_machine.py tests/unit/test_domain_models.py
```

### T03 SQLite schema 与仓储

**目标：** 持久化 Story、Bible、Segment、Choice、Branch、MemorySnapshot 和事件，并保证事务、外键和幂等约束。  
**文件：** `src/storyflow/db/schema.sql`、`src/storyflow/db/database.py`、`src/storyflow/db/repositories.py`、`tests/integration/test_repositories.py`  
**依赖：** T02  
**预计：** 90 分钟

**失败测试：**

- 重复 `generation_key` 不产生第二个片段。
- 事务中途失败时不留下半场景或孤立选择。
- 父片段不存在时写入失败。
- 当前分支可按父节点顺序恢复正文。

**步骤：**

- [ ] 写临时 SQLite fixture 和 schema 初始化失败测试。
- [ ] 增加 Story 创建/读取测试并确认失败。
- [ ] 编写最小 `schema.sql` 与连接生命周期。
- [ ] 实现 Story/Bible 仓储使第一组测试变绿。
- [ ] 写 Segment 幂等和外键测试并确认失败。
- [ ] 实现 Segment、Choice、Event 原子提交。
- [ ] 写 Branch/MemorySnapshot 路径恢复测试并确认失败。
- [ ] 实现分支和快照仓储。
- [ ] 启用 WAL、foreign_keys 和事务回滚。
- [ ] 运行集成测试并检查无临时数据库残留。

**验证：**

```bash
pytest -q tests/integration/test_repositories.py
```

## PR-02：LLM 接口与故事创建

### T04 LLM 抽象与 fake LLM

**目标：** 提供不依赖真实网络的结构化生成和流式文本接口。  
**文件：** `src/storyflow/llm/base.py`、`src/storyflow/llm/fake.py`、`src/storyflow/llm/provider.py`、`tests/unit/test_fake_llm.py`  
**依赖：** PR-01  
**预计：** 60 分钟

**失败测试：** fake LLM 能按脚本返回 JSON、逐块流式文本、模拟超时/非法结构，并能断言收到的上下文。

**步骤：**

- [ ] 写 `LLMClient` 协议使用测试并确认接口不存在。
- [ ] 定义 `generate_json()` 和 `stream_text()` 协议。
- [ ] 写 fake 响应队列和调用记录测试。
- [ ] 实现脚本化 `FakeLLMClient`。
- [ ] 写非法 JSON、超时和流中断测试。
- [ ] 实现确定性错误注入。
- [ ] 创建真实 provider 的薄适配骨架，不写业务循环。
- [ ] 确认所有单测无网络运行。

**验证：**

```bash
pytest -q tests/unit/test_fake_llm.py
```

### T05 故事创建与故事圣经

**目标：** 实现创建故事草稿、生成故事圣经、结构重试和用户确认。  
**文件：** `src/storyflow/prompts/bible.py`、`src/storyflow/services/bible.py`、`src/storyflow/api/routes/stories.py`、`tests/integration/test_story_creation.py`  
**依赖：** T04  
**预计：** 75～90 分钟

**失败测试：**

- 未确认 Bible 不能开始生成。
- 首次非法结构、第二次合法时成功创建。
- 连续两次非法结构时不留下半成品 Bible。
- 输入总长度和必填项得到校验。

**步骤：**

- [ ] 写创建 Story 草稿 API 测试并确认失败。
- [ ] 实现输入模型和草稿写入。
- [ ] 写故事圣经成功及非法 JSON 重试测试。
- [ ] 编写版本化 Bible prompt 模板。
- [ ] 实现 `BibleService.generate()`，最多重试一次。
- [ ] 写事务失败无半成品测试。
- [ ] 实现 Bible、初始人物和首个 StoryArc 原子提交。
- [ ] 写确认接口与重复确认测试。
- [ ] 实现 `DRAFT → IDLE` 状态转换。
- [ ] 运行创建流程集成测试。

**验证：**

```bash
pytest -q tests/integration/test_story_creation.py
```

## PR-03：选择策略与上下文

### T06 选择点策略

**目标：** 用确定性代码接受、拒绝或强制模型建议的选择点。  
**文件：** `src/storyflow/services/choice_policy.py`、`tests/unit/test_choice_policy.py`  
**依赖：** PR-01  
**预计：** 60 分钟

**失败测试：**

- 三种频率对应正确最小/最大场景间隔。
- 未达最小间隔时拒绝模型建议。
- 达到最大间隔时要求选择或安全暂停。
- 重复选项、空效果、无明确冲突被拒绝。

**步骤：**

- [ ] 参数化写出少/中/多的间隔测试。
- [ ] 运行测试确认策略缺失。
- [ ] 实现频率配置映射。
- [ ] 写模型建议接受/拒绝测试。
- [ ] 实现 `ChoiceDecision`：continue/accept/force/pause。
- [ ] 写选项唯一性和 effect 分类测试。
- [ ] 实现选项质量的确定性最低门槛。
- [ ] 增加边界值与异常输入测试。
- [ ] 重构为无数据库、无 LLM 的纯函数。

**验证：**

```bash
pytest -q tests/unit/test_choice_policy.py
```

### T07 上下文预算与分层记忆

**目标：** 在固定预算内优先保留世界规则、当前弧、相关人物、活跃伏笔和最近文本。  
**文件：** `src/storyflow/services/context_builder.py`、`src/storyflow/services/memory.py`、`src/storyflow/prompts/memory.py`、`tests/unit/test_context_builder.py`、`tests/unit/test_memory.py`  
**依赖：** T03  
**预计：** 90 分钟

**失败测试：**

- 30 个场景后上下文仍不超过配置预算。
- 固定设定、当前弧、最近选择和活跃伏笔不可被裁掉。
- 已回收伏笔退出活跃上下文。
- 最近 2 个场景保留原文，更早内容只使用摘要。

**步骤：**

- [ ] 创建 30 场景记忆 fixture。
- [ ] 写预算上限测试并确认失败。
- [ ] 实现确定性字符/token 估算接口。
- [ ] 写优先级裁剪测试。
- [ ] 实现分层选择和裁剪顺序。
- [ ] 写最近场景、历史摘要和伏笔状态测试。
- [ ] 实现上下文结构化输出。
- [ ] 写记忆更新结构解析测试。
- [ ] 实现最小 `MemoryService` 更新接口。
- [ ] 运行压力 fixture 并记录上下文大小。

**验证：**

```bash
pytest -q tests/unit/test_context_builder.py tests/unit/test_memory.py
```

## PR-04：生成协调与流式接口

### T08 生成状态协调器

**目标：** 串联上下文、导演、选择策略、作者和提交过程，但不把它实现为自主 Agent。  
**文件：** `src/storyflow/prompts/director.py`、`src/storyflow/prompts/writer.py`、`src/storyflow/services/generation.py`、`tests/integration/test_generation_service.py`  
**依赖：** PR-02、PR-03  
**预计：** 90 分钟

**失败测试：**

- 正确经历 `IDLE → PLANNING → STREAMING → COMMITTING → IDLE`。
- 有选择时最终进入 `WAITING_CHOICE`。
- `DRAFT`、`WAITING_CHOICE`、`PAUSED` 不允许直接生成。
- 导演结构非法时按策略重试并安全停止。

**步骤：**

- [ ] 用 fake LLM 写无选择的状态序列测试。
- [ ] 运行并保存服务缺失的红色结果。
- [ ] 实现 director prompt 和结构化计划调用。
- [ ] 接入 ChoicePolicy 与 writer 流接口。
- [ ] 写有选择的状态序列测试。
- [ ] 实现场景提交和选择创建。
- [ ] 写非法起始状态参数化测试。
- [ ] 实现状态前置检查。
- [ ] 写导演失败和 writer 失败测试。
- [ ] 实现错误状态及可重试错误码。

**验证：**

```bash
pytest -q tests/integration/test_generation_service.py
```

### T09 流式生成接口

**目标：** 通过 POST 流式响应发送计划状态、正文增量、提交和选择事件。  
**文件：** `src/storyflow/api/routes/generation.py`、`src/storyflow/api/errors.py`、`tests/integration/test_streaming_api.py`  
**依赖：** T08  
**预计：** 75 分钟

**事件协议：** `planning` → 多个 `delta` → `committed` → `choice|continue|paused`；错误为 `error`。

**失败测试：**

- 事件顺序固定且每个事件可解析。
- 选择正文完成后才下发选项。
- 流结束前数据库没有可见正式场景。
- 健康心跳不写入正文。

**步骤：**

- [ ] 写流式响应解析 fixture。
- [ ] 写事件顺序测试并确认 404/接口缺失。
- [ ] 定义版本化事件 schema。
- [ ] 实现 POST streaming route。
- [ ] 写 choice 只在 committed 后出现的测试。
- [ ] 实现末尾控制事件。
- [ ] 写心跳和空 delta 测试。
- [ ] 实现心跳与内容分离。
- [ ] 写错误事件不泄露内部异常测试。
- [ ] 运行集成测试并人工检查示例流。

**验证：**

```bash
pytest -q tests/integration/test_streaming_api.py
```

### T10 幂等、断线与恢复

**目标：** 防止重复场景、并发生成和应用重启后的重复计费。  
**文件：** `src/storyflow/services/generation.py`、`src/storyflow/api/routes/generation.py`、`tests/integration/test_generation_recovery.py`  
**依赖：** T09  
**预计：** 75 分钟

**失败测试：**

- 相同幂等键只创建一个片段。
- 同一分支并发第二次生成返回冲突。
- 流中断不提交半场景。
- 重启时遗留活动状态恢复为 `ERROR`，不会自动重发 LLM 请求。

**步骤：**

- [ ] 写相同 key 两次请求测试。
- [ ] 实现数据库唯一约束命中后的已有结果返回。
- [ ] 写并发锁/版本冲突测试。
- [ ] 实现分支级乐观锁。
- [ ] 写 writer 中途异常测试。
- [ ] 实现 buffer 与事务提交边界。
- [ ] 写遗留状态恢复测试。
- [ ] 实现启动时恢复服务。
- [ ] 运行 20 次重复请求压力测试。
- [ ] 检查无重复片段和未释放状态。

**验证：**

```bash
pytest -q tests/integration/test_generation_recovery.py
```

## PR-05：选择、分支和故事弧

### T11 预设与自定义选择

**目标：** 原子提交一次选择，将影响写入记忆并恢复生成。  
**文件：** `src/storyflow/api/routes/choices.py`、`src/storyflow/services/memory.py`、`tests/integration/test_choice_submission.py`  
**依赖：** PR-04  
**预计：** 75 分钟

**失败测试：**

- 非 `WAITING_CHOICE` 状态拒绝提交。
- 同一 choice version 重复点击只成功一次。
- 预设效果进入下一场景上下文。
- 自定义行动长度非法时状态不变。
- 自定义行动解析失败时保留等待选择状态。

**步骤：**

- [ ] 写预设选择成功/重复测试。
- [ ] 实现选择版本检查和原子提交。
- [ ] 写 effect 应用到记忆的测试。
- [ ] 实现人物、信息、路线效果合并。
- [ ] 写自定义行动输入边界测试。
- [ ] 实现自定义行动结构解析调用。
- [ ] 写解析失败事务回滚测试。
- [ ] 实现失败后原状态保留。
- [ ] 运行下一场景上下文集成测试。

**验证：**

```bash
pytest -q tests/integration/test_choice_submission.py
```

### T12 分支与记忆快照恢复

**目标：** 从历史选择创建新分支，共享分叉前正文并恢复当时记忆。  
**文件：** `src/storyflow/services/branches.py`、`src/storyflow/api/routes/choices.py`、`tests/integration/test_branching.py`  
**依赖：** T11  
**预计：** 75 分钟

**失败测试：**

- 分叉前路径共享，分叉后片段独立。
- 原分支 head 不变。
- 新分支恢复选择前快照。
- 兄弟分支内容不会混入当前上下文。

**步骤：**

- [ ] 写两层父路径 fixture。
- [ ] 写创建分支路径测试并确认失败。
- [ ] 实现 Branch 创建和 head 指针。
- [ ] 写原分支不可变测试。
- [ ] 实现快照复制/引用策略。
- [ ] 写上下文仅取当前路径测试。
- [ ] 接入 ContextBuilder 的 branch filter。
- [ ] 写不存在/越权选择的错误测试。
- [ ] 运行分支路径和记忆回归测试。

**验证：**

```bash
pytest -q tests/integration/test_branching.py
```

### T13 动态故事弧与摘要

**目标：** 每 5 个场景更新滚动摘要，故事弧结束后生成下一弧并保持既有事实。  
**文件：** `src/storyflow/services/memory.py`、`src/storyflow/prompts/memory.py`、`tests/integration/test_story_arc.py`  
**依赖：** T07、T12  
**预计：** 75 分钟

**失败测试：**

- 第 5 个场景触发摘要，其他场景不触发。
- 已提交正文不会因摘要失败而丢失。
- 旧弧结束后新弧建立并进入上下文。
- 新弧不得覆盖固定世界规则和已发生事实。

**步骤：**

- [ ] 写摘要触发边界测试。
- [ ] 实现摘要调度条件。
- [ ] 写摘要结构解析及失败测试。
- [ ] 实现可重试记忆更新状态。
- [ ] 写故事弧退出条件测试。
- [ ] 实现下一弧生成与校验。
- [ ] 写固定事实不可覆盖测试。
- [ ] 实现合并冲突拒绝逻辑。
- [ ] 使用 fake LLM 连续运行 12 场景验证。

**验证：**

```bash
pytest -q tests/integration/test_story_arc.py
```

## PR-06：WebUI

### T14 创建向导和书架

**目标：** 用户可创建、确认、查看和恢复小说。  
**文件：** `src/storyflow/templates/base.html`、`index.html`、`create.html`、`static/css/app.css`、`static/js/api.js`、`static/js/create.js`、`tests/integration/test_web_pages.py`  
**依赖：** T05；静态壳可提前，联调基于 PR-04  
**预计：** 90 分钟

**失败测试：** 页面路由可访问；表单字段与 API schema 一致；未确认 Bible 显示确认界面而非阅读器。

**步骤：**

- [ ] 写首页、创建页、故事页状态码测试。
- [ ] 实现模板路由和基础布局。
- [ ] 按 Open Design 原则定义字号、阅读宽度、颜色和状态组件。
- [ ] 写创建表单必填/长度的前端约束。
- [ ] 实现分步创建向导。
- [ ] 接入创建和 Bible 生成 API。
- [ ] 实现 Bible 预览、修改和确认操作。
- [ ] 实现书架列表和最近状态。
- [ ] 人工检查桌面和窄屏布局。
- [ ] 记录 UI 决策到 SPEC/日志。

**验证：**

```bash
pytest -q tests/integration/test_web_pages.py
```

### T15 流式阅读器和自动续写

**目标：** 在阅读页逐段显示正文，无选择时自动请求下一场景。  
**文件：** `src/storyflow/templates/reader.html`、`src/storyflow/static/js/reader.js`、`src/storyflow/static/css/app.css`、`tests/e2e/test_reader_stream.py`  
**依赖：** T09、T14  
**预计：** 90 分钟

**失败测试：** fake 流能按 delta 顺序显示；收到 `continue` 才发起下一请求；收到 `choice` 不再请求。

**步骤：**

- [ ] 写浏览器 fake stream fixture。
- [ ] 写 delta 顺序渲染失败测试。
- [ ] 实现 fetch streaming parser。
- [ ] 写 `continue` 自动请求测试。
- [ ] 实现单一 active request 控制器。
- [ ] 写 `choice/paused/error` 停止测试。
- [ ] 实现控制事件处理和错误恢复。
- [ ] 增加自动滚动、阅读位置和生成阶段提示。
- [ ] 测试刷新不会自动重复生成。
- [ ] 人工检查长文本阅读体验。

**验证：**

```bash
pytest -q tests/e2e/test_reader_stream.py
```

### T16 选择、暂停、恢复和分支 UI

**目标：** 完成用户可见的核心互动闭环。  
**文件：** `src/storyflow/templates/reader.html`、`src/storyflow/static/js/reader.js`、`src/storyflow/static/css/app.css`、`tests/e2e/test_reader_choices.py`  
**依赖：** T11、T12、T15  
**预计：** 90 分钟

**失败测试：**

- 等待选择时显示 3 个选项和自定义输入。
- 选择提交期间按钮禁用，重复点击只发送一次。
- 暂停后当前场景结束但不自动续写。
- 从历史选择创建新分支后切换到新路径。

**步骤：**

- [ ] 写选择卡渲染测试。
- [ ] 实现预设选项和自定义行动提交。
- [ ] 写重复点击与错误恢复测试。
- [ ] 实现提交锁和版本冲突提示。
- [ ] 写暂停/继续按钮测试。
- [ ] 实现 pause_requested UI 状态。
- [ ] 写历史选择和新分支测试。
- [ ] 实现简化分支列表和切换。
- [ ] 增加人物、活跃伏笔侧栏的 P2 展示；若超时可删除。
- [ ] 完整人工走查一次主流程。

**验证：**

```bash
pytest -q tests/e2e/test_reader_choices.py
```

## PR-07：安全、治理和导出

### T17 匿名会话隔离

**目标：** 在线演示中不同浏览器会话不能读取彼此故事。  
**文件：** `src/storyflow/security/sessions.py`、`src/storyflow/api/dependencies.py`、`tests/integration/test_session_isolation.py`  
**依赖：** T03  
**预计：** 60 分钟

**失败测试：** 会话 A 创建的故事无法被会话 B 读取、选择、生成、分支或导出。

**步骤：**

- [ ] 写两个客户端 Cookie 隔离 fixture。
- [ ] 写跨会话读写矩阵测试并确认失败。
- [ ] 实现随机 session id 和签名 HttpOnly Cookie。
- [ ] 在仓储查询强制加入 session 条件。
- [ ] 写 Cookie 篡改和过期测试。
- [ ] 实现无效 Cookie 轮换。
- [ ] 运行所有故事路由隔离回归。

**验证：**

```bash
pytest -q tests/integration/test_session_isolation.py
```

### T18 凭据与日志脱敏

**目标：** API Key 只在服务端安全来源中存在，并支持 set/status/update/clear。  
**文件：** `src/storyflow/security/credentials.py`、`src/storyflow/security/redaction.py`、`src/storyflow/cli.py`、`tests/unit/test_credentials.py`、`tests/unit/test_redaction.py`  
**依赖：** T01  
**预计：** 75 分钟

**失败测试：**

- Keychain 优先于 secret 文件，开发 `.env` 仅为显式降级来源。
- `status` 不回显明文。
- Key、Authorization、Cookie 和疑似密钥格式在日志中被替换。
- `/health` 只显示 configured/unconfigured。

**步骤：**

- [ ] 写凭据来源优先级测试。
- [ ] 实现 `CredentialProvider` 和 secret 文件读取。
- [ ] 写 keyring mock 的 set/status/update/clear 测试。
- [ ] 实现隐藏输入 CLI。
- [ ] 写日志脱敏参数化测试。
- [ ] 实现 logging filter。
- [ ] 写异常响应不含密钥测试。
- [ ] 接入全局异常处理和健康状态。
- [ ] 扫描测试输出确保无 fixture 明文泄漏。

**验证：**

```bash
pytest -q tests/unit/test_credentials.py tests/unit/test_redaction.py
```

### T19 速率、并发和成本护栏

**目标：** 限制每会话速率、分支并发、场景长度和无人值守自动生成数量。  
**文件：** `src/storyflow/security/rate_limit.py`、`src/storyflow/config.py`、`src/storyflow/api/routes/generation.py`、`tests/integration/test_generation_limits.py`  
**依赖：** T10、T17  
**预计：** 60 分钟

**失败测试：**

- 超过会话速率返回 429。
- 同一分支第二个活动请求返回 409。
- 连续 5 个无选择场景后进入安全暂停。
- 超长模型输出被截断并标记错误，不提交不完整场景。

**步骤：**

- [ ] 写可注入时钟的速率限制测试。
- [ ] 实现单进程滑动窗口限制器。
- [ ] 写自动场景计数测试。
- [ ] 实现批次计数和安全暂停。
- [ ] 写输出上限和超时测试。
- [ ] 实现流式计数器和取消。
- [ ] 写配置边界测试。
- [ ] 接入并发、速率和成本相关错误码。
- [ ] 运行主流程回归。

**验证：**

```bash
pytest -q tests/integration/test_generation_limits.py
```

### T20 Markdown 导出

**目标：** 导出当前分支而不混入兄弟分支。  
**文件：** `src/storyflow/services/export.py`、`src/storyflow/api/routes/export.py`、`tests/integration/test_export.py`  
**依赖：** T12、T17  
**预计：** 45 分钟

**失败测试：** 多分支 fixture 中只输出当前路径，顺序正确，含标题和已选选项，不含隐藏 effects。

**步骤：**

- [ ] 创建分叉故事 fixture。
- [ ] 写路径和排除兄弟分支测试。
- [ ] 实现当前 branch 路径读取。
- [ ] 写 Markdown 转义和标题测试。
- [ ] 实现导出格式化。
- [ ] 写跨会话导出拒绝测试。
- [ ] 实现下载响应头和安全文件名。
- [ ] 人工打开一次导出文件检查可读性。

**验证：**

```bash
pytest -q tests/integration/test_export.py
```

## PR-08：发布与最终验证

### T21 端到端测试与演示夹具

**目标：** 使用 fake LLM 确定性复现完整核心流程，形成演示和回归凭据。  
**文件：** `tests/fixtures/story_script.json`、`tests/e2e/test_full_journey.py`、`scripts/demo_seed.py`、`README.md`  
**依赖：** PR-06、PR-07  
**预计：** 90 分钟

**演示流程：** 创建 → Bible → 两场景自动生成 → 关键选择 → 用户选择 → 新方向 → 回到旧选择 → 新分支 → 导出。

**步骤：**

- [ ] 编写固定导演、正文、选择和记忆响应脚本。
- [ ] 写完整旅程测试并确认至少一个阶段失败。
- [ ] 补齐最少联调缺口使旅程通过。
- [ ] 加入刷新恢复和幂等断言。
- [ ] 加入跨会话隔离断言。
- [ ] 加入当前分支导出断言。
- [ ] 运行完整旅程 3 次确认结果一致。
- [ ] 保存命令和预期输出到 README 演示章节。

**验证：**

```bash
pytest -q tests/e2e/test_full_journey.py
make test
```

### T22 Docker 分发

**目标：** 在全新环境中通过单次构建和运行启动应用，数据和 Key 不进入镜像。  
**文件：** `Dockerfile`、`.dockerignore`、`docker-compose.example.yml`、`tests/integration/test_container_config.py`、`README.md`  
**依赖：** T18、T21  
**预计：** 60 分钟

**失败测试/检查：** 镜像以非 root 用户运行；只写 `/data`；secret 文件未进入镜像层；健康检查成功。

**步骤：**

- [ ] 写 Docker 配置静态检查测试。
- [ ] 创建多阶段或精简 Dockerfile。
- [ ] 配置非 root 用户、`/data` volume 和健康检查。
- [ ] 编写 `.dockerignore` 排除 Git、数据库、测试缓存和 secret。
- [ ] 创建不含真实 Key 的 compose 示例。
- [ ] 构建镜像并运行健康检查。
- [ ] 检查容器用户和写权限。
- [ ] 在 README 写获取、运行、secret、平台和限制。

**验证：**

```bash
docker build -t storyflow:local .
docker run --rm -p 8000:8000 -v storyflow-data:/data storyflow:local
```

### T23 GitLab CI 与 secret scan

**目标：** 每次 push 自动执行测试、静态检查、密钥扫描和镜像构建。  
**文件：** `.gitlab-ci.yml`、`scripts/secret_scan.py`、`tests/unit/test_secret_scan.py`、`README.md`  
**依赖：** T22  
**预计：** 60 分钟

**失败测试：** 扫描 fixture 中的假 Key 时失败；安全 fixture 通过；CI 明确存在名为 `unit-test` 的 job。

**步骤：**

- [ ] 写 secret scan 的危险/安全 fixture 测试。
- [ ] 实现最小扫描脚本并忽略测试假值白名单。
- [ ] 创建 `.gitlab-ci.yml` 的 `unit-test` job。
- [ ] 增加 lint/typecheck job。
- [ ] 增加镜像 build job。
- [ ] 缓存依赖但不缓存 secret 或数据库。
- [ ] 推送分支并观察首次流水线。
- [ ] 修复 CI 特有问题直至全部通过。
- [ ] 保存最后一次 pass 记录。

**验证：**

```bash
python scripts/secret_scan.py .
make test
```

### T24 部署、README 与最终验收

**目标：** 提供可访问 WebUI，完成所有课程交付与全新机器验证。  
**文件：** `README.md`、`SPEC_PROCESS.md`、`AGENT_LOG.md`、`REFLECTION.md`、`PLAN.md`  
**依赖：** T23  
**预计：** 2～3 小时，不含本人撰写反思的时间

**步骤：**

- [ ] 选择支持容器与 Secret 的部署平台。
- [ ] 用平台 Secret 配置 Key，不在命令或日志中输出。
- [ ] 部署并验证公开健康检查和 WebUI。
- [ ] 用新匿名会话跑一次真实模型核心流程。
- [ ] 从一台干净环境按 README 执行安装和运行。
- [ ] 核对 README 必须章节：简介、安装、运行、分发、目录、安全边界、限制、部署。
- [ ] 核对 `SPEC_PROCESS.md` 的 3 轮迭代和冷启动证据。
- [ ] 核对 `AGENT_LOG.md` 的 task、skill、prompt、commit、人工修改和教训。
- [ ] 由本人撰写 1500～2500 字 `REFLECTION.md`；如 AI 仅润色需标注。
- [ ] 更新本计划全部状态与 commit hash。
- [ ] 确认最后一次 CI/CD 为 pass。
- [ ] 按最终交付清单逐项签字。

**最终验证：**

```bash
make lint
make typecheck
make test
docker build -t storyflow:final .
python scripts/secret_scan.py .
git status --short
```

## 7. 十天执行日历

| 天数 | 目标 | 对应任务 |
| --- | --- | --- |
| Day 1 | 冷启动、修订规约、项目骨架 | CS-01、T01 |
| Day 2 | 领域状态与数据库 | T02、T03 |
| Day 3 | LLM 抽象、Bible、选择策略 | T04、T05、T06 |
| Day 4 | 上下文和生成协调 | T07、T08 |
| Day 5 | 流式接口、幂等恢复 | T09、T10 |
| Day 6 | 选择、分支、故事弧 | T11、T12、T13 |
| Day 7 | 创建页、书架、流式阅读器 | T14、T15 |
| Day 8 | 互动 UI、安全和导出 | T16～T20 |
| Day 9 | E2E、Docker、CI | T21～T23 |
| Day 10 | 部署、全新环境验收、文档 | T24 |

进度控制：若 Day 6 结束时 T10 尚未完成，立即删除人物/伏笔侧栏等 P2；若 Day 8 结束时 T16 尚未完成，保留分支后端与测试但将复杂分支 UI 降级为列表。

## 8. 每个 Task 的标准 subagent 指令模板

```text
你只负责 PLAN.md 中的 <TASK_ID>，工作区为 <WORKTREE_PATH>。

先阅读 SPEC.md 中与该任务相关的章节和 PLAN.md 的任务描述。
不得实现任务范围以外的功能；遇到规约歧义立即暂停提问。

严格执行 TDD：
1. 先写任务列出的失败测试；
2. 运行并展示预期失败；
3. 编写最少实现使其通过；
4. 运行相关回归测试；
5. 仅在测试保持通过时重构。

完成后报告：
- 修改文件；
- 红色测试及其失败原因；
- 绿色测试命令和结果；
- 与 SPEC 的对应关系；
- 未解决风险；
- 建议 commit message。

不要提交真实 API Key，不要自行扩大依赖或修改架构。
```

## 9. 两阶段评审模板

### 第一阶段：SPEC 合规

- 是否只实现本任务范围？
- 是否满足对应用户故事和 AC？
- 是否引入了 SPEC 未声明的行为？
- 边界、错误和安全规则是否落实？
- 是否出现“测试通过但产品语义错误”？

### 第二阶段：代码质量

- 状态与领域逻辑是否保持纯净、可测试？
- 是否存在重复、过度抽象或隐式全局状态？
- 并发、事务、幂等和错误处理是否可靠？
- 日志是否可能泄露 Key、Cookie、Prompt 或正文？
- 测试是否验证行为而非实现细节？
- 命名、类型和目录职责是否清晰？

## 10. 最终交付检查表

- [ ] `SPEC.md`
- [ ] `PLAN.md`，全部任务附 commit hash
- [ ] `SPEC_PROCESS.md`，含至少 3 轮迭代和冷启动 diff
- [ ] `AGENT_LOG.md`
- [ ] 完整源代码和测试
- [ ] README 必须章节齐全
- [ ] Docker 分发产物与安全配置说明
- [ ] `.gitlab-ci.yml` 含 `unit-test` job
- [ ] 最后一次 CI/CD 为 pass
- [ ] 可访问 WebUI URL
- [ ] 1500～2500 字本人反思 `REFLECTION.md`
- [ ] 完整 commit / worktree / PR 历史
- [ ] 无真实凭据和敏感日志

