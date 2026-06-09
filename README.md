# Agent 智能客服系统

基于 **LangGraph 自定义 StateGraph** 构建的 Agent 智能客服系统。自主设计 5 节点 2 条件边的混合架构，LLM 作为推理引擎自主调用 4 个工具（知识库检索 / 联网搜索 / FAQ 匹配 / 人工转接），支持对话摘要、会话结束总结和 SSE 流式推送。

> 当前版本: **v3.2.0** — 混合架构（规则路由 + ReAct 循环）

## 核心特性

### Agent 决策引擎

```
classify_intent ──► [FAQ直达 | 结束会话 | summarize → agent ⇄ tools]
                                                       ↓
                                             session_end_summary
```

- **5 节点 StateGraph**：classify_intent → summarize → agent → tools → session_end_summary
- **2 条件边**：意图路由（3 路分支）+ 工具循环（ReAct）
- **规则快速路由**：FAQ / 转人工 / 结束会话关键词匹配，零 LLM 延迟
- **ReAct 循环**：LLM 自主决策——分析问题 → 选择工具 → 读取结果 → 继续或回答
- **轮次触发摘要**：对话 ≥6 轮自动压缩旧消息为 ≤200 字摘要，增量合并
- **会话结束总结**：自动生成全局摘要（含工具调用统计 + 问题清单）
- **4 个工具**：

| 工具 | 职责 | 核心能力 |
|------|------|----------|
| `search_knowledge_base` | 知识库检索（核心工具） | 查询改写 → 混合检索 → 重排序 → Parent-Child 展开 |
| `web_search` | 联网搜索 | Tavily API 实时搜索外部信息 |
| `lookup_faq` | FAQ 匹配 | 高频问题关键词秒级命中 |
| `escalate_to_human` | 人工转接 | 投诉 / 退款 / 复杂售后转人工 |

### 知识库检索引擎（search_knowledge_base）

Agent 调用最频繁的核心工具，自研五级管道：

```
Query Rewrite → Hybrid Search (Dense + BM25 + RRF) → Rerank (Cross-Encoder) → Parent-Child → 中文排版修复
```

- **查询改写**：LLM 驱动指代消解 + 短查询扩展（"那纯棉的呢？"→"纯棉材质衣物的洗涤保养方法"）
- **混合检索**：Chroma 向量（语义）+ 自研 BM25（关键词）双路召回，RRF 算法融合
- **重排序**：gte-rerank Cross-Encoder 精排 Top-20 → Top-3
- **中文修复**：7 道正则 Pass 清理分块导致的断行、标点粘连

### 工程能力

- **延迟加载**：Embedding / BM25 / Chroma / Reranker 仅首次工具调用时初始化，闲聊零开销
- **实例池化**：按 user_id 缓存 AgentService，避免重复加载重型组件
- **用户隔离**：Chroma Collection + SQLite Checkpointer + MySQL 三层物理隔离
- **SSE 流式**：6 种事件类型（token / tool_start / tool_end / summarize / session_end / thinking）
- **优雅降级**：Redis 不可用自动跳过、Tavily 未配置注册占位工具
- **格式化引擎**：前端 12 阶段 Markdown 渲染 + 四段式结构化输出（核心结论 → 层级序号 → 补充提醒 → 信息来源）
- **JWT 认证**：access_token（30min）+ refresh_token（7day）+ Redis 黑名单

## 技术栈

| 层级 | 技术 |
|------|------|
| Agent 框架 | **LangGraph StateGraph**（自定义 5 节点 2 条件边） |
| LLM | 通义千问 qwen3-max（DashScope） |
| 工具调用 | LangChain `bind_tools` + LangGraph `ToolNode` |
| 对话持久化 | AsyncSqliteSaver（LangGraph Checkpointer，用户隔离） |
| Embedding | text-embedding-v4（DashScope） |
| Reranker | gte-rerank Cross-Encoder（DashScope） |
| 向量数据库 | Chroma（本地持久化，collection 级别隔离） |
| 关键词检索 | 自研 BM25（jieba 分词 + 倒排索引） |
| Web 框架 | FastAPI + SSE（sse-starlette） |
| 关系数据库 | MySQL 8.0 + SQLAlchemy 2.0 Async |
| 缓存 | Redis 7.x（优雅降级） |
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
#   DASHSCOPE_API_KEY    — 阿里云 API Key（必填，LLM + Embedding + Reranker）
#   MYSQL_PASSWORD       — 数据库密码（必填）
#   JWT_SECRET_KEY       — 随机 32 位密钥（必填）
# 可选项：
#   TAVILY_API_KEY       — Tavily 联网搜索 Key
#   REDIS_URL            — Redis 连接（不可用时自动降级）
#   AGENT_BACKEND        — "custom"（混合架构）/ "legacy"（create_agent 兼容）
```

### 4. 初始化数据库

```bash
# 方式A：导入 SQL 文件
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

# Swagger 文档 → http://localhost:8000/docs
# 前端界面   → http://localhost:8000/frontend/
```

## 项目结构

```
RAG/
├── app/
│   └── fastapi_server.py              # FastAPI 主入口 + 生命周期管理
├── src/
│   ├── config.py                      # 全局配置（环境变量 + 工厂函数）
│   ├── agent/                         # Agent 决策引擎（v3.2.0 混合架构）
│   │   ├── __init__.py                #   公共 API（AgentService / AgentState / format_answer_output）
│   │   ├── state.py                   #   AgentState TypedDict（messages / summary / is_session_end）
│   │   ├── prompts.py                 #   3 个 System Prompt（Agent / Summarize / SessionEnd）
│   │   ├── classifier.py              #   意图分类（FAQ / 转人工 / 结束关键词规则匹配）
│   │   ├── formatter.py               #   回答格式化（7 道正则后处理）
│   │   ├── streaming.py               #   流式事件分类（6 种 SSE 事件）
│   │   ├── service.py                 #   AgentService 编排层（Graph 构建 + 5 节点 + 公共 API）
│   │   └── tools/                     #   Agent 工具集
│   │       ├── __init__.py            #     工具导出
│   │       ├── search_kb.py           #     知识库检索（核心工具：改写→混合检索→重排→展开）
│   │       ├── web_search.py          #     联网搜索（Tavily API）
│   │       ├── faq.py                 #     FAQ 快速匹配
│   │       └── escalate.py            #     人工转接
│   ├── rag/                           # RAG 管线（独立部署的检索服务）
│   │   ├── async_service.py           #   异步 RAG 服务（LangGraph 5 节点）
│   │   └── rewriter.py                #   Query Rewrite（指代消解 + 关键词补充）
│   ├── retrieval/                     # 检索引擎（可插拔）
│   │   ├── vector_store.py            #   Chroma 向量检索
│   │   ├── bm25.py                    #   自研 BM25 关键词检索
│   │   ├── hybrid.py                  #   混合检索 + RRF 融合
│   │   └── reranker.py                #   gte-rerank Cross-Encoder 重排序
│   ├── knowledge/                     # 知识库管理
│   │   ├── service.py                 #   文档上传 / MD5 去重 / 切分
│   │   └── splitter.py                #   语义分块器
│   ├── storage/                       # 对话历史存储（可插拔）
│   │   ├── file_store.py              #   JSON 文件后端
│   │   └── mysql_store.py             #   MySQL 后端
│   ├── api/                           # REST API 路由
│   │   ├── auth.py                    #   认证（注册 / 登录 / 刷新 / 登出）
│   │   ├── chat.py                    #   对话（SSE 流式 + 非流式 + AgentService 实例池）
│   │   ├── knowledge.py               #   知识库管理
│   │   └── user.py                    #   用户信息
│   ├── auth/                          # JWT 认证
│   │   ├── jwt_handler.py             #   Token 生成 / 校验
│   │   ├── security.py                #   密码哈希 + 用户依赖注入
│   │   └── schemas.py                 #   Pydantic 模型
│   ├── db/                            # 数据库 ORM
│   │   ├── database.py                #   SQLAlchemy Async Engine + 自动建表
│   │   └── models.py                  #   ORM 模型（User / ChatHistory / KnowledgeDoc）
│   └── cache/
│       └── redis_client.py            #   Redis 客户端（优雅降级 + 连通性测试）
├── frontend/                          # 前端 SPA
│   ├── index.html                     #   入口页面
│   ├── css/style.css                  #   全局样式 + 四段式结构化样式 + 深色模式
│   └── js/
│       ├── app.js                     #   应用入口 + 页面路由
│       ├── router.js                  #   Hash 路由
│       ├── api.js                     #   API 客户端（SSE + JWT 拦截器）
│       ├── auth.js                    #   登录 / 注册
│       ├── chat.js                    #   对话页（Markdown 渲染 + 格式化管道 + 工具事件展示）
│       ├── knowledge.js               #   知识库管理
│       └── profile.js                 #   个人中心
├── data/                              # 持久化数据（运行时生成）
│   ├── documents/                     #   原始文档（TXT）
│   ├── chroma/                        #   Chroma 向量库
│   ├── chat_history/                  #   SQLite Checkpointer + 对话历史
│   └── md5.text                       #   MD5 去重记录
├── eval/                              # 评估框架
│   └── rag_evaluation.py              #   检索质量评估脚本
├── run.py                             # 便捷启动入口
├── requirements.txt                   # Python 依赖
├── init.sql                           # 数据库初始化 SQL
└── .env.example                       # 环境变量模板

模块总数: 14 个 Python 包 | Agent 拆分: 7 个文件（从 1307 行单文件重构）
```

## 架构详解

### Agent 状态流转

```
START
  │
  ▼
┌──────────────────────┐
│   classify_intent    │  规则匹配（零 LLM 延迟）
│                      │
│  FAQ 关键词命中？    │─── faq_direct ──► END
│  转人工关键词命中？  │─── end_session ─► session_end_summary
│  结束关键词命中？    │─── continue ────► summarize
│  都不匹配 → continue │
└──────┬───────────────┘
       │ continue
       ▼
┌──────────────────────┐
│     summarize        │  轮次触发对话压缩
│                      │
│  rounds < 6？       │── 短路跳过
│  距上次 < 3 轮？     │── 短路跳过
│  rounds ≥ 6：        │
│  旧消息 → LLM 压缩   │── 增量合并已有摘要
│  → SystemMessage     │   保留最近 6 条消息
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐     有 tool_calls
│       agent          │──────────────────────┐
│  LLM + 4 工具        │                      │
│  决策：用哪个工具？   │◄─────────────────────┘
│  直接回答？          │     无 tool_calls → END
└──────┬───────────────┘
       │ 有 tool_calls
       ▼
┌──────────────────────┐
│       tools          │  ToolNode 执行
│                      │
│  search_kb ──────────┤── 五级检索管道
│  web_search ─────────┤── Tavily API
│  lookup_faq ─────────┤── 关键词匹配
│  escalate_to_human ──┤── 转人工响应
└──────┬───────────────┘
       │
       └──► agent（ReAct 循环：思考→行动→观察→思考）
```

### SSE 事件类型（Agent → 前端流式通信）

| 事件 | 消息来源 | data | 前端渲染 |
|------|----------|------|----------|
| `token` | `AIMessageChunk.content` | 文本片段 | 流式打字效果 |
| `tool_start` | `AIMessage.tool_calls` | `{"tools": [{"name": "...", "args": {...}}]}` | "🔍 正在检索知识库…" |
| `tool_end` | `ToolMessage` | `{"tool": "...", "result_preview": "..."}` | "✅ 已完成" + 结果预览 |
| `summarize` | `SystemMessage` 含摘要 | 空 | "📝 对话已自动总结" |
| `session_end` | `AIMessage` 含会话总结 | 空 | 总结卡片 |
| `thinking` | 其他无内容消息 | 空 | 忽略 |
| `done` | 流结束 | `[DONE]` | 触发格式化 + DOM 渲染 |

### 前端格式化管线

```
LLM 原始输出
  │
  ▼
format_answer_output()   后端正则（7 Pass）
  │                      【核心结论】→ 层级序号 → 【补充提醒】→ 【信息来源】
  ▼
cleanChineseText()       前端清理（7 Pass）
  │                      合并断裂段落 / 修复标点 / 清理空行
  ▼
formatMarkdown()         Markdown → HTML（12 Phase）
  │                      marked.js 渲染 + highlight.js 代码高亮
  ▼
CSS 样式包裹              section-core（蓝框）/ section-reminder（黄框）/ section-source（灰虚线）
  ▼
DOM 展示
```

## API 概览

| 模块 | 方法 | 端点 | 说明 |
|------|------|------|------|
| 认证 | POST | `/api/auth/register` | 用户注册 |
| | POST | `/api/auth/login` | 登录（返回 access + refresh token） |
| | POST | `/api/auth/refresh` | 刷新 Token |
| | POST | `/api/auth/logout` | 登出（Token 加入黑名单） |
| 对话 | POST | `/api/chat/stream` | 流式对话（SSE，含 6 种 Agent 事件） |
| | POST | `/api/chat/` | 非流式对话 |
| | GET | `/api/chat/sessions` | 会话列表 |
| | GET | `/api/chat/history/{id}` | 会话历史 |
| | DELETE | `/api/chat/history/{id}` | 清空会话 |
| 知识库 | POST | `/api/knowledge/upload` | 上传文档 |
| | GET | `/api/knowledge/documents` | 文档列表 |
| | DELETE | `/api/knowledge/documents/{id}` | 删除文档 |
| 用户 | GET | `/api/user/me` | 当前用户信息 |
| | PUT | `/api/user/me` | 更新用户信息 |
| 系统 | GET | `/health` | 健康检查 |

## 配置参考

完整环境变量见 `.env.example`，关键配置：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DASHSCOPE_API_KEY` | — | 阿里云 API Key（**必填**，LLM + Embedding + Reranker） |
| `MYSQL_PASSWORD` | — | MySQL 密码（**必填**） |
| `JWT_SECRET_KEY` | — | JWT 密钥（**必填，≥32 位**） |
| `TAVILY_API_KEY` | — | 联网搜索 Key（可选） |
| `REDIS_URL` | `redis://localhost:6379` | Redis 连接（可选，失败降级） |
| `AGENT_BACKEND` | `custom` | Agent 后端：`custom`=混合架构 / `legacy`=create_agent |
| `AGENT_SUMMARY_TRIGGER_ROUNDS` | `6` | 触发对话摘要的轮数阈值 |
| `AGENT_SUMMARY_KEEP_RECENT` | `6` | 摘要后保留的最近消息数 |
| `AGENT_SUMMARY_MIN_INTERVAL_ROUNDS` | `3` | 两次摘要间最小轮数间隔 |
| `AGENT_CLASSIFY_ENABLED` | `true` | 是否启用规则快速路由 |
| `WEB_SEARCH_ENABLED` | `true` | 是否启用联网搜索 |
| `CHAT_MODEL_NAME` | `qwen3-max` | LLM 模型 |
| `EMBEDDING_MODEL_NAME` | `text-embedding-v4` | Embedding 模型 |

## 架构演进

```
v1.x (Demo)          v2.x (RAG 管线)       v3.0.0 (Agent 黑盒)    v3.2.0 (Agent 自定义)
─────────            ──────────────        ──────────────────     ─────────────────────
用户输入              用户输入               用户输入                用户输入
  ↓                     ↓                     ↓                      ↓
向量检索              Query Rewrite         create_agent          classify_intent
  ↓                     ↓                   LLM + 4 tools         规则快速路由
LLM 生成              Hybrid Search              ↓               ↙    ↓    ↘
                      + Rerank              工具调用循环          FAQ  结束  summarize
                      + Parent-Child                             直达  会话    ↓
                           ↓                                    agent ⇄ tools
                      LLM 流式生成                                  ↓
                                                             session_end_summary
```

> 演进关键：v3.2.0 从 LangChain 黑盒 `create_agent` 迁移至自定义 LangGraph StateGraph，获得了完整的图结构控制权——可插入前置路由、中途摘要、后置总结。

## License

MIT
