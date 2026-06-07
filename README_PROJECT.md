# RAG 智能客服系统 — 项目介绍

## 一、项目概述

基于 **RAG（检索增强生成）** 架构的智能客服系统。将企业知识库文档（TXT）进行语义分块后存入向量数据库，用户提问时通过「混合检索 + 重排序 + LLM 生成」链路返回精准回答，杜绝大模型幻觉。

**核心价值**：让 AI 基于**你的知识库**回答问题，而非凭空编造。

## 二、技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| LLM 模型 | 通义千问 qwen3-max（DashScope API） | 文本生成 |
| Embedding | text-embedding-v4（DashScope API） | 文本向量化 |
| Reranker | gte-rerank（DashScope API） | Cross-Encoder 精排 |
| 向量数据库 | Chroma（本地持久化） | 文档向量存储 |
| Web 框架 | **FastAPI**（新）+ Streamlit（保留） | RESTful API + 旧版 UI |
| 关系数据库 | **MySQL 8.0** | 用户/会话/文档元数据 |
| 缓存 | **Redis 7.x** | JWT 黑名单 / 查询缓存 / 限流 |
| 认证 | **JWT（PyJWT + bcrypt）** | access_token + refresh_token |
| 分词 | jieba | BM25 中文分词 |
| 关键词检索 | BM25（自研） | 精确关键词匹配 |

## 三、系统架构

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
│   │ 认证服务  │    │  RAG 核心引擎 │    │  知识库管理        │      │
│   │ JWT+bcrypt│    │ (AsyncRag)  │    │  (KnowledgeBase)  │      │
│   └─────┬─────┘    └──────┬───────┘    └────────┬─────────┘      │
│         │                 │                     │                 │
├─────────┼─────────────────┼─────────────────────┼─────────────────┤
│         ▼                 ▼                     ▼                 │
│   ┌─────────────────────────────────────────────────────────┐    │
│   │                      数据层                               │    │
│   │  ┌──────────┐  ┌──────────┐  ┌────────────────────┐     │    │
│   │  │  MySQL   │  │  Redis   │  │  Chroma (向量库)    │     │    │
│   │  │ 用户/会话 │  │ 缓存/黑名单│  │  文档向量+元数据    │     │    │
│   │  └──────────┘  └──────────┘  └────────────────────┘     │    │
│   └─────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

## 四、RAG 检索链路（5 级管道）

这是系统的核心竞争力——经过消融实验验证的五级检索管线：

```
用户查询
  │
  ▼
┌─────────────────┐
│ ① Query Rewrite  │  LLM 改写短查询、消解指代词（"那纯棉的呢？"→"纯棉材质保养方法"）
└────────┬────────┘
         ▼
┌─────────────────┐
│ ② Hybrid Search  │  向量检索 Top-20 (语义) + BM25 Top-20 (关键词) → RRF 融合
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
│ ⑤ LLM 生成       │  qwen3-max 流式生成 → 逐 token 输出
└─────────────────┘
```

各优化独立贡献（消融实验数据）：**混合检索 > Parent-Child ≈ Re-ranking**

## 五、用户隔离方案

系统从三个层面实现多用户数据隔离：

| 隔离层面 | 实现方式 | 说明 |
|---------|---------|------|
| **知识库** | Chroma 按用户分 Collection | 用户 A 的文档存入 `rag_user_A_id`，用户 B 存入 `rag_user_B_id`，物理隔离 |
| **对话历史** | MySQL `chat_history` 表 `user_id` 字段 | 所有查询带 `WHERE user_id = ?` |
| **文档元数据** | MySQL `knowledge_docs` 表 `user_id` 字段 | 用户级 MD5 去重 |
| **API 层** | JWT 认证 + `get_current_user` 依赖注入 | 从 token 解析 user_id，注入到所有业务逻辑 |

## 六、目录结构

```
RAG/
├── app/
│   ├── fastapi_server.py      # 🆕 FastAPI 主入口
│   ├── app_qa.py              # Streamlit 问答 UI（保留）
│   └── app_file_uploader.py   # Streamlit 上传 UI（保留）
├── src/
│   ├── config_data.py         # 🔧 全局配置（含 MySQL/Redis/JWT）
│   ├── rag_async.py           # 🔧 异步 RAG 服务（支持 user_id 隔离）
│   ├── rag.py                 # 同步 RAG 服务（兼容保留）
│   ├── hybrid_retriever.py    # 混合检索（向量 + BM25 → RRF）
│   ├── bm25_retriever.py      # BM25 关键词检索器
│   ├── vector_stores.py       # 🔧 Chroma 向量库（支持自定义 collection）
│   ├── reranker.py            # gte-rerank 重排序
│   ├── query_rewriter.py      # LLM 查询改写
│   ├── knowledge_base.py      # 🔧 知识库管理（支持自定义 collection）
│   ├── semantic_splitter.py   # 语义分块器
│   ├── file_history_store.py  # 文件对话历史（兼容保留）
│   ├── history_store_mysql.py # 🆕 MySQL 对话历史存储
│   ├── db/                    # 🆕 数据库模块
│   │   ├── database.py        # SQLAlchemy async engine
│   │   └── models.py          # ORM 模型
│   ├── auth/                  # 🆕 认证模块
│   │   ├── jwt_handler.py     # JWT 生成/验证
│   │   ├── security.py        # bcrypt + get_current_user
│   │   └── schemas.py         # Pydantic 模型
│   ├── cache/                 # 🆕 缓存模块
│   │   └── redis_client.py    # Redis 连接 + 黑名单 + 限流
│   └── api/                   # 🆕 API 路由
│       ├── auth.py            # 认证端点
│       ├── chat.py            # 对话端点
│       ├── knowledge.py       # 知识库端点
│       └── user.py            # 用户端点
├── eval/
│   ├── rag_evaluation.py      # 消融实验评估框架
│   └── eval_report_quick.md   # 评估报告
├── data/                      # 原始文档
│   ├── 洗涤养护.txt
│   ├── 颜色选择.txt
│   └── 尺码推荐.txt
├── init.sql                   # 🆕 MySQL 初始化脚本
├── README_PROJECT.md          # 🆕 本文档
├── README_API.md              # 🆕 API 对接文档（供前端开发）
├── requirements.txt           # 🔧 依赖清单
├── .env.example               # 🔧 环境变量模板
└── RAG优化.md                 # 优化实施记录
```

> 🆕 = 本次企业级改造新增  &nbsp; 🔧 = 本次修改

## 七、快速启动

### 前提条件

- Python 3.10+ 虚拟环境（本项目使用 `D:\Environment\pytorch_12.4`）
- MySQL 8.0 已安装并运行
- Redis 7.x 已安装并运行
- 阿里云 DashScope API Key

### 步骤

```bash
# 1. 克隆项目
cd RAG

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 DASHSCOPE_API_KEY、MySQL 密码、Redis 地址等

# 4. 初始化数据库
# 方式A：直接导入 SQL
mysql -u root -p < init.sql

# 方式B：用 Python 自动建表
python -c "import asyncio; from src.db.database import init_db; asyncio.run(init_db())"

# 5. 启动 FastAPI 服务
uvicorn app.fastapi_server:app --reload --host 0.0.0.0 --port 8000

# 6. 访问 API 文档
# http://localhost:8000/docs     # Swagger UI（可在线测试所有接口）

# 7.（可选）启动 Streamlit 旧版 UI
streamlit run app/app_qa.py
```

## 八、关键设计决策

| 决策 | 选择 | 原因 |
|------|------|------|
| 用户知识库隔离 | Chroma 按用户分 Collection | 物理隔离 > metadata 过滤，最安全可靠 |
| 密码哈希 | bcrypt（直接调用） | passlib 与本环境 bcrypt 5.x 不兼容 |
| JWT 库 | PyJWT | 环境已有，无需额外安装 python-jose |
| 异步数据库驱动 | aiomysql | 与 FastAPI 异步事件循环无缝配合 |
| RAG 历史存储 | 闭包捕获 user_id | 避免依赖 LangChain 新版 API 参数，更稳健 |
| 流式输出 | SSE（Server-Sent Events） | 比 WebSocket 更轻量，浏览器原生支持 |

## 九、已实施的优化清单

| # | 优化项 | 文件 | 效果 |
|---|--------|------|------|
| 1 | Re-ranking | `reranker.py` | gte-rerank 精排，去噪提纯 |
| 2 | 语义分块 + Parent-Child | `semantic_splitter.py` | 碎片→完整段落 |
| 3 | 混合检索 | `hybrid_retriever.py` | 向量+BM25 双路互补 |
| 4 | Query Rewrite | `query_rewriter.py` | 短查询扩展+指代消解 |
| 5 | 异步改造 | `rag_async.py` | 全链路异步 |
| 6 | **FastAPI 后端** | `fastapi_server.py` | RESTful API |
| 7 | **MySQL 用户存储** | `db/models.py` | 用户/会话持久化 |
| 8 | **JWT 认证** | `auth/` | 登录/权限控制 |
| 9 | **Redis 缓存** | `cache/` | 黑名单/缓存/限流 |
| 10 | **用户隔离** | 全链路 | 多用户数据隔离 |

> 优化 1-5 的详细实施记录见 [RAG优化.md](RAG优化.md)
