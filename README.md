# Agent 智能客服系统

基于 **Agent（LLM 自主决策 + 工具调用）** 架构的企业级智能客服系统。LLM 自主判断用户意图——是否查知识库、是否匹配 FAQ、是否追问澄清、是否转人工，彻底告别固定管线模式的局限。

> v3.0.0 从 RAG 固定管线升级为 LangGraph ReAct Agent 模式。v2.x RAG 管线仍可通过 `AGENT_MODE=false` 切换使用。

## ✨ 核心特性

### Agent 智能决策
- **自主工具调用**：LLM 自主决定调用 `search_knowledge_base` / `lookup_faq` / `escalate_to_human`
- **多步推理**：检索不充分时自动优化查询重试，不满足于"搜一次就回答"
- **追问澄清**：用户问题模糊时主动询问细节，而非猜测意图
- **转人工**：投诉/退款/复杂售后自动标记转人工，附问题摘要

### RAG 检索管道
- **五级检索管线**：Query Rewrite → Hybrid Search（向量+BM25）→ Re-ranking → Parent-Child 展开 → LLM 流式生成
- **混合检索**：Dense（语义）+ Sparse（关键词）双路召回 + RRF 融合
- **重排序**：gte-rerank Cross-Encoder 精排，将 Top-20 提炼为 Top-3

### 工程能力
- **用户隔离**：Chroma 按用户分 Collection + SQLite checkpointer 按用户分库 + MySQL WHERE user_id
- **流式对话**：SSE（Server-Sent Events）支持 Agent 事件（token / tool_start / tool_end / thinking）
- **知识库管理**：上传 TXT 文档自动语义分块、MD5 去重、向量化入库
- **RESTful API**：FastAPI 框架，OpenAPI 文档自动生成
- **JWT 认证**：access_token + refresh_token + Redis 黑名单

## 技术栈

| 层级 | 技术 |
|------|------|
| Agent 框架 | LangGraph + LangChain `create_agent` |
| LLM | 通义千问 qwen3-max（DashScope） |
| Embedding | text-embedding-v4（DashScope） |
| Reranker | gte-rerank（DashScope） |
| 向量数据库 | Chroma（本地持久化） |
| 对话持久化 | SQLite（AsyncSqliteSaver，用户隔离） |
| Web 框架 | FastAPI |
| 关系数据库 | MySQL 8.0 |
| 缓存 | Redis 7.x |
| 认证 | JWT + bcrypt |

## 快速开始

### 1. 环境要求

- Python 3.10+
- MySQL 8.0
- Redis 7.x
- 阿里云 DashScope API Key → [获取地址](https://dashscope.console.aliyun.com/)

### 2. 安装

```bash
git clone https://github.com/six-seven67/RAG-LangChain.git
cd RAG-LangChain
pip install -r requirements.txt
```

### 3. 配置

```bash
cp .env.example .env
# 编辑 .env 填入你的配置：
#   DASHSCOPE_API_KEY=你的阿里云APIKey
#   MYSQL_PASSWORD=你的数据库密码
#   JWT_SECRET_KEY=随机生成一个至少32位的密钥
#   AGENT_MODE=true   # true=Agent模式（默认），false=传统RAG
```

### 4. 初始化数据库

```bash
# 方式A：直接导入 SQL
mysql -u root -p < init.sql

# 方式B：Python 自动建表
python -c "import asyncio; from src.db.database import init_db; asyncio.run(init_db())"
```

### 5. 启动

```bash
# 启动 API 服务
uvicorn app.fastapi_server:app --reload --host 0.0.0.0 --port 8000

# 访问 Swagger 文档 → http://localhost:8000/docs

# (可选) 启动 Streamlit 旧版界面
streamlit run app/app_qa.py
```

## API 概览

| 模块 | 端点 | 说明 |
|------|------|------|
| 认证 | `POST /api/auth/register` | 注册 |
| | `POST /api/auth/login` | 登录 |
| | `POST /api/auth/refresh` | 刷新 Token |
| 对话 | `POST /api/chat/stream` | 流式对话（SSE，含 Agent 事件） |
| | `GET /api/chat/sessions` | 会话列表 |
| | `GET /api/chat/history/{id}` | 会话历史 |
| 知识库 | `POST /api/knowledge/upload` | 上传文档 |
| | `GET /api/knowledge/documents` | 文档列表 |

完整 API 文档及前端对接指南 → [docs/API.md](docs/API.md)

## 项目结构

```
RAG/
├── app/                    # Web 应用入口
│   ├── fastapi_server.py   # FastAPI 主入口（v3.0.0 Agent）
│   ├── app_qa.py           # Streamlit 问答界面
│   └── app_file_uploader.py# Streamlit 上传界面
├── src/                    # 核心源码
│   ├── config.py           # 全局配置
│   ├── agent/              # 🆕 Agent 模块（v3.0.0）
│   │   ├── service.py      #   AgentService（create_agent）
│   │   └── tools/          #   工具（一个文件一个工具）
│   │       ├── search_kb.py    # 知识库检索
│   │       ├── escalate.py     # 转人工
│   │       └── faq.py          # FAQ 匹配
│   ├── rag/                # RAG 管道（v2.x 兼容）
│   │   ├── async_service.py    # 异步 RAG 服务
│   │   ├── sync_service.py     # 同步 RAG（遗留）
│   │   └── rewriter.py         # Query Rewrite
│   ├── retrieval/          # 检索引擎（可插拔）
│   │   ├── vector_store.py     # Chroma 向量检索
│   │   ├── bm25.py             # BM25 关键词检索
│   │   ├── hybrid.py           # 混合检索 + RRF 融合
│   │   └── reranker.py         # gte-rerank 重排序
│   ├── knowledge/          # 知识库管理
│   │   ├── service.py          # 文档上传/去重
│   │   └── splitter.py         # 语义分块
│   ├── storage/            # 对话历史存储（可插拔）
│   │   ├── file_store.py       # 文件后端
│   │   └── mysql_store.py      # MySQL 后端
│   ├── api/                # API 路由
│   ├── auth/               # JWT 认证
│   ├── db/                 # 数据库 ORM
│   └── cache/              # Redis 缓存
├── frontend/               # 前端界面（HTML/CSS/JS）
├── data/                   # 持久化数据
│   ├── documents/          #   原始文档
│   ├── chroma/             #   Chroma 向量库
│   ├── chat_history/       #   SQLite 对话历史
│   └── md5.text            #   MD5 去重记录
├── docs/                   # 文档
├── eval/                   # 评估框架
├── run.py                  # 便捷启动入口
├── requirements.txt
├── init.sql
└── .env.example
```

## 架构演进

```
v1.x (MVP)       v2.x (RAG 管线)          v3.0.0 (Agent)
─────────        ──────────────          ─────────────
用户输入          用户输入                 用户输入
  ↓                 ↓                       ↓
向量检索          查询改写             LLM 自主决策
  ↓                 ↓                  ↙    ↓    ↘
LLM 生成          混合检索          查库   FAQ   转人工
  ↓                 ↓                  ↘    ↓    ↙
回答              重排序               综合生成回答
                   ↓
              Parent-Child展开
                   ↓
              LLM 流式生成
```

## 相关文档

- [项目详细介绍](docs/PROJECT.md) — 架构设计、优化清单、技术决策
- [API 对接文档](docs/API.md) — 前端开发必读（含 SSE Agent 事件示例）
- [优化记录](docs/OPTIMIZATION.md) — 7 项核心优化的实施过程与消融实验数据
- [Git 使用指南](docs/GIT_GUIDE.md) — 版本管理操作说明
- [修改日志](docs/CHANGELOG.md) — Bug 修复与代码变更记录（仅本地）

## License

MIT
