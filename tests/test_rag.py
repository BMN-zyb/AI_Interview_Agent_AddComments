"""
RAG Debug Test - Full Pipeline Visibility
"""

# BM25 检索器：基于关键词的稀疏检索
from rag.retrievers.bm25_retriever import BM25Retriever
# 向量检索器：基于语义嵌入的稠密检索
from rag.retrievers.vector_retriever import VectorRetriever
# 混合检索器：融合 BM25 与向量检索结果
from rag.retrievers.hybrid_retriever import HybridRetriever
# LLM 重排器：用大模型对候选结果重新排序，提升相关性
from rag.reranker import LLMReranker  # LLMReranker 单例

# 评估指标计算函数：一次性计算 faithfulness/relevance/completeness 等多项指标
from rag.evaluator.metrics import compute_all

# 在模块级别实例化重排器（作为单例复用，避免每次调用都重复初始化大模型客户端）
reranker = LLMReranker()



# 测试评估指标计算的基础正确性：给定问答与上下文，检查各项分数是否落在合法区间 [0, 1]
def test_metrics_basic():
    # 调用评估函数，传入问题、答案、上下文、参考答案，得到各项指标分数
    scores = compute_all(
        # 待评估的问题
        question="什么是 Python GIL？",
        # 待评估的（模型）答案
        answer="GIL 是全局解释器锁，限制同一时刻只有一个线程执行 Python 字节码",
        # 检索到的上下文片段
        context="GIL（Global Interpreter Lock）是 CPython 中的一个互斥锁",
        # 参考标准答案（此处与 answer 相同，便于得到较高分数）
        reference="GIL 是全局解释器锁，限制同一时刻只有一个线程执行 Python 字节码",
    )

    # 打印各项分数，便于人工观察评估结果
    print("scores:", scores)

    # 断言忠实度（答案是否基于上下文）分数在 [0,1] 区间内，验证指标取值合法
    assert 0 <= scores["faithfulness"] <= 1
    # 断言相关性（答案与问题的相关程度）分数在 [0,1] 区间内
    assert 0 <= scores["relevance"] <= 1
    # 断言完整性（答案对问题的覆盖程度）分数在 [0,1] 区间内
    assert 0 <= scores["completeness"] <= 1




# =========================
# 选择 retriever
# =========================
# 根据 mode 字符串构造对应的检索器实例，便于在调试时切换不同检索策略
def build_retriever(mode="hybrid"):
    # 关键词检索模式：返回 BM25 检索器
    if mode == "bm25":
        return BM25Retriever()
    # 向量检索模式：返回向量检索器
    elif mode == "vector":
        return VectorRetriever()
    # 混合检索模式（默认）：返回混合检索器
    elif mode == "hybrid":
        return HybridRetriever()
    # 非法模式：抛出异常提示调用方传入了未知的检索类型
    else:
        raise ValueError(f"Unknown mode: {mode}")


# =========================
# Debug Pipeline
# =========================
# 完整 RAG 调试流程：召回 -> 重排 -> 构造上下文 -> 评估，并在每一步打印中间结果便于排查
def run_rag_debug(query: str, top_k=5, mode="hybrid"):
    # 打印查询、所用检索器等头部信息，分隔不同次调试输出
    print("\n" + "=" * 60)
    print("🔍 QUERY:", query)
    print("📦 RETRIEVER:", mode)
    print("=" * 60)

    # 按指定模式构造检索器
    retriever = build_retriever(mode)

    # 1. 召回
    # 召回候选片段；故意取 top_k 的 3 倍数量，给后续重排留出更大的候选池
    candidates = retriever.retrieve(query, top_k=top_k * 3)

    # 打印重排前的召回结果
    print("\n📌 [1. RETRIEVAL - BEFORE RERANK]")
    # 遍历每个候选，打印其编号、id 及前 80 个字符的文本预览
    for i, c in enumerate(candidates):
        print(f"{i+1}. id={c['id']} | text={c['text'][:80]}")

    # 2. LLM rerank
    # 用 LLM 重排器对候选重新排序，并截取最终需要的 top_k 条
    reranked = reranker.rerank(query, candidates, top_k=top_k)

    # 打印重排后的结果，便于对比重排前后的顺序变化
    print("\n📌 [2. RERANK - AFTER LLM RERANK]")
    # 遍历重排后的结果，打印编号、id 及文本预览
    for i, c in enumerate(reranked):
        print(f"{i+1}. id={c['id']} | text={c['text'][:80]}")

    # 3. 构造 context
    # 将重排后各片段的文本用换行拼接成最终喂给 LLM 的上下文
    context = "\n".join([c["text"] for c in reranked])

    # 打印最终构造出的上下文内容
    print("\n📌 [3. FINAL CONTEXT -> LLM]")
    print(context)

    # 4. mock answer / reference（你可以换真实生成结果）
    # 调试用：直接取重排第一名的文本作为答案；若无结果则为空字符串（避免索引越界）
    answer = reranked[0]["text"] if reranked else ""
    # 参考答案同样使用该文本（调试场景下没有真实标准答案）
    reference = answer

    # 5. evaluator
    # 调用评估函数，对当前问答与上下文打分
    scores = compute_all(
        # 原始查询作为问题
        question=query,
        # 上一步得到的答案
        answer=answer,
        # 拼接出的上下文
        context=context,
        # 参考答案
        reference=reference,
    )

    # 打印评估分数
    print("\n📊 [4. EVALUATION]")
    print(scores)

    # 返回完整的调试结果字典，包含各阶段中间产物，便于上层进一步分析
    return {
        # 原始查询
        "query": query,
        # 最终答案
        'answer': answer,
        # 重排前的召回候选
        "retrieved": candidates,
        # 重排后的结果
        "reranked": reranked,
        # 拼接出的上下文
        "context": context,
        # 评估分数
        "scores": scores,
    }


# =========================
# CLI test
# =========================
# 当脚本被直接运行时，跑一次完整的 RAG 调试流程作为命令行手动测试
if __name__ == "__main__":
    # 用一个较复杂的中文技术问题触发混合检索调试，top_k=3 只看前 3 条
    test1 = run_rag_debug(
        "Transformer的位置编码为什么用正弦余弦函数，而不是直接学习一个位置embedding？",
        top_k=3,
        mode="hybrid"
    )

    # 打印本次调试得到的参考答案，分隔线包裹以突出显示
    print("\n" + "=" * 60)
    print("test reference answer:", test1['answer'])
    print("=" * 60)

    # 额外运行一次指标基础测试，验证评估指标本身工作正常
    test_metrics_basic()


