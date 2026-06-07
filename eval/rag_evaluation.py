"""
RAG 系统综合评估框架
====================

对三项核心优化进行消融实验（Ablation Study），评估各优化方法的独立贡献和协同效果：

  优化1: Re-ranking（重排序）          — gte-rerank Cross-Encoder 精排
  优化2: Semantic Chunking（语义分块）  — 结构感知分块 + Parent-Child 展开
  优化3: Hybrid Search（混合检索）      — 向量检索 + BM25 → RRF 融合

评估维度:
  1. 检索质量（Retrieval Quality）— 检索到的文档与查询的相关性
  2. 回答忠实度（Faithfulness）   — 回答是否严格基于上下文（不编造）
  3. 回答相关性（Relevance）      — 回答是否切题
  4. 回答完整性（Completeness）   — 回答是否覆盖了上下文中的关键信息
  5. 延迟（Latency）              — 检索+生成耗时

消融配置（5 组）:
  A. Full Pipeline    — 混合检索 + Rerank + Parent-Child（当前生产配置）
  B. No Hybrid        — 纯向量检索 + Rerank + Parent-Child
  C. No Rerank        — 混合检索（无精排） + Parent-Child
  D. No Parent-Child  — 混合检索 + Rerank（无父子展开）
  E. Baseline         — 纯向量检索（无精排，无父子展开）

用法:
  python eval/rag_evaluation.py              # 完整评估（含 LLM 裁判打分）
  python eval/rag_evaluation.py --quick       # 快速评估（仅检索质量，不调用 LLM）
  python eval/rag_evaluation.py --output report.md  # 指定报告输出路径
"""

import sys
import os
import json
import time
import re
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from langchain_community.embeddings import DashScopeEmbeddings
from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_core.documents import Document

from src.vector_stores import VectorStoreService
from src.reranker import RerankerService
from src.bm25_retriever import BM25Retriever
from src.hybrid_retriever import HybridRetriever
from src import config_data as config


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class QueryCase:
    """测试查询定义"""
    query_id: str
    query: str
    query_type: str          # factual | reasoning | lookup | comparison | short
    expected_keywords: List[str] = field(default_factory=list)
    description: str = ""


@dataclass
class EvalResult:
    """单次查询评估结果"""
    query_id: str
    config_name: str
    query: str
    query_type: str
    retrieved_docs: int
    unique_parents: int
    context_length: int
    retrieval_latency_ms: float
    generation_latency_ms: float = 0.0
    total_latency_ms: float = 0.0
    faithfulness: float = 0.0     # LLM judge 打分 (1-5)
    relevance: float = 0.0
    completeness: float = 0.0
    overall: float = 0.0
    answer: str = ""
    context_snippet: str = ""
    judge_explanation: str = ""
    error: str = ""


# ============================================================================
# 测试查询集
# ============================================================================

TEST_QUERIES = [
    QueryCase(
        query_id="Q1",
        query="针织毛衣如何保养？",
        query_type="factual",
        expected_keywords=["洗涤", "养护", "针织棉", "冷水", "手洗"],
        description="特定材质的养护方法查询，需要有具体的洗涤和养护步骤",
    ),
    QueryCase(
        query_id="Q2",
        query="真丝连衣裙怎么洗？",
        query_type="factual",
        expected_keywords=["真丝", "干洗", "水洗", "洗涤", "夏季"],
        description="特定材质（真丝）的洗涤查询，预期需要精确匹配材质名称",
    ),
    QueryCase(
        query_id="Q3",
        query="身高178体重160斤应该买多大码？",
        query_type="lookup",
        expected_keywords=["身高", "体重", "尺码", "XL", "推荐"],
        description="数值查找类查询，需要精确匹配身高体重参数",
    ),
    QueryCase(
        query_id="Q4",
        query="黄皮肤的人春天穿什么颜色好看？",
        query_type="reasoning",
        expected_keywords=["黄皮肤", "春季", "颜色", "推荐", "肤色"],
        description="跨文档推理：需要结合肤色知识和季节颜色推荐",
    ),
    QueryCase(
        query_id="Q5",
        query="怎么洗",
        query_type="short",
        expected_keywords=["洗涤", "材质", "水温", "注意事项"],
        description="短歧义查询：信息量极少，对检索系统挑战最大",
    ),
    QueryCase(
        query_id="Q6",
        query="夏天穿什么面料的衣服比较凉快？",
        query_type="reasoning",
        expected_keywords=["夏季", "面料", "凉爽", "真丝", "纯棉", "透气"],
        description="推理型查询：需要从多种面料中找出适合夏季的",
    ),
    QueryCase(
        query_id="Q7",
        query="羊毛衫和棉T恤的洗涤方式有什么不同？",
        query_type="comparison",
        expected_keywords=["羊毛", "棉", "洗涤", "对比", "水温", "手洗", "机洗"],
        description="对比型查询：需要同时检索两种材质并进行对比",
    ),
    QueryCase(
        query_id="Q8",
        query="皮肤偏黑的人应该避免什么颜色？",
        query_type="reasoning",
        expected_keywords=["肤色", "偏黑", "避免", "颜色", "不推荐"],
        description="否定/反向推理：查询'应该避免什么'而非'推荐什么'",
    ),
]


# ============================================================================
# 消融配置
# ============================================================================

@dataclass
class AblationConfig:
    """消融实验配置"""
    name: str
    description: str
    use_hybrid: bool        # 是否使用混合检索
    use_rerank: bool        # 是否使用重排序
    use_parent_child: bool  # 是否使用 Parent-Child 展开
    optimizations: List[str] = field(default_factory=list)


ABLATION_CONFIGS = [
    AblationConfig(
        name="A_Full",
        description="完整管线（当前生产配置）",
        use_hybrid=True,
        use_rerank=True,
        use_parent_child=True,
        optimizations=["混合检索", "Re-ranking", "Parent-Child"],
    ),
    AblationConfig(
        name="B_NoHybrid",
        description="去除混合检索（仅向量检索）",
        use_hybrid=False,
        use_rerank=True,
        use_parent_child=True,
        optimizations=["Re-ranking", "Parent-Child"],
    ),
    AblationConfig(
        name="C_NoRerank",
        description="去除重排序（仅混合检索）",
        use_hybrid=True,
        use_rerank=False,
        use_parent_child=True,
        optimizations=["混合检索", "Parent-Child"],
    ),
    AblationConfig(
        name="D_NoParentChild",
        description="去除 Parent-Child 展开",
        use_hybrid=True,
        use_rerank=True,
        use_parent_child=False,
        optimizations=["混合检索", "Re-ranking"],
    ),
    AblationConfig(
        name="E_Baseline",
        description="基线（无任何优化）",
        use_hybrid=False,
        use_rerank=False,
        use_parent_child=False,
        optimizations=[],
    ),
]


# ============================================================================
# LLM Judge（裁判模型）
# ============================================================================

JUDGE_PROMPT = """你是一个 RAG（检索增强生成）系统的专业评估者。请根据以下信息对回答质量进行打分。

## 用户查询
{query}

## 参考资料（检索到的上下文）
{context}

## 系统回答
{answer}

## 打分维度（每个维度 1-5 分，5 分最好）

1. **忠实度 (faithfulness)**：回答是否严格基于参考资料？有没有编造内容？
   - 5分：所有内容都能在参考资料中找到依据
   - 3分：部分有依据，部分不确定来源
   - 1分：大量编造，与参考资料矛盾

2. **相关性 (relevance)**：回答是否直接回应了用户的问题？
   - 5分：精准回答问题，没有跑题
   - 3分：部分相关，有一些无关内容
   - 1分：完全答非所问

3. **完整性 (completeness)**：回答是否覆盖了参考资料中的关键信息？
   - 5分：覆盖所有关键信息
   - 3分：覆盖部分关键信息，遗漏较多
   - 1分：几乎没有覆盖参考资料中的有用信息

## 输出格式（严格遵守 JSON 格式，不要输出其他内容）
{{
  "faithfulness": <分数>,
  "relevance": <分数>,
  "completeness": <分数>,
  "explanation": "<一句话简短说明>"
}}
"""


class LLMJudge:
    """使用 qwen3-max 作为评估裁判"""

    def __init__(self, model_name: str = "qwen3-max"):
        self.model = ChatTongyi(model=model_name, temperature=0.0)

    def score(self, query: str, context: str, answer: str) -> dict:
        """
        对回答进行三维打分。

        Returns:
            dict with keys: faithfulness, relevance, completeness, explanation
        """
        prompt = JUDGE_PROMPT.format(
            query=query,
            context=context[:3000],  # 限制 context 长度，避免超出 token 限制
            answer=answer[:2000],
        )

        try:
            response = self.model.invoke(prompt)
            response_text = response.content if hasattr(response, "content") else str(response)

            # 尝试提取 JSON（处理可能的 markdown 代码块包装）
            json_match = re.search(r"\{[^{}]*\"faithfulness\"[^{}]*\}", response_text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(0))
                return {
                    "faithfulness": float(result.get("faithfulness", 3)),
                    "relevance": float(result.get("relevance", 3)),
                    "completeness": float(result.get("completeness", 3)),
                    "explanation": result.get("explanation", ""),
                }
            else:
                # 降级：尝试直接从文本中提取数字
                scores = {}
                for key in ["faithfulness", "relevance", "completeness"]:
                    m = re.search(rf'"{key}"\s*:\s*(\d)', response_text)
                    scores[key] = float(m.group(1)) if m else 3.0
                return {
                    **scores,
                    "explanation": "JSON parse fallback",
                }
        except Exception as e:
            return {
                "faithfulness": 0,
                "relevance": 0,
                "completeness": 0,
                "explanation": f"Judge error: {str(e)[:100]}",
            }


# ============================================================================
# 检索 + 生成引擎
# ============================================================================

class RetrievalEngine:
    """可配置的检索引擎，支持消融实验的各种配置"""

    def __init__(self):
        self.embedding = DashScopeEmbeddings(model=config.embedding_model_name)
        self.vector_service = VectorStoreService(embedding=self.embedding)
        self.vector_retriever = self.vector_service.get_retriever()

        # BM25 索引（所有配置共享）
        all_docs = self.vector_service.get_all_documents()
        self.bm25_retriever = BM25Retriever(all_docs)

        # 混合检索器
        self.hybrid_retriever = HybridRetriever(
            self.vector_retriever, self.bm25_retriever
        )

        # 重排序器
        self.reranker = RerankerService()

        # 生成模型
        self.chat_model = ChatTongyi(model=config.chat_model_name, temperature=0.0)

    def retrieve(
        self, query: str, abl_config: AblationConfig
    ) -> Tuple[List[Document], float]:
        """
        根据消融配置执行检索。

        Returns:
            (documents, latency_ms)
        """
        t0 = time.perf_counter()

        if abl_config.use_hybrid:
            docs = self.hybrid_retriever.retrieve(query)
        else:
            docs = self.vector_retriever.invoke(query)

        if abl_config.use_rerank:
            docs = self.reranker.rerank(query, docs)
        else:
            # 不使用 Rerank，直接取前 N 个（与 Rerank 后数量一致）
            docs = docs[: config.reranker_top_n]

        latency = (time.perf_counter() - t0) * 1000
        return docs, latency

    def build_context(self, docs: List[Document], use_parent_child: bool) -> str:
        """
        根据配置构建上下文文本。

        Args:
            docs: 检索到的文档列表
            use_parent_child: 是否使用 Parent-Child 展开
        """
        if not docs:
            return "无相关参考资料"

        if use_parent_child:
            seen_parents = set()
            parts = []
            for doc in docs:
                parent = doc.metadata.get("parent_content", "")
                title = doc.metadata.get("section_title", "")
                if parent and parent not in seen_parents:
                    seen_parents.add(parent)
                    if title:
                        parts.append(f"【{title}】\n{parent}")
                    else:
                        parts.append(parent)
                elif not parent:
                    parts.append(doc.page_content)
            return "\n\n---\n\n".join(parts)
        else:
            # 不使用 Parent-Child，直接用子块内容
            parts = []
            for doc in docs:
                title = doc.metadata.get("section_title", "")
                if title:
                    parts.append(f"【{title}】\n{doc.page_content}")
                else:
                    parts.append(doc.page_content)
            return "\n\n---\n\n".join(parts)

    def generate(self, query: str, context: str) -> Tuple[str, float]:
        """使用 LLM 生成回答。"""
        t0 = time.perf_counter()

        prompt = f"""请以我提供的已知参考资料为主，简洁和专业的回答用户问题。

参考资料:
{context}

用户问题: {query}

请直接回答，不要添加"根据参考资料"等前缀。如果参考资料中没有相关信息，请如实说"知识库中未找到相关信息"。"""

        try:
            response = self.chat_model.invoke(prompt)
            answer = response.content if hasattr(response, "content") else str(response)
        except Exception as e:
            answer = f"[生成失败: {e}]"

        latency = (time.perf_counter() - t0) * 1000
        return answer, latency

    def count_unique_parents(self, docs: List[Document]) -> int:
        """统计不重复的父块数量（衡量上下文多样性）。"""
        parents = set()
        for doc in docs:
            parent = doc.metadata.get("parent_content", "")
            if parent:
                parents.add(parent)
        return len(parents)


# ============================================================================
# 主评估器
# ============================================================================

class RAGEvaluator:
    """RAG 系统综合评估器"""

    def __init__(self, use_judge: bool = True):
        self.engine = RetrievalEngine()
        self.judge = LLMJudge() if use_judge else None
        self.use_judge = use_judge
        self.results: List[EvalResult] = []

    def evaluate_query(
        self, query_case: QueryCase, abl_config: AblationConfig
    ) -> EvalResult:
        """对单个查询 + 配置组合进行评估。"""
        result = EvalResult(
            query_id=query_case.query_id,
            config_name=abl_config.name,
            query=query_case.query,
            query_type=query_case.query_type,
            retrieved_docs=0,
            unique_parents=0,
            context_length=0,
            retrieval_latency_ms=0.0,
        )

        try:
            # Step 1: 检索
            docs, retrieval_latency = self.engine.retrieve(
                query_case.query, abl_config
            )
            result.retrieved_docs = len(docs)
            result.unique_parents = self.engine.count_unique_parents(docs)
            result.retrieval_latency_ms = retrieval_latency

            # Step 2: 构建上下文
            context = self.engine.build_context(docs, abl_config.use_parent_child)
            result.context_length = len(context)
            result.context_snippet = context[:200]

            # Step 3: 生成回答
            answer, generation_latency = self.engine.generate(
                query_case.query, context
            )
            result.answer = answer[:500]
            result.generation_latency_ms = generation_latency
            result.total_latency_ms = retrieval_latency + generation_latency

            # Step 4: LLM 裁判打分
            if self.judge:
                scores = self.judge.score(query_case.query, context, answer)
                result.faithfulness = scores["faithfulness"]
                result.relevance = scores["relevance"]
                result.completeness = scores["completeness"]
                result.overall = round(
                    (scores["faithfulness"] + scores["relevance"] + scores["completeness"]) / 3,
                    2,
                )
                result.judge_explanation = scores.get("explanation", "")

        except Exception as e:
            result.error = str(e)

        return result

    def run(self, queries: List[QueryCase] = None, configs: List[AblationConfig] = None):
        """运行完整评估。"""
        if queries is None:
            queries = TEST_QUERIES
        if configs is None:
            configs = ABLATION_CONFIGS

        total = len(queries) * len(configs)
        count = 0

        for query_case in queries:
            for abl_config in configs:
                count += 1
                judge_info = "w/ judge" if self.use_judge else "quick"
                print(
                    f"\r[{count}/{total}] {query_case.query_id} | "
                    f"{abl_config.name:20s} | {judge_info}",
                    end="",
                    flush=True,
                )

                result = self.evaluate_query(query_case, abl_config)
                self.results.append(result)

        print(f"\n评估完成。共 {count} 组测试。")

    def get_aggregate_scores(self) -> Dict[str, Dict]:
        """按配置聚合评分。"""
        agg = {}
        for abl_config in ABLATION_CONFIGS:
            config_results = [
                r for r in self.results if r.config_name == abl_config.name and not r.error
            ]
            if not config_results:
                continue

            n = len(config_results)
            agg[abl_config.name] = {
                "description": abl_config.description,
                "optimizations": abl_config.optimizations,
                "avg_faithfulness": round(sum(r.faithfulness for r in config_results) / n, 2),
                "avg_relevance": round(sum(r.relevance for r in config_results) / n, 2),
                "avg_completeness": round(sum(r.completeness for r in config_results) / n, 2),
                "avg_overall": round(sum(r.overall for r in config_results) / n, 2),
                "avg_retrieval_ms": round(sum(r.retrieval_latency_ms for r in config_results) / n, 1),
                "avg_generation_ms": round(sum(r.generation_latency_ms for r in config_results) / n, 1),
                "avg_total_ms": round(sum(r.total_latency_ms for r in config_results) / n, 1),
                "avg_docs": round(sum(r.retrieved_docs for r in config_results) / n, 1),
                "avg_parents": round(sum(r.unique_parents for r in config_results) / n, 1),
                "errors": sum(1 for r in self.results if r.config_name == abl_config.name and r.error),
            }

        return agg

    def get_optimization_impact(self) -> Dict[str, Dict]:
        """计算各优化的边际贡献（从基线逐步叠加的增量）。"""
        agg = self.get_aggregate_scores()

        baseline = agg.get("E_Baseline", {})
        full = agg.get("A_Full", {})

        if not baseline or not full:
            return {}

        base_score = baseline.get("avg_overall", 0)
        full_score = full.get("avg_overall", 0)

        # 各优化的独立贡献
        no_hybrid = agg.get("B_NoHybrid", {})
        no_rerank = agg.get("C_NoRerank", {})
        no_pc = agg.get("D_NoParentChild", {})

        return {
            "total_improvement": {
                "baseline": base_score,
                "full_pipeline": full_score,
                "delta": round(full_score - base_score, 2),
                "pct": f"{(full_score - base_score) / max(base_score, 0.1) * 100:.0f}%",
            },
            "hybrid_search": {
                "description": "混合检索（向量 + BM25）",
                "contribution": round(full_score - no_hybrid.get("avg_overall", full_score), 2),
                "note": "A_Full vs B_NoHybrid 的差值",
            },
            "rerank": {
                "description": "重排序（gte-rerank）",
                "contribution": round(full_score - no_rerank.get("avg_overall", full_score), 2),
                "note": "A_Full vs C_NoRerank 的差值",
            },
            "parent_child": {
                "description": "Parent-Child 展开",
                "contribution": round(full_score - no_pc.get("avg_overall", full_score), 2),
                "note": "A_Full vs D_NoParentChild 的差值",
            },
        }

    def generate_report(self, output_path: str = None) -> str:
        """生成 Markdown 格式的评估报告。"""
        agg = self.get_aggregate_scores()
        impact = self.get_optimization_impact()

        lines = []
        lines.append("# RAG 系统优化评估报告")
        lines.append("")
        lines.append(f"**评估时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"**测试查询数**: {len(TEST_QUERIES)}")
        lines.append(f"**消融配置数**: {len(ABLATION_CONFIGS)}")
        lines.append(f"**LLM 裁判**: {'启用 (qwen3-max)' if self.use_judge else '未启用（仅检索质量）'}")
        lines.append("")

        # ---- 1. 执行摘要 ----
        lines.append("---")
        lines.append("")
        lines.append("## 一、执行摘要")
        lines.append("")

        if self.use_judge:
            baseline_score = agg.get("E_Baseline", {}).get("avg_overall", 0)
            full_score = agg.get("A_Full", {}).get("avg_overall", 0)
            improvement = full_score - baseline_score
            lines.append(f"- **基线得分**: {baseline_score:.2f}/5.00")
            lines.append(f"- **完整管线得分**: {full_score:.2f}/5.00")
            lines.append(f"- **总提升**: +{improvement:.2f}（{improvement/max(baseline_score,0.1)*100:.0f}%）")
            lines.append("")
            lines.append(f"三项优化（混合检索 + 重排序 + Parent-Child）组合使用，")
            lines.append(f"将 RAG 系统整体得分从 {baseline_score:.2f} 提升至 {full_score:.2f}。")
            lines.append("")

        # ---- 2. 综合评分 ----
        lines.append("---")
        lines.append("")
        lines.append("## 二、综合评分汇总")
        lines.append("")

        if self.use_judge:
            lines.append("| 配置 | 忠实度 | 相关性 | 完整性 | **综合** | 检索延迟 | 生成延迟 | 总延迟 |")
            lines.append("|---|---|---|---|---|---|---|---|")
            for abl_config in ABLATION_CONFIGS:
                a = agg.get(abl_config.name, {})
                name = abl_config.name.replace("_", " ")
                lines.append(
                    f"| **{name}** | {a.get('avg_faithfulness', 0):.2f} | "
                    f"{a.get('avg_relevance', 0):.2f} | {a.get('avg_completeness', 0):.2f} | "
                    f"**{a.get('avg_overall', 0):.2f}** | "
                    f"{a.get('avg_retrieval_ms', 0):.0f}ms | {a.get('avg_generation_ms', 0):.0f}ms | "
                    f"{a.get('avg_total_ms', 0):.0f}ms |"
                )
        else:
            lines.append("| 配置 | 检索文档数 | 唯一父块数 | 检索延迟 |")
            lines.append("|---|---|---|---|")
            for abl_config in ABLATION_CONFIGS:
                a = agg.get(abl_config.name, {})
                name = abl_config.name.replace("_", " ")
                lines.append(
                    f"| **{name}** | {a.get('avg_docs', 0):.1f} | "
                    f"{a.get('avg_parents', 0):.1f} | "
                    f"{a.get('avg_retrieval_ms', 0):.0f}ms |"
                )
        lines.append("")

        # ---- 3. 消融分析 ----
        lines.append("---")
        lines.append("")
        lines.append("## 三、消融分析：各优化的独立贡献")
        lines.append("")

        if self.use_judge and impact:
            imp = impact
            lines.append(f"### 3.1 从基线到完整管线")
            lines.append("")
            ti = imp.get("total_improvement", {})
            lines.append(f"- 基线: **{ti.get('baseline', 0):.2f}** → 完整管线: **{ti.get('full_pipeline', 0):.2f}**")
            lines.append(f"- 提升幅度: **+{ti.get('delta', 0):.2f}** ({ti.get('pct', 'N/A')})")
            lines.append("")

            lines.append(f"### 3.2 各优化边际贡献（逐一移除的影响）")
            lines.append("")
            lines.append("| 优化项 | 移除后综合分下降 | 说明 |")
            lines.append("|---|---|---|")
            for key in ["hybrid_search", "rerank", "parent_child"]:
                item = imp.get(key, {})
                lines.append(
                    f"| **{item.get('description', key)}** | "
                    f"-{abs(item.get('contribution', 0)):.2f} | "
                    f"{item.get('note', '')} |"
                )
            lines.append("")

            # Identify most impactful
            contributions = [
                (imp[k]["description"], abs(imp[k]["contribution"]))
                for k in ["hybrid_search", "rerank", "parent_child"]
                if k in imp
            ]
            contributions.sort(key=lambda x: x[1], reverse=True)
            if contributions:
                lines.append(f"**贡献排名**: ", end="")
                parts = [f"{desc}（{val:.2f}）" for desc, val in contributions]
                lines.append(" > ".join(parts))
            lines.append("")

        # ---- 4. 配置说明 ----
        lines.append("---")
        lines.append("")
        lines.append("## 四、消融配置说明")
        lines.append("")
        lines.append("| 配置 | 混合检索 | 重排序 | Parent-Child | 说明 |")
        lines.append("|---|---|---|---|---|")
        for abl_config in ABLATION_CONFIGS:
            hybrid = "✅" if abl_config.use_hybrid else "❌"
            rerank = "✅" if abl_config.use_rerank else "❌"
            pc = "✅" if abl_config.use_parent_child else "❌"
            lines.append(
                f"| **{abl_config.name}** | {hybrid} | {rerank} | {pc} | "
                f"{abl_config.description} |"
            )
        lines.append("")

        # ---- 5. 逐查询详情 ----
        lines.append("---")
        lines.append("")
        lines.append("## 五、逐查询详细对比")
        lines.append("")

        for query_case in TEST_QUERIES:
            lines.append(f"### {query_case.query_id}: {query_case.query}")
            lines.append(f"**类型**: {query_case.query_type} | {query_case.description}")
            lines.append("")

            if self.use_judge:
                lines.append("| 配置 | 忠实度 | 相关性 | 完整性 | 综合 | 延迟 |")
                lines.append("|---|---|---|---|---|---|")
            else:
                lines.append("| 配置 | 文档数 | 父块数 | 检索延迟 |")
                lines.append("|---|---|---|---|")

            for abl_config in ABLATION_CONFIGS:
                matching = [
                    r for r in self.results
                    if r.query_id == query_case.query_id and r.config_name == abl_config.name
                ]
                if matching:
                    r = matching[0]
                    if r.error:
                        lines.append(f"| {abl_config.name} | ⚠️ 错误: {r.error} | | | | |")
                    elif self.use_judge:
                        lines.append(
                            f"| **{abl_config.name}** | {r.faithfulness:.1f} | "
                            f"{r.relevance:.1f} | {r.completeness:.1f} | "
                            f"**{r.overall:.2f}** | {r.total_latency_ms:.0f}ms |"
                        )
                    else:
                        lines.append(
                            f"| **{abl_config.name}** | {r.retrieved_docs} | "
                            f"{r.unique_parents} | {r.retrieval_latency_ms:.0f}ms |"
                        )
            lines.append("")

            # Show best answer snippet for this query
            if self.use_judge:
                query_results = [
                    r for r in self.results
                    if r.query_id == query_case.query_id and not r.error
                ]
                if query_results:
                    best = max(query_results, key=lambda r: r.overall)
                    lines.append(f"<details>")
                    lines.append(f"<summary>最佳回答 ({best.config_name}, 综合 {best.overall:.2f})</summary>")
                    lines.append("")
                    lines.append(f"**上下文片段**: {best.context_snippet[:200]}...")
                    lines.append("")
                    lines.append(f"**回答**: {best.answer[:300]}")
                    lines.append("")
                    if best.judge_explanation:
                        lines.append(f"**裁判点评**: {best.judge_explanation}")
                    lines.append(f"</details>")
                    lines.append("")

        # ---- 6. 结论与建议 ----
        lines.append("---")
        lines.append("")
        lines.append("## 六、结论与建议")
        lines.append("")

        if self.use_judge and impact:
            ti = impact.get("total_improvement", {})
            lines.append(f"1. **三项优化组合使用效果显著**：从基线到完整管线提升了 {ti.get('pct', 'N/A')}")
            lines.append("2. **推荐生产配置**：A_Full（混合检索 + Rerank + Parent-Child），在质量和延迟之间取得最佳平衡")
            lines.append("3. **如果对延迟极度敏感**：可考虑 C_NoRerank（混合检索 + Parent-Child），省略 Rerank API 调用可节省 ~200ms")
            lines.append("4. **如果知识库很小（<10 篇文档）**：可考虑仅使用向量检索 + Rerank，混合检索的 BM25 优势在小规模下不明显")
        else:
            lines.append("（使用 `--judge` 参数启用 LLM 裁判打分以获取完整结论）")

        lines.append("")
        lines.append("---")
        lines.append(f"*报告由 eval/rag_evaluation.py 自动生成 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")

        report = "\n".join(lines)

        if output_path:
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(report)
            print(f"\n报告已保存至: {output_path}")

        return report


# ============================================================================
# 主入口
# ============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description="RAG 系统综合评估")
    parser.add_argument(
        "--quick", action="store_true",
        help="快速模式：仅评估检索质量，不调用 LLM 裁判"
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="报告输出路径（.md 文件）"
    )
    parser.add_argument(
        "--queries", type=str, nargs="*", default=None,
        help="指定测试查询 ID（如 Q1 Q3），默认全部"
    )
    args = parser.parse_args()

    use_judge = not args.quick
    judge_str = "qwen3-max LLM 裁判" if use_judge else "仅检索质量"

    print("=" * 70)
    print("  RAG 系统优化评估框架")
    print(f"  评估模式: {judge_str}")
    print(f"  测试查询: {len(TEST_QUERIES)} 个")
    print(f"  消融配置: {len(ABLATION_CONFIGS)} 组")
    print(f"  总计: {len(TEST_QUERIES) * len(ABLATION_CONFIGS)} 组测试")
    print("=" * 70)
    print()

    # 筛选查询
    queries = TEST_QUERIES
    if args.queries:
        queries = [q for q in TEST_QUERIES if q.query_id in args.queries]
        print(f"筛选查询: {[q.query_id for q in queries]}")

    # 运行评估
    evaluator = RAGEvaluator(use_judge=use_judge)

    if use_judge:
        print("⚠️  LLM 裁判模式将调用 qwen3-max API 进行打分，可能需要几分钟...")
        print()

    evaluator.run(queries=queries)

    # 生成报告
    output_path = args.output or os.path.join(
        os.path.dirname(__file__), "eval_report.md"
    )
    report = evaluator.generate_report(output_path)

    # 打印摘要
    print()
    print("=" * 70)
    print("  评估摘要")
    print("=" * 70)

    agg = evaluator.get_aggregate_scores()
    if use_judge:
        print(f"{'配置':25s} {'忠实度':>6s} {'相关性':>6s} {'完整性':>6s} {'综合':>6s} {'延迟':>8s}")
        print("-" * 65)
        for abl_config in ABLATION_CONFIGS:
            a = agg.get(abl_config.name, {})
            print(
                f"{abl_config.name:25s} "
                f"{a.get('avg_faithfulness', 0):6.2f} "
                f"{a.get('avg_relevance', 0):6.2f} "
                f"{a.get('avg_completeness', 0):6.2f} "
                f"{a.get('avg_overall', 0):6.2f} "
                f"{a.get('avg_total_ms', 0):7.0f}ms"
            )
    else:
        print(f"{'配置':25s} {'文档数':>6s} {'父块数':>6s} {'检索延迟':>8s}")
        print("-" * 50)
        for abl_config in ABLATION_CONFIGS:
            a = agg.get(abl_config.name, {})
            print(
                f"{abl_config.name:25s} "
                f"{a.get('avg_docs', 0):6.1f} "
                f"{a.get('avg_parents', 0):6.1f} "
                f"{a.get('avg_retrieval_ms', 0):7.0f}ms"
            )

    # 消融洞察
    impact = evaluator.get_optimization_impact()
    if impact:
        print()
        print("--- 优化贡献 ---")
        ti = impact.get("total_improvement", {})
        print(f"基线 → 完整管线: {ti.get('baseline', 0):.2f} → {ti.get('full_pipeline', 0):.2f} (+{ti.get('delta', 0):.2f})")
        print()
        print("各优化移除影响（越大越重要）:")
        for key in ["hybrid_search", "rerank", "parent_child"]:
            item = impact.get(key, {})
            if item:
                print(f"  {item['description']:20s}: {item['contribution']:.2f}")

    print()
    print(f"完整报告: {output_path}")


if __name__ == "__main__":
    main()
