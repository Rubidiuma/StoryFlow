# StoryFlow

AI 驱动的中文互动小说生成平台。用户定义世界、主角和文风，AI 持续生成叙事并在关键节点呈现三种选项，每次选择都改变故事走向。

## 特性

- **故事圣经生成** — 基于 LLM 自动生成世界规则、主角核心与初始故事弧
- **流式阅读器** — Server-Sent Events 逐段推送场景内容，无选择时自动续写
- **选择系统** — 预设选项 + 自定义行动，选择效果写入分层记忆
- **分支与回退** — 从任意历史选择创建新分支，原分支完整保留
- **滚动摘要** — 每 5 个场景自动压缩，维持模型上下文预算
- **Markdown 导出** — 按当前分支路径导出，不混入兄弟分支
- **会话隔离** — 匿名会话通过 `X-Session-ID` 头隔离，不同浏览器互不可见
- **速率护栏** — 每会话滑动窗口速率限制；同一分支不允许并发生成

## 快速开始

### 依赖

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) 包管理器

### 安装与运行

```bash
git clone https://github.com/Rubidiuma/PersonalNovel.git
cd PersonalNovel
pip install uv
uv sync --extra dev
UV_CACHE_DIR=.uv-cache uv run uvicorn storyflow.main:app --host 127.0.0.1 --port 8000
```

打开 http://localhost:8000 即可访问书架页面。

### 配置 LLM 密钥

通过环境变量传入（不要写入代码或 git）：

```bash
export STORYFLOW_LLM_KEY=your-api-key-here
```

或使用 secret 文件（更安全）：

```bash
echo "your-api-key-here" > ~/.storyflow_key.txt
# 在代码中传入路径：CredentialProvider(secret_file=Path("~/.storyflow_key.txt"))
```

## 测试

```bash
make test          # 运行所有测试（268 个）
make lint          # Ruff 代码风格检查
make typecheck     # mypy 类型检查
python scripts/secret_scan.py .   # 扫描意外提交的密钥
```

## Docker 分发

```bash
# 构建镜像
docker build -t storyflow:local .

# 运行（数据持久化到 volume）
docker run --rm -p 8000:8000 \
  -v storyflow-data:/data \
  -e STORYFLOW_LLM_KEY=your-key \
  storyflow:local

# 或使用 Compose 示例（需先编辑密钥配置）
cp docker-compose.example.yml docker-compose.yml
# 编辑 docker-compose.yml 配置密钥后：
docker compose up
```

镜像安全特性：
- 以 `storyflow` 非 root 用户运行
- 只有 `/data` 目录可写（挂载为 volume）
- HEALTHCHECK 指向 `/health` 端点
- `.dockerignore` 排除测试、缓存、数据库和 secret 文件

## 目录结构

```
src/storyflow/
├── api/routes/      # FastAPI 路由（web HTML、stories、choices、generation、export）
├── db/              # SQLite 仓储与 schema
├── domain/          # 领域模型与状态机
├── llm/             # LLM 客户端抽象与 Fake 实现
├── prompts/         # 版本化 prompt 模板
├── security/        # 会话隔离、速率限制、凭据、脱敏
├── services/        # 业务逻辑（生成、Bible、导出、分支、记忆）
├── static/          # CSS + JS（书架、创建向导、阅读器）
└── templates/       # Jinja2 HTML 模板
tests/
├── unit/            # 纯函数单元测试
├── integration/     # TestClient + 真实 SQLite 集成测试
└── e2e/             # 完整流程端到端测试
```

## API 速查

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/stories` | 创建故事草稿 |
| POST | `/stories/{id}/bible/generate` | 生成故事圣经 |
| POST | `/stories/{id}/bible/confirm` | 确认圣经 → IDLE |
| POST | `/api/stories/{id}/generate` | SSE 流式生成一个场景 |
| POST | `/api/choices/{id}/select` | 提交预设/自定义选择 |
| POST | `/api/choices/{id}/branch` | 从历史选择创建新分支 |
| GET  | `/api/stories/{id}/export.md` | 导出当前分支 Markdown |
| GET  | `/stories/{id}/reader` | 阅读器页面 |

所有 API 支持通过 `X-Session-ID` 请求头进行会话隔离。

## 安全边界

- LLM 密钥只从 secret 文件或环境变量读取，不写入代码
- 异常响应中的密钥通过 `RedactionFilter` 脱敏
- 不同会话通过 `X-Session-ID` 隔离；无头时向后兼容
- 速率限制防止单会话滥用（默认值见 `config.py`）
- Docker 镜像以非 root 用户运行，secret 文件不进入镜像层

## 限制

- 当前 LLM 后端需自行接入（`llm/provider.py`），开发测试使用 `FakeLLMClient`
- 仅支持单进程部署（并发控制基于进程内锁）
- 速率限制为内存存储，重启后重置
- 不支持多用户账号系统，仅匿名会话隔离

## 部署

参见 `docker-compose.example.yml` 及上方 Docker 章节。推荐在支持容器的平台（Railway、Fly.io、Render 等）上通过 Secret 管理器注入 LLM 密钥，避免环境变量出现在日志中。

---

*本项目为课程作业，使用 Claude Code + Codex 协作完成，详见 `AGENT_LOG.md` 和 `COLLABORATION.md`。*
