# RAG Agent — 企业制度文档智能问答系统

基于 **LangGraph 自定义 StateGraph** 构建的 ToB 知识库文档 RAG Agent。用户上传企业制度文档构建专属知识库，Agent 基于文档内容进行检索增强生成（RAG），实现精准、可验证的文档问答。

> 当前版本：**v3.3.0** — 6 节点 StateGraph（意图分类 → 对话压缩 → ReAct 循环 → 幻觉校验 → 会话总结）

---

## 核心特性

### Agent 决策引擎

```
classify_intent ──► [闲聊直达 | 结束会话 | summarize → agent ⇄ tools]
                                                          ↓
                                      hallucination_check → agent（重试一次）
                                                          ↓
                                                session_end_summary
```

- **6 节点 StateGraph**：classify_intent → summarize → agent → tools → hallucination_check → session_end_summary
- **3 条件边**：意图路由（3 路分支）+ ReAct 工具循环 + 幻觉校验重试
- **规则快速路由**：闲聊 / 会话结束关键词匹配，零 LLM 延迟直达
- **ReAct 循环**：LLM 自主决策——分析问题 → 选择工具 → 读取结果 → 继续或回答
- **双阈值对话压缩**：轮次 ≥ 6 **或** Token ≥ 4000 触发摘要，`RemoveMessage` 真正删除旧消息
- **幻觉校验**：LLM-as-Judge 两层检查——空检索预检 + 回答 vs 检索内容事实核查，未通过则强制重生成
- **会话结束总结**：自动生成全局摘要（含检索主题统计 + 问题清单）
- **2 个工具**：

| 工具 | 职责 | 核心能力 |
|------|------|----------|
| `search_knowledge_base` | 知识库检索（核心工具） | 查询改写 → 混合检索 → RRF 融合 → 重排序 → Parent-Child 展开 |
| `web_search` | 联网搜索 | Tavily API 实时搜索外部信息 |

### RAG 检索管线

Agent 调用最频繁的核心工具，自研五级管道：

```
Query Rewrite → Hybrid Search (Dense + BM25 + RRF) → Rerank (Cross-Encoder) → Parent-Child 展开 → 中文排版修复
```

#### 在线检索（对话时实时执行）

- **查询改写**：LLM 驱动指代消解 + 短查询扩展（"那纯棉的呢？" → "纯棉材质衣物的洗涤保养方法"）
- **混合检索**：Chroma 向量（语义）+ 自研 BM25（关键词，jieba 分词，RSJ-IDF）双路召回，RRF 算法融合
- **重排序**：DashScope gte-rerank Cross-Encoder 精排 Top-20 → Top-3（API 不可用时自动降级）
- **Parent-Child 展开**：Child 块（500 chars）精确检索 → Parent 块（2000 chars）提供完整上下文 → 去重返回 ≤5 篇
- **中文修复**：正则清洗分块导致的 CJK 断行、书名号内换行、行内多余空白

#### 离线上传（构建知识库）

```
原始文档(.txt/.pdf/.docx/.xlsx) → 格式解析 → 数据清洗 → Parent-Child 语义分块 → Chroma 向量存储
```

- **多格式支持**：TXT / PDF / DOCX / XLSX，自动解析提取纯文本
- **数据清洗**：去除乱码字符、合并断裂段落、统一标点与空白
- **语义分块**：Parent 块（2000 chars，overlap 200）+ Child 块（500 chars，overlap 50）
- **MD5 去重**：MySQL 层按内容 MD5 用户级去重
- **先写 MySQL 再写 Chroma**：MySQL 为权威源，Chroma 失败则回滚 MySQL 记录 + 删除上传文件
- **用户隔离**：每个用户独立 Chroma Collection（`rag_user_{id}`）

### 前端 SPA（Vue 3）

```
frontend_vue/
├── src/
│   ├── App.vue                          # 根组件（导航栏 + 路由视图 + Toast + 命令面板）
│   ├── router/index.js                  # Hash 路由（/ → /chat, /login, /register, /knowledge, /profile）
│   ├── views/
│   │   ├── ChatView.vue                 # 对话页（SSE 流式 + Markdown 渲染 + 工具状态卡片 + 幻觉提示）
│   │   ├── KnowledgeView.vue            # 知识库管理（拖拽上传 + 文档列表 + 删除）
│   │   ├── LoginView.vue / RegisterView.vue  # 登录 / 注册
│   │   └── ProfileView.vue             # 个人中心
│   ├── components/
│   │   ├── Navbar.vue                   # 顶部导航栏（响应式 + 移动端侧边栏）
│   │   ├── ToastContainer.vue           # 全局通知容器
│   │   └── CommandPalette.vue           # Ctrl+K 命令面板
│   ├── stores/toast.js                  # Pinia Toast 状态管理
│   ├── utils/markdown.js                # 自研 Markdown 渲染器（含 XSS 防护）
│   └── composables/                     # 组合式函数（键盘快捷键等）
```

- **Vue 3 Composition API** + Vue Router + Pinia
- **SSE 流式对话**：实时打字效果 + 工具调用状态卡片（🔍 检索中 / ✅ 已完成）
- **拖拽上传**：知识库页面支持文件拖拽 + 格式标签（.txt / .pdf / .docx / .xlsx）
- **自研 Markdown 渲染器**：正则管线，零第三方依赖，含 XSS 协议白名单防护
- **幻觉重试联动**：前端接收 `hallucination` 事件 → 清空气泡 → 等待 Agent 重新生成
- **响应式设计**：移动端侧边栏 + 骨架屏加载态
- **键盘快捷键**：Enter 发送 / Shift+Enter 换行 / Ctrl+K 命令面板

### 后端 API（FastAPI）

| 模块 | 方法 | 端点 | 说明 |
|------|------|------|------|
| 认证 | POST | `/api/auth/register` | 用户注册（bcrypt 哈希） |
| | POST | `/api/auth/login` | 登录（access 30min + refresh 7day） |
| | POST | `/api/auth/refresh` | 刷新 Token（原子防重放） |
| | POST | `/api/auth/logout` | 登出（refresh_token 加入 Redis 黑名单） |
| 对话 | POST | `/api/chat/stream` | 流式对话（SSE，8 种事件类型） |
| | POST | `/api/chat/` | 非流式对话（Agent 异常时保存错误回复） |
| | GET | `/api/chat/sessions` | 会话列表 |
| | GET | `/api/chat/history/{id}` | 会话历史 |
| | DELETE | `/api/chat/history/{id}` | 清空会话 |
| 知识库 | POST | `/api/knowledge/upload` | 上传文档（TXT/PDF/DOCX/XLSX，≤10MB） |
| | GET | `/api/knowledge/documents` | 文档列表 |
| | DELETE | `/api/knowledge/documents/{id}` | 删除文档（Chroma 向量 + 原文件同步清理） |
| 用户 | GET | `/api/user/me` | 当前用户信息 |
| | PUT | `/api/user/me` | 更新用户信息 |
| 系统 | GET | `/health` | 健康检查 |

### SSE 事件类型（Agent → 前端流式通信）

| 事件 | 触发条件 | 前端渲染 |
|------|----------|----------|
| `token` | `AIMessageChunk.content` | 流式打字效果 |
| `tool_start` | `AIMessage.tool_calls` | "🔍 正在检索知识库…" |
| `tool_end` | `ToolMessage` | "✅ 已完成" + 结果预览 |
| `summarize` | SystemMessage 含摘要 | "📝 对话已自动总结" |
| `hallucination` | 幻觉校验 SystemMessage | 警告提示 + 清空气泡 + 等待重生成 |
| `session_end` | AIMessage 含会话总结 | 总结卡片 |
| `thinking` | LLM 思考阶段 | 思考状态指示 |
| `done` | 流结束 | 触发格式化 + DOM 渲染 |

### 工程能力

- **延迟加载**：Embedding / BM25 / Chroma / Reranker 仅首次工具调用时初始化，闲聊零开销
- **实例池化**：按 session_id 缓存 AgentService，避免重复加载重型组件
- **并发安全**：`asyncio.Lock` + 双重检查模式防止竞争条件重复初始化
- **三级用户隔离**：Chroma `rag_user_{id}` + MySQL `WHERE user_id` + SQLite `checkpoints_agent_user_{id}.db`
- **优雅降级**：Redis 不可用自动跳过 / Tavily 未配置注册占位工具 / Reranker 失败降级为原始排序
- **Token 安全保障**：JWT `token_version` 机制（改密码 → version+1 → 所有旧 Token 失效）+ Redis SETNX 原子黑名单
- **XSS 防护**：前端 Markdown 渲染 URL 协议白名单（仅允许 http/https/mailto/tel，阻断 javascript:/data:）
- **评估框架**：100 条企业知识库测试集的召回率评估脚本（子串匹配 + 关键词覆盖率双重判定）

---

## 技术栈

| 层级 | 技术 |
|------|------|
| LLM | 通义千问 Qwen-Max（ChatTongyi，DashScope） |
| Embedding | text-embedding-v4（DashScope） |
| Reranker | gte-rerank Cross-Encoder（DashScope） |
| Agent 框架 | **LangGraph StateGraph**（自定义 6 节点 + 3 条件边） |
| 工具调用 | LangChain `bind_tools` + LangGraph `ToolNode` |
| 对话持久化 | AsyncSqliteSaver（LangGraph Checkpointer，用户隔离） |
| 向量数据库 | Chroma（本地持久化，Collection 级别隔离） |
| 关键词检索 | 自研 BM25（jieba 分词 + 倒排索引 + RSJ-IDF） |
| Web 框架 | FastAPI + SSE（sse-starlette） |
| 前端 | Vue 3（Composition API）+ Vue Router（Hash History）+ Pinia + Vite |
| Markdown 渲染 | 自研正则管线（零第三方依赖） |
| 关系数据库 | MySQL 8.0 + SQLAlchemy 2.0 Async（aiomysql） |
| 缓存 | Redis 7.x（优雅降级，不可用时自动跳过） |
| 认证 | PyJWT + bcrypt + Redis 黑名单 + token_version |
| 联网搜索 | Tavily Search API |

---

## 快速开始

### 1. 环境要求

- Python 3.10+
- Node.js 18+（前端构建）
- MySQL 8.0
- Redis 7.x（可选，不可用时自动降级）
- 阿里云 DashScope API Key → [获取地址](https://dashscope.console.aliyun.com/)
- Tavily API Key（可选，用于联网搜索）→ [获取地址](https://tavily.com/)

### 2. 安装

```bash
git clone https://github.com/six-seven67/Agent-RAG-LangGraph.git
cd Agent-RAG-LangGraph

# 后端依赖
pip install -r requirements.txt

# 前端依赖 + 构建
cd frontend_vue
npm install
npm run build
cd ..
```

### 3. 配置

```bash
cp .env.example .env
# 编辑 .env，必填项：
#   DASHSCOPE_API_KEY    — 阿里云 API Key（必填，LLM + Embedding + Reranker）
#   MYSQL_PASSWORD       — 数据库密码（必填）
# 可选项：
#   JWT_SECRET_KEY       — JWT 密钥（未设置时自动生成随机 32 位密钥）
#   TAVILY_API_KEY       — Tavily 联网搜索 Key
#   REDIS_URL            — Redis 连接（不可用时自动降级）
```

### 4. 初始化数据库

```bash
# 方式 A：导入 SQL schema
mysql -u root -p < data/init.sql

# 方式 B：Python 自动建表
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

---

## 项目结构

```
Agent-RAG-LangGraph/
├── app/
│   └── fastapi_server.py              # FastAPI 主入口 + 生命周期管理
├── frontend_vue/                       # 前端 SPA（Vue 3 + Vite）
│   ├── index.html                      #   入口页面
│   ├── vite.config.js                  #   Vite 配置（API 代理 + 开发 proxy）
│   └── src/
│       ├── App.vue                     #   根组件
│       ├── main.js                     #   应用入口（路由 + Pinia + 全局样式）
│       ├── router/index.js             #   Hash 路由 + beforeEach 鉴权守卫
│       ├── views/                      #   页面视图
│       │   ├── ChatView.vue            #     对话页（SSE 流式 + Markdown + 幻觉联动）
│       │   ├── KnowledgeView.vue       #     知识库管理（拖拽上传 + 列表 + 删除）
│       │   ├── LoginView.vue           #     登录
│       │   ├── RegisterView.vue        #     注册
│       │   └── ProfileView.vue         #     个人中心
│       ├── components/                 #   通用组件
│       │   ├── Navbar.vue              #     导航栏（响应式 + 移动端侧边栏）
│       │   ├── ToastContainer.vue      #     通知容器
│       │   └── CommandPalette.vue      #     命令面板（Ctrl+K）
│       ├── api/index.js                #   API 封装（含 SSE stream + Token 自动刷新）
│       ├── stores/toast.js             #   Pinia Toast 状态管理
│       ├── utils/markdown.js           #   自研 Markdown → HTML 渲染器（正则管线）
│       └── composables/                #   组合式函数（键盘快捷键等）
├── src/
│   ├── config.py                      # 全局配置（环境变量 + 工厂函数 + JWT 自检）
│   ├── agent/                          # Agent 决策引擎
│   │   ├── __init__.py                 #   公共 API
│   │   ├── state.py                    #   AgentState（messages / summary / retry_count）
│   │   ├── prompts.py                  #   4 个 Prompt 模板
│   │   ├── classifier.py               #   意图分类（闲聊 / 结束会话规则匹配）
│   │   ├── formatter.py                #   回答后处理（旧格式转换 + 空行清理）
│   │   ├── streaming.py                #   流式事件分类（8 种 SSE 事件）
│   │   ├── nodes.py                    #   6 个节点实现（与图编排解耦）
│   │   ├── service.py                  #   AgentService 编排层（图构建 + 路由 + 并发安全）
│   │   └── tools/                      #   Agent 工具集
│   │       ├── __init__.py             #     工具导出
│   │       ├── search_kb.py            #     知识库检索（核心工具）
│   │       └── web_search.py           #     联网搜索（Tavily API）
│   ├── rag/                            # RAG 查询改写
│   │   └── rewriter.py                #   Query Rewrite（指代消解 + 关键词扩展）
│   ├── retrieval/                      # 检索引擎（可插拔）
│   │   ├── vector_store.py             #   Chroma 向量检索
│   │   ├── bm25.py                     #   自研 BM25 关键词检索
│   │   ├── hybrid.py                   #   混合检索 + RRF 融合
│   │   └── reranker.py                 #   gte-rerank Cross-Encoder 重排序
│   ├── knowledge/                      # 知识库管理
│   │   ├── service.py                  #   文档上传 / 向量存储 / 按 doc_id 删除
│   │   ├── parser.py                   #   多格式解析（TXT / PDF / DOCX / XLSX）
│   │   ├── cleaner.py                  #   数据清洗（乱码 / 断行 / 标点统一）
│   │   └── splitter.py                 #   Parent-Child 语义分块器
│   ├── storage/                        # 对话历史存储
│   │   ├── file_store.py               #   JSON 文件后端
│   │   └── mysql_store.py              #   MySQL 后端
│   ├── api/                            # REST API 路由
│   │   ├── auth.py                     #   认证（注册/登录/刷新/登出）
│   │   ├── chat.py                     #   对话（SSE 流式 + 非流式 + 实例池）
│   │   ├── knowledge.py                #   知识库管理（上传/列表/删除）
│   │   └── user.py                     #   用户信息 + 改密码（token_version 递增）
│   ├── auth/                           # JWT 认证模块
│   │   ├── jwt_handler.py              #   Token 生成 / 校验（含 token_version）
│   │   ├── security.py                 #   密码哈希 + 用户依赖注入（验证 token_version）
│   │   └── schemas.py                  #   Pydantic 请求/响应模型
│   ├── db/                             # 数据库 ORM
│   │   ├── database.py                 #   SQLAlchemy Async Engine + 自动建表
│   │   └── models.py                   #   ORM 模型（User / KnowledgeDoc）
│   └── cache/
│       └── redis_client.py             #   Redis 客户端（优雅降级 + SETNX 原子操作）
├── data/
│   ├── init.sql                        # 数据库初始化 Schema
│   └── migration_add_token_version.sql # 幂等迁移脚本（token_version 列）
├── eval/                               # 评估框架
│   ├── rag_eval_recall.py              #   100 条测试集召回率评估脚本
│   └── RAG召回率测试集_100条完整版.txt  #   企业知识库测试集
├── docs/                               # 项目文档（本地参考，不上传）
├── run.py                              # 便捷启动入口
├── requirements.txt                    # Python 依赖
└── .env.example                        # 环境变量模板
```

---

## 架构详解

### Agent 状态流转

```
START
  │
  ▼
┌──────────────────────┐
│   classify_intent    │  规则匹配（零 LLM 延迟）
│                      │
│  闲聊关键词命中？    │─── direct_chat ──► END
│  结束关键词命中？    │─── end_session ──► session_end_summary ──► END
│  都不匹配 → continue │─── summarize
└──────┬───────────────┘
       │ continue
       ▼
┌──────────────────────┐
│     summarize        │  双阈值触发对话压缩
│                      │
│  rounds < 6 且       │── 短路跳过
│  tokens < 4000？     │
│  距上次 < 3 轮？     │── 短路跳过
│  触发条件满足：       │
│  → LLM 压缩旧消息    │── RemoveMessage 真正删除
│  → 增量合并已有摘要  │   保留最近 6 条消息
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐     有 tool_calls
│       agent          │──────────────────────┐
│  LLM + 2 工具         │                      │
│  决策：检索 or 回答？ │◄─────────────────────┘
└──────┬───────────────┘
       │ 无 tool_calls          │ 有 tool_calls
       ▼                        ▼
┌──────────────────────┐   ┌──────────────────────┐
│  hallucination_check │   │       tools          │
│  两层检查：           │   │  ToolNode 执行        │
│  1. 空检索预检        │   │                      │
│  2. LLM 事实核查       │   │  search_kb ──────────┤
│                      │   │  web_search ──────────┤
│  PASS → END          │   └──────┬───────────────┘
│  FAIL → agent（重试） │          │
└──────────────────────┘          └──► agent（ReAct 循环）
```

### 知识库使用流程

```
                    离线上传（构建知识库）
                    ════════════════
                    用户选择文件
                          │
                          ▼
                    ┌───────────┐
                    │  parser   │  格式解析 → 提取纯文本
                    │  cleaner  │  数据清洗 → 去除乱码/合并断行
                    │ splitter  │  Parent-Child 语义分块
                    └─────┬─────┘
                          │
                          ▼
                    ┌───────────┐
                    │  MySQL    │  先写权威记录 + MD5 去重
                    │  Chroma   │  再写向量（失败则回滚 MySQL）
                    └─────┬─────┘
                          │
                          ▼
                     知识库就绪 ✓


                    在线检索（对话时实时执行）
                    ════════════════
                    用户提问
                       │
                       ▼
                    ┌──────────────┐
                    │ QueryRewriter│  指代消解 + 短查询扩展
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────┐
                    │HybridRetrieve│  Dense + BM25 → RRF 融合
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────┐
                    │ Reranker     │  Cross-Encoder 精排 Top-3
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────┐
                    │ Parent-Child │  Child 命中 → Parent 上下文
                    │ 展开 + 去重   │  最多返回 5 篇文段
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────┐
                    │ LLM 生成     │  基于文档上下文生成回答
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────┐
                    │ Hallucination│  回答 vs 检索内容事实核查
                    │ Check        │  FAIL → Agent 重新生成
                    └──────────────┘
```

---

## 配置参考

完整环境变量见 `.env.example`，关键配置：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DASHSCOPE_API_KEY` | — | 阿里云 API Key（**必填**，LLM + Embedding + Reranker） |
| `MYSQL_PASSWORD` | — | MySQL 密码（**必填**） |
| `JWT_SECRET_KEY` | 自动生成 | JWT 密钥（未设置时自动生成随机 32 位 hex） |
| `TAVILY_API_KEY` | — | 联网搜索 Key（可选） |
| `REDIS_URL` | `redis://localhost:6379` | Redis 连接（可选，失败自动降级） |
| `CHAT_MODEL_NAME` | `qwen3-max` | LLM 模型 |
| `EMBEDDING_MODEL_NAME` | `text-embedding-v4` | Embedding 模型 |
| `AGENT_SUMMARY_TRIGGER_ROUNDS` | `6` | 触发对话摘要的轮数阈值 |
| `AGENT_SUMMARY_TOKEN_THRESHOLD` | `4000` | 触发对话摘要的 Token 数阈值（~2000 tokens） |
| `AGENT_SUMMARY_KEEP_RECENT` | `6` | 摘要后保留的最近消息数 |
| `AGENT_SUMMARY_MIN_INTERVAL_ROUNDS` | `3` | 两次摘要间最小轮数间隔 |
| `PARENT_CHUNK_SIZE` | `2000` | Parent 块大小（上下文窗口） |
| `CHILD_CHUNK_SIZE` | `500` | Child 块大小（检索精度） |
| `RERANKER_TOP_N` | `3` | 重排序后返回的文档数 |
| `QUERY_REWRITE_MIN_LENGTH` | `15` | 触发查询改写的最短问题长度 |

---

## 架构演进

```
v1.x (Demo)         v2.x (RAG 管线)      v3.0.0 (Agent 黑盒)   v3.3.0 (Agent 自定义)
─────────           ──────────────       ──────────────────    ─────────────────────
用户输入             用户输入              用户输入               用户输入
  ↓                    ↓                     ↓                     ↓
向量检索             Query Rewrite         create_agent           classify_intent
  ↓                    ↓                   LLM + 4 tools          规则快速路由
LLM 生成             Hybrid Search              ↓              ↙    ↓    ↘
                     + Rerank              工具调用循环         闲聊    结束   summarize
                     + Parent-Child                             直达    会话     ↓
                          ↓                                                   agent ⇄ tools
                     LLM 流式生成                                                 ↓
                                                                       hallucination_check
                                                                                ↓
                                                                       session_end_summary

v1 → v2:  从简单向量检索升级为五级 RAG 管线（改写 → 混合 → 重排 → 展开 → 修复）
v2 → v3.0: 引入 Agent 决策层，LLM 自主选择工具
v3.0 → v3.3:
  - 从黑盒 create_agent 迁移至自定义 StateGraph（6 节点 + 3 条件边）
  - 新增：意图路由 / 双阈值压缩 / 幻觉校验 / 会话总结
  - 去除客服定位 → 聚焦知识库文档问答
  - 4 工具精简为 2 工具（search_knowledge_base + web_search）
  - 前端从原生 JS 重构为 Vue 3 SPA
  - 安全加固：JWT token_version / Redis 原子黑名单 / XSS 协议白名单 / 并发锁
```

---

## License

MIT
