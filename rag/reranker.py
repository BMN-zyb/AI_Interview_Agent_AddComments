"""
LLM Reranker：使用大模型对候选文档做精排
比传统 cross-encoder 更灵活，能针对具体 query 判断相关性
"""
from __future__ import annotations

# 标准库：类型注解
from typing import Any, Dict, List

# loguru：结构化日志库
from loguru import logger

# 智能体基类，提供 invoke_llm_json 等调用大模型的通用方法
from agents.base_agent import BaseAgent

# 精排提示词模板：要求模型对候选文档按相关性排序，仅返回 id 的 JSON 数组
RERANK_PROMPT = """你是相关性评估专家。针对用户 Query，对以下候选文档按相关性从高到低排序。
只需返回排序后的 id 列表（JSON 数组），不要多余文字。

Query: {query}

候选文档：
{docs}

输出格式：["id1", "id2", ...]
"""


class LLMReranker(BaseAgent):
    """基于大模型的精排器：对候选文档做相关性重排序

    相比传统 cross-encoder，借助 LLM 的语义理解能力，能针对具体 Query 更灵活地判断相关性。
    """

    # 智能体名称标识（供基类/日志识别）
    name = "llm_reranker"

    def rerank(
        self, query: str, candidates: List[Dict[str, Any]], top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """对候选文档做 LLM 精排

        参数:
            query: 用户查询文本
            candidates: 粗召回得到的候选文档列表（每项含 id/text 等）
            top_k: 最终返回的文档条数，默认 5
        返回:
            List[Dict]: 重排序后取前 top_k 的文档列表；异常时回退为原始顺序
        """
        # 候选为空时直接返回空列表，避免无意义的 LLM 调用
        if not candidates:
            return []
        # 拼接候选文档文本：每条格式为 [id] 正文，仅取前 20 条、每条截断 300 字以控制 prompt 长度
        docs_text = "\n".join(
            f"[{c['id']}] {c['text'][:300]}" for c in candidates[:20]
        )
        try:
            # 调用大模型，填充模板后期望返回 JSON 格式的排序结果
            parsed = self.invoke_llm_json(
                RERANK_PROMPT.format(query=query, docs=docs_text), ""
            )
            # 若模型直接返回 JSON 数组，则它本身就是有序 id 列表
            if isinstance(parsed, list):
                ordered_ids = parsed
            # 否则兼容字典返回：依次尝试 order / ids 字段，都没有则空列表
            else:
                ordered_ids = parsed.get("order", parsed.get("ids", []))
        except Exception as e:
            # LLM 调用或解析失败时记录警告，并降级为原始顺序的前 top_k
            logger.warning("Reranker 失败，保持原序: {}", e)
            return candidates[:top_k]

        # 建立 id -> 文档 的映射，便于按模型给出的顺序回查完整文档
        id_to_doc = {c["id"]: c for c in candidates}
        # 存放重排序后的文档列表
        reranked: List[Dict[str, Any]] = []
        # 按模型给出的 id 顺序，依次取出对应文档（跳过无效/不存在的 id）
        for rid in ordered_ids:
            if rid in id_to_doc:
                reranked.append(id_to_doc[rid])
        # 兜底：补充未被排序的
        # 防止模型遗漏部分候选：把未出现在结果中的文档追加到末尾
        for c in candidates:
            if c["id"] not in [r["id"] for r in reranked]:
                reranked.append(c)
        # 截取前 top_k 条返回
        return reranked[:top_k]


    # def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
    #     query = state.get("query", "")
    #     candidates = state.get("candidates", [])
    #     top_k = state.get("top_k", 5)

    #     reranked = self.rerank(query, candidates, top_k)

    #     return {
    #         **state,
    #         "candidates": reranked,
    #     }


    def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """实现基类要求的 run 接口（图节点入口）

        参数:
            state: 工作流共享状态字典
        返回:
            Dict: 原样返回 state（reranker 不作为图节点参与流程）
        """
        # reranker 不走 graph node，这里做兼容占位
        # 直接透传状态，不做任何处理
        return state

# 模块级全局单例，供查询引擎等模块直接调用
reranker = LLMReranker()
