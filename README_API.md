# RAG 智能客服系统 — 前端 API 对接文档

> **用途**：本文档写给前端开发者或 AI 编码助手，用于设计/开发本系统的前端界面（Web、小程序、App 等）。

---

## 一、基本信息

| 项目 | 说明 |
|------|------|
| **Base URL** | `http://localhost:8000`（开发环境） |
| **认证方式** | JWT Bearer Token（`Authorization: Bearer <access_token>`） |
| **Token 有效期** | access_token: 30分钟 / refresh_token: 7天 |
| **请求格式** | JSON（`Content-Type: application/json`） |
| **流式响应** | SSE（`text/event-stream`） |
| **文件上传** | `multipart/form-data` |

## 二、认证流程

### 2.1 整体流程

```
注册 → 登录（获取 token）→ 携带 token 调用业务 API
                                ↓
                         token 过期 → 用 refresh_token 换新 → 继续调用
                                ↓
                         登出 → 清除本地 token
```

### 2.2 Token 存储建议

- access_token：内存变量（不持久化，30分钟过期后自动刷新）
- refresh_token：localStorage 或安全 cookie（7天有效）
- 每次打开应用时，先用 refresh_token 换新的 access_token

---

## 三、接口详细说明

### 3.1 认证模块 `/api/auth`

#### POST `/api/auth/register` — 注册

```
Method: POST
URL: /api/auth/register
Content-Type: application/json
Auth: 不需要
```

**请求体：**
```json
{
  "username": "zhangsan",
  "password": "mypassword123",
  "email": "zhangsan@example.com"
}
```
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| username | string | ✅ | 2-50字符，仅允许字母/数字/下划线/中文 |
| password | string | ✅ | 6-128字符 |
| email | string | ❌ | 邮箱地址 |

**成功响应 (201)：**
```json
{
  "access_token": "eyJhbGciOi...",
  "refresh_token": "eyJhbGciOi...",
  "token_type": "bearer"
}
```

**错误响应：**
```json
// 409 用户名已存在
{ "detail": "用户名已存在" }
```

---

#### POST `/api/auth/login` — 登录

```
Method: POST
URL: /api/auth/login
Content-Type: application/json
Auth: 不需要
```

**请求体：**
```json
{
  "username": "zhangsan",
  "password": "mypassword123"
}
```

**成功响应 (200)：**
```json
{
  "access_token": "eyJhbGciOi...",
  "refresh_token": "eyJhbGciOi...",
  "token_type": "bearer"
}
```

**错误响应：**
```json
// 401 凭据错误
{ "detail": "用户名或密码错误" }

// 403 账号禁用
{ "detail": "账号已被禁用" }
```

---

#### POST `/api/auth/refresh` — 刷新 Token

```
Method: POST
URL: /api/auth/refresh
Content-Type: application/json
Auth: 不需要
```

**请求体：**
```json
{
  "refresh_token": "eyJhbGciOi..."
}
```

**成功响应 (200)：**
```json
{
  "access_token": "eyJhbGciOi...(新)",
  "refresh_token": "eyJhbGciOi...(新)",
  "token_type": "bearer"
}
```

> ⚠️ 刷新后旧的 refresh_token 立即失效，请用新返回的一对 token 替换本地存储。

---

#### POST `/api/auth/logout` — 登出

```
Method: POST
URL: /api/auth/logout
Content-Type: application/json
Auth: ✅ Bearer <access_token>
```

**请求体：** 无

**成功响应 (200)：**
```json
{ "message": "已登出，请清除本地 token" }
```

> 前端收到响应后应清除本地存储的所有 token。

---

#### GET `/api/auth/me` — 获取当前用户信息

```
Method: GET
URL: /api/auth/me
Auth: ✅ Bearer <access_token>
```

**成功响应 (200)：**
```json
{
  "id": 1,
  "username": "zhangsan",
  "email": "zhangsan@example.com",
  "is_active": true,
  "created_at": "2026-06-07 12:00:00"
}
```

---

### 3.2 对话模块 `/api/chat`

#### GET `/api/chat/sessions` — 获取会话列表

```
Method: GET
URL: /api/chat/sessions
Auth: ✅ Bearer <access_token>
```

**成功响应 (200)：**
```json
{
  "sessions": [
    {
      "session_id": "a1b2c3d4-...",
      "title": "针织毛衣怎么洗？",
      "last_active": "2026-06-07T15:30:00"
    }
  ],
  "total": 1
}
```

> `title` 取自该会话中第一条用户消息（截断到 50 字符），前端直接用它显示会话名称，无需展示 UUID。

> 前端可据此渲染「历史会话列表」。

---

#### GET `/api/chat/history/{session_id}` — 获取会话历史

```
Method: GET
URL: /api/chat/history/a1b2c3d4-...
Auth: ✅ Bearer <access_token>
```

**成功响应 (200)：**
```json
{
  "session_id": "a1b2c3d4-...",
  "messages": [
    { "role": "user", "content": "针织毛衣怎么洗？", "created_at": "2026-06-07T15:30:00" },
    { "role": "assistant", "content": "针织毛衣建议冷水手洗...", "created_at": "2026-06-07T15:30:05" }
  ],
  "total": 2
}
```

> 用于进入某个历史会话时加载全部对话记录。

---

#### DELETE `/api/chat/history/{session_id}` — 删除会话

```
Method: DELETE
URL: /api/chat/history/a1b2c3d4-...
Auth: ✅ Bearer <access_token>
```

**成功响应 (200)：**
```json
{ "message": "会话 a1b2c3d4-... 已清空" }
```

---

#### POST `/api/chat/` — 发送消息（非流式）

```
Method: POST
URL: /api/chat/?query=针织毛衣怎么洗？&session_id=a1b2c3d4-...
Content-Type: 无请求体（参数在 URL query string）
Auth: ✅ Bearer <access_token>
```

**Query 参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| query | string | ✅ | 用户提问内容 |
| session_id | string | ❌ | 会话 ID，不传则自动创建新会话 |

**成功响应 (200)：**
```json
{
  "session_id": "a1b2c3d4-...",
  "query": "针织毛衣怎么洗？",
  "answer": "针织毛衣建议使用冷水手洗，洗涤后平铺晾干..."
}
```

> ⚠️ 此接口为**同步等待**，大模型生成完成才返回，适合后台调用。前端建议使用 `/stream` 接口。

---

#### POST `/api/chat/stream` — 发送消息（SSE 流式，推荐）

```
Method: POST
URL: /api/chat/stream?query=针织毛衣怎么洗？&session_id=a1b2c3d4-...
Content-Type: 无请求体（参数在 URL query string）
Accept: text/event-stream
Auth: ✅ Bearer <access_token>
```

**Query 参数：**（同非流式接口）

**SSE 事件流格式：**

```
event: token
data: 针织

event: token
data: 毛衣

event: token
data: 建议

...

event: token
data: 。

event: done
data: [DONE]
```

**前端 SSE 消费示例（JavaScript）：**
```javascript
async function sendMessage(query, sessionId) {
  const params = new URLSearchParams({ query });
  if (sessionId) params.append('session_id', sessionId);

  const response = await fetch(
    `http://localhost:8000/api/chat/stream?${params}`,
    {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${accessToken}`,
        'Accept': 'text/event-stream',
      },
    }
  );

  const reader = response.body
    .pipeThrough(new TextDecoderStream())
    .getReader();

  let fullAnswer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    // 解析 SSE 格式
    const lines = value.split('\n');
    for (const line of lines) {
      if (line.startsWith('event: token')) continue; // 跳过 event 行
      if (line.startsWith('data: ')) {
        const data = line.slice(6);
        if (data === '[DONE]') break;
        fullAnswer += data;
        // 逐字更新 UI
        updateMessageBubble(data);
      }
    }
  }

  return fullAnswer;
}
```

> 关键点：每个 `data:` 行是一个文本 token，前端应**逐字追加**到对话气泡中。

---

### 3.3 知识库模块 `/api/knowledge`

#### POST `/api/knowledge/upload` — 上传文档

```
Method: POST
URL: /api/knowledge/upload
Content-Type: multipart/form-data
Auth: ✅ Bearer <access_token>
```

**请求体（form-data）：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file | File | ✅ | TXT 文件（UTF-8 编码） |

**成功响应 (200)：**
```json
{
  "message": "上传成功，共 15 个语义块",
  "filename": "洗涤养护.txt",
  "md5": "a1b2c3d4e5f6...",
  "chunk_count": 15
}
```

**错误响应：**
```json
// 400 格式错误
{ "detail": "仅支持 TXT 格式文件" }

// 409 重复上传
{ "detail": "文件已存在，请勿重复上传" }
```

---

#### GET `/api/knowledge/documents` — 文档列表

```
Method: GET
URL: /api/knowledge/documents
Auth: ✅ Bearer <access_token>
```

**成功响应 (200)：**
```json
{
  "documents": [
    {
      "id": 1,
      "filename": "洗涤养护.txt",
      "md5_hash": "a1b2c3d4e5f6...",
      "chunk_count": 90,
      "created_at": "2026-06-07T12:00:00"
    }
  ],
  "total": 1
}
```

> 前端可据此渲染「知识库文件管理」页面。

---

#### DELETE `/api/knowledge/documents/{doc_id}` — 删除文档

```
Method: DELETE
URL: /api/knowledge/documents/1
Auth: ✅ Bearer <access_token>
```

**成功响应 (200)：**
```json
{ "message": "文档 '洗涤养护.txt' 已删除" }
```

**错误响应 (404)：**
```json
{ "detail": "文档不存在或无权访问" }
```

---

### 3.4 用户模块 `/api/user`

#### GET `/api/user/profile` — 个人信息

```
Method: GET
URL: /api/user/profile
Auth: ✅ Bearer <access_token>
```

**响应：**（同 `/api/auth/me`）

---

#### PUT `/api/user/profile` — 更新个人信息

```
Method: PUT
URL: /api/user/profile?email=newemail@example.com
Auth: ✅ Bearer <access_token>
```

**Query 参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| email | string | ❌ | 新邮箱 |

---

#### PUT `/api/user/password` — 修改密码

```
Method: PUT
URL: /api/user/password
Content-Type: application/json
Auth: ✅ Bearer <access_token>
```

**请求体：**
```json
{
  "old_password": "mypassword123",
  "new_password": "newpassword456"
}
```

**成功响应 (200)：**
```json
{ "message": "密码修改成功" }
```

---

### 3.5 系统

#### GET `/health` — 健康检查

```
Method: GET
URL: /health
Auth: 不需要
```

**响应：**
```json
{ "status": "ok", "service": "RAG 智能客服系统", "version": "2.0.0" }
```

---

## 四、错误码速查

| HTTP 状态码 | 含义 | 常见原因 |
|-----------|------|---------|
| 200 | 成功 | — |
| 201 | 创建成功 | 注册/上传成功 |
| 400 | 请求参数错误 | 格式校验失败 |
| 401 | 未授权 | token 缺失、过期、无效 |
| 403 | 禁止访问 | 账号禁用、无权访问该资源 |
| 404 | 资源不存在 | 会话/文档不存在或不属于当前用户 |
| 409 | 冲突 | 用户名已存在、文件重复上传 |
| 500 | 服务器错误 | 后端异常 |

## 五、前端界面设计建议

### 5.1 页面结构

建议设计以下页面：

| 页面 | 路由 | 功能 |
|------|------|------|
| **登录页** | `/login` | 用户名+密码登录 |
| **注册页** | `/register` | 注册新账号 |
| **对话页（主页）** | `/chat` | 核心功能：新对话 / 历史会话列表 / 流式对话 |
| **知识库管理** | `/knowledge` | 文件上传 / 文档列表 / 删除 |
| **个人中心** | `/profile` | 个人信息 / 修改密码 / 登出 |

### 5.2 对话页设计要点

```
┌──────────────────────────────────────────────┐
│  🤖 RAG 智能客服          [知识库] [👤] [退出] │
├─────────────┬────────────────────────────────┤
│ 历史会话列表  │                                │
│             │   👤 针织毛衣怎么保养？           │
│ 📁 毛衣保养   │   🤖 针织毛衣建议冷水手洗，     │
│ 📁 尺码选择   │      洗涤后平铺晾干...          │
│ 📁 颜色搭配   │                                │
│             │   👤 那纯棉的呢？                │
│ [+ 新对话]   │   🤖 纯棉材质可以机洗...         │
│             │                                │
│             ├────────────────────────────────┤
│             │ [输入框___________________] [发送]│
└─────────────┴────────────────────────────────┘
```

**关键交互：**
1. **新对话**：不带 session_id 发送第一条消息，从响应中获取 session_id
2. **历史会话**：点击左侧会话 → `GET /api/chat/history/{id}` 加载历史 → 渲染对话
3. **发送消息**：用 `POST /api/chat/stream`，逐字渲染 AI 回答
4. **自动滚动**：新 token 到达时自动滚动到底部
5. **加载状态**：AI 思考时显示 "..." 动画

### 5.3 Token 管理流程

```javascript
// API 请求拦截器伪代码
async function apiRequest(url, options = {}) {
  // 1. 自动附加 token
  options.headers = {
    ...options.headers,
    'Authorization': `Bearer ${getAccessToken()}`,
  };

  let response = await fetch(url, options);

  // 2. 401 → 尝试刷新 token → 重试
  if (response.status === 401) {
    const newToken = await refreshAccessToken();
    if (newToken) {
      options.headers['Authorization'] = `Bearer ${newToken}`;
      response = await fetch(url, options);
    } else {
      // 刷新失败 → 跳转登录页
      redirectToLogin();
    }
  }

  return response;
}
```

### 5.4 知识库管理页设计要点

- **上传区域**：拖拽上传 / 点击选择文件（仅 .txt）
- **文件列表**：表格展示（文件名、分块数、上传时间、操作）
- **上传反馈**：显示 Toast「上传成功，共 N 个语义块」或错误提示
- **删除确认**：二次确认弹窗

---

## 六、完整使用流程示例

```
1. 用户打开应用 → 进入登录页
2. 输入用户名密码 → POST /api/auth/login → 获取 access_token + refresh_token
3. 进入对话页 → GET /api/chat/sessions → 加载历史会话列表
4. 用户输入 "针织毛衣怎么保养？" 并点击发送
5. 前端调用 POST /api/chat/stream?query=针织毛衣怎么保养？
   → SSE 流式接收 token → 逐字渲染回答
6. 用户点击「知识库」→ GET /api/knowledge/documents → 展示已上传文档
7. 用户上传新文档 → POST /api/knowledge/upload → 刷新文档列表
8. 用户登出 → POST /api/auth/logout → 清除本地 token → 跳转登录页
```

---

## 附录：OpenAPI / Swagger

启动服务后访问 `http://localhost:8000/docs` 可直接在浏览器中**交互式测试所有接口**，无需手写 curl。

访问 `http://localhost:8000/openapi.json` 可获取 OpenAPI 3.0 规范的 JSON 文件，可导入 Postman、Apifox 等工具。
