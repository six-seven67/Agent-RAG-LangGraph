# RAG 智能客服系统

基于 **RAG（Retrieval-Augmented Generation）** 架构的企业级智能客服系统。将私有知识库文档通过语义分块存入向量数据库，用户提问时经「混合检索 + 重排序 + LLM 生成」返回精准回答，杜绝大模型幻觉。

## ✨ 核心特性

- **五级 RAG 检索管线**：Query Rewrite → Hybrid Search（向量+BM25）→ Re-ranking → Parent-Child 展开 → LLM 流式生成
- **用户隔离**：Chroma 按用户分 Collection 物理隔离 + MySQL 数据隔离 + JWT 认证
- **流式对话**：SSE（Server-Sent Events）实时逐字输出，类 ChatGPT 体验
- **知识库管理**：上传 TXT 文档自动语义分块、MD5 去重、向量化入库
- **RESTful API**：FastAPI 框架，OpenAPI 文档自动生成，即开即用
- **多端兼容**：支持新前端（任何框架）、Streamlit 旧版 UI、第三方 API 调用

## 技术栈

| 层级 | 技术 |
|------|------|
| LLM | 通义千问 qwen3-max（DashScope） |
| Embedding | text-embedding-v4（DashScope） |
| Reranker | gte-rerank（DashScope） |
| 向量数据库 | Chroma（本地持久化） |
| Web 框架 | FastAPI + Streamlit |
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
| 对话 | `POST /api/chat/stream` | 流式对话（SSE） |
| | `GET /api/chat/sessions` | 会话列表 |
| | `GET /api/chat/history/{id}` | 会话历史 |
| 知识库 | `POST /api/knowledge/upload` | 上传文档 |
| | `GET /api/knowledge/documents` | 文档列表 |

完整 API 文档及前端对接指南 → [README_API.md](README_API.md)

## 项目结构

```
RAG-LangChain/
├── app/                    # Web 应用
│   ├── fastapi_server.py   # FastAPI 主入口
│   ├── app_qa.py           # Streamlit 问答界面
│   └── app_file_uploader.py# Streamlit 上传界面
├── src/                    # 核心源码
│   ├── rag_async.py        # 异步 RAG 引擎
│   ├── hybrid_retriever.py # 混合检索引擎
│   ├── reranker.py         # 重排序服务
│   ├── query_rewriter.py   # 查询改写
│   ├── knowledge_base.py   # 知识库管理
│   ├── vector_stores.py    # Chroma 向量库
│   ├── db/                 # 数据库模块
│   ├── auth/               # 认证模块
│   ├── cache/              # Redis 缓存模块
│   └── api/                # API 路由
├── frontend/               # 前端界面
├── eval/                   # 评估框架
├── data/                   # 原始文档
├── init.sql                # 数据库初始化脚本
├── requirements.txt        # Python 依赖
└── .env.example            # 环境变量模板
```

## 相关文档

- [项目详细介绍](README_PROJECT.md) — 架构设计、优化清单、技术决策
- [API 对接文档](README_API.md) — 前端开发必读（含 SSE 示例代码）
- [RAG 优化记录](RAG优化.md) — 5 项核心优化的实施过程与消融实验数据
- [Git 使用指南](GIT_GUIDE.md) — 版本管理操作说明

## License

MIT
