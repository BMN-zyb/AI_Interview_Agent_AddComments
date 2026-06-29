"""
统一查询引擎入口：
- hybrid_query: 混合检索 + RRF 融合
- full_query: 混合检索 + LLM Rerank（精排）
"""
from __future__ import annotations

# 标准库：类型注解，用于标注返回值的列表/字典结构
from typing import Any, Dict, List

# LLM 精排器单例（对候选文档做相关性重排）
from rag.reranker import reranker
# 混合检索器（向量 + BM25 双路融合）
from rag.retrievers.hybrid_retriever import HybridRetriever


class QueryEngine:
    """RAG 统一查询引擎：封装混合检索与可选的 LLM 精排两种查询模式"""

    def __init__(self) -> None:
        """初始化查询引擎，内部持有一个混合检索器实例"""
        # 实例化混合检索器，供两种查询模式复用
        self.hybrid = HybridRetriever()

    def hybrid_query(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        """仅做混合检索（快速模式）

        参数:
            query: 用户查询文本
            top_k: 返回的文档条数，默认 10
        返回:
            List[Dict]: 混合检索（向量 + BM25 + RRF 融合）后的文档列表
        """
        # 直接返回混合检索结果，不做后续精排，速度更快
        return self.hybrid.retrieve(query, top_k=top_k)

    def full_query(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """混合检索 + LLM Rerank（精排模式）

        参数:
            query: 用户查询文本
            top_k: 最终返回的文档条数，默认 5
        返回:
            List[Dict]: 经 LLM 精排后取前 top_k 的文档列表
        """
        # 先粗召回更多候选（top_k 的 3 倍），为精排留出筛选空间
        candidates = self.hybrid.retrieve(query, top_k=top_k * 3)
        # 用 LLM 对候选重排序后，截取前 top_k 条返回
        return reranker.rerank(query, candidates, top_k=top_k)


# 模块级全局单例，供外部直接 import 使用，避免重复初始化检索器
query_engine = QueryEngine()
