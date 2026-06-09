# Agent 智能客服系统 — 项目介绍

## 一、项目概述

基于 **Agent（LLM 自主决策 + 工具调用）** 架构的智能客服系统。LLM 通过 ReAct 模式自主判断用户意图——是否查知识库、是否匹配 FAQ、是否追问澄清、是否转人工——彻底告别固定管线"所有问题走同一条路"的局限。

**核心价值**：让 AI 成为真正的"智能客服 agent"，而非简单的"搜索+生成"管道。

> v3.0.0 新增 Agent 模式。v2.x 的传统 RAG 固定管线仍可通过环境变量 `AGENT_MODE=false` 切换使用。

## 二、技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| Agent 框架 | **LangGraph + LangChain `create_agent`** | ReAct Agent，LLM 自主决策 |
| 对话持久化 | **SQLite (AsyncSqliteSaver)** | 每用户一个 DB，含 tool 消息 |
| LLM 模型 | 通义千问 qwen3-max（DashScope API） | 原生支持 function calling |
| Embedding | text-embedding-v4（DashScope API） | 文本向量化 |
| Reranker | gte-rerank（DashScope API） | Cross-Encoder 精排 |
| 向量数据库 | Chroma（本地持久化） | 文档向量存储 |
| Web 框架 | **FastAPI**（新）+ Streamlit（保留） | RESTful API + 旧版 UI |
| 前端 | **原生 HTML/CSS/JS**（零框架依赖） | SPA 路由 + SSE 流式 |
| 关系数据库 | **MySQL 8.0** | 用户/会话/文档元数据 |
| 缓存 | **Redis 7.x** | JWT 黑名单 / 查询缓存 / 限流 |
| 认证 | **JWT（PyJWT + bcrypt）** | access_token + refresh_token |
| 分词 | jieba | BM25 中文分词 |

## 三、系统架构

### 3.1 Agent 模式（v3.0.0，当前默认）

```
┌──────────────────────────────────────────────────────────────────┐
│                         客户端层                                   │
│   ┌──────────┐  ┌──────────────┐  ┌─────────────┐               │
│   │ 浏览器    │  │  Streamlit   │  │ 第三方应用    │               │
│   │ (新前端)  │  │  (兼容保留)   │  │ (API 调用)   │               │
│   └─────┬─────┘  └──────┬───────┘  └──────┬──────┘               │
│         │               │                 │                       │
├─────────┼───────────────┼─────────────────┼───────────────────────┤
│         ▼               ▼                 ▼                       │
│   ┌─────────────────────────────────────────────────────────┐    │
│   │                  FastAPI 网关层                           │    │
│   │  • JWT 认证中间件  • CORS  • 限流  • 黑名单校验          │    │
│   └──────────────────────────┬──────────────────────────────┘    │
│                              │                                    │
│         ┌────────────────────┼────────────────────┐              │
│         ▼                    ▼                    ▼              │
│   ┌──────────┐    ┌──────────────┐    ┌──────────────────┐      │
│   │ 认证服务  │    │ Agent 引擎   │    │  知识库管理        │      │
│   │ JWT+bcrypt│    │ (AgentService)│   │  (KnowledgeBase)  │      │
│   └─────┬─────┘    └──────┬───────┘    └────────┬─────────┘      │
│         │                 │                     │                 │
│         │          ┌──────┴───────┐              │                 │
│         │          │  Agent 循环   │              │                 │
│         │          │ ┌──────────┐ │              │                 │
│         │          │ │ LLM 决策  │ │              │                 │
│         │          │ │  ↙  ↓  ↘ │ │              │                 │
│         │          │ │ 查库 FAQ 转人工│           │                 │
│         │          │ └──────────┘ │              │                 │
│         │          └──────────────┘              │                 │
├─────────┼─────────────────┼─────────────────────┼─────────────────┤
│         ▼                 ▼                     ▼                 │
│   ┌─────────────────────────────────────────────────────────┐    │
│   │                      数据层                               │    │
│   │  ┌──────────┐  ┌──────────┐  ┌────────────────────┐     │    │
│   │  │  MySQL   │  │  Redis   │  │  Chroma + SQLite   │     │    │
│   │  │ 用户/会话 │  │ 缓存/黑名单│  │  向量库 + 对话历史  │     │    │
│   │  └──────────┘  └──────────┘  └────────────────────┘     │    │
│   └─────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

### 3.2 Agent 决策流程

```
用户消息
  │
  ▼
┌─────────────────┐
│ LLM 分析意图     │  「这是知识性问题 / 闲聊 / 投诉？」
└────────┬────────┘
         │
    ┌────┼────┐
    ▼    ▼    ▼
  查库  FAQ  闲聊/转人工
    │    │     │
    ▼    ▼     ▼
  检索  匹配  直接回复
    │    │
    ▼    ▼
┌─────────────────┐
│ 检索结果判断     │  信息充分？ → 回答
│                 │  信息不足？ → 追问 or 转人工
└────────┬────────┘
         ▼
    流式输出回答
    (含 tool_start / tool_end SSE 事件)
```

### 3.3 RAG 检索链路（Agent 工具 `search_knowledge_base` 内部）

```
用户查询
  │
  ▼
┌─────────────────┐
│ ① Query Rewrite  │  LLM 改写短查询、消解指代词
└────────┬────────┘
         ▼
┌─────────────────┐
│ ② Hybrid Search  │  向量检索 Top-20 + BM25 Top-20 → RRF 融合
└────────┬────────┘
         ▼
┌─────────────────┐
│ ③ Re-ranking     │  gte-rerank Cross-Encoder 精排 → Top-3
└────────┬────────┘
         ▼
┌─────────────────┐
│ ④ Parent-Child   │  子块精确命中 → 父块完整展开 → 去重
└────────┬────────┘
         ▼
┌─────────────────┐
│ ⑤ 格式化返回     │  返回 top-5 文档给 LLM
└─────────────────┘
```

## 四、Agent 工具

| 工具 | 功能 | 触发场景 |
|------|------|---------|
| `search_knowledge_base` | 封装完整 RAG 检索管道（改写→混合检索→重排序→Parent-Child展开），返回 top-5 文档 | 产品/服务/知识性问题 |
| `lookup_faq` | 高频常见问题快速关键词匹配（营业时间、退换货、发货、支付、发票等 8 类） | FAQ 命中的常见问题 |
| `escalate_to_human` | 标记会话转人工，附带问题摘要 | 投诉、退款、复杂售后 |

### Agent System Prompt 核心行为准则

1. **知识库优先**：产品/服务/知识性问题必须先检索再回答
2. **FAQ 快速匹配**：高频常见问题优先用 lookup_faq
3. **不编造信息**：知识库和 FAQ 都没有的信息，明确告知不知道
4. **追问澄清**：问题模糊或不完整时，先追问再检索
5. **转人工**：投诉/退款/复杂售后等超出知识库范围的问题转人工
6. **简洁专业**：回答简洁明了，分点列出，语气友好

## 五、用户隔离方案

| 隔离层面 | 实现方式 | 说明 |
|---------|---------|------|
| **知识库** | Chroma 按用户分 Collection | `rag_user_{user_id}` 物理隔离 |
| **对话历史（Agent）** | SQLite 按用户分 DB | `chat_history/checkpoints_agent_user_{user_id}.db` |
| **对话历史（MySQL）** | `chat_history` 表 `WHERE user_id = ?` | 用于 API 查询和前端展示 |
| **文档元数据** | MySQL `knowledge_docs` 表 `user_id` 字段 | 用户级 MD5 去重 |
| **API 层** | JWT 认证 + `get_current_user` 依赖注入 | 全局注入 user_id |

## 六、目录结构

```
RAG/
├── app/
│   ├── fastapi_server.py      # FastAPI 主入口（v3.0.0 Agent 智能客服）
│   ├── app_qa.py              # Streamlit 问答 UI（保留）
│   └── app_file_uploader.py   # Streamlit 上传 UI（保留）
├── src/
│   ├── agent/                 # 🆕 Agent 模块（v3.0.0）
│   │   ├── __init__.py        #   模块入口
│   │   ├── tools.py           #   Agent 工具（search / faq / escalate）
│   │   └── service.py         #   AgentService（create_agent + AsyncSqliteSaver）
│   ├── config_data.py         # 全局配置（含 Agent 配置）
│   ├── rag_async.py           # 异步 RAG 服务（v2.x 兼容保留）
│   ├── rag.py                 # 同步 RAG 服务（兼容保留）
│   ├── hybrid_retriever.py    # 混合检索（向量 + BM25 → RRF）
│   ├── bm25_retriever.py      # BM25 关键词检索器
│   ├── vector_stores.py       # Chroma 向量库（支持自定义 collection）
│   ├── reranker.py            # gte-rerank 重排序
│   ├── query_rewriter.py      # LLM 查询改写
│   ├── knowledge_base.py      # 知识库管理（支持自定义 collection）
│   ├── semantic_splitter.py   # 语义分块器
│   ├── file_history_store.py  # 文件对话历史（兼容保留）
│   ├── history_store_mysql.py # MySQL 对话历史存储
│   ├── db/                    # 数据库模块
│   │   ├── database.py        # SQLAlchemy async engine
│   │   └── models.py          # ORM 模型
│   ├── auth/                  # 认证模块
│   │   ├── jwt_handler.py     # JWT 生成/验证
│   │   ├── security.py        # bcrypt + get_current_user
│   │   └── schemas.py         # Pydantic 模型
│   ├── cache/                 # 缓存模块
│   │   └── redis_client.py    # Redis 连接 + 黑名单 + 限流
│   └── api/                   # API 路由
│       ├── auth.py            # 认证端点
│       ├── chat.py            # 对话端点（Agent SSE 事件增强）
│       ├── knowledge.py       # 知识库端点
│       └── user.py            # 用户端点
├── frontend/                  # 🆕 前端界面（SPA）
│   ├── index.html             #   入口
│   ├── css/style.css          #   全局样式
│   └── js/                    #   JS 模块（api/router/auth/chat/knowledge/profile/app）
├── eval/
│   ├── rag_evaluation.py      # 消融实验评估框架
│   └── eval_report_quick.md   # 评估报告
├── data/                      # 原始文档
│   ├── 洗涤养护.txt
│   ├── 颜色选择.txt
│   └── 尺码推荐.txt
├── init.sql                   # MySQL 初始化脚本
├── README.md                  # 项目主文档
├── README_PROJECT.md          # 本文档
├── README_API.md              # API 对接文档（供前端开发）
├── GIT_GUIDE.md               # Git 使用指南
├── RAG优化.md                 # 优化实施记录
├── CHANGELOG.md               # 修改日志（仅本地）
├── requirements.txt           # 依赖清单
└── .env.example               # 环境变量模板
```

> 🆕 = v3.0.0 Agent 升级新增

## 七、快速启动

### 前提条件

- Python 3.10+ 虚拟环境（本项目使用 `D:\Environment\pytorch_12.4`）
- MySQL 8.0 已安装并运行
- Redis 7.x 已安装并运行
- 阿里云 DashScope API Key

### 步骤

```bash
# 1. 进入项目目录
cd RAG

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 DASHSCOPE_API_KEY、MySQL 密码、Redis 地址等
# AGENT_MODE=true  （默认 Agent 模式）

# 4. 初始化数据库
# 方式A：直接导入 SQL
mysql -u root -p < init.sql

# 方式B：用 Python 自动建表
python -c "import asyncio; from src.db.database import init_db; asyncio.run(init_db())"

# 5. 启动 FastAPI 服务
uvicorn app.fastapi_server:app --reload --host 0.0.0.0 --port 8000

# 6. 访问
# API 文档: http://localhost:8000/docs     # Swagger UI（可在线测试所有接口）
# 前端界面: 打开 frontend/index.html 或部署到 Web 服务器
# 健康检查: http://localhost:8000/health

# 7.（可选）启动 Streamlit 旧版 UI
streamlit run app/app_qa.py
```

## 八、关键设计决策

| 决策 | 选择 | 原因 |
|------|------|------|
| Agent 框架 | LangGraph `create_agent` + 自定义工具 | LangChain 官方推荐的 ReAct Agent 实现 |
| Agent 对话持久化 | SQLite (AsyncSqliteSaver) | 每用户一个 DB 物理隔离，含 tool 消息 |
| RAG 作为工具 | `search_knowledge_base` tool | Agent 自主决定何时检索，而非每次都检索 |
| Agent vs RAG 切换 | 环境变量 `AGENT_MODE` | 向后兼容，v2.x RAG 管线保留可用 |
| 用户知识库隔离 | Chroma 按用户分 Collection | 物理隔离 > metadata 过滤 |
| 密码哈希 | bcrypt（直接调用） | passlib 与本环境 bcrypt 5.x 不兼容 |
| JWT 库 | PyJWT | 环境已有，无需额外安装 python-jose |
| 异步数据库驱动 | aiomysql | 与 FastAPI 异步事件循环无缝配合 |
| 流式输出 | SSE（Server-Sent Events） | 比 WebSocket 更轻量，浏览器原生支持 |
| 前端框架 | 原生 HTML/CSS/JS | 零依赖，直接部署，无构建工具 |

## 九、已实施的优化清单

| # | 优化项 | 文件 | 效果 |
|---|--------|------|------|
| 1 | Re-ranking | `reranker.py` | gte-rerank 精排，去噪提纯 |
| 2 | 语义分块 + Parent-Child | `semantic_splitter.py` | 碎片→完整段落 |
| 3 | 混合检索 | `hybrid_retriever.py` | 向量+BM25 双路互补 |
| 4 | Query Rewrite | `query_rewriter.py` | 短查询扩展+指代消解 |
| 5 | 异步改造 | `rag_async.py` | 全链路异步 |
| 6 | FastAPI 后端 | `fastapi_server.py` | RESTful API |
| 7 | MySQL 用户存储 | `db/models.py` | 用户/会话持久化 |
| 8 | JWT 认证 | `auth/` | 登录/权限控制 |
| 9 | Redis 缓存 | `cache/` | 黑名单/缓存/限流 |
| 10 | 用户隔离 | 全链路 | 多用户数据隔离 |
| 11 | **Agent 智能决策** | `src/agent/` | LLM 自主调用工具，告别固定管线 |

> 优化 1-5 的详细实施记录见 [RAG优化.md](RAG优化.md)
