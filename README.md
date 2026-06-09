# RAG 智能客服系统

基于 **LangGraph 自定义 StateGraph** 的企业级智能客服系统。采用 v3.2.0 混合架构（规则路由 + ReAct 循环），支持知识库检索、联网搜索、FAQ 快速匹配、对话摘要、会话结束总结及人工转接。

## 核心特性

### Agent 智能决策（v3.2.0 混合架构）

```
classify_intent ──► [FAQ直达 | 结束会话 | summarize → agent ⇄ tools]
                                                       ↓
                                             session_end_summary
```

- **规则快速路由**：FAQ / 转人工 / 结束会话关键词匹配，零 LLM 延迟
- **ReAct 循环**：LLM 自主决策工具调用（`search_knowledge_base` / `web_search` / `lookup_faq` / `escalate_to_human`）
- **轮次触发摘要**：对话超 6 轮自动压缩历史为 ≤200 字摘要，增量合并
- **会话结束总结**：用户结束时自动生成全局摘要（含工具统计、问题清单）
- **流式事件**：SSE 推送 6 种事件（`token` / `tool_start` / `tool_end` / `summarize` / `session_end` / `thinking`）

### RAG 检索管道

- **五级管线**：Query Rewrite → Hybrid Search（Dense + BM25 + RRF）→ Rerank → 中文排版清理
- **混合检索**：向量语义检索 + BM25 关键词检索双路召回，RRF 融合
- **重排序**：gte-rerank Cross-Encoder 精排，Top-20 → Top-3
- **联网搜索**：Tavily API 实时搜索外部信息（时效问题、知识库补充）

### 工程能力

- **延迟加载**：Embedding / BM25 / Chroma / Reranker 仅在首次工具调用时初始化
- **实例池化**：按 user_id 缓存 AgentService，避免重复加载重型组件
- **用户隔离**：Chroma Collection + SQLite Checkpointer + MySQL 三层面数据隔离
- **中文排版优化**：7 道清理 Pass + 结构化输出格式化 + Markdown 渲染
- **前端格式化**：`【核心结论】→ 层级序号 → 【补充提醒】→ 【信息来源】` 四段式结构
- **代码块增强**：语法高亮（highlight.js）+ 一键复制按钮
- **认证体系**：JWT（access + refresh token）+ Redis 黑名单 + bcrypt 密码哈希
- **优雅降级**：Redis 不可用时自动跳过缓存，不影响核心对话功能

## 技术栈

| 层级 | 技术 |
|------|------|
| Agent 框架 | **LangGraph StateGraph**（自定义 5 节点图） |
| LLM | 通义千问 qwen3-max（DashScope） |
| Embedding | text-embedding-v4（DashScope） |
| Reranker | gte-rerank（DashScope） |
| 向量数据库 | Chroma（本地持久化） |
| Checkpointer | SQLite（AsyncSqliteSaver，用户隔离） |
| Web 框架 | FastAPI + SSE（sse-starlette） |
| 关系数据库 | MySQL 8.0 + SQLAlchemy 2.0 Async |
| 缓存 | Redis 7.x（aioredis，优雅降级） |
| 认证 | PyJWT + bcrypt |
| 联网搜索 | Tavily Search API |

## 快速开始

### 1. 环境要求

- Python 3.10+
- MySQL 8.0
- Redis 7.x（可选，不可用时自动降级）
- 阿里云 DashScope API Key → [获取地址](https://dashscope.console.aliyun.com/)
- Tavily API Key（可选，用于联网搜索）→ [获取地址](https://tavily.com/)

### 2. 安装

```bash
git clone https://github.com/six-seven67/RAG-LangChain.git
cd RAG-LangChain
pip install -r requirements.txt
```

### 3. 配置

```bash
cp .env.example .env
# 编辑 .env，必填项：
#   DASHSCOPE_API_KEY    — 阿里云 API Key（必填）
#   MYSQL_PASSWORD       — 数据库密码（必填）
#   JWT_SECRET_KEY       — 随机生成 32 位密钥（必填）
# 可选项：
#   TAVILY_API_KEY       — 联网搜索 Key
#   REDIS_URL            — Redis 连接（不可用时自动降级）
#   AGENT_BACKEND        — "custom"（混合架构）/ "legacy"（兼容）
```

### 4. 初始化数据库

```bash
# 方式A：导入 SQL
mysql -u root -p < init.sql

# 方式B：Python 自动建表
python -c "import asyncio; from src.db.database import init_db; asyncio.run(init_db())"
```

### 5. 启动

```bash
# 开发模式（热重载）
python run.py

# 或直接使用 uvicorn
uvicorn app.fastapi_server:app --reload --host 0.0.0.0 --port 8000

# 访问 Swagger 文档 → http://localhost:8000/docs
# 访问前端界面 → http://localhost:8000/frontend/
```

## 项目结构

```
RAG/
├── app/                              # Web 应用入口
│   └── fastapi_server.py             # FastAPI 主入口 + 生命周期管理
├── src/                              # 核心源码
│   ├── config.py                     # 全局配置（环境变量 + 默认值 + 工具函数）
│   ├── agent/                        # Agent 模块（v3.2.0 混合架构）
│   │   ├── __init__.py               #   公共 API 导出（AgentService / AgentState / format_answer_output）
│   │   ├── state.py                  #   AgentState TypedDict（messages / summary / is_session_end）
│   │   ├── prompts.py                #   System Prompts（AGENT / SUMMARIZE / SESSION_END_SUMMARY）
│   │   ├── classifier.py             #   意图分类（FAQ / 转人工 / 结束会话关键词匹配 + classify_intent 节点）
│   │   ├── formatter.py              #   回答格式化（7 道正则后处理 + 四段式结构）
│   │   ├── streaming.py              #   流式事件分类（chunk → token / tool_start / tool_end / summarize / session_end）
│   │   ├── service.py                #   AgentService 编排层（Graph 构建 + 5 节点 + ainvoke / astream）
│   │   └── tools/                    #   Agent 工具（工厂模式，支持用户隔离）
│   │       ├── __init__.py           #     工具导出
│   │       ├── search_kb.py          #     知识库检索（Query Rewrite → Hybrid → Rerank → 中文清理）
│   │       ├── web_search.py         #     联网搜索（Tavily API）
│   │       ├── faq.py                #     FAQ 快速匹配
│   │       └── escalate.py           #     人工转接
│   ├── rag/                          # RAG 管道
│   │   ├── async_service.py          #   异步 RAG 服务（LangGraph StateGraph）
│   │   └── rewriter.py               #   Query Rewrite（指代消解 + 关键词补充）
│   ├── retrieval/                    # 检索引擎（可插拔）
│   │   ├── vector_store.py           #   Chroma 向量检索
│   │   ├── bm25.py                   #   BM25 关键词检索
│   │   ├── hybrid.py                 #   混合检索 + RRF 融合
│   │   └── reranker.py               #   gte-rerank Cross-Encoder 重排序
│   ├── knowledge/                    # 知识库管理
│   │   ├── service.py                #   文档上传 / MD5 去重 / 切分
│   │   └── splitter.py               #   语义分块器
│   ├── storage/                      # 对话历史存储（可插拔）
│   │   ├── file_store.py             #   JSON 文件后端
│   │   └── mysql_store.py            #   MySQL 后端
│   ├── api/                          # API 路由
│   │   ├── auth.py                   #   认证（注册 / 登录 / 刷新 / 登出）
│   │   ├── chat.py                   #   对话（SSE 流式 + 非流式 + AgentService 实例池）
│   │   ├── knowledge.py              #   知识库管理
│   │   └── user.py                   #   用户信息
│   ├── auth/                         # JWT 认证
│   │   ├── jwt_handler.py            #   Token 生成 / 校验
│   │   ├── security.py               #   密码哈希 + 用户依赖注入
│   │   └── schemas.py                #   Pydantic 模型
│   ├── db/                           # 数据库 ORM
│   │   ├── database.py               #   SQLAlchemy Async Engine + 自动建表
│   │   └── models.py                 #   ORM 模型（User / ChatHistory）
│   └── cache/                        # Redis 缓存
│       └── redis_client.py           #   Redis 客户端（优雅降级 + 连通性测试）
├── frontend/                         # 前端 SPA
│   ├── index.html                    #   入口页面
│   ├── css/
│   │   └── style.css                 #   全局样式 + 结构化输出（section-core/reminder/source）+ 深色模式
│   └── js/
│       ├── app.js                    #   应用入口 + 页面路由
│       ├── router.js                 #   Hash 路由
│       ├── api.js                    #   API 客户端（SSE 流式 + JWT 拦截器）
│       ├── auth.js                   #   登录 / 注册
│       ├── chat.js                   #   对话页（Markdown 渲染 + 格式化管道 + 工具事件展示）
│       ├── knowledge.js              #   知识库管理页
│       └── profile.js                #   个人中心
├── data/                             # 持久化数据
│   ├── documents/                    #   原始文档（TXT）
│   ├── chroma/                       #   Chroma 向量库
│   ├── chat_history/                 #   SQLite 对话历史 + Checkpoints
│   └── md5.text                      #   MD5 去重记录
├── docs/                             # 项目文档
│   ├── PROJECT.md                    #   架构设计 + 技术决策
│   ├── OPTIMIZATION.md               #   性能优化记录
│   └── CHANGELOG.md                  #   版本变更日志
├── eval/                             # 评估框架
│   └── rag_evaluation.py             #   检索质量评估脚本
├── run.py                            # 便捷启动入口（dev / prod）
├── requirements.txt                  # Python 依赖
├── init.sql                          # 数据库初始化 SQL
└── .env.example                      # 环境变量模板
```

## 架构详解

### Agent 状态流转

```
START
  │
  ▼
┌──────────────────────┐
│   classify_intent    │  规则匹配快速路由（零 LLM）
│                      │  • FAQ 命中 → 注入答案 → END
│                      │  • 转人工命中 → 转接 → END
│                      │  • 结束会话 → session_end_summary
│                      │  • 无匹配 → continue
└──────┬───────────────┘
       │ continue
       ▼
┌──────────────────────┐
│     summarize        │  轮次触发对话压缩
│                      │  • 短路跳过（<6 轮）
│                      │  • 增量合并（已有摘要时）
│                      │  • 保留最近 6 条消息
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐     有 tool_calls
│       agent          │──────────────────────┐
│  LLM + bind_tools    │                      │
│  4 个工具绑定         │◄─────────────────────┘
└──────┬───────────────┘     无 tool_calls → END
       │
       ▼
┌──────────────────────┐
│       tools          │  ToolNode（懒加载）
│  search_kb           │  • 知识库 → 五级检索管道
│  web_search          │  • 实时信息 → Tavily
│  lookup_faq          │  • 高频问题 → FAQ 库
│  escalate_to_human   │  • 复杂问题 → 转人工
└──────┬───────────────┘
       │
       └──► agent（循环）
```

### SSE 事件类型

| 事件 | 触发时机 | data 格式 |
|------|----------|-----------|
| `token` | LLM 逐字生成 | 文本片段（string） |
| `tool_start` | Agent 决定调用工具 | `{"tools": [{"name": "...", "args": {...}}]}` |
| `tool_end` | 工具执行完成 | `{"tool": "...", "result_preview": "..."}` |
| `summarize` | 对话历史被压缩 | 空 |
| `session_end` | 会话结束总结生成 | 空 |
| `thinking` | LLM 推理中（无输出） | 空 |
| `done` | 流结束 | `[DONE]` |

### 前端格式化管线

```
LLM 原始输出
  │
  ▼
format_answer_output()   # 后端正则后处理（7 道 Pass）
  │                      #   【核心结论】→ 层级序号 → 【补充提醒】→ 【信息来源】
  ▼
cleanChineseText()       # 前端 7 道清理 Pass（中文排版修复）
  │                      #   合并断裂段落、清理多余空行、修复标点
  ▼
formatMarkdown()         # 12 阶段 HTML 渲染（代码块高亮 / 表格 / 引用 / 列表 / 内联）
  │
  ▼
Phase 12 段落包裹        # CSS 结构化样式
  │                      #   section-core（蓝色左框）/ section-reminder（黄色）/ section-source（虚线灰底）
  ▼
DOM 渲染                 # marked.js + highlight.js → 最终展示
```

## API 概览

| 模块 | 方法 | 端点 | 说明 |
|------|------|------|------|
| 认证 | POST | `/api/auth/register` | 用户注册 |
| | POST | `/api/auth/login` | 登录（返回 access + refresh token） |
| | POST | `/api/auth/refresh` | 刷新 Token |
| | POST | `/api/auth/logout` | 登出（Token 加入 Redis 黑名单） |
| 对话 | POST | `/api/chat/stream` | 流式对话（SSE，含 6 种 Agent 事件） |
| | POST | `/api/chat/` | 非流式对话 |
| | GET | `/api/chat/sessions` | 会话列表（按最近活动排序） |
| | GET | `/api/chat/history/{id}` | 会话历史 |
| | DELETE | `/api/chat/history/{id}` | 清空会话 |
| 知识库 | POST | `/api/knowledge/upload` | 上传文档（TXT） |
| | GET | `/api/knowledge/documents` | 文档列表 |
| | DELETE | `/api/knowledge/documents/{id}` | 删除文档 |
| 用户 | GET | `/api/user/me` | 当前用户信息 |
| | PUT | `/api/user/me` | 更新用户信息 |
| 系统 | GET | `/health` | 健康检查 |

## 配置参考

完整环境变量列表见 `.env.example`，关键配置：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DASHSCOPE_API_KEY` | — | 阿里云 API Key（**必填**） |
| `MYSQL_PASSWORD` | — | MySQL 密码（**必填**） |
| `JWT_SECRET_KEY` | — | JWT 签名密钥（**必填，≥32 位**） |
| `CHAT_MODEL_NAME` | `qwen3-max` | LLM 模型 |
| `EMBEDDING_MODEL_NAME` | `text-embedding-v4` | Embedding 模型 |
| `REDIS_URL` | `redis://localhost:6379` | Redis 连接（可选，失败降级） |
| `TAVILY_API_KEY` | — | 联网搜索 API Key（可选） |
| `AGENT_BACKEND` | `custom` | `custom`=混合架构 / `legacy`=create_agent |
| `AGENT_SUMMARY_TRIGGER_ROUNDS` | `6` | 触发摘要的对话轮数 |
| `AGENT_SUMMARY_KEEP_RECENT` | `6` | 摘要后保留的最近消息数 |
| `AGENT_SUMMARY_MIN_INTERVAL_ROUNDS` | `3` | 两次摘要最小轮数间隔 |
| `WEB_SEARCH_ENABLED` | `true` | 是否启用联网搜索 |
| `AGENT_CLASSIFY_ENABLED` | `true` | 是否启用规则快速路由 |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Access Token 有效期 |
| `QUERY_REWRITE_ENABLED` | `true` | 是否启用查询改写 |

## 架构演进

```
v1.x (MVP)           v2.x (RAG 管线)          v3.0.0 (Agent)         v3.2.0 (混合架构)
─────────            ──────────────           ─────────────          ─────────────────
用户输入              用户输入                  用户输入               用户输入
  ↓                     ↓                        ↓                     ↓
向量检索              查询改写              LLM 自主决策            classify_intent
  ↓                     ↓                   ↙   ↓   ↘             规则快速路由
LLM 生成              混合检索            查库  FAQ  转人工       ↙    ↓    ↘
  ↓                     ↓                   ↘   ↓   ↙           FAQ  结束  summarize
回答                  重排序                综合生成回答           直达  会话    ↓
                       ↓                                          agent ⇄ tools
                  Parent-Child                                       ↓
                       ↓                                        LLM 直接回答
                  LLM 流式生成                                       ↓
                       ↓                                    session_end_summary
                     回答
```

## 相关文档

- [架构设计](docs/PROJECT.md) — 详细架构、技术决策
- [性能优化](docs/OPTIMIZATION.md) — 延迟加载、实例池化、Benchmark
- [变更日志](docs/CHANGELOG.md) — 版本历史与 Bug 修复

## License

MIT
