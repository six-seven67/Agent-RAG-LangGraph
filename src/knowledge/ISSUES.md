# 数据离线上传问题分析与修复记录

> 分析范围：`src/knowledge/service.py`、`src/knowledge/splitter.py`、`src/api/knowledge.py`
>
> 最新版本：v3.3.0
> 最后更新：2026-06-12

---

## v3.3.0 新增功能（2026-06-12）

### 1. 多格式文档上传支持

**新增文件：** [parser.py](src/knowledge/parser.py)

| 格式 | 解析库 | 提取方式 |
|------|--------|----------|
| `.txt` | 内置 | UTF-8 / GBK 自动检测解码 |
| `.pdf` | pypdf | 逐页提取文本（扫描版需 OCR） |
| `.docx` | python-docx | 段落 + 表格文本提取 |
| `.xlsx` | openpyxl | 按 sheet 遍历单元格，tab 分隔保留结构 |

入口函数：`parse_document(file_bytes, filename)` → 根据扩展名自动路由

### 2. 数据清洗模块

**新增文件：** [cleaner.py](src/knowledge/cleaner.py)

| 清洗类型 | 规则 |
|----------|------|
| 通用 | 去除控制字符、统一换行符、压缩多余空白行 |
| PDF 专项 | 修复断行连字（行尾 `-` 合并）、过滤页眉页码短行 |
| Excel 专项 | 去除纯 tab 空行、压缩连续 tab |

入口函数：`clean_text(text, filename)` → 根据扩展名自动选择策略

### 3. 通用 Parent-Child 语义分块（最终方案）

**修改文件：** [splitter.py](src/knowledge/splitter.py)、[config.py](src/config.py)

采用适用于绝大多数文档场景的 **Parent-Child 父子文档分块** 策略，替代了领域特定的 `_split_washing_care` / `_split_color_guide`。

**分层设计：**

| 层级 | 大小 | 用途 |
|------|------|------|
| **Parent 块** | ~2000 chars（`parent_chunk_size`） | 保留完整语义上下文，LLM 生成回答时使用 |
| **Child 块** | ~500 chars（`child_chunk_size`） | 精确检索单元，向量相似度匹配用 |

**检索策略：** 用 Child 做向量匹配（精准）→ 返回 Child 关联的 Parent 全文（上下文充足）

**三种文本长度自适应：**
| 文本长度 | 策略 |
|----------|------|
| ≤ 500 chars | 单块处理（child，parent_content = 全文） |
| 500 ~ 2000 chars | 单层 Child 切分，parent_content = 全文 |
| > 2000 chars | 完整两层：先切 Parent，再从每个 Parent 切 Child |

**metadata 关键字段：**
- `chunk_type`: `"parent"` | `"child"`
- `parent_index`: Child 所属 Parent 的序号
- `parent_content`: Child 关联的 Parent 完整文本（检索命中 Child 后返回此字段）
- `child_count`: Parent 下包含的 Child 数量

**config.py 新增参数：**
```python
parent_chunk_size = 2000
parent_chunk_overlap = 200
child_chunk_size = 500
child_chunk_overlap = 50
```

### 4. 原文件保存

**修改文件：** [api/knowledge.py](src/api/knowledge.py)、[config.py](src/config.py)

- 上传时自动保存原文件到 `data/uploads/{user_id}/{timestamp}_{filename}`
- 删除文档时同步删除原文件（通过 glob 匹配时间戳前缀）
- 去重拦截时自动清理已保存的重复文件
- 上传响应中返回 `saved_path` 字段

### 5. 上传流程（完整链路）

```
用户上传文件
  → 格式校验（.txt/.pdf/.docx/.xlsx）
  → 大小校验（≤ 10 MB）
  → 保存原文件到 data/uploads/{user_id}/
  → parser.parse_document() 提取纯文本
  → cleaner.clean_text() 数据清洗
  → 计算 MD5 + MySQL 用户级去重
  → splitter.split_text() 通用分块
  → Chroma 向量化存储
  → MySQL 记录元数据
```

### 新增依赖

```
pypdf>=6.0.0        # PDF 解析
python-docx>=1.0.0  # Word 解析
openpyxl>=3.0.0     # Excel 解析
```

---

## v3.2.1 修复记录（2026-06-12）

## 1. 双轨去重机制不一致（数据一致性风险）✅ 已修复

**位置：** [service.py:24-68](src/knowledge/service.py#L24-L68) + [api/knowledge.py:67-78](src/api/knowledge.py#L67-L78)

**问题：**
- API 层使用 **MySQL** 做用户级去重（`user_id + md5_hash` 联合查询）
- `KnowledgeBaseService.upload_bt_str()` 内部还使用 **全局 `md5.text` 文件** 做第二次去重
- 两套去重机制隔离粒度不同：MySQL 是按用户隔离的，`md5.text` 是全局的

**影响：**
- 用户 A 上传文档 X → 全局 `md5.text` 记录了 X 的 MD5
- 用户 B 上传相同文档 X → API 层 MySQL 检查通过（B 没传过），但 `KnowledgeBaseService` 内部的文件检查会错误拦截，返回"文件已存在"
- 两套机制各自写入、各自检查，长期运行必然出现不一致

**修复方案：**
- 从 `service.py` 中**移除 `check_md5()` 和 `save_md5()` 两个文件级 MD5 函数**
- 去重统一由 API 层 MySQL 管理（`user_id + md5_hash` 联合唯一约束）
- `upload_bt_str` 不再自行检查重复，由调用方（API 层）在上游保证

**修改文件：** [service.py](src/knowledge/service.py) — 删除 `check_md5`/`save_md5`，`upload_bt_str` 移除去重逻辑

---

## 2. Chroma 写入与 MD5 记录无事务保护 ✅ 已修复

**位置：** [service.py:190-193](src/knowledge/service.py#L190-L193)（旧版）

**问题：**
```python
self.chroma.add_texts(texts, metadatas=metadatas)  # 步骤1
save_md5(md5_str)                                    # 步骤2
```
- `add_texts` 成功后若 `save_md5` 失败（磁盘满、权限问题），数据已入库但 MD5 未记录
- 下次上传相同内容时 MD5 检查不命中，Chroma 中产生重复向量数据
- 没有任何回滚或补偿机制

**修复方案：**
- MD5 文件操作已随问题1一同移除，不再存在步骤2失败的问题
- 新增 **Chroma 写入失败回滚机制**：`upload_bt_str` 中用 try/except 包裹 `add_texts`，失败时自动调用 `delete_by_doc_id()` 清理已写入的部分数据
- 每个 chunk 分配唯一 ID（`{doc_id}_{chunk_index}`），使精确回滚成为可能

**修改文件：** [service.py](src/knowledge/service.py) — `upload_bt_str` 添加 try/except + 回滚逻辑

---

## 3. MD5 文件操作存在并发竞态 ✅ 已修复

**位置：** [service.py:42-52](src/knowledge/service.py#L42-L52)（旧版）

**问题：**
- `check_md5` 和 `save_md5` 对 `md5.text` 的读写没有任何锁保护
- 两个并发上传请求可能同时通过 MD5 检查（都读到旧文件），然后都写入 Chroma，最后各自追加 MD5 —— 产生重复数据
- `open(path).readlines()` 未显式关闭文件句柄（line 48），依赖 GC 回收

**修复方案：**
- 文件级 MD5 操作已随问题1 一并移除
- 并发安全由 MySQL 数据库的事务隔离级别保证（`user_id + md5_hash` 唯一索引）

**修改文件：** [service.py](src/knowledge/service.py) — 移除 `check_md5`/`save_md5`

---

## 4. 分块策略硬编码，通用文档退化为整块 ✅ 已修复

**位置：** [splitter.py:45-50](src/knowledge/splitter.py#L45-L50) + [splitter.py:232-258](src/knowledge/splitter.py#L232-L258)（旧版）

**问题：**
- `split_by_structure` 仅识别 `"洗涤养护"` 和 `"颜色选择"` 两种业务文档
- 其他所有文档走 `_split_simple` → **整篇文本作为一个 chunk**
- `config.py` 中已经定义了 `chunk_size=1000`、`chunk_overlap=100`、`separators` 等通用分块参数，但完全未被 `split_by_structure` 使用

**影响：**
- 一篇 10 万字的通用文档被当作一个 chunk 存入 Chroma，embedding 语义被稀释，检索命中率极低
- 通用文档的 embedding 向量也可能超出模型的输入 token 限制

**修复方案：**
- 新增 `_split_generic()` 函数，使用 **`RecursiveCharacterTextSplitter`** 作为通用文档兜底策略
- 直接读取 `config.chunk_size`、`config.chunk_overlap`、`config.separators` 参数
- `_split_simple` 重命名为 `_split_generic`（语义更准确）
- 业务文档分块失败时也降级到 `_split_generic`（而非 `_split_simple`）
- 验证结果：之前 10 万字文档 = 1 chunk，现在 ≈ 100 chunk（按 chunk_size=1000）

**修改文件：** [splitter.py](src/knowledge/splitter.py) — 新增 `_split_generic`，替换 `_split_simple`

---

## 5. `operator` 字段始终为空 ✅ 已修复

**位置：** [service.py:185](src/knowledge/service.py#L185)（旧版）

**问题：**
```python
meta["operator"] = ""  # 添加操作者信息（当前为空）
```
- API 层已有 `current_user`（含 `id`、`username`），但没有传递给 `upload_bt_str`
- 所有 chunk 的 metadata 中 operator 永远为空字符串，无法追溯操作者

**修复方案：**
- `upload_bt_str` 新增 `operator` 参数
- API 层调用时传入 `current_user.username`（fallback 到 `str(current_user.id)`）
- chunk metadata 中 `operator` 字段现在会记录实际操作者

**修改文件：** [service.py](src/knowledge/service.py) + [api/knowledge.py](src/api/knowledge.py)

---

## 6. 上传无文件大小限制 ✅ 已修复

**位置：** [api/knowledge.py:32-36](src/api/knowledge.py#L32-L36)（旧版）

**问题：**
- 没有对 `UploadFile` 做大小校验
- 大文件会导致：内存溢出、embedding API 调用费用过高、请求超时

**修复方案：**
- 新增 `MAX_UPLOAD_SIZE = 10 * 1024 * 1024`（10 MB）
- 新增 `_read_file_content()` 辅助函数，在读取文件后立即校验大小
- 超过限制返回 `HTTP 413 Request Entity Too Large`
- 10MB 的 TXT 文本 ≈ 1000 万字符，分块后约 1 万 chunk，在合理范围内

**修改文件：** [api/knowledge.py](src/api/knowledge.py) — 新增 `MAX_UPLOAD_SIZE` 常量和 `_read_file_content` 函数

---

## 7. Chroma 同步操作阻塞异步事件循环 ✅ 已修复

**位置：** [service.py:190](src/knowledge/service.py#L190)（旧版）

**问题：**
- `self.chroma.add_texts()` 是同步调用（内部含 embedding API 网络请求）
- 在 FastAPI `async def` 端点中直接调用，会阻塞整个 event loop
- 应使用 `asyncio.to_thread()` 或 `run_in_executor` 将同步操作放到线程池

**修复方案：**
- `upload_bt_str` 改为 `async def`
- `chroma.add_texts()` 通过 `await asyncio.to_thread(self.chroma.add_texts, ...)` 在线程池执行
- `delete_by_doc_id` 同样使用 `await asyncio.to_thread(...)` 包装 Chroma 的 `get`/`delete` 操作
- API 层调用改为 `await kb_svc.upload_bt_str(...)`

**修改文件：** [service.py](src/knowledge/service.py) — `upload_bt_str` 异步化 + `asyncio.to_thread`
[api/knowledge.py](src/api/knowledge.py) — `await kb_svc.upload_bt_str(...)`

---

## 8. 删除文档仅删 MySQL 元数据，Chroma 数据残留 ✅ 已修复

**位置：** [api/knowledge.py:146-150](src/api/knowledge.py#L146-L150)（旧版）

**问题：**
- 代码注释已承认："Chroma 不支持按 metadata 批量删除"
- 删除文档只删除了 `knowledge_docs` 表中的记录
- Chroma collection 中的向量数据仍然存在，检索时仍可能被命中
- 属于已知但未解决的数据一致性问题

**修复方案：**
- 由于上传时每个 chunk 的 metadata 已包含 `doc_id`（= md5_hash），可通过 metadata 过滤找到所有关联分块
- 新增 `KnowledgeBaseService.delete_by_doc_id(doc_id)` 方法：
  1. `chroma.get(where={"doc_id": doc_id})` → 获取所有分块 ID
  2. `chroma.delete(ids=chunk_ids)` → 批量删除
- API 层 `delete_document` 端点改为：先调 `kb_svc.delete_by_doc_id(doc.md5_hash)` 清理 Chroma，再删 MySQL 记录
- Chroma 清理失败时不阻塞 MySQL 删除（记录 warning 日志，可异步补偿）

**修改文件：** [service.py](src/knowledge/service.py) — 新增 `delete_by_doc_id` 方法
[api/knowledge.py](src/api/knowledge.py) — `delete_document` 增加 Chroma 清理步骤

---

## 9. 分块数量解析依赖字符串匹配 ✅ 已修复

**位置：** [api/knowledge.py:94-97](src/api/knowledge.py#L94-L97)（旧版）

**问题：**
```python
match = re.search(r'共\s*(\d+)\s*个语义块', result_msg)
```
- 从人类可读消息中正则提取 chunk_count，耦合脆弱
- 如果 `upload_bt_str` 的返回消息格式发生变化，chunk_count 静默变为 0，MySQL 记录不准确
- 应让 `upload_bt_str` 返回结构化数据（如 dict），而非纯文本消息

**修复方案：**
- `upload_bt_str` 返回 `dict` 结构：`{"success": bool, "chunk_count": int, "doc_id": str, "message": str}`
- API 层直接用 `upload_result["chunk_count"]` 获取分块数，不再解析字符串

**修改文件：** [service.py](src/knowledge/service.py) — `upload_bt_str` 返回 dict
[api/knowledge.py](src/api/knowledge.py) — 移除正则解析，改用结构化字段

---

## 10. Embedding API 调用无重试机制 ⚠️ 部分缓解

**位置：** [service.py:130](src/knowledge/service.py#L130) + [service.py:190](src/knowledge/service.py#L190)（旧版）

**问题：**
- `DashScopeEmbeddings` 和 `chroma.add_texts()` 内部会调用阿里云 embedding API
- 遇到网络抖动、限流时直接抛出异常，上传失败，用户需手动重试
- 无指数退避重试、无断点续传

**当前状态：**
- 写入失败时增加了回滚机制（清理部分写入数据），用户可安全重试
- 指数退避重试（如 tenacity 库）需要评估对 embedding API 计费的影响
- 标记为后续迭代优化项

**后续建议：**
- 使用 `tenacity` 库添加 `@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30))`
- 需确认阿里云 DashScope embedding API 的幂等性和限流策略后再实施

---

## 总结

| 优先级 | 问题 | 状态 |
|--------|------|------|
| **P0** | 双轨去重不一致 | ✅ 已修复 — 移除文件 MD5，统一 MySQL |
| **P0** | 通用文档退化为单 chunk | ✅ 已修复 — RecursiveCharacterTextSplitter 兜底 |
| **P1** | 并发竞态 + 无事务保护 | ✅ 已修复 — 移除竞态源 + Chroma 写入回滚 |
| **P1** | 删除不清理 Chroma | ✅ 已修复 — delete_by_doc_id 同步清理 |
| **P2** | 同步阻塞 event loop | ✅ 已修复 — asyncio.to_thread 异步化 |
| **P2** | 无文件大小限制 | ✅ 已修复 — MAX_UPLOAD_SIZE = 10MB |
| **P3** | operator 为空 | ✅ 已修复 — 传入 current_user.username |
| **P3** | chunk_count 解析脆弱 | ✅ 已修复 — 返回结构化 dict |
| **P3** | Embedding API 无重试 | ⚠️ 部分缓解 — 写入失败回滚，重试待后续迭代 |

### 涉及修改的文件

| 文件 | 变更类型 |
|------|----------|
| [service.py](src/knowledge/service.py) | **重写** — 移除文件 MD5、异步化、结构化返回、回滚机制、新增 delete_by_doc_id |
| [splitter.py](src/knowledge/splitter.py) | **修改** — `_split_simple` → `_split_generic`，使用 RecursiveCharacterTextSplitter |
| [api/knowledge.py](src/api/knowledge.py) | **重写** — 文件大小限制、operator 传递、结构化返回、Chroma 同步删除 |

### 未修改的文件

| 文件 | 原因 |
|------|------|
| `__init__.py` | 公共 API 无变化（`KnowledgeBaseService` 类名和方法签名兼容） |
| `data/md5.text` | 旧文件保留，不再写入（向后兼容，已有记录可作历史参考） |






用户上传文件
    ↓
API 层校验格式/大小 → ✅ 保存原文件
    ↓
parser 多格式解析 → ✅ PDF/DOCX/XLSX/TXT
    ↓
cleaner 数据清洗 → ✅ 分格式专项清洗
    ↓
MD5计算 → ✅ 清洗后计算 + MySQL用户级去重
    ↓
splitter 分块 → ✅ Parent-Child 两层 + overlap
    ↓
service 异步入库 → ✅ Chroma + 失败自动回滚
    ↓
MySQL 记录元数据 → ✅ 支持列表/删除管理