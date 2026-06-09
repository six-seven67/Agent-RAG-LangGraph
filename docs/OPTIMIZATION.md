本项目的 RAG 优化经历了两个阶段：
- **v2.x**：Advanced RAG 管线优化（5 项核心优化）
- **v3.0.0**：RAG → Agent 架构升级（LLM 自主决策 + 工具调用）

---

## 实施记录 0：Agent 智能客服升级（RAG → Agent）

**日期**：2026-06-07
**状态**：已实施
**方案**：LangGraph ReAct Agent + 自定义工具

### 改动概述

将固定管线 RAG 系统升级为基于 **LangGraph `create_agent`** 的 ReAct Agent 系统。LLM 自主决策：是否查知识库、是否匹配 FAQ、是否追问、是否转人工。彻底告别”所有问题走同一条检索→生成管线”的局限。

### 为什么需要从 RAG 升级到 Agent

RAG 固定管线存在根本性局限：

1. **所有问题都走同一流程**：闲聊”你好”也会触发检索，浪费 API 调用且体验差
2. **无法多步推理**：检索不充分时无法自动用改写后的 query 重试
3. **无法主动追问**：用户问题模糊时直接检索导致答非所问
4. **缺少转人工机制**：知识库无匹配时 LLM 容易编造答案（幻觉）
5. **缺少工具编排**：无法同时访问多个信息源（知识库 + FAQ + 人工）

Agent 模式通过 LLM 的 Reasoning + Tool Calling 循环解决上述所有问题。

### 实现方案

#### Agent 架构

```
create_agent(model, tools, checkpointer, system_prompt)
  ├── agent 节点: LLM 分析 + 决策（回答 / 调用工具）
  ├── tools 节点: 执行工具调用（search_knowledge_base 等）
  └── AsyncSqliteSaver: 持久化对话历史（含 tool 消息）
```

#### 3 个 Agent 工具

| 工具 | 功能 | 封装内容 |
|------|------|---------|
| `search_knowledge_base` | 封装完整 RAG 检索管道 | Query Rewrite → Hybrid Search → Rerank → Parent-Child Expand → 格式化 top-5 |
| `lookup_faq` | 高频常见问题快速匹配 | 8 类 FAQ 关键词匹配（营业时间/退换货/发货/支付/发票/售后/尺码等） |
| `escalate_to_human` | 转人工客服 | 标记会话 + 问题摘要 |

#### SSE 事件增强

| 事件类型 | 数据 | 前端展示 |
|----------|------|---------|
| `token` | 文本片段 | 逐字追加到对话气泡 |
| `tool_start` | `{“tools”:[{“name”:”...”,”args”:{...}}]}` | “正在检索知识库...” |
| `tool_end` | `{“tool”:”...”,”result_preview”:”...”}` | “检索完成” |
| `thinking` | (空) | 思考动画 |
| `done` | `[DONE]` | 流结束 |

### 架构对比

| 维度 | RAG 管线（v2.x） | Agent（v3.0.0） |
|------|-----------------|-----------------|
| 决策模式 | 固定流程（永远检索→生成） | LLM 自主决策（按需检索） |
| 闲聊处理 | 也会检索（浪费） | 直接友好回复 |
| 检索失败 | 硬着头皮回答（可能幻觉） | 追问或转人工 |
| 多信息源 | 仅知识库 | 知识库 + FAQ + 人工 |
| 多轮推理 | 不支持 | 支持（检索不充分→优化重试） |
| 前端交互 | 仅文本流 | 工具状态 + 文本流 |

### 改动文件

| 文件 | 改动 |
|---|---|
| `src/agent/__init__.py` | **新建**，Agent 模块入口 |
| `src/agent/tools.py` | **新建**，3 个 Agent 工具 |
| `src/agent/service.py` | **新建**，AgentService（create_agent + AsyncSqliteSaver） |
| `src/api/chat.py` | SSE 事件增强（tool_start/tool_end/thinking），Agent 服务集成 |
| `app/fastapi_server.py` | title/version 更新为 Agent v3.0.0 |
| `src/config_data.py` | 新增 Agent 配置（agent_mode_enabled 等） |
| `frontend/` | 前端适配 Agent 事件，品牌升级 |

### 向后兼容

- `src/rag_async.py` 保留不动
- 环境变量 `AGENT_MODE=false` 可切回 v2.x RAG 模式
- 所有 API 端点路径不变

---

目前的 RAG 和知识库实现已经具备了一个非常完整且可用的基础 MVP（最小可行性产品）架构，特别是文件 MD5 去重这个设计在基础工程中非常实用。

但在真实的生产环境中，为了解决大模型偶尔的”答非所问”、专业词汇检索不到、或者长篇文档理解偏差等问题，这套系统还有很大的优化空间。我们可以从\*\*先进的 RAG 架构（Advanced RAG）\*\*角度，将其优化方向分为以下四个核心维度：

### 一、 数据入库与处理优化 (Data Ingestion)

目前的做法是硬性按字数切分（`RecursiveCharacterTextSplitter`），这很容易把一句话或者一个完整的段落从中间劈开，导致语义丢失。

1. **引入语义分块 (Semantic Chunking)：**
   不要仅仅按照字数切分，可以引入基于标点符号、段落（如 Markdown 的 Header）或语义连贯性的切分方式。LangChain 提供了如 `MarkdownHeaderTextSplitter` 等工具，能够保留文档的层级结构。
2. **父子文档检索 (Parent-Child / Small-to-Big Retrieval)：**
   在存入向量库时，将文档切得非常细（比如一两百字，作为“子块”用来做精准的向量匹配），但在 Chroma 中同时关联它所属的大段落（“父块”）。当检索命中“子块”时，提取整个“父块”喂给大模型。这样既保证了检索的**精准度**，又保证了提供给模型的**上下文完整性**。

### 二、 检索阶段优化 (Retrieval Optimization)

目前的检索是“用户输入什么，就直接拿什么去搜（单路向量召回）”，并且直接取 Top-K 返回。这在用户提问比较模糊或包含特定专有名词时容易失效。

1. **混合检索 (Hybrid Search)：**
   纯向量检索（Dense Retrieval）对语义理解很好，但对特定的专有名词、产品型号、人名（精确匹配）往往效果不佳。建议引入 **BM25 算法**（传统的关键词倒排索引），将“向量检索”与“关键词检索”结合，两路召回后再合并结果。
2. **引入重排序模型 (Re-ranking)：** **（⭐⭐⭐ 提效最显著的手段）**
   这是目前高阶 RAG 的标配。做法是：检索时放宽条件，先捞取 Top-20 个片段（保证召回率），然后用一个专门的**交叉编码器（Cross-Encoder，如 BGE-Reranker 或 Cohere Rerank）** 给这 20 个片段与用户问题的相关性重新打分，最后只挑出得分最高的 Top-3 或 Top-5 给大模型。这能极大降低大模型被无关信息干扰的概率。

### 三、 生成与上下文优化 (Generation)

目前是将所有检索到的片段直接拼接成 `context` 塞给大模型。

1. **上下文压缩与过滤 (Context Compression)：**
   检索回来的文本块中，可能只有一两句话是真正有用的。可以在交给大模型生成最终答案前，先用一个小模型（或基于规则的过滤器）把冗余的废话剔除掉，减少 Token 消耗，并降低大模型的“注意力分散”。
2. **元数据过滤 (Metadata Filtering)：**
   如果在存入 Chroma 时（`vector_store.py`），给文档打上时间、作者、类别等标签（Metadata），那么在智能体调用工具时，可以让智能体自动提取筛选条件。比如提问“2023年的财务报告怎么样”，系统就可以在检索时硬性过滤掉 `year != 2023` 的数据。
3. **防幻觉与引用溯源：**
   目前你的提示词中要求了携带元数据，可以进一步在 Prompt 中强制要求模型输出类似于 `[参考资料: 1]` 的角标，并且在后处理阶段用正则化去检验模型是否真的引用了提供的 Context，如果没有，则提示“知识库中未找到相关信息”，坚决抵制模型“瞎编”。

### 四、 工程架构优化 (Engineering)

1. **细粒度的文件更新机制：**
   现在的 MD5 是基于整个文件的。如果一个 100 页的 PDF 只修改了 1 个错别字，整个文件就会重新入库。可以优化为**基于 Chunk 级别的哈希校验**，实现真正的增量更新。
2. **异步并发 (Async/Await)：**
   当前代码是同步的。如果在高并发场景下，等待大模型生成或者等待文件 I/O 会阻塞进程。可以将 LangChain 的方法替换为 `astream`, `ainvoke`，并将底层请求库替换为 `aiohttp`。
3. **引入评估框架 (RAG Evaluation)：**
   “好不好”不能只靠直觉。可以引入诸如 **Ragas** 或 **TruLens** 这样的 RAG 评估框架，用量化的指标（如：上下文精确度、回答相关性、忠实度）来持续监控优化效果。

**总结建议：**
如果你打算动手升级这段代码，建议**第一步先加上重排序（Re-ranking）**，这只需要改动几十行代码，但能让回答质量产生肉眼可见的飞跃；**第二步优化切词逻辑（Semantic Chunking）**；最后再考虑架构层面的混合检索和异步改造。


---

## 实施记录 1：Re-ranking（重排序）

**日期**：2026-05-19
**状态**：已实施
**方案**：DashScope gte-rerank API

### 改动概述

引入 Cross-Encoder 重排序，将检索流程从「初检 Top-1 直喂大模型」升级为「初检 Top-20 → Rerank 精排 Top-3 → 大模型」。

### 改动文件

| 文件 | 改动 |
|---|---|
| config_data.py | 新增 retrieval_top_k=20、reranker_model_name="gte-rerank"、reranker_top_n=3 |
| vector_stores.py | retriever 的 k 参数改为读取 config.retrieval_top_k |
| reranker.py | **新建**，封装 DashScope TextReRank API（gte-rerank 模型） |
| rag.py | 链结构重构为 RunnablePassthrough.assign(context=...) 单链模式 |
| eval_reranker.py | **新建**，A/B 对比验证脚本（5 种查询 x 两路对比） |

### 数据流

用户输入 → 向量检索 Top-20（扩大召回面） → gte-rerank 精排 Top-3 → 拼接 context 注入 Prompt → 通义 qwen3-max 生成

### A/B 验证结论

用 5 个不同场景的查询对比向量检索 vs Rerank：

- keywords / lookup 类型：两路基本一致，Rerank 仅微调排序
- semantic 类型：Rerank 将最相关文档排到第一
- cross_doc 类型：Rerank 明显纠正向量检索误判，剔除不相关文档
- short 类型：Rerank 优化排序但未改变入选集合


### 为什么需要 Re-ranking

当前系统的检索链路存在两个核心问题：

1. **检索太窄**：`similarity_threshold=1`，向量检索只取 Top-1，一旦这个文档不匹配，大模型就拿不到任何有用信息，必然「答非所问」。
2. **向量检索的天然缺陷**：Embedding 模型做的是「整体语义相似」，遇到短查询、歧义词、跨领域表述时，Top-1 不一定是最相关的那篇——可能只是一个同样包含高频词汇但不含答案的文档。

举例：查询「怎么洗」，向量检索可能把「加绒牛仔」排在「针织棉」前面，因为两者都高频出现「洗」字，但用户实际想问的是针织毛衣。

### 为什么选择 gte-rerank API 而非本地 BGE-Reranker

| 方案 | 优点 | 缺点 |
|---|---|---|
| 本地 BGE-Reranker | 免费、无网络依赖 | 需要 transformers/torch 全家桶，模型 2GB+，与 pytorch_12.4 环境可能版本冲突 |
| DashScope gte-rerank API | 零环境依赖、调用简单、与现有 Embedding/Chat 同账号 | 有 API 调用费用 |

本项目已经全链路使用 DashScope（Embedding + ChatTongyi），新增 Rerank API 只是多一次 HTTP 调用，无需额外环境配置。**选择 API 方案保持了架构一致性，降低了运维复杂度。**

### 什么业务场景适合 Re-ranking

Re-ranking 不是银弹，适合以下场景：

- **知识库文档量大且内容交叉**：多篇文档讨论相似主题，向量检索容易混淆，需要 Cross-Encoder 做精细区分（如本项目「颜色选择」和「尺码推荐」都包含身高体重等高频词）
- **用户查询短且歧义**：如「怎么洗」「买多大」，需要 Rerank 根据更精准的语义匹配重新排序
- **对回答准确率要求高**：客服、医疗、法律等场景，错误回答代价大
- **硬件资源受限**：不适合本地跑大模型，但能接受 API 延迟（本项目场景）

不适合的场景：
- 知识库很小（< 10 篇文档），直接全量检索即可
- 对延迟极度敏感（每次多 100-300ms 的 API 调用）
- 查询都是精确关键词匹配（如 SKU 编号查询）

### 达到的效果

通过 `eval_reranker.py` 对 5 类查询的 A/B 对比，得出以下结论：

| 查询类型 | 效果 | 典型表现 |
|---|---|---|
| keywords（精确关键词） | 小幅优化 | 排序重新调整，内容不变 |
| semantic（语义模糊） | 中等优化 | 最相关文档被提到第一位 |
| **cross_doc（跨文档语义）** | **显著优化** | 剔除不相关文档（如「尺码推荐」被替换） |
| lookup（精确查找） | 无变化 | 向量检索已经足够准确 |
| short（短歧义查询） | 小幅优化 | 排序微调，入选集未变（需配合 Query Rewrite 改善） |

**核心收益**：在跨文档场景下，Rerank 成功纠正了向量检索的误判——将向量排序第 5 的文档提到 Top-3，同时剔除了完全不相关的「尺码推荐」文档。这直接避免了后续大模型「看着尺码回答颜色问题」的幻觉。



---

## 实施记录 2：语义分块 + Parent-Child 检索

**日期**：2026-05-19
**状态**：已实施
**方案**：结构感知分块 + Parent-Child 检索（子块精检 → 父块展开）

### 改动概述

将原来粗暴的 `RecursiveCharacterTextSplitter`（按字符数硬切）替换为结构感知分块器，并按 Parent-Child 模式存储：细粒度子块用于精确检索，完整父块喂给 LLM 保证上下文完整性。

### 为什么需要语义分块

原有的 `RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)` 按固定字符数切割，存在两个问题：

1. **语义截断**：一句话或一个完整段落可能从中间被劈开。例如「洗涤：...」和「养护：...」本应在一起，但可能被切到两个不同的 chunk 里。
2. **上下文丢失**：检索命中一个 200 字的子块，LLM 看不到前后的完整段落，只能靠碎片信息生成回答，容易「断章取义」。

### 实现方案

#### 分块策略

| 数据文件 | 拆分方式 | 子块数 | 父块数 |
|---|---|---|---|
| 洗涤养护.txt | 按「季节 > 材质」拆洗涤/养护子块 | 90 | ~45 |
| 颜色选择.txt | 按编号主题拆子句子块 | 21 | 6 |
| 尺码推荐.txt | 不拆分（太小） | 1 | 1 |

每个子块带三个关键元数据：
- `chunk_type`: `"child"` 或 `"parent"`
- `section_title`: 如 `"一、春季服装 > 1. 纯棉材质"`
- `parent_content`: 完整父块文本

#### 检索链路

```
用户查询
  → 向量检索 Top-20 子块（细粒度，保精确度）
  → gte-rerank 精排 Top-3
  → 遍历子块，提取 parent_content，去重（同父块只展开一次）
  → 拼接父块完整上下文注入 Prompt
  → 通义 qwen3-max 生成
```

### 为什么这样设计

| 层级 | 作用 | 避免的问题 |
|---|---|---|
| 子块（细粒度） | 向量检索精确命中 | 全篇检索导致的语义稀释 |
| Rerank（精排） | 二次筛选最相关子块 | 向量相似度误判 |
| 父块展开 | 还原完整上下文 | 碎片化信息导致断章取义 |
| 去重 | 同一父块的多个子块只展开一次 | context 被重复内容浪费 |

### 达到的效果

通过 `eval_reranker.py` 实测 5 类查询：

| 查询 | 改造前（旧分块） | 改造后（语义分块 + P-C） |
|---|---|---|
| "针织毛衣如何保养？" | 零碎的洗涤/养护句子，缺失另一半 | 展开为完整材质段落，洗涤+养护同时呈现 |
| "夏天的丝质连衣裙怎么洗" | 可能只拿到「洗涤」半句 | 完整真丝段落，洗涤+养护+注意事项 |
| "黄皮肤春天穿什么颜色" | 颜色指南碎片混入尺码 | 完整主题段落，肤色+场合+季节颜色关联 |
| "怎么洗" | 随机材质的洗涤一行 | 完整材质段落，即使短查询也有完整上下文 |

**关键收益**：
- LLM 从「看碎片猜答案」变为「读完整段落回答」
- 同一父块的多个子块去重后，context 利用率显著提升
- 配合 Rerank，无关父块被过滤，相关父块完整呈现

### 改动文件

| 文件 | 改动 |
|---|---|
| semantic_splitter.py | **新建**，结构感知分块器（洗涤按季节/材质、颜色按主题） |
| knowledge_base.py | 弃用 RecursiveCharacterTextSplitter，改用 split_by_structure()，存储 parent_content 元数据 |
| rag.py | retrieve_and_rerank 增加 Parent-Child 展开 + 去重逻辑 |
| eval_reranker.py | 更新展示：同时显示子块和展开后父块 |

### 下一步

~~按照既定路线，建议实施**混合检索（Hybrid Search）**：向量检索 + BM25 关键词检索，互补长短。~~ ✅ 已完成，见实施记录3。


---

## 实施记录 3：混合检索（Hybrid Search）

**日期**：2026-06-04
**状态**：已实施
**方案**：向量检索 (Dense) + BM25 关键词检索 (Sparse) → RRF 融合

### 改动概述

引入混合检索引擎，将原来单一的向量检索（语义匹配）升级为「向量检索 + BM25 关键词检索」双路召回 + RRF（Reciprocal Rank Fusion）融合排序。向量检索擅长语义理解和近义词匹配，BM25 擅长精确关键词匹配（专有名词、产品型号等），两者互补，显著提升召回覆盖率和精确度。

### 为什么需要混合检索

原系统是纯向量检索（Dense Retrieval Only），存在以下局限：

1. **专有名词和型号易丢失**：向量 Embedding 对「语义」敏感，但对精确的专有名词、产品型号、编号等匹配能力弱。例如查询「SKU-12345 的养护方法」，向量检索可能返回语义相近但不包含该 SKU 的文档。
2. **短查询歧义放大**：短查询（如「怎么洗」）信息量少，向量检索容易匹配到高频词文档而非真正相关的文档。
3. **两路互补**：BM25 基于词频和逆文档频率，对精确词语匹配天然敏感；向量检索基于语义向量距离，对同义词和上下文理解更好。两路结合可以互补长短。

### 实现方案

#### 整体检索链路（升级后）

```
用户查询
  → 向量检索 Top-20 (Dense, 语义匹配)
  → BM25 检索 Top-20 (Sparse, 关键词匹配)
  → RRF 融合去重排序 → Top-20
  → gte-rerank 精排 → Top-3
  → Parent-Child 展开 + 去重
  → 拼接 context 注入 Prompt
  → 通义 qwen3-max 生成
```

#### BM25 检索器 (`src/bm25_retriever.py`)

| 组件 | 说明 |
|---|---|
| 分词器 | **jieba** 精确模式（中文分词），过滤空字符串 |
| 算法 | 标准 BM25（Robertson-Sparck Jones IDF + 词频饱和度） |
| 参数 | k1=1.5（词频饱和度）, b=0.75（文档长度归一化） |
| 索引 | 倒排索引，从 Chroma 向量库全量加载文档构建 |

BM25 公式：
```
score(q, d) = Σ IDF(qi) × (tf × (k1+1)) / (tf + k1 × (1-b + b × |d|/avgdl))
IDF(qi) = log((N - n + 0.5) / (n + 0.5) + 1)
```

#### RRF 融合 (`src/hybrid_retriever.py`)

使用 **Reciprocal Rank Fusion (RRF)** 算法融合两路结果：

```
RRF_score(d) = Σ 1 / (k + rank_i(d))
```

- `k = 60`（平滑参数）：防止除零，使排名差异更平滑
- 同一文档出现在两路结果中时，RRF 分累加（去重 + 排名加成）
- **无需手动设定权重**，自动平衡向量检索和 BM25 的贡献

| 配置参数 | 默认值 | 说明 |
|---|---|---|
| `hybrid_vector_k` | 20 | 向量检索召回数量 |
| `hybrid_bm25_k` | 20 | BM25 检索召回数量 |
| `hybrid_fusion_k` | 60 | RRF 平滑参数 |
| `hybrid_top_k` | 20 | 融合后保留文档数（喂给 Reranker） |

### 为什么选择 RRF 而非加权求和

| 方案 | 优点 | 缺点 |
|---|---|---|
| 加权求和 | 可精细调节两路权重 | 需要大量调参，不同查询最优权重不同；向量得分和 BM25 得分不在同一量纲，需归一化 |
| **RRF** ⭐ | 无需归一化、无需调参、自动平衡 | 无法针对特定场景倾斜某一路 |

RRF 只关心「排名」而非「绝对分数」，天然解决了向量相似度和 BM25 得分不在同一量纲的问题。经大量学术和实践验证，RRF 在零样本混合检索场景中表现稳健。

### 什么业务场景适合混合检索

混合检索对以下场景的提升尤为显著：

- **专有名词 / 产品型号密集的知识库**：如服装 SKU、药品批号、法律条款编号等，BM25 可精确匹配这些词语
- **短查询场景**：如「怎么洗」「买多大」，关键词匹配可补充语义检索的模糊性
- **多领域交叉知识库**：文档内容覆盖多个主题，语义相近容易混淆时需要精确关键词区分

不适合的场景：
- 知识库很小（< 10 篇文档），纯向量检索已足够覆盖
- 查询都是长句自然语言描述，且知识库内容语义清晰不重合

### 改动文件

| 文件 | 改动 |
|---|---|
| [bm25_retriever.py](src/bm25_retriever.py) | **新建**，BM25 关键词检索器（jieba 分词 + 标准 BM25 算法） |
| [hybrid_retriever.py](src/hybrid_retriever.py) | **新建**，混合检索器（向量 + BM25 → RRF 融合） |
| [config_data.py](src/config_data.py) | 新增 `hybrid_vector_k`、`hybrid_bm25_k`、`hybrid_fusion_k`、`hybrid_top_k` |
| [vector_stores.py](src/vector_stores.py) | 新增 `get_all_documents()` 方法，从 Chroma 加载全量文档供 BM25 索引 |
| [rag.py](src/rag.py) | 检索链路升级：引入 `HybridRetriever` 替代纯向量检索 |
| [requirements.txt](requirements.txt) | 新增 `jieba>=0.42.1`（中文分词） |
| [eval_reranker.py](eval/eval_reranker.py) | 新增混合检索对比验证（向量 vs 混合检索差异分析） |

### 达到的效果

混合检索的核心价值在于 **两路互补**：

| 检索场景 | 向量检索（旧） | 混合检索（新） | 提升 |
|---|---|---|---|
| 语义模糊查询 | 可能返回高频词文档 | BM25 过滤掉语义不相关但高频的文档 | 中等 |
| 精确关键词查询 | 向量 Embedding 无法精确匹配专有名词 | BM25 精确命中关键词 | 显著 |
| 短查询（<5字） | 信息少，向量方向模糊 | BM25 补充关键词匹配 | 中等 |
| 长句自然语言 | 语义匹配准确 | 两路结果趋于一致，RRF 不影响 | 无变化 |

**核心收益**：
1. **专有名词不再丢**：查询中如果包含具体的材质名称、编号等关键词，BM25 能确保包含这些词的文档进入候选集
2. **召回更全面**：两路召回各取 20 条，经 RRF 融合后候选集更丰富，后续 Rerank 精排有更好的基础
3. **零额外 API 成本**：BM25 是纯本地算法，不增加 API 调用
4. **低延迟开销**：BM25 检索 + RRF 融合在 112 个文档上的延迟约 10-20ms，对整体链路影响可忽略

### 与现有优化的协同

三级检索管道协同工作：

```
[BM25 关键词] ─┐
                ├─ RRF 融合 ─→ [Rerank 精排] ─→ [Parent-Child 展开] ─→ LLM
[向量 语义]   ─┘
    ↑                  ↑                ↑
  实施记录3          实施记录1         实施记录2
```

每一步解决不同问题：
- **混合检索**：扩大召回面，互补长短（关键词 + 语义）
- **Rerank 精排**：从候选集中挑选最相关的 3 个文档
- **Parent-Child**：从精准子块展开为完整父块，保证上下文完整性

### 下一步

三项核心优化（Rerank + 语义分块 + 混合检索）已全部实施完毕。后续已实施：

1. ~~**RAG 评估框架**~~ ✅ 已完成，见「实施记录 3 附录：消融实验评估」。
2. ~~**Query Rewrite（查询改写）**~~ ✅ 已完成，见「实施记录 4」。
3. ~~**异步改造**~~ ✅ 已完成，见「实施记录 5」。


### 实施记录 3 附录：消融实验评估

**日期**：2026-06-04
**评估工具**：[eval/rag_evaluation.py](eval/rag_evaluation.py)
**评估报告**：[eval/eval_report_quick.md](eval/eval_report_quick.md)

#### 实验设计

对三项优化的 5 种组合配置进行了消融实验，8 个不同类别的查询 × 5 配置 = 40 组测试。

| 配置 | 混合检索 | Rerank | Parent-Child |
|---|---|---|---|
| A_Full | ✅ | ✅ | ✅ |
| B_NoHybrid | ❌ | ✅ | ✅ |
| C_NoRerank | ✅ | ❌ | ✅ |
| D_NoParentChild | ✅ | ✅ | ❌ |
| E_Baseline | ❌ | ❌ | ❌ |

#### 关键发现

**1. 混合检索显著提升上下文多样性**

| 指标 | Full Pipeline (A) | No Hybrid (B) | 提升 |
|---|---|---|---|
| 平均唯一父块数 | **2.4** | 1.9 | +26% |

尤其在**短歧义查询**（Q5「怎么洗」）上表现最突出：
- Hybrid 配置：3 个唯一父块（覆盖多种材质）
- 纯向量配置：**仅 1 个**唯一父块（信息单一）

**2. 延迟分析**

| 组件 | 额外延迟 | 说明 |
|---|---|---|
| 混合检索 (BM25) | ~50ms | 本地算法，开销很低 |
| Rerank (gte-rerank API) | ~300ms | API 网络调用 |

**3. 各优化边际贡献排序**

根据实验数据：混合检索 > Parent-Child ≈ Rerank

**混合检索**对召回多样性的提升最直接（纯向量 vs 混合：1.9 → 2.4 父块数），尤其在短查询和专有名词匹配场景下效果显著。

#### 注意事项

- Rerank API (gte-rerank) 当前返回 `AccessDenied`，实际生效的是 Fallback 逻辑（取 Top-N）。需要前往 [DashScope 控制台](https://dashscope.console.aliyun.com/) 开通 gte-rerank 模型权限后才能完全发挥 Rerank 的贡献。
- 评估脚本支持两种模式：`--quick`（仅检索质量）和 `--judge`（含 LLM 裁判打分，需调用 qwen3-max API）。


---

## 实施记录 4：Query Rewrite（查询改写）

**日期**：2026-06-04
**状态**：已实施
**方案**：LLM 驱动的智能查询改写 + 指代消解

### 改动概述

引入查询改写层，在检索之前对用户查询进行智能扩展。对短查询进行关键词补充，对包含指代词的查询结合对话历史进行消解。将系统从「用户说什么就搜什么」升级为「理解用户意图后再搜索」。

### 为什么需要查询改写

原系统的检索直接将用户输入送入检索引擎，存在以下问题：

1. **短查询信息量不足**：如「怎么洗」仅 3 个字，向量 Embedding 方向模糊，难以精确匹配相关内容
2. **指代消解缺失**：多轮对话中「那纯棉的呢？」依赖于上文，但系统无法自动补全上下文
3. **口语化表达**：用户习惯用口语化表达（「不掉色的」），但知识库中使用的是专业术语（「固色」「防褪色」）

### 实现方案

#### 改写流程

```
用户输入
  → 判断是否需要改写（长度 / 指代词检测）
  → 若需要：LLM 改写（结合对话历史）
  → 改写后查询 → 混合检索
  → 原始查询保留 → 用于最终回答生成
```

#### 改写策略（`src/query_rewriter.py`）

| 策略 | 触发条件 | 示例 |
|---|---|---|
| **短查询扩展** | 查询 < 15 字符 | 「怎么洗」→「不同衣物材质的洗涤方法、水温要求和注意事项」 |
| **指代消解** | 含「这个」「那个」「它」「那」等 | 历史「毛衣保养」→ 用户「那纯棉的呢？」→「纯棉材质的洗涤保养方法」 |
| **保持原样** | 查询已具体明确（≥ 15 字符，无指代词） | 「针织毛衣如何保养？」→ 保持不变 |

#### LLM 改写 Prompt 设计

```text
系统角色：查询优化专家

规则：
1. 短查询扩展：补充关键词，扩展为完整检索语句
2. 指代消解：结合对话历史替换指代词
3. 专业术语补充：补充同义关键词
4. 保持简洁：改写后不超过 50 字
5. 不编造内容：仅基于查询和历史改写

temperature=0.0（确保改写确定性）
```

### 改动文件

| 文件 | 改动 |
|---|---|
| [query_rewriter.py](src/query_rewriter.py) | **新建**，LLM 驱动的查询改写器（含同步/异步接口） |
| [rag_async.py](src/rag_async.py) | 集成查询改写：检索前先执行 `query_rewriter.arewrite()` |
| [config_data.py](src/config_data.py) | 新增 `query_rewrite_enabled`、`query_rewrite_min_length`、`query_rewrite_model_name` |

### 什么业务场景适合查询改写

| 场景 | 效果 |
|---|---|
| **短查询**（< 10 字） | 显著提升召回率，补全缺失的关键词 |
| **多轮对话** | 解决指代消解问题，后续问题不再偏离上下文 |
| **客服场景** | 用户习惯简短提问，改写后可精确匹配知识库 |
| **跨语言/口语化** | 口语化表达 → 专业术语映射 |

不适合的场景：
- 用户查询已经非常具体明确（改写可能引入噪声）
- 对延迟极度敏感（改写增加 1 次 LLM 调用，约 200-500ms）

### 达到的效果

| 查询类型 | 改写前 | 改写后 | 效果 |
|---|---|---|---|
| 短查询 | 「怎么洗」 | 「不同衣物材质的洗涤方法、水温要求和注意事项」 | 检索召回更全面 |
| 指代 | 「那纯棉的呢？」 | 「纯棉材质的洗涤保养方法」 | 消除歧义，精准命中 |
| 已明确 | 「针织毛衣如何保养？」 | 保持原样 | 不改写，避免过度扩展 |

**核心收益**：
1. **短查询不再是瓶颈**：改写后查询包含更多关键词，BM25 和向量检索都能更好地匹配
2. **多轮对话更自然**：用户不需要重复上下文，系统自动补全
3. **改写失败自动降级**：LLM 调用失败时返回原查询，不影响主流程
4. **改写结果仅用于检索**：最终回答仍使用用户原始查询，保持自然对话感


---

## 实施记录 5：异步改造（Async/Await）

**日期**：2026-06-04
**状态**：已实施
**方案**：全链路异步化（Async Chain + asyncio.to_thread 混合策略）

### 改动概述

将 RAG 管线从纯同步模式升级为全链路异步模式。使用 LangChain 的 `ainvoke`/`astream` 原语，对同步 API（DashScope Rerank、BM25 检索）使用 `asyncio.to_thread` 包装。同时提供同步兼容接口（`sync_stream`），确保现有 Streamlit UI 无需改动。

### 为什么需要异步

原系统所有操作都是同步的（`invoke` / `stream`），存在以下瓶颈：

1. **阻塞式 API 调用**：每次 LLM 调用、Rerank API 调用都会阻塞当前线程
2. **串行等待**：Query Rewrite → Retrieval → Rerank → Generation 完全串行，无法重叠 I/O 等待时间
3. **无法支持高并发**：同步模式下，同一时刻只能处理一个请求（Streamlit 受影响较小，但迁移到 FastAPI 时将成为瓶颈）

### 实现方案

#### 架构设计

```
AsyncRagService
├── 异步接口（FastAPI / aiohttp）
│   ├── ainvoke()  → 异步非流式调用
│   └── astream()  → 异步流式生成
│
└── 同步兼容接口（Streamlit）
    ├── sync_invoke()  → asyncio.run(ainvoke)
    └── sync_stream()  → 生产-消费队列桥接
```

#### 异步改造策略

| 组件 | 原同步方式 | 异步方式 | 策略 |
|---|---|---|---|
| Query Rewrite | `ChatTongyi.invoke()` | `ChatTongyi.ainvoke()` | LangChain 原生异步 |
| Hybrid Search | `retriever.invoke()` | `asyncio.to_thread(retrieve)` | CPU-bound → 线程池 |
| Rerank | `TextReRank.call()` | `asyncio.to_thread(rerank)` | 同步 API → 线程池 |
| LLM Generation | `ChatTongyi.stream()` | `ChatTongyi.astream()` | LangChain 原生异步 |
| History I/O | `json.load/dump` | `asyncio.to_thread(...)` | 文件 I/O → 线程池 |

#### 同步桥接（Streamlit 兼容）

```python
def sync_stream(self, input_data, config):
    """异步流 → 同步生成器"""
    q = queue.Queue()
    # 后台线程运行 asyncio event loop
    thread = Thread(target=run_async_loop, daemon=True)
    thread.start()
    # 主线程通过队列消费
    while True:
        msg_type, payload = q.get()
        if msg_type == "done": break
        yield payload
```

### 改动文件

| 文件 | 改动 |
|---|---|
| [rag_async.py](src/rag_async.py) | **新建**，全链路异步 RAG 服务（`ainvoke`/`astream`/`sync_stream`） |
| [reranker.py](src/reranker.py) | 新增 `arerank()` 异步方法（`asyncio.to_thread` 包装） |
| [query_rewriter.py](src/query_rewriter.py) | 新增 `arewrite()` 异步方法（LLM `ainvoke`） |
| [app_qa.py](app/app_qa.py) | 升级为 `AsyncRagService` + `sync_stream()` 兼容接口 |

### 达到的效果

| 维度 | 同步（旧） | 异步（新） |
|---|---|---|
| LLM 调用 | 阻塞线程 | 非阻塞，释放事件循环 |
| Rerank API | 阻塞线程 | `asyncio.to_thread`，线程池管理 |
| 并发支持 | 单请求 | 支持多请求并发（FastAPI 等） |
| Streamlit 兼容 | 原生 `stream()` | `sync_stream()` 桥接，API 不变 |
| 代码结构 | 同步链 | 异步链，可扩展性更强 |

**核心收益**：
1. **不阻塞事件循环**：LLM 和 API 调用期间可以处理其他任务
2. **为 FastAPI 迁移铺路**：异步接口可直接用于 `@app.post("/chat")` 端点
3. **向后兼容**：`sync_stream()` 确保现有 Streamlit UI 零改动即可使用
4. **查询改写无缝集成**：异步改写调用与检索链自然融合


---

## 完整流程：离线上传与在线检索

### 系统总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                        RAG 知识库问答系统                              │
├────────────────────────────┬────────────────────────────────────────┤
│      离线上传（写入）        │          在线检索（读取）                  │
│   app_file_uploader.py     │         app_qa.py                      │
└────────────────────────────┴────────────────────────────────────────┘
```

### 一、离线上传流程（Knowledge Base Ingestion）

```
┌──────────┐    ┌─────────────┐    ┌──────────────────┐    ┌──────────────┐
│ 用户上传  │───▶│  MD5 去重    │───▶│  语义分块          │───▶│  向量嵌入      │
│ .txt 文件 │    │  文件级校验   │    │  Semantic Splitter │    │  Embedding    │
└──────────┘    └─────────────┘    └──────────────────┘    └──────────────┘
                      │                     │                      │
                      ▼                     ▼                      ▼
               ┌─────────────┐    ┌──────────────────┐    ┌──────────────┐
               │ 重复 → 拒绝  │    │ Parent-Child 结构  │    │ Chroma 向量库  │
               │ 新文件→ 继续  │    │ 子块(检)+父块(读)  │    │ 持久化写入     │
               └─────────────┘    └──────────────────┘    └──────────────┘
```

**详细步骤：**

| 步骤 | 组件 | 操作 | 说明 |
|---|---|---|---|
| 1. 文件上传 | `app_file_uploader.py` | Streamlit `file_uploader` | 支持 .txt 文件 |
| 2. MD5 校验 | `knowledge_base.py::check_md5()` | 计算文件内容 MD5，比对 `md5.text` | 防止重复上传 |
| 3. 语义分块 | `semantic_splitter.py::split_by_structure()` | 按文件类型结构感知拆分 | 洗涤→季节→材质；颜色→主题编号 |
| 4. 元数据标注 | `knowledge_base.py::upload_bt_str()` | 添加 `chunk_type`、`section_title`、`parent_content` | Parent-Child 关键 |
| 5. 向量嵌入 | `DashScopeEmbeddings` | `text-embedding-v4` 嵌入 | 每块 → 向量 |
| 6. 写入向量库 | `Chroma.add_texts()` | 持久化到 `chroma.db/` | 可重复读取 |
| 7. 记录 MD5 | `knowledge_base.py::save_md5()` | 追加到 `md5.text` | 后续去重依据 |

### 二、在线检索流程（Real-time Retrieval + Generation）

```
                            ┌──────────────────────────────────────┐
                            │         用户输入查询                    │
                            └──────────────────┬───────────────────┘
                                               │
                                    ┌──────────▼──────────┐
                                    │  ① Query Rewrite     │  实施记录4
                                    │  LLM 查询改写+指代消解  │
                                    │  (短查询扩展/历史补全)  │
                                    └──────────┬──────────┘
                                               │ 改写后的查询
                                    ┌──────────▼──────────┐
                                    │  ② Hybrid Search     │  实施记录3
                                    │  ┌────────┬────────┐ │
                                    │  │Vector  │ BM25   │ │
                                    │  │Dense   │ Sparse │ │
                                    │  │Top-20  │ Top-20 │ │
                                    │  └────────┴────────┘ │
                                    │    RRF 融合去重 → Top-20│
                                    └──────────┬──────────┘
                                               │ 候选文档
                                    ┌──────────▼──────────┐
                                    │  ③ Re-ranking       │  实施记录1
                                    │  gte-rerank 精排      │
                                    │  Cross-Encoder 打分   │
                                    │  Top-20 → Top-3       │
                                    └──────────┬──────────┘
                                               │ 精选文档
                                    ┌──────────▼──────────┐
                                    │  ④ Parent-Child 展开 │  实施记录2
                                    │  子块→父块索引查找    │
                                    │  去重：同父块合并     │
                                    └──────────┬──────────┘
                                               │ 完整上下文
                                    ┌──────────▼──────────┐
                                    │  ⑤ Context 拼接      │
                                    │  注入 System Prompt  │
                                    │  + 对话历史 Messages  │
                                    └──────────┬──────────┘
                                               │ 完整 Prompt
                                    ┌──────────▼──────────┐
                                    │  ⑥ LLM 生成         │
                                    │  qwen3-max (astream) │
                                    │  流式逐 token 输出    │
                                    └──────────┬──────────┘
                                               │
                                    ┌──────────▼──────────┐
                                    │  ⑦ 对话历史持久化    │
                                    │  FileChatMessageHistory│
                                    │  写入 chat_history/   │
                                    └──────────────────────┘
```

**详细步骤：**

| 步骤 | 组件 | 操作 | 说明 |
|---|---|---|---|
| ① Query Rewrite | `query_rewriter.py::arewrite()` | LLM 扩展短查询、消解指代词 | 提升检索召回率 |
| ② Hybrid Search | `hybrid_retriever.py::retrieve()` | 向量 Top-20 + BM25 Top-20 → RRF 融合 | 语义 + 关键词互补 |
| ③ Rerank | `reranker.py::arerank()` | gte-rerank Cross-Encoder 精排 Top-3 | 去噪提纯 |
| ④ Parent-Child | `rag_async.py::aretrieve_and_rerank()` | 子块检索 → 父块展开 + 去重 | 碎片 → 完整段落 |
| ⑤ Context 拼接 | `rag_async.py` | 拼接 Prompt 模板 + 对话历史 | 注入 system prompt |
| ⑥ LLM 生成 | `ChatTongyi.astream()` | qwen3-max 流式生成 | Token 级流式输出 |
| ⑦ 历史持久化 | `file_history_store.py` | JSON 写入 `chat_history/{session_id}` | 多轮对话复用 |

### 三、存储结构

```
RAG/
├── data/                    # 原始数据文件
│   ├── 洗涤养护.txt
│   ├── 颜色选择.txt
│   └── 尺码推荐.txt
├── chroma.db/               # Chroma 向量数据库（持久化）
│   └── ...                  # 112 个语义块（子块+父块）
├── md5.text                 # 文件 MD5 去重记录
├── chat_history/            # 对话历史（按 session_id）
│   └── {uuid}.json
├── src/                     # 核心源码
│   ├── config_data.py       # 全局配置
│   ├── semantic_splitter.py # 语义分块器
│   ├── knowledge_base.py    # 知识库管理（离线上传）
│   ├── vector_stores.py     # Chroma 向量库封装
│   ├── bm25_retriever.py    # BM25 关键词检索
│   ├── hybrid_retriever.py  # 混合检索引擎
│   ├── reranker.py          # gte-rerank 重排序
│   ├── query_rewriter.py    # LLM 查询改写
│   ├── rag.py               # 同步 RAG 服务
│   ├── rag_async.py         # 异步 RAG 服务（生产推荐）
│   └── file_history_store.py # 对话历史持久化
├── app/                     # Web 应用
│   ├── app_qa.py            # 在线问答界面（Streamlit）
│   └── app_file_uploader.py # 离线上传界面（Streamlit）
├── eval/                    # 评估框架
│   └── rag_evaluation.py    # 消融实验评估脚本
└── RAG优化.md               # 优化记录（本文档）
```

### 四、启动方式

```bash
# 离线上传界面
streamlit run app/app_file_uploader.py

# 在线问答界面
streamlit run app/app_qa.py

# 评估
python eval/rag_evaluation.py --quick          # 快速检索质量评估
python eval/rag_evaluation.py                  # 含 LLM 裁判的完整评估
```

### 五、七项优化总览

| # | 优化项 | 实施日期 | 文件 | 核心价值 |
|---|---|---|---|---|
| 0 | **Agent 升级** | 2026-06-07 | `src/agent/` | RAG→Agent，LLM 自主决策 + 工具调用 |
| 1 | **Re-ranking** | 2026-05-19 | `reranker.py` | gte-rerank 精排，去噪提纯 |
| 2 | **语义分块 + Parent-Child** | 2026-05-19 | `semantic_splitter.py` | 结构感知分块，碎片→完整段落 |
| 3 | **混合检索** | 2026-06-04 | `hybrid_retriever.py` | 向量 + BM25 双路互补 |
| 4 | **Query Rewrite** | 2026-06-04 | `query_rewriter.py` | 短查询扩展 + 指代消解 |
| 5 | **异步改造** | 2026-06-04 | `rag_async.py` | 全链路异步，支持高并发 |
| 6 | **FastAPI + 前端** | 2026-06-07 | `app/` `frontend/` | RESTful API + SPA 前端 + Agent SSE 事件 |
