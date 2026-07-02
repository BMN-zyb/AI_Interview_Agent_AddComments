# InterviewAgent 手敲路线图（plan.md）

> 目标：把这套**工程级 AI 模拟面试官**从零手敲一遍，边敲边读懂。本文件给出**最优敲码顺序**——严格按依赖自底向上、并贴合 README 的「三层架构 / 八大亮点」叙事，让每敲完一层都能**立刻自检**。
>
> 用法：新建一个空目录作练习工程（下记 `$DST`），把**当前目录**当参考答案。每敲完一个文件，`diff` 比对自查（忽略行尾空白）：
> ```bash
> diff <(sed 's/[[:space:]]*$//' "$DST/config/settings.py") \
>      <(sed 's/[[:space:]]*$//'  config/settings.py)   # 无输出=一致
> ```

---

## 一、两条铁律（先读，否则会卡）

### 🔑 铁律 1：`.env` 里必须有 `DASHSCOPE_API_KEY`，否则**任何 import 都失败**

[config/settings.py](config/settings.py) 里 `dashscope_api_key: str = Field(...)` 是**必填字段**，且文件末尾 `settings = get_settings()` 在**模块导入时**就构造单例。任何模块只要（间接）`from config import settings`，缺这个 key 就直接 import 崩溃。

- **Tier A 离线导入自检**：只要 `.env` 里给 `DASHSCOPE_API_KEY` 一个**占位值**（如 `sk-placeholder`），import 就能通过——它是 `str` 字段，导入时**不校验真伪**。其余 MySQL/Redis/Weaviate/GitHub 字段都有默认值，不缺就不报错。
- **Tier B 联机运行**：真正跑 LLM/检索/记忆时，才需要**真实 key + 对应服务**。

### 🔌 铁律 2：连接都是惰性的 → 全项目可先离线敲完再上服务

所有外部连接（Weaviate `get_weaviate_client()`、Redis、MySQL、LLM）都写在**函数/方法里**，不在模块顶层。所以：

> **你可以只用一个占位 `.env`、不装任何 MySQL/Redis/Weaviate/模型，就把整套 Python 手敲完并逐文件 `python -c "import X"` 自检。** 外部服务留到需要「真跑」的阶段（8–12，或你想提前联机的任意子系统）再拉起。

**两级自检贯穿全程**：
| 级别 | 需要什么 | 命令样例 | 验证了什么 |
|---|---|---|---|
| **A · 离线导入** | 占位 `.env` | `cd $DST && python -c "import rag; print('ok')"` | 语法 + import 接线正确 |
| **B · 联机运行** | 真实 key + 对应服务 | 见各阶段 | 逻辑真的能跑 |

---

## 二、外部服务与「真跑」时机

| 服务 | 谁需要它（Tier B） | 何时装 |
|---|---|---|
| **DashScope key（真实）** | agents / rag(embedding) / reranker / skills / 编排 / 全部 LLM | 想联机验证 Agent 时（Phase 2 起） |
| **Weaviate** | rag 向量检索 / indexer / query_engine | Phase 3 想真跑检索时 |
| **Redis** | memory 短期记忆 | Phase 4 |
| **MySQL** | memory 长期记忆 / init_db | Phase 4 |
| **faster-whisper / CosyVoice / ffmpeg**（重、可选） | audio STT/TTS | Phase 6（可跳过，不影响主流程） |
| **GitHub Token**（可选） | mcp github_tool | Phase 7（可跳过） |

> 建议：**先用占位 `.env` 把 Phase 0–8 全部手敲 + Tier A 自检过一遍**（零服务、最省心）；然后按 [scripts/check_env.py](scripts/check_env.py) 的清单拉起服务、换上真实 key，再从想联机的阶段做 Tier B。

**不要手敲**：`images/`（截图）、`rag/knowledge_base/knowledge/*.md`（示例语料，直接拷）、`.venv/`、各 `__pycache__/`、`.pytest_cache/`、模型权重。

---

## 三、依赖分层（箭头 = 依赖；★=README 重点文件）

```
config/settings.py ★  ← 根：必填 DASHSCOPE_API_KEY，import 时即建单例
     │  └─ config/logging.py ──► config/__init__.py（导出 settings / setup_logger）
     ▼
agents/base_agent.py ★  ← Agent 基类(LLM调用)；被 8Agent + skills + rag.reranker 共同依赖
     ├─ agents/{intent_router,jd_analyzer,resume_analyzer,question_planner,
     │          interviewer,evaluator,study_planner,chat_agent}(×8) ─► agents/__init__.py
     ├─ skills/base_skill ─► {quiz,teach,compare,project} ─► skill_registry ─► skills/__init__
     └─ rag/reranker ★
   rag/retrievers:  vector(config) · bm25(纯Python,可离线单测) ─► hybrid ─► retrievers/__init__
          indexer(config+vector) ·  query_engine ★(reranker+hybrid) ─► rag/__init__
          evaluator: metrics ─► rag_evaluator ─► topk_experiment ─► evaluator/__init__
   memory:  models ─► short_term(Redis) · long_term(MySQL,+models) ─► memory_manager ─► __init__
   audio:   audio_manager ─► stt(+manager) · tts(config) ─► audio/__init__
   mcp:     mcp_client · tools/github_tool(config) · tools/web_scraper(audio+memory+graph惰性)
     ▼
orchestration:  state ─► difficulty_fsm(config) ★
     nodes ★(顶层依赖 agents+state；惰性依赖 rag/memory/skills/fsm) ─► edges(state) ─►
     graph ★(edges+nodes+state) ─► orchestration/__init__     ← DAG 大脑，整合全栈
     ▼
api:  schemas · middleware · routers{health,upload★,interview★,websocket★} ─► main ★
cli/main.py ★（typer 入口，惰性驱动 graph/memory/indexer）
frontend:  index.html ★ + static/css/style.css + static/js/main.js ★（消费 API/WS 契约）
```

### 阶段一览

| 阶段 | 主题（README 亮点） | 关键文件（约行） | Tier B 需要 |
|---|---|---|---|
| 0 | 脚手架 + 占位 .env | 目录树 / pyproject / requirements / **.env(占位 key)** / 空 `__init__` | — |
| 1 | 配置中心 | settings(129)·logging(68)·__init__ + check_env(133) | — |
| 2 | ①多 Agent | base_agent(171) + 8 个 Agent(42~348) + __init__ | DashScope |
| 3 | ②③ RAG | retrievers(vector102/bm25133/hybrid105)·reranker(116)·indexer(156)·query_engine(53)·evaluator(metrics96/rag_evaluator117/topk82) + build_index | Weaviate+key |
| 4 | ④ 记忆 | models(82)·short_term(215)·long_term(242)·memory_manager(208) + init_db | Redis+MySQL |
| 5 | ⑥ 技能 | base_skill(66)·quiz(219)·teach(75)·compare(128)·project(111)·registry(63) | DashScope |
| 6 | ⑧ 语音 | audio_manager(167)·stt(387)·tts(226) | whisper/CosyVoice(可选) |
| 7 | ⑦ MCP | mcp_client(136)·github_tool(229)·web_scraper(506) | GitHub Token(可选) |
| 8 | ⑤ 难度FSM + DAG 编排 | state(90)·difficulty_fsm(76)·nodes(236)·edges(77)·graph(151) | 全栈 |
| 9 | Web API | schemas(124)·middleware(68)·routers{health22,upload123,interview235,websocket850}·main(90) | 全栈 |
| 10 | CLI 入口 | cli/main.py(713) | 全栈 |
| 11 | 前端 | index.html(298)·style.css(517)·main.js(1314) | 全栈 |
| 12 | 拉服务 + 端到端 + 测试 | start_services.sh · tests/* | 全栈 |

---

## 四、分阶段详解

### 阶段 0 · 脚手架 + 占位 .env

- 建目录（与参考项目同构）：
  ```
  agents/ api/routers/ audio/ cli/ config/ frontend/static/css frontend/static/js
  mcp/tools/ memory/ orchestration/ rag/evaluator rag/retrievers rag/knowledge_base/knowledge
  scripts/ skills/ tests/
  ```
- 抄散文件：[pyproject.toml](pyproject.toml)、[requirements.txt](requirements.txt)、[requirements-dev.txt](requirements-dev.txt)、[.gitignore](.gitignore)、[alembic.ini](alembic.ini)。
- **建 `.env`（关键）**：`cp .env.example .env`，把 `DASHSCOPE_API_KEY` 填成**占位值**（如 `sk-placeholder`）即可解锁全部 Tier A 自检；其余保持默认。真实 key 到联机阶段再换。
- 建**空** `__init__.py`（占位让 import 成立，真实内容到各自阶段/末尾再敲）：`agents/ api/ api/routers/ audio/ cli/ config/ mcp/ mcp/tools/ memory/ orchestration/ rag/ rag/evaluator/ rag/retrievers/ skills/`。
- 拷示例语料：`rag/knowledge_base/knowledge/*.md`（Phase 3 建索引用）。
- venv：`python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`。

**Tier A**：`cd $DST && python -c "print('scaffold ok')"`。

> ⚠️ **facade `__init__` 顺序**：`config/__init__` 要导出 `settings`（几乎所有模块靠 `from config import settings`）→ 必须在 settings.py **之后**填内容；`agents/__init__` 在 8 个 Agent 之后；`skills/skill_registry` 在 4 个 skill 之后；`rag/__init__`、`orchestration/__init__` 都在其内部模块之后。**Phase 0 先留空，到位后再填。**

---

### 阶段 1 · 配置中心 config（settings → logging → __init__）

| 文件 | 行 | 作用 | 依赖 |
|---|---|---|---|
| [config/settings.py](config/settings.py) | 129 | `Settings`（pydantic-settings 读 .env）+ `settings` 单例；LLM/DB/Redis/Weaviate/RAG/FSM 全量配置 | 仅 pydantic |
| [config/logging.py](config/logging.py) | 68 | `setup_logger`（loguru），读 `settings.log_level` | config.settings |
| `config/__init__.py` | 小 | 导出 `settings` + `setup_logger` | logging, settings |
| [scripts/check_env.py](scripts/check_env.py) | 133 | 环境体检：Python/依赖/.env/MySQL/Redis/Weaviate/DashScope 连通性——**贯穿全程的诊断工具，先敲** | — |

**Tier A**：`python -c "from config import settings; print(settings.llm_model, settings.rag_top_k)"`
**Tier B（可选）**：`python scripts/check_env.py`（先看哪些服务已就绪，规划后续联机节奏）。

---

### 阶段 2 · Agent 基石 + 八大 Agent（README 亮点①）

先敲基类，再敲 8 个专职 Agent（都只依赖 base_agent），最后填 `agents/__init__`。

| 顺序 | 文件 | 行 | 职责 |
|---|---|---|---|
| 1 | [agents/base_agent.py](agents/base_agent.py) ★ | 171 | Agent 基类：统一 LLM 调用能力（被 8Agent + skills + rag.reranker 依赖）|
| 2 | [agents/chat_agent.py](agents/chat_agent.py) | 42 | 闲聊/降级对话（最简，适合先热身）|
| 3 | [agents/intent_router.py](agents/intent_router.py) | 113 | 意图识别与路由 |
| 4 | [agents/jd_analyzer.py](agents/jd_analyzer.py) | 104 | JD 解析（技术栈/职级）|
| 5 | [agents/resume_analyzer.py](agents/resume_analyzer.py) | 98 | 简历匹配画像 |
| 6 | [agents/question_planner.py](agents/question_planner.py) | 122 | 题目分布规划 |
| 7 | [agents/study_planner.py](agents/study_planner.py) | 204 | 复习计划生成 |
| 8 | [agents/evaluator.py](agents/evaluator.py) ★ | 228 | 逐题打分 + 报告 |
| 9 | [agents/interviewer.py](agents/interviewer.py) ★ | 348 | 面试主控（出题+追问，最复杂，压轴）|
| 10 | `agents/__init__.py` | 36 | 汇出 8 个 Agent（`orchestration.nodes` 靠它）|

**Tier A**：`python -c "import agents; print('agents ok')"`
**Tier B**：`python -m pytest tests/test_agents.py`（测 intent_router + jd_analyzer，需真实 key）。也可写个 3 行脚本让 `chat_agent` 回一句话做 LLM 冒烟。

---

### 阶段 3 · RAG 检索系统（README 亮点②③）

顺序：检索器 → 重排 → 索引/查询引擎 → 评估。**bm25_retriever 与 metrics 是纯 Python、可离线单测**，是本阶段的早期确定性胜利。

| 顺序 | 文件 | 行 | 作用 | 依赖 |
|---|---|---|---|---|
| 1 | [rag/retrievers/vector_retriever.py](rag/retrievers/vector_retriever.py) ★ | 102 | Weaviate 向量检索 + `get_weaviate_client()` | config |
| 2 | [rag/retrievers/bm25_retriever.py](rag/retrievers/bm25_retriever.py) ★ | 133 | BM25 关键词检索（**纯 Python，可离线跑**）| — |
| 3 | [rag/retrievers/hybrid_retriever.py](rag/retrievers/hybrid_retriever.py) ★ | 105 | RRF 融合双路 | config, bm25, vector |
| 4 | `rag/retrievers/__init__.py` | 小 | 汇出 3 检索器 | 上面三者 |
| 5 | [rag/reranker.py](rag/reranker.py) ★ | 116 | LLM 精排 | agents.base_agent |
| 6 | [rag/indexer.py](rag/indexer.py) ★ | 156 | 建向量+BM25 索引 | config, vector（+惰性 bm25）|
| 7 | [rag/query_engine.py](rag/query_engine.py) ★ | 53 | RAG 查询入口（检索→融合→精排）| reranker, hybrid |
| 8 | `rag/__init__.py` | 小 | 汇出 query_engine | query_engine |
| 9 | [rag/evaluator/metrics.py](rag/evaluator/metrics.py) | 96 | 三维指标定义（**纯逻辑，可离线**）| — |
| 10 | [rag/evaluator/rag_evaluator.py](rag/evaluator/rag_evaluator.py) ★ | 117 | 忠实/相关/完整 评估 | metrics, query_engine |
| 11 | [rag/evaluator/topk_experiment.py](rag/evaluator/topk_experiment.py) | 82 | TopK 调优实验 | rag_evaluator, query_engine |
| 12 | `rag/evaluator/__init__.py` | 小 | 汇出 rag_evaluator | rag_evaluator |
| 13 | [scripts/build_index.py](scripts/build_index.py) | 24 | CLI 建索引 | rag.indexer |

**Tier A**：`python -c "import rag; import rag.evaluator; print('rag ok')"`
**Tier B**：先离线单测纯 Python 部分 → `python -m pytest tests/test_rag.py`（含 bm25/metrics 可无 Weaviate 跑的用例）；再拉起 Weaviate → `python scripts/build_index.py` → 用 [tests/show_weaviate.py](tests/show_weaviate.py) 看入库结果。

---

### 阶段 4 · 记忆系统 memory（README 亮点④）

| 顺序 | 文件 | 行 | 作用 | 依赖 |
|---|---|---|---|---|
| 1 | [memory/models.py](memory/models.py) | 82 | SQLAlchemy ORM（用户画像/面试记录）| 仅 sqlalchemy |
| 2 | [memory/short_term.py](memory/short_term.py) ★ | 215 | Redis 短期记忆（会话窗口 + 24h TTL）| config |
| 3 | [memory/long_term.py](memory/long_term.py) ★ | 242 | MySQL 长期记忆（画像/薄弱点）| config, models |
| 4 | [memory/memory_manager.py](memory/memory_manager.py) ★ | 208 | 统一管理器（惰性组合短期/长期）| （惰性）short_term/long_term/models |
| 5 | `memory/__init__.py` | 小 | 汇出 `memory_manager` | memory_manager |
| 6 | [scripts/init_db.py](scripts/init_db.py) | 24 | 建 MySQL 表 | memory.long_term |

**Tier A**：`python -c "import memory; print('memory ok')"`
**Tier B**：拉起 Redis+MySQL → `python scripts/init_db.py` → `python -m pytest tests/test_memory.py`。

---

### 阶段 5 · 技能系统 skills（README 亮点⑥）

基类 → 4 个 skill → 注册中心。均基于 `agents.base_agent`（已就绪）。

| 顺序 | 文件 | 行 | 作用 |
|---|---|---|---|
| 1 | [skills/base_skill.py](skills/base_skill.py) | 66 | Skill 基类（有状态多轮）|
| 2 | [skills/quiz_skill.py](skills/quiz_skill.py) ★ | 219 | 问答测验（有状态，最典型，先敲）|
| 3 | [skills/teach_skill.py](skills/teach_skill.py) | 75 | 教学讲解 |
| 4 | [skills/compare_skill.py](skills/compare_skill.py) | 128 | 技术对比 |
| 5 | [skills/project_skill.py](skills/project_skill.py) | 111 | 项目亮点（STAR）|
| 6 | [skills/skill_registry.py](skills/skill_registry.py) | 63 | 注册中心（汇总 4 skill）|
| 7 | `skills/__init__.py` | 小 | 汇出 `skill_registry` |

**Tier A**：`python -c "from skills.skill_registry import skill_registry; print(list(skill_registry.list() if hasattr(skill_registry,'list') else skill_registry.__dict__))"`（能列出 4 个 skill 即可，具体接口以源码为准）。

---

### 阶段 6 · 语音系统 audio（README 亮点⑧，可选/较重）

只依赖 config，可提前也可延后；因被 websocket / web_scraper 消费，放在 MCP/API 之前。

| 顺序 | 文件 | 行 | 作用 | 依赖 |
|---|---|---|---|---|
| 1 | [audio/audio_manager.py](audio/audio_manager.py) | 167 | 音频流统一管理 | —（外部库）|
| 2 | [audio/stt.py](audio/stt.py) ★ | 387 | faster-whisper 语音转文字 | audio_manager |
| 3 | [audio/tts.py](audio/tts.py) ★ | 226 | CosyVoice 文字转语音 | config |
| 4 | `audio/__init__.py` | 小 | 汇出 manager/stt/tts | 上面三者 |

**Tier A**：`python -c "import audio"`（**前提是 faster-whisper 等库已装**；未装可跳过，不影响主面试流程）。
**Tier B**：装 ffmpeg + 模型后做一次 STT/TTS 冒烟。

---

### 阶段 7 · MCP 工具（README 亮点⑦，可选）

| 顺序 | 文件 | 行 | 作用 | 依赖 |
|---|---|---|---|---|
| 1 | [mcp/mcp_client.py](mcp/mcp_client.py) ★ | 136 | MCP 客户端（工具调用入口）| 外部 mcp 库 |
| 2 | [mcp/tools/github_tool.py](mcp/tools/github_tool.py) ★ | 229 | GitHub 项目分析工具 | config |
| 3 | [mcp/tools/web_scraper.py](mcp/tools/web_scraper.py) | 506 | 网页抓取工具 | audio.stt/tts, memory.memory_manager（+惰性 graph）|
| 4 | `mcp/tools/__init__.py` · `mcp/__init__.py` | 小 | 汇出 | mcp_client |

> 💡 **提示（README 注明「代码部分由 AI 生成」）**：[web_scraper.py](mcp/tools/web_scraper.py) 顶部竟 import 了 `audio.stt/tts` 与 `memory.memory_manager`（与 websocket 雷同，疑似模板复制残留）。**照抄即可、不要改**；这也是它必须排在 audio+memory 之后的原因。

**Tier A**：`python -c "import mcp"`（web_scraper 需 audio 库在场）。

---

### 阶段 8 · 难度 FSM + DAG 编排（README 亮点⑤ + 大脑）

顺序：叶子(state/fsm) → 节点 → 边 → 图。`nodes` 顶层只依赖 `agents`+`state`，但**惰性调用 rag/memory/skills/fsm**——所以放在全部能力层就绪之后，才能真跑。

| 顺序 | 文件 | 行 | 作用 | 依赖 |
|---|---|---|---|---|
| 1 | [orchestration/state.py](orchestration/state.py) ★ | 90 | 全局 `InterviewState`（DAG 共享状态）| —（TypedDict）|
| 2 | [orchestration/difficulty_fsm.py](orchestration/difficulty_fsm.py) ★ | 76 | 三级难度状态机 | config |
| 3 | [orchestration/nodes.py](orchestration/nodes.py) ★ | 236 | 各阶段节点（route/rag_retrieve/ask/evaluate/report/...）| agents,state（+惰性 rag/memory/skills/fsm）|
| 4 | [orchestration/edges.py](orchestration/edges.py) | 77 | 流转规则 | state |
| 5 | [orchestration/graph.py](orchestration/graph.py) ★ | 151 | LangGraph StateGraph 主图 + `get_compiled_graph()` | edges, nodes, state |
| 6 | `orchestration/__init__.py` | 小 | 汇出 graph | graph |

**Tier A**：`python -c "from orchestration.graph import get_compiled_graph; g=get_compiled_graph(); print('graph compiled')"`（编译成功即证明全栈 import 接线通）。
**Tier B**：备齐服务+真实 key，用一个最小 state 走一遍 `route → jd_analyze` 或 `chat` 分支。

---

### 阶段 9 · Web API 层（FastAPI）

顺序：数据结构 → 中间件 → 各路由（由简到繁）→ 装配 main。`websocket.py` 850 行是全项目最大文件，整合 audio+memory+orchestration，压轴。

| 顺序 | 文件 | 行 | 作用 | 依赖 |
|---|---|---|---|---|
| 1 | [api/schemas.py](api/schemas.py) | 124 | 请求/响应 Pydantic 模型 | 仅 pydantic |
| 2 | [api/middleware.py](api/middleware.py) | 68 | 日志/鉴权中间件 | —（config）|
| 3 | [api/routers/health.py](api/routers/health.py) | 22 | 健康检查 | schemas |
| 4 | [api/routers/upload.py](api/routers/upload.py) ★ | 123 | 简历/JD 上传 | schemas |
| 5 | [api/routers/interview.py](api/routers/interview.py) ★ | 235 | 面试核心 REST | schemas, memory_manager（+惰性 graph）|
| 6 | [api/routers/websocket.py](api/routers/websocket.py) ★ | 850 | 实时面试 WS（语音+多轮）| audio.stt/tts, memory_manager（+惰性 graph/nodes）|
| 7 | `api/routers/__init__.py` | 15 | 汇出路由 | 上面路由 |
| 8 | [api/main.py](api/main.py) ★ | 90 | FastAPI 应用装配 + 挂载 | middleware, routers, config.logging |
| 9 | `api/__init__.py` | 小 | 包导出 | — |

**Tier A**：`python -c "from api.main import app; print(len(app.routes),'routes')"`
**Tier B**：`uvicorn api.main:app --port 8000` → 开 `/docs`、`GET /api/health`、`POST /api/interview/start`。

---

### 阶段 10 · CLI 入口

- [cli/main.py](cli/main.py) ★（713）：typer 命令行，惰性驱动 `orchestration.graph` / `memory_manager` / `rag.indexer`；提供 `interview`（本地面试）与 `serve`（起 Web）子命令。

**Tier A**：`python -c "import cli.main"` / `python -m cli.main --help`
**Tier B**：`python -m cli.main interview --jd "..." --resume ./resume.pdf --total 5`（需全栈 + 真实 key）。

---

### 阶段 11 · 前端

顺序：结构 → 样式 → 交互（`main.js` 1314 行，含 WebSocket/摄像头/语音，压轴）。依赖后端 API/WS 契约，故最后敲。

| 顺序 | 文件 | 行 | 作用 |
|---|---|---|---|
| 1 | [frontend/index.html](frontend/index.html) ★ | 298 | 面试 Web UI |
| 2 | [frontend/static/css/style.css](frontend/static/css/style.css) | 517 | 样式 |
| 3 | [frontend/static/js/main.js](frontend/static/js/main.js) ★ | 1314 | 前端交互（WS/摄像头/STT/TTS 对接）|

**Tier B**：`python -m cli.main serve --port 8000` → 浏览器开 `http://localhost:8000` 走一遍完整面试（可选语音+摄像头）。

---

### 阶段 12 · 拉服务 + 端到端 + 测试收尾

- [scripts/start_services.sh](scripts/start_services.sh)（30）/ `start_services_on3090.sh`（47）：一键拉起依赖。
- 备齐 MySQL+Redis+Weaviate、换真实 `DASHSCOPE_API_KEY` → `python scripts/check_env.py` 全绿。
- 全量测试：`python -m pytest`（`tests/test_agents|test_rag|test_memory|test_api`；**注意这些是需要真实服务/Key 的集成测试，不是离线 stub**）。
- 端到端：CLI 跑一场 5 题面试；或 Web 模式跑完整流程看评估报告。

---

## 五、收尾自查清单

- [ ] 占位 `.env` 下，**每个包都能 `python -c "import <pkg>"`**（Tier A 全过）——证明 11k 行的 import 接线零错。
- [ ] `from orchestration.graph import get_compiled_graph; get_compiled_graph()` 能编译（全栈接线通）。
- [ ] 换真实 key + 服务后 `scripts/check_env.py` 全绿。
- [ ] CLI 能跑完一场面试并出报告；`/docs` 可见、`/api/health` 绿。
- [ ] 逐文件 `diff` 与原件零差异（或仅空白差异）。
- [ ] 读懂 README「面试流程 DAG」如何由 `state`+`nodes`+`edges`+`graph` 四件套落地。

## 六、给手敲者的三点提醒

1. **先离线、后联机**：用占位 key 把 Phase 0–8 敲完 + Tier A 过一遍，最省心；服务留到真跑再拉起（惰性连接允许这么做）。
2. **facade `__init__` 最后填**：`config/agents/skills/rag/orchestration/memory/audio/mcp` 的 `__init__.py`（尤其汇出型）在其内部模块齐了之后再补内容，Phase 0 先留空。
3. **AI 生成的小瑕疵照抄不改**：如 [web_scraper.py](mcp/tools/web_scraper.py) 的多余 import——本练习目标是「敲一遍读懂」，忠实复刻即可；真要重构留到之后。
