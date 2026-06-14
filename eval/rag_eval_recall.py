"""
RAG 召回率评估脚本 — 基于 100 条企业知识库测试集

评估当前检索 pipeline 对 100 条真实企业知识库查询的召回效果。
测试集包含 6 个分类、6 种问题类型。

检索 Pipeline（与 Agent search_knowledge_base 工具一致）:
  查询改写 → 混合检索(向量+BM25) → Cross-Encoder 重排序 → Parent-Child 展开

用法:
  python eval/rag_eval_recall.py                  # 完整 100 条评估
  python eval/rag_eval_recall.py --limit 20       # 仅前 20 条（快速测试）
  python eval/rag_eval_recall.py --category 考勤与休假制度  # 筛选分类
"""

import sys
import os
import re
import time
import json
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from langchain_community.embeddings import DashScopeEmbeddings
from langchain_core.documents import Document

from src.retrieval import VectorStoreService
from src.retrieval import RerankerService
from src.retrieval import BM25Retriever
from src.retrieval import HybridRetriever
from src.rag.rewriter import QueryRewriter
import src.config as config


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class TestQuery:
    """测试集单条查询"""
    query_id: str
    question: str
    expected_answer: str       # 正确答案片段
    question_type: str         # 事实类 | 细节类 | 对比类 | 总结类 | 流程类 | 短歧义类
    category: str              # 考勤与休假制度 | 薪酬福利制度 | ...


@dataclass
class EvalResult:
    """单条评估结果"""
    query_id: str
    question: str
    expected_answer: str
    question_type: str
    category: str
    # 检索指标
    docs_retrieved: int        # 检索到的文档数
    unique_parents: int        # 去重后的父块数
    context_length: int        # 上下文总长度
    retrieval_latency_ms: float
    # 召回判定
    substring_match: bool      # 精确子串匹配
    substring_rank: int        # 首次匹配的排名（0=未匹配）
    keyword_coverage: float    # 关键词覆盖率 (0.0~1.0)
    matched_keywords: str      # 匹配到的关键词样例
    context_snippet: str       # 检索上下文片段


# ============================================================================
# 测试集解析
# ============================================================================

def parse_test_set(filepath: str) -> List[TestQuery]:
    """解析 RAG召回率测试集_100条完整版.txt。

    Returns:
        TestQuery 列表
    """
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    queries = []
    # 按 ================ 分割成块
    blocks = re.split(r"={10,}", content)

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        # 提取字段
        query_id = _extract_field(block, r"测试编号[：:]", r"(\d+)")
        question = _extract_field(block, r"问题[：:]", r"(.+?)(?:\n正确答案片段|$)")
        expected = _extract_field(block, r"正确答案片段[：:]", r"(.+?)(?:\n问题类型|$)")
        qtype = _extract_field(block, r"问题类型[：:]", r"(.+?)(?:\n所属分类|$)")
        category = _extract_field(block, r"所属分类[：:]", r"(.+?)$")

        if query_id and question and expected:
            queries.append(TestQuery(
                query_id=query_id.strip(),
                question=question.strip(),
                expected_answer=expected.strip(),
                question_type=qtype.strip() if qtype else "未知",
                category=category.strip() if category else "未知",
            ))

    return queries


def _extract_field(text: str, label_pattern: str, value_pattern: str) -> Optional[str]:
    """从文本块中提取字段值。"""
    m = re.search(label_pattern + r"\s*" + value_pattern, text, re.DOTALL | re.MULTILINE)
    if m:
        return m.group(1).strip()
    return None


# ============================================================================
# 关键词提取（简易，不依赖 jieba）
# ============================================================================

def extract_keywords(text: str, min_len: int = 2) -> List[str]:
    """从文本中提取关键词。

    使用中文分词启发式：按标点、数字、英文字母边界切分，
    过滤单字和纯标点/数字片段。
    """
    # 按常见分隔符切分
    tokens = re.split(r"[，。；、！？\s\n,\.;!?（）\(\)\[\]【】《》\"\'\"\':：/\-—\d]+", text)
    keywords = []
    for t in tokens:
        t = t.strip()
        if len(t) >= min_len and not t.isdigit():  # type: ignore
            keywords.append(t)
    return keywords


def calc_keyword_coverage(keywords: List[str], context: str) -> Tuple[float, List[str]]:
    """计算关键词在上下文中的覆盖率。

    Returns:
        (覆盖率, 匹配到的关键词列表)
    """
    if not keywords:
        return 0.0, []
    matched = [kw for kw in keywords if kw in context]
    return len(matched) / len(keywords), matched


# ============================================================================
# 检索引擎
# ============================================================================

class EvalRetrievalEngine:
    """复用生产检索 pipeline 进行评估。"""

    def __init__(self):
        self.embedding = DashScopeEmbeddings(model=config.embedding_model_name)
        self.vector_service = VectorStoreService(embedding=self.embedding)
        self.vector_retriever = self.vector_service.get_retriever()

        all_docs = self.vector_service.get_all_documents()
        self.bm25_retriever = BM25Retriever(all_docs)
        self.hybrid_retriever = HybridRetriever(
            self.vector_retriever, self.bm25_retriever
        )
        self.reranker = RerankerService()
        self.query_rewriter = QueryRewriter()

    async def retrieve(self, query: str, top_k: int = 5) -> Tuple[List[Document], str, float]:
        """执行完整检索 pipeline。

        Returns:
            (documents, rewritten_query, latency_ms)
        """
        t0 = time.perf_counter()

        # Step 1: 查询改写
        rewritten = await self.query_rewriter.arewrite(query)

        # Step 2: 混合检索
        docs = self.hybrid_retriever.retrieve(rewritten)

        # Step 3: 重排序
        if docs:
            docs = await self.reranker.arerank(rewritten, docs)

        latency = (time.perf_counter() - t0) * 1000
        return docs[:top_k], rewritten, latency

    @staticmethod
    def build_context(docs: List[Document]) -> str:
        """Parent-Child 展开 + 去重，拼接为上下文字符串。"""
        if not docs:
            return ""

        seen_parents = set()
        parts = []
        for doc in docs:
            parent = doc.metadata.get("parent_content", "")
            title = doc.metadata.get("section_title", "")
            source = doc.metadata.get("source", "")

            if parent and parent not in seen_parents:
                seen_parents.add(parent)
                header = f"【{title}】" if title else ""
                src = f" (来源: {source})" if source else ""
                parts.append(f"{header}{parent}{src}")
            elif not parent:
                parts.append(doc.page_content)

        return "\n\n---\n\n".join(parts)

    @staticmethod
    def count_unique_parents(docs: List[Document]) -> int:
        parents = set()
        for doc in docs:
            parent = doc.metadata.get("parent_content", "")
            if parent:
                parents.add(parent)
        return len(parents)


# ============================================================================
# 召回判定
# ============================================================================

def judge_recall(expected: str, docs: List[Document], context: str) -> dict:
    """判定检索结果是否覆盖预期答案。

    两种方法:
    1. 子串匹配 — 预期答案片段是否在 context 中出现（含部分匹配）
    2. 关键词覆盖率 — 预期答案的关键词在 context 中的覆盖比例
    """
    # 方法 1: 子串匹配（逐文档 + 总体 context）
    substring_rank = 0
    for rank, doc in enumerate(docs, 1):
        content = doc.page_content
        parent = doc.metadata.get("parent_content", "")
        combined = f"{content}\n{parent}"
        # 检查长句子片段（取预期答案的连续15字片段）
        for i in range(0, len(expected) - 14, 5):
            snippet = expected[i:i + 15]
            if len(snippet) >= 10 and snippet in combined:
                substring_rank = rank
                break
        if substring_rank > 0:
            break

    # 如果没有 15 字匹配，尝试更短片段
    if substring_rank == 0:
        for rank, doc in enumerate(docs, 1):
            content = doc.page_content
            parent = doc.metadata.get("parent_content", "")
            combined = f"{content}\n{parent}"
            for i in range(0, len(expected) - 9, 3):
                snippet = expected[i:i + 10]
                if len(snippet) >= 8 and snippet in combined:
                    substring_rank = rank
                    break
            if substring_rank > 0:
                break

    # 方法 2: 关键词覆盖率
    keywords = extract_keywords(expected)
    coverage, matched_kw = calc_keyword_coverage(keywords, context)

    return {
        "substring_match": substring_rank > 0,
        "substring_rank": substring_rank,
        "keyword_coverage": round(coverage, 3),
        "matched_keywords": ", ".join(matched_kw[:10]),
    }


# ============================================================================
# 主评估器
# ============================================================================

class RecallEvaluator:
    """RAG 召回率评估器"""

    def __init__(self):
        self.engine = EvalRetrievalEngine()
        self.results: List[EvalResult] = []

    async def evaluate_query(self, query: TestQuery, top_k: int = 5) -> EvalResult:
        """评估单条查询的召回效果。"""
        t0 = time.perf_counter()

        try:
            docs, rewritten, retrieval_latency = await self.engine.retrieve(
                query.question, top_k=top_k
            )
        except Exception as e:
            return EvalResult(
                query_id=query.query_id,
                question=query.question,
                expected_answer=query.expected_answer,
                question_type=query.question_type,
                category=query.category,
                docs_retrieved=0,
                unique_parents=0,
                context_length=0,
                retrieval_latency_ms=(time.perf_counter() - t0) * 1000,
                substring_match=False,
                substring_rank=0,
                keyword_coverage=0.0,
                matched_keywords=f"ERROR: {e}",
                context_snippet="",
            )

        context = self.engine.build_context(docs)
        parents = self.engine.count_unique_parents(docs)

        # 召回判定
        judge = judge_recall(query.expected_answer, docs, context)

        return EvalResult(
            query_id=query.query_id,
            question=query.question,
            expected_answer=query.expected_answer,
            question_type=query.question_type,
            category=query.category,
            docs_retrieved=len(docs),
            unique_parents=parents,
            context_length=len(context),
            retrieval_latency_ms=retrieval_latency,
            substring_match=judge["substring_match"],
            substring_rank=judge["substring_rank"],
            keyword_coverage=judge["keyword_coverage"],
            matched_keywords=judge["matched_keywords"],
            context_snippet=context[:300] if context else "",
        )

    async def run(self, queries: List[TestQuery], top_k: int = 5):
        """运行批量评估。"""
        total = len(queries)
        for i, q in enumerate(queries, 1):
            prefix = f"[{i}/{total}]"
            print(f"\r{prefix} {q.query_id}: {q.question[:40]}...", end="", flush=True)
            result = await self.evaluate_query(q, top_k=top_k)
            self.results.append(result)
        print(f"\r{'='*60}")
        print(f"评估完成。共 {total} 条查询。")

    # ---- 聚合统计 ----

    def _non_error(self) -> List[EvalResult]:
        return [r for r in self.results if r.docs_retrieved > 0 or r.substring_match]

    def overall_stats(self) -> dict:
        """总体统计。"""
        valid = self._non_error()
        n = len(valid)
        if n == 0:
            return {}

        substring_matches = sum(1 for r in valid if r.substring_match)

        # MRR
        reciprocal_ranks = [
            1.0 / r.substring_rank for r in valid if r.substring_rank > 0
        ]
        mrr = sum(reciprocal_ranks) / n if reciprocal_ranks else 0.0

        avg_kw_coverage = sum(r.keyword_coverage for r in valid) / n
        avg_latency = sum(r.retrieval_latency_ms for r in valid) / n
        avg_docs = sum(r.docs_retrieved for r in valid) / n
        avg_parents = sum(r.unique_parents for r in valid) / n
        avg_ctx_len = sum(r.context_length for r in valid) / n

        return {
            "total_queries": len(self.results),
            "valid_results": n,
            "substring_recall": round(substring_matches / n, 3) if n else 0,
            "substring_recall_pct": f"{substring_matches / n * 100:.1f}%" if n else "N/A",
            "mrr": round(mrr, 3),
            "avg_keyword_coverage": round(avg_kw_coverage, 3),
            "avg_latency_ms": round(avg_latency, 1),
            "avg_docs": round(avg_docs, 1),
            "avg_parents": round(avg_parents, 1),
            "avg_context_length": int(avg_ctx_len),
        }

    def stats_by_category(self) -> Dict[str, dict]:
        """按分类分组统计。"""
        groups = defaultdict(list)
        for r in self._non_error():
            groups[r.category].append(r)

        result = {}
        for cat, items in sorted(groups.items()):
            n = len(items)
            matched = sum(1 for r in items if r.substring_match)
            result[cat] = {
                "count": n,
                "recall": round(matched / n, 3) if n else 0,
                "recall_pct": f"{matched / n * 100:.0f}%" if n else "N/A",
                "avg_kw_coverage": round(sum(r.keyword_coverage for r in items) / n, 3),
                "avg_latency": round(sum(r.retrieval_latency_ms for r in items) / n, 0),
            }
        return result

    def stats_by_type(self) -> Dict[str, dict]:
        """按问题类型分组统计。"""
        groups = defaultdict(list)
        for r in self._non_error():
            groups[r.question_type].append(r)

        result = {}
        for qtype, items in sorted(groups.items()):
            n = len(items)
            matched = sum(1 for r in items if r.substring_match)
            result[qtype] = {
                "count": n,
                "recall": round(matched / n, 3) if n else 0,
                "recall_pct": f"{matched / n * 100:.0f}%" if n else "N/A",
                "avg_kw_coverage": round(sum(r.keyword_coverage for r in items) / n, 3),
            }
        return result

    def low_recall_queries(self) -> List[EvalResult]:
        """返回低召回查询（子串未匹配 + 关键词覆盖率 < 0.3）。"""
        return [
            r for r in self._non_error()
            if not r.substring_match and r.keyword_coverage < 0.3
        ]

    # ---- 报告生成 ----

    def generate_report(self, output_path: str) -> str:
        """生成 Markdown 评估报告并保存。"""
        overall = self.overall_stats()
        by_cat = self.stats_by_category()
        by_type = self.stats_by_type()
        low = self.low_recall_queries()

        lines = []
        lines.append("# RAG 召回率评估报告")
        lines.append("")
        lines.append(f"**评估时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"**测试集**: RAG召回率测试集_100条完整版.txt")
        lines.append(f"**检索 Pipeline**: 查询改写 → 混合检索(向量+BM25) → Cross-Encoder 重排序 → Parent-Child 展开")
        lines.append(f"**Top-K**: 5")
        lines.append("")

        # ---- 一、总体指标 ----
        lines.append("---")
        lines.append("")
        lines.append("## 一、总体指标")
        lines.append("")
        lines.append("| 指标 | 值 |")
        lines.append("|---|---|")
        lines.append(f"| 测试查询总数 | {overall.get('total_queries', 0)} |")
        lines.append(f"| 子串匹配召回 (Recall@5) | **{overall.get('substring_recall_pct', 'N/A')}** ({overall.get('substring_recall', 0):.3f}) |")
        lines.append(f"| MRR (Mean Reciprocal Rank) | {overall.get('mrr', 0):.3f} |")
        lines.append(f"| 平均关键词覆盖率 | {overall.get('avg_keyword_coverage', 0):.1%} |")
        lines.append(f"| 平均检索延迟 | {overall.get('avg_latency_ms', 0):.0f}ms |")
        lines.append(f"| 平均检索文档数 | {overall.get('avg_docs', 0):.1f} |")
        lines.append(f"| 平均唯一父块数 | {overall.get('avg_parents', 0):.1f} |")
        lines.append(f"| 平均上下文长度 | {overall.get('avg_context_length', 0):,} 字 |")
        lines.append("")

        # ---- 二、按分类 ----
        lines.append("---")
        lines.append("")
        lines.append("## 二、按分类统计")
        lines.append("")
        lines.append("| 分类 | 查询数 | 子串召回 | 关键词覆盖率 | 平均延迟 |")
        lines.append("|---|---|---|---|---|")
        for cat, stats in by_cat.items():
            lines.append(
                f"| {cat} | {stats['count']} | "
                f"**{stats['recall_pct']}** | "
                f"{stats['avg_kw_coverage']:.1%} | "
                f"{stats['avg_latency']:.0f}ms |"
            )
        lines.append("")

        # ---- 三、按问题类型 ----
        lines.append("---")
        lines.append("")
        lines.append("## 三、按问题类型统计")
        lines.append("")
        lines.append("| 问题类型 | 查询数 | 子串召回 | 关键词覆盖率 |")
        lines.append("|---|---|---|---|")
        for qtype, stats in by_type.items():
            lines.append(
                f"| {qtype} | {stats['count']} | "
                f"**{stats['recall_pct']}** | "
                f"{stats['avg_kw_coverage']:.1%} |"
            )
        lines.append("")

        # ---- 四、低召回诊断 ----
        if low:
            lines.append("---")
            lines.append("")
            lines.append(f"## 四、低召回查询诊断（{len(low)} 条）")
            lines.append("")
            lines.append("以下查询的检索结果未能有效覆盖预期答案：")
            lines.append("")
            lines.append("| 编号 | 问题 | 分类 | 关键词覆盖 | 诊断 |")
            lines.append("|---|---|---|---|---|")
            for r in low[:20]:  # 最多显示 20 条
                diagnosis = _diagnose(r)
                lines.append(
                    f"| {r.query_id} | {r.question[:40]} | {r.category} | "
                    f"{r.keyword_coverage:.1%} | {diagnosis} |"
                )
            if len(low) > 20:
                lines.append(f"| ... | *还有 {len(low) - 20} 条* | | | |")
            lines.append("")

            # 诊断建议
            lines.append("### 诊断分析")
            lines.append("")
            cat_low = defaultdict(int)
            type_low = defaultdict(int)
            for r in low:
                cat_low[r.category] += 1
                type_low[r.question_type] += 1
            lines.append("**低召回集中的分类**:")
            for cat, cnt in sorted(cat_low.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"- {cat}: {cnt} 条")
            lines.append("")
            lines.append("**低召回集中的问题类型**:")
            for qtype, cnt in sorted(type_low.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"- {qtype}: {cnt} 条")
            lines.append("")

        # ---- 五、逐查询详情 ----
        lines.append("---")
        lines.append("")
        lines.append("## 五、逐查询详情")
        lines.append("")
        for r in self.results:
            status = "✅" if r.substring_match else ("⚠️" if r.keyword_coverage >= 0.3 else "❌")
            lines.append(f"### {status} {r.query_id}: {r.question}")
            lines.append(f"**分类**: {r.category} | **类型**: {r.question_type}")
            lines.append("")
            lines.append(f"<details>")
            lines.append(f"<summary>详细结果</summary>")
            lines.append("")
            lines.append(f"- **子串匹配**: {'是 (排名 #{})'.format(r.substring_rank) if r.substring_match else '否'}")
            lines.append(f"- **关键词覆盖率**: {r.keyword_coverage:.1%}")
            lines.append(f"- **匹配关键词**: {r.matched_keywords or '无'}")
            lines.append(f"- **文档数/父块数**: {r.docs_retrieved}/{r.unique_parents}")
            lines.append(f"- **检索延迟**: {r.retrieval_latency_ms:.0f}ms")
            lines.append("")
            lines.append(f"**预期答案片段**:")
            lines.append(f"> {r.expected_answer[:200]}")
            lines.append("")
            lines.append(f"**检索上下文片段**:")
            lines.append(f"```")
            lines.append(r.context_snippet[:400] if r.context_snippet else "(无)")
            lines.append(f"```")
            lines.append(f"</details>")
            lines.append("")

        lines.append("---")
        lines.append(f"*报告由 eval/rag_eval_recall.py 自动生成 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")

        report = "\n".join(lines)

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\n报告已保存至: {output_path}")

        return report


def _diagnose(r: EvalResult) -> str:
    """诊断低召回原因。"""
    reasons = []
    if r.docs_retrieved == 0:
        reasons.append("无检索结果")
    if r.context_length < 100:
        reasons.append("上下文过短")
    if r.unique_parents <= 1:
        reasons.append("父块单一")
    if r.keyword_coverage < 0.1:
        reasons.append("关键词几乎无覆盖")
    return "; ".join(reasons) if reasons else "待分析"


# ============================================================================
# 主入口
# ============================================================================

async def main():
    import argparse

    parser = argparse.ArgumentParser(description="RAG 召回率评估")
    parser.add_argument(
        "--limit", type=int, default=None,
        help="仅评估前 N 条查询（快速测试）"
    )
    parser.add_argument(
        "--category", type=str, default=None,
        help="按分类筛选（如 '考勤与休假制度'）"
    )
    parser.add_argument(
        "--top-k", type=int, default=5,
        help="检索返回文档数（默认 5）"
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="报告输出路径（默认 eval/eval_report_recall.md）"
    )
    args = parser.parse_args()

    # 解析测试集
    test_file = os.path.join(os.path.dirname(__file__), "RAG召回率测试集_100条完整版.txt")
    if not os.path.exists(test_file):
        print(f"错误: 测试集文件不存在: {test_file}")
        return

    queries = parse_test_set(test_file)
    print(f"解析测试集: {len(queries)} 条查询")

    # 筛选
    if args.category:
        queries = [q for q in queries if q.category == args.category]
        print(f"按分类 '{args.category}' 筛选: {len(queries)} 条")
    if args.limit:
        queries = queries[:args.limit]
        print(f"限制前 {args.limit} 条")

    # 统计概览
    cats = defaultdict(int)
    types = defaultdict(int)
    for q in queries:
        cats[q.category] += 1
        types[q.question_type] += 1
    print(f"分类分布: {dict(cats)}")
    print(f"类型分布: {dict(types)}")
    print()

    # 运行评估
    evaluator = RecallEvaluator()
    print("=" * 60)
    print("  开始评估...")
    print("=" * 60)
    await evaluator.run(queries, top_k=args.top_k)

    # 输出摘要
    overall = evaluator.overall_stats()
    print()
    print("=" * 60)
    print("  评估摘要")
    print("=" * 60)
    print(f"  子串匹配召回: {overall.get('substring_recall_pct', 'N/A')}")
    print(f"  MRR:           {overall.get('mrr', 0):.3f}")
    print(f"  关键词覆盖率:  {overall.get('avg_keyword_coverage', 0):.1%}")
    print(f"  平均延迟:      {overall.get('avg_latency_ms', 0):.0f}ms")

    # 按分类
    print()
    print("--- 按分类召回 ---")
    by_cat = evaluator.stats_by_category()
    for cat, stats in by_cat.items():
        bar = "█" * int(stats['recall'] * 20)
        print(f"  {cat:12s}: {stats['recall_pct']:>4s} {bar}")

    # 低召回
    low = evaluator.low_recall_queries()
    print(f"\n低召回查询 (<30% 关键词覆盖): {len(low)} 条")

    # 生成报告
    output_path = args.output or os.path.join(
        os.path.dirname(__file__), "eval_report_recall.md"
    )
    evaluator.generate_report(output_path)
    print(f"\n完整报告: {os.path.abspath(output_path)}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
