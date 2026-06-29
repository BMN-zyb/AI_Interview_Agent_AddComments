"""
自定义评估指标：Faithfulness / Relevance / Completeness 的本地封装
"""
from __future__ import annotations

# 标准库：类型注解，Dict 用于标注返回的指标字典
from typing import Any, Dict


def compute_faithfulness(answer: str, context: str) -> float:
    """忠实度：答案是否全部来源于 context（简化版：基于 token 重合度）

    参数:
        answer: 模型生成的答案文本
        context: 检索到的上下文文本
    返回:
        float: 0~1 的忠实度分数，越高表示答案越扎根于上下文
    """
    # 上下文或答案任一为空时无法评估，直接返回 0
    if not context or not answer:
        return 0.0
    # 将答案小写化并按空白切分为去重的 token 集合
    ans_tokens = set(answer.lower().split())
    # 将上下文同样处理为去重 token 集合
    ctx_tokens = set(context.lower().split())
    # 答案无有效 token 时返回 0，避免后续除零
    if not ans_tokens:
        return 0.0
    # 计算答案与上下文的 token 交集大小（即被上下文支撑的词数）
    overlap = len(ans_tokens & ctx_tokens)
    # 重合占比乘以 1.5 放大，并用 min 截断到 1.0，得到最终忠实度
    return min(1.0, overlap / len(ans_tokens) * 1.5)


def compute_relevance(question: str, answer: str) -> float:
    """相关性：答案是否切题（简化版）

    参数:
        question: 用户问题文本
        answer: 模型生成的答案文本
    返回:
        float: 0~1 的相关性分数，越高表示答案与问题越契合
    """
    # 问题 token 去重集合
    q_tokens = set(question.lower().split())
    # 答案 token 去重集合
    a_tokens = set(answer.lower().split())
    # 问题无有效 token 时返回 0，避免除零
    if not q_tokens:
        return 0.0
    # 问答交集占问题词数的比例乘 1.2 放大，并截断到 1.0
    return min(1.0, len(q_tokens & a_tokens) / len(q_tokens) * 1.2)


def compute_completeness(answer: str, reference: str) -> float:
    """完整性：相对参考答案的覆盖度

    参数:
        answer: 模型生成的答案文本
        reference: 标准/参考答案文本
    返回:
        float: 0~1 的完整性分数；无参考答案时，有答案记 1.0、无答案记 0.0
    """
    # 没有参考答案时，只要有答案就视为完整（1.0），否则为 0.0
    if not reference:
        return 1.0 if answer else 0.0
    # 参考答案 token 去重集合
    ref_tokens = set(reference.lower().split())
    # 生成答案 token 去重集合
    ans_tokens = set(answer.lower().split())
    # 参考答案无有效 token 时返回 0，避免除零
    if not ref_tokens:
        return 0.0
    # 计算答案对参考答案要点的覆盖比例，并截断到 1.0
    return min(1.0, len(ref_tokens & ans_tokens) / len(ref_tokens))


def compute_all(
    question: str, answer: str, context: str, reference: str = ""
) -> Dict[str, float]:
    """一次性计算忠实度/相关性/完整性三项指标

    参数:
        question: 用户问题
        answer: 模型答案
        context: 检索上下文
        reference: 参考答案，默认空串
    返回:
        Dict[str, float]: 含 faithfulness/relevance/completeness 三个键的分数字典
    """
    # 汇总三个维度的评估结果为一个字典返回
    return {
        "faithfulness": compute_faithfulness(answer, context),  # 忠实度
        "relevance": compute_relevance(question, answer),  # 相关性
        "completeness": compute_completeness(answer, reference),  # 完整性
    }
