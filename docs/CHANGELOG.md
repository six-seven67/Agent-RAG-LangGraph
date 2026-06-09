# 修改日志（CHANGELOG）

> ⚠️ **仅本地使用，不上传 Git。** 记录每次 Bug 修复、废弃代码替换、版本升级等变更。

---

## 2026-06-07 — v3.0.0: RAG → Agent 智能客服升级

### 修改内容
将固定管线 RAG 系统升级为基于 LangGraph ReAct Agent 的智能客服系统。

**核心变化**：
- RAG（v2.x）：固定流程「查询改写 → 检索 → 重排序 → 生成」
- Agent（v3.x）：LLM 自主决策 → 查知识库 / 查FAQ / 追问 / 转人工

### 为什么要修改
RAG 管线的局限：
1. 所有问题都走同一流程 — 闲聊「你好」也会触发检索
2. 无法处理多步骤推理 — 检索不充分时不能自动优化查询重试
3. 无法主动追问 — 用户问题模糊时直接检索导致答非所问
4. 缺少转人工机制 — 知识库无匹配时容易编造答案

Agent 模式通过 LangGraph `create_react_agent` + 工具调用解决上述问题。

### 新增文件
- `src/agent/__init__.py` — Agent 模块入口
- `src/agent/tools.py` — 3 个 Agent 工具：
  - `search_knowledge_base`（P0）：封装 RAG 检索管道
  - `lookup_faq`（P1）：高频常见问题快速匹配
  - `escalate_to_human`（P1）：转接人工客服
- `src/agent/service.py` — AgentService 类，基于 `create_react_agent`

### 修改文件
- `src/api/chat.py` — SSE 流式增强（新增 tool_start/tool_end/thinking 事件），切换到 AgentService
- `app/fastapi_server.py` — title/version 更新为 Agent 智能客服系统 v3.0.0
- `src/config_data.py` — 新增 Agent 配置项（agent_mode_enabled 等）
- `CHANGELOG.md` — 本文档

### 保留不变（向后兼容）
- `src/rag_async.py` — 保留原 RAG 服务，可通过 `AGENT_MODE=false` 切换回 RAG 模式
- `src/auth/`、`src/db/`、`src/cache/` — 认证/数据库/缓存层完全不变
- 所有对外 API 端点路径不变

### 涉及文件
- `src/agent/__init__.py`：新建
- `src/agent/tools.py`：search_knowledge_base + lookup_faq + escalate_to_human 工具
- `src/agent/service.py`：AgentService（create_react_agent）
- `src/api/chat.py`：SSE 事件增强 + Agent 服务切换
- `app/fastapi_server.py`：版本号更新
- `src/config_data.py`：Agent 配置项

### 验证结果
- ✅ Agent ainvoke() 正确区分知识问题（调用工具）和闲聊（直接回答）
- ✅ Agent astream() 流式正确产出 token / tool_start / tool_end 事件
- ✅ `create_react_agent` → `create_agent` 弃用已修复
- ✅ 无 LangChain 弃用警告（仅无关的 jieba 警告）

---

## 2026-06-07 — 前端美化 + 文档升级

### 修改内容
1. **前端 CSS 全面美化**：新配色方案（warm indigo）、渐变按钮、圆角阴影、动画增强、响应式优化
2. **前端 JS 增强**：Agent 工具事件支持（tool_start/tool_end 状态卡片）、会话标题显示（使用 API 返回的 title 而非 UUID）
3. **品牌升级**：RAG 智能客服 → Agent 智能客服（HTML/CSS/JS 全部更新）
4. **文档升级**：README.md、README_PROJECT.md、README_API.md、RAG优化.md、GIT_GUIDE.md 全部更新为 Agent v3.0.0 内容

### 为什么要修改
- 前端 UI 过于朴素，需要提升用户体验
- Agent 模式新增 tool_start/tool_end 事件，前端需要对应的展示能力
- 会话列表用 UUID 前缀显示，实际 API 已返回有意义的 title
- 文档内容停留在 v2.x RAG 时代，v3.0.0 Agent 升级后未同步更新

### 涉及文件
- `frontend/css/style.css`：全面重写（CSS Variables、卡片、渐变、动画、工具状态样式）
- `frontend/js/chat.js`：Agent 事件处理（tool_start/tool_end）+ 会话标题显示
- `frontend/js/api.js`：SSE 流解析新增 tool_start/tool_end/thinking 事件回调
- `frontend/js/auth.js`：品牌文字更新
- `frontend/js/app.js`：品牌文字更新
- `frontend/index.html`：title 和 navbar 品牌更新
- `README.md`：重写为 Agent v3.0.0
- `README_PROJECT.md`：新增 Agent 架构、工具说明、决策流程图
- `README_API.md`：新增 Agent SSE 事件文档、前端对接示例更新
- `RAG优化.md`：新增"实施记录 0：Agent 升级"章节
- `GIT_GUIDE.md`：版本号更新，tag 示例更新为 v3.0.0

### 验证结果
- ✅ 前端 CSS 无语法错误
- ✅ 前端 JS SSE 解析兼容 tool_start/tool_end/thinking 事件
- ✅ 所有 .md 文件内容与当前 v3.0.0 架构一致
- ✅ 品牌文字全部统一为 Agent 智能客服系统

---

## 2026-06-07 — LangGraph 迁移：替换已弃用的 RunnableWithMessageHistory

### 修改内容
将 `src/rag_async.py` 中的 `RunnableWithMessageHistory` 替换为 LangGraph 的 `StateGraph` + `AsyncSqliteSaver`。

### 为什么要修改
LangChain 在较新版本中将 `RunnableWithMessageHistory` 标记为已弃用（deprecated），运行时产生以下警告：

```
LangChainDeprecationWarning: RunnableWithMessageHistory is deprecated.
Use LangGraph's built-in persistence instead.
```

官方推荐的替代方案是使用 LangGraph 的内置持久化机制。LangGraph 的 checkpointer 系统：
- 自动管理对话历史的加载/保存
- 支持 SQLite 持久化（服务重启不丢失）
- 原生支持异步（无 async/sync 桥接死锁风险）
- 支持 `stream_mode="messages"` 实现 token 级别流式输出

### 具体改动

**`src/rag_async.py`** — 核心改动：
1. **移除**：`RunnableWithMessageHistory`、`RunnableLambda`、`RunnablePassthrough` 导入
2. **新增**：LangGraph `StateGraph`、`START`/`END`、`add_messages` reducer、`AsyncSqliteSaver`
3. **State 定义**：`RagState(TypedDict)` — `messages`（由 checkpointer 管理）+ `context`
4. **Graph 结构**：`START → retrieve → generate → END`
   - `_retrieve_node`: 查询改写 → 混合检索 → 重排序 → Parent-Child 展开
   - `_generate_node`: 提示词模板 + ChatTongyi 生成
5. **持久化**：`AsyncSqliteSaver` 使用用户隔离的 SQLite 数据库文件
   - 默认：`chat_history/checkpoints_default.db`
   - 用户隔离：`chat_history/checkpoints_user_{user_id}.db`
6. **流式输出**：使用 `graph.astream(stream_mode="messages")` 实现 token 级别流式

**`requirements.txt`** — 新增依赖：
- `langgraph>=1.1.0`
- `langgraph-checkpoint-sqlite>=3.1.0`
- `aiosqlite>=0.22.0`

### API 兼容性
对外接口完全兼容，无需修改调用方代码：
- `AsyncRagService(user_id=...)` — 构造函数签名不变
- `.astream(input_data, session_config)` — 流式调用不变
- `.ainvoke(input_data, session_config)` — 非流式调用不变
- `.sync_stream()` / `.sync_invoke()` — 同步兼容包装器不变

### 验证结果
- ✅ 导入成功，无 LangChain 弃用警告
- ✅ `ainvoke()` 非流式 RAG 调用正常
- ✅ `astream()` 流式 RAG 调用正常（token 级别输出）
- ✅ 用户隔离：不同 user_id 使用独立 SQLite 数据库
- ✅ `stream_mode="messages"` 正常工作

---

## 2026-06-07 — 修复：系统不响应（async/sync 桥接死锁）

### 问题
用户在对话页面发送消息后，系统不返回任何回答，浏览器一直等待。

### 根因
`src/history_store_mysql.py` 中的 `MySQLChatMessageHistory` 在 FastAPI 异步事件循环中被
`RunnableWithMessageHistory` 同步调用，`messages` 属性内部使用 `asyncio.run()` 在独立线程
创建新的 SQLAlchemy 异步会话，导致事件循环死锁。

调用链：
```
FastAPI async handler
  → RunnableWithMessageHistory (同步接口)
    → MySQLChatMessageHistory.messages (property)
      → asyncio.run(get_session())  ← 死锁！在已有事件循环中创建新循环
```

### 修复方法
将对话历史管理解耦为两层：

1. **RAG 链内部**（`src/rag_async.py`）：使用 `FileChatMessageHistory`（同步文件 I/O，无死锁）
2. **API 层**（`src/api/chat.py`）：独立管理 MySQL 对话历史（用于前端展示）

在调用 RAG 链之前/之后，API 层自行将 user/assistant 消息写入 MySQL 的 `chat_history` 表。

### 涉及文件
- `src/rag_async.py`：`_get_history` 闭包始终使用 `FileChatMessageHistory`
- `src/api/chat.py`：`chat()` 和 `chat_stream()` 中手动保存用户消息和 AI 回答到 MySQL
- `src/history_store_mysql.py`：保留但不在 RAG 链中使用

---

## 2026-06-07 — 修复：会话列表显示 UUID 而非有意义标题

### 问题
`GET /api/chat/sessions` 返回的会话列表以 `session_id` (UUID) 作为标识，
前端无法区分不同会话的内容。

### 修复方法
在 `list_sessions()` 中添加子查询：对每个 `session_id`，查询该会话中最早的
一条 `role="user"` 消息内容，截断到 50 字符作为 `title` 字段返回。

### 涉及文件
- `src/api/chat.py`：`list_sessions()` 方法

---

## 2026-06-07 — 修复：passlib + bcrypt 5.0.0 不兼容

### 问题
安装依赖时报错：
```
AttributeError: module 'bcrypt' has no attribute '__about__'
ValueError: password cannot be longer than 72 bytes
```

### 根因
passlib 1.7.4 依赖 bcrypt 的 `__about__` 模块来检测版本，但 bcrypt 5.0.0
移除了该模块。此外 passlib 内部对密码长度的处理与 bcrypt 5.0.0 不兼容。

### 修复方法
移除 passlib 依赖，改用 bcrypt 原生 API：

```python
# 密码哈希
def hash_password(password: str) -> str:
    pwd_bytes = password.encode("utf-8")[:_BCRYPT_MAX_LENGTH]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")

# 密码验证
def verify_password(plain_password: str, hashed_password: str) -> bool:
    pwd_bytes = plain_password.encode("utf-8")[:_BCRYPT_MAX_LENGTH]
    return bcrypt.checkpw(pwd_bytes, hashed_password.encode("utf-8"))
```

### 涉及文件
- `src/auth/security.py`：`hash_password()` 和 `verify_password()` 函数
- `requirements.txt`：移除 `passlib`

---

## 模板

```markdown
## YYYY-MM-DD — 标题

### 问题
（如果是 Bug 修复）描述现象和影响。

### 根因
（如果是 Bug 修复）技术层面的根本原因分析。

### 修改内容
描述具体改了什么。

### 为什么要修改
（如果是废弃代码替换）说明原技术为何被弃用，新技术有何优势。

### 涉及文件
- 文件路径：改动说明

### 验证结果
- ✅ 验证项
```
# 循环导入问题修复

## 🐛 **问题描述**

运行 FastAPI 服务时出现循环导入错误：

```python
ImportError: cannot import name 'QueryRewriter' from partially initialized module 
'src.rag' (most likely due to a circular import)
```

---

## 🔍 **问题分析**

### **循环导入路径**

```
src/api/chat.py
  → from src.agent.service import AgentService
    → src/agent/service.py (第44行)
      → from src.rag import QueryRewriter
        → src/rag/__init__.py (第6行)
          → from src.rag.async_service import AsyncRagService
            → src/rag/async_service.py (第49行)
              → from src.rag import QueryRewriter  # ❌ 循环！
```

### **根本原因**

1. `agent/service.py` 通过 `from src.rag import QueryRewriter` 导入
2. 这会触发 `src/rag/__init__.py` 的初始化
3. `__init__.py` 首先导入 `async_service.AsyncRagService`
4. `async_service.py` 又尝试从 `src.rag` 导入 `QueryRewriter`
5. 此时 `src.rag` 模块尚未完全初始化（还在执行 `__init__.py`）
6. Python 抛出循环导入错误

---

## ✅ **解决方案**

### **修改前（错误）**

```python
# src/agent/service.py (第44行)
from src.rag import QueryRewriter

# src/rag/async_service.py (第49行)
from src.rag import QueryRewriter
```

### **修改后（正确）**

```python
# src/agent/service.py (第44行)
from src.rag.rewriter import QueryRewriter

# src/rag/async_service.py (第49行)
from src.rag.rewriter import QueryRewriter
```

---

## 📋 **最佳实践**

### **避免循环导入的规则**

1. ✅ **直接导入具体模块**，不要通过包间接导入
   ```python
   # 好
   from src.rag.rewriter import QueryRewriter
   
   # 避免（可能触发循环）
   from src.rag import QueryRewriter
   ```

2. ✅ **延迟导入**（在函数内部导入）
   ```python
   def some_function():
       from src.rag import QueryRewriter  # 运行时才导入
       ...
   ```

3. ✅ **重构代码结构**，消除循环依赖
   ```
   如果 A → B → C → A 形成循环
   考虑将共享部分提取到 D，让 A、B、C 都依赖 D
   ```

4. ❌ **避免在 `__init__.py` 中导入所有子模块**
   ```python
   # 可能导致问题的写法
   from src.rag.async_service import AsyncRagService
   from src.rag.sync_service import RagService
   from src.rag.rewriter import QueryRewriter
   ```

---

## 🔧 **相关文件修改**

### **1. src/rag/async_service.py**

```diff
- from src.rag import QueryRewriter
+ from src.rag.rewriter import QueryRewriter
```

### **2. src/agent/service.py**

```diff
- from src.rag import QueryRewriter
+ from src.rag.rewriter import QueryRewriter
```

---

## 🧪 **验证修复**

### **方法 1：启动 FastAPI 服务**

```bash
python run.py
```

访问 `http://127.0.0.1:8000/docs` 确认服务正常启动。

### **方法 2：测试聊天接口**

```bash
curl -X POST "http://127.0.0.1:8000/api/chat/stream?query=你好" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

应该返回流式响应，而不是 500 错误。

### **方法 3：运行测试脚本**

```bash
python test_langgraph_improvement.py
```

所有测试应该通过。

---

## 📚 **相关知识**

### **Python 模块导入机制**

1. **首次导入**：Python 执行模块文件，将结果缓存到 `sys.modules`
2. **重复导入**：直接从 `sys.modules` 获取，不重新执行
3. **部分初始化**：模块正在执行但未完成时，`sys.modules` 中已有条目但不完整

### **循环导入的典型场景**

```python
# a.py
from b import B  # 触发 b.py 的执行

class A:
    pass

# b.py
from a import A  # ❌ a.py 尚未执行完成，A 未定义

class B:
    pass
```

### **解决循环导入的策略**

| 策略 | 适用场景 | 示例 |
|------|---------|------|
| 直接导入具体模块 | 简单的循环 | `from pkg.module import Class` |
| 延迟导入 | 仅在函数中使用 | 在函数内部 `import` |
| 依赖注入 | 工具类/服务类 | 通过参数传入依赖 |
| 重构代码 | 复杂的循环 | 提取共享模块 |

---

## 💡 **总结**

这次修复的核心原则：

> **始终直接导入具体的模块文件，避免通过包的 `__init__.py` 间接导入。**

这样可以：
- ✅ 避免循环导入
- ✅ 提高代码可读性（明确依赖来源）
- ✅ 减少不必要的模块加载

---

## 🔗 **相关文档**

- [Python 官方文档 - 模块导入](https://docs.python.org/3/reference/import.html)
- [LangGraph 改进文档](./LANGGRAPH_IMPROVEMENT.md)
- [FastAPI 最佳实践](https://fastapi.tiangolo.com/tutorial/bigger-applications/)
