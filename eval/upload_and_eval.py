"""
一键脚本：清理旧数据 → 上传企业制度文档 → 运行召回率评估

Usage:
    python eval/upload_and_eval.py              # 完整 100 条评估
    python eval/upload_and_eval.py --limit 20   # 仅前 20 条
"""
import asyncio
import os
import shutil
import sys
import time

# 切换到项目根目录
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.config as config
from src.knowledge.service import KnowledgeBaseService, get_string_md5

DOCS_DIR = os.path.join("data", "documents")
DOC_FILES = [
    "考勤与休假制度.txt",
    "薪酬福利制度.txt",
    "入职离职流程.txt",
    "办公管理制度.txt",
    "产品功能说明.txt",
    "安全与合规制度.txt",
]


async def clean_chroma():
    """清空 Chroma 向量库（删除并重建 collection）。"""
    print("=" * 60)
    print("Step 1: 清理旧 Chroma 数据...")
    print("=" * 60)

    chroma_dir = config.chroma_path
    if os.path.exists(chroma_dir):
        shutil.rmtree(chroma_dir)
        print(f"  已删除 Chroma 目录: {chroma_dir}")
    os.makedirs(chroma_dir, exist_ok=True)
    print("  Chroma 已重置\n")


async def upload_documents():
    """上传 6 份企业制度文档到 Chroma。"""
    print("=" * 60)
    print("Step 2: 上传企业制度文档...")
    print("=" * 60)

    kb = KnowledgeBaseService(collection_name=config.collection_name)
    total_chunks = 0

    for fname in DOC_FILES:
        fpath = os.path.join(DOCS_DIR, fname)
        if not os.path.exists(fpath):
            print(f"  [WARN] File not found, skip: {fpath}")
            continue

        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()

        t0 = time.monotonic()
        result = await kb.upload_bt_str(
            data=content,
            filename=fname,
            md5_str=get_string_md5(content),
            operator="eval",
        )
        elapsed = time.monotonic() - t0

        if result.get("success"):
            chunks = result.get("chunk_count", 0)
            total_chunks += chunks
            print(f"  [OK] {fname} -> {chunks} chunks ({elapsed:.1f}s)")
        else:
            print(f"  [FAIL] {fname}: {result.get('message', 'unknown')}")

    print(f"\n  总计上传 {len(DOC_FILES)} 份文档, {total_chunks} 个分块\n")


async def run_evaluation(limit: int = None):
    """运行召回率评估。"""
    print("=" * 60)
    print("Step 3: 运行召回率评估...")
    print("=" * 60)

    from eval.rag_eval_recall import (
        RecallEvaluator, parse_test_set, EvalRetrievalEngine,
    )

    # 解析测试集
    test_file = os.path.join("eval", "RAG召回率测试集_100条完整版.txt")
    queries = parse_test_set(test_file)
    print(f"  解析到 {len(queries)} 条查询")

    if limit:
        queries = queries[:limit]
        print(f"  限制为前 {limit} 条")

    # 运行评估
    evaluator = RecallEvaluator()
    await evaluator.run(queries, top_k=5)

    # 生成报告
    output_path = os.path.join("eval", "eval_report_recall.md")
    evaluator.generate_report(output_path)

    # 打印汇总
    stats = evaluator.overall_stats()
    print("\n" + "=" * 60)
    print("评估完成!")
    print("=" * 60)
    if stats:
        print(f"  总查询数:       {stats['total_queries']}")
        print(f"  Recall@5:       {stats['substring_recall_pct']}")
        print(f"  MRR:            {stats['mrr']:.3f}")
        print(f"  Avg 关键词覆盖率: {stats['avg_keyword_coverage']:.1%}")
        print(f"  Avg 延迟:       {stats['avg_latency_ms']:.0f}ms")
        print(f"  Avg 上下文长度:  {stats['avg_context_length']:,} 字")

    # 按分类统计
    by_cat = evaluator.stats_by_category()
    if by_cat:
        print(f"\n  按分类 Recall@5:")
        for cat, s in by_cat.items():
            print(f"    {cat}: {s['recall_pct']} ({s['count']}条)")

    print(f"\n  报告已保存至: {output_path}")


def main():
    limit = None
    if "--limit" in sys.argv:
        idx = sys.argv.index("--limit")
        if idx + 1 < len(sys.argv):
            limit = int(sys.argv[idx + 1])

    asyncio.run(_main(limit))


async def _main(limit: int = None):
    await clean_chroma()
    await upload_documents()
    await run_evaluation(limit)


if __name__ == "__main__":
    main()
