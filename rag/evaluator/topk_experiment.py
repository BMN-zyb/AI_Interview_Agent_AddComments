"""
TopK 调优实验脚本：
对比 top_k = 3, 5, 10, 20 下的 RAG 评估分数，找出最优 K
"""
from __future__ import annotations

# 标准库：JSON 读写
import json
# 标准库：文件系统路径操作
from pathlib import Path

# loguru：结构化日志库
from loguru import logger

# RAG 评估器（计算各项指标）
from rag.evaluator.rag_evaluator import RAGEvaluator
# 全局查询引擎单例（用于按不同 top_k 检索上下文）
from rag.query_engine import query_engine

# 评估集文件路径，内容形如 [{question, ground_truth}]
EVAL_SET_PATH = Path("data/rag_eval_set.json")


def run_topk_experiment(top_k_list: list[int] = (3, 5, 10, 20)) -> dict:
    """对比不同 top_k 取值下的 RAG 评估分数，用于调优最优 K

    参数:
        top_k_list: 待对比的 top_k 取值列表，默认 (3, 5, 10, 20)
    返回:
        dict: 形如 {"top_3": {指标...}, ...} 的各档位评估结果；评估集缺失时返回空字典
    """
    # 评估集文件不存在时记录错误并提前返回
    if not EVAL_SET_PATH.exists():
        logger.error("评估集不存在：{}", EVAL_SET_PATH)
        return {}

    # 读取评估集 JSON（指定 UTF-8 以正确处理中文）
    with open(EVAL_SET_PATH, "r", encoding="utf-8") as f:
        eval_set = json.load(f)  # [{question, ground_truth}]

    # 实例化评估器
    evaluator = RAGEvaluator()
    # 汇总各 top_k 档位评估结果的字典
    results: dict = {}
    # 依次遍历每个待测 top_k
    for k in top_k_list:
        # 分别收集问题、答案、上下文，供批量评估
        questions, answers, contexts = [], [], []
        # 遍历评估集中的每条样本
        for item in eval_set:
            # 取出当前问题
            q = item["question"]
            # 用当前 top_k 做精排检索，得到候选上下文
            ctx = query_engine.full_query(q, top_k=k)
            # 提取候选文档的正文文本列表
            ctx_texts = [c["text"] for c in ctx]
            # 简化：使用第一条 context 作为回答基础（真实场景应让 LLM 生成）
            # 此处用所有上下文拼接（截断 1000 字）模拟答案，仅为实验便利
            answers.append(" ".join(ctx_texts)[:1000])
            # 记录该问题的上下文列表
            contexts.append(ctx_texts)
            # 记录问题
            questions.append(q)

        # 对当前 top_k 档位的全部样本运行评估
        scores = evaluator.evaluate(questions, answers, contexts)
        # 以 top_k 标签存入结果字典
        results[f"top_{k}"] = scores
        # 输出该档位的评估分数
        logger.info("top_k={} => {}", k, scores)

    # 保存
    # 将所有档位结果写入实验结果文件（缩进美化、保留中文）
    Path("data/experiment_results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return results


# 作为脚本直接运行时，执行实验并打印结果
if __name__ == "__main__":
    print(run_topk_experiment())
