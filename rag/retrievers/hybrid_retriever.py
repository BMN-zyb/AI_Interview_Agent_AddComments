"""
混合检索器：向量 + BM25 双路并行，RRF 融合去重
"""
from __future__ import annotations

# 标准库：类型注解
from typing import Any, Dict, List

# loguru：结构化日志库
from loguru import logger

# 项目全局配置（检索权重、top_k 等参数）
from config import settings
# BM25 关键词检索器
from rag.retrievers.bm25_retriever import BM25Retriever
# 向量语义检索器
from rag.retrievers.vector_retriever import VectorRetriever


def reciprocal_rank_fusion(
    vector_results: List[Dict[str, Any]],
    bm25_results: List[Dict[str, Any]],
    *,
    vector_weight: float = 0.6,
    bm25_weight: float = 0.4,
    k: int = 60,
) -> List[Dict[str, Any]]:
    """RRF 融合：score = w1/(k+rank1) + w2/(k+rank2)

    将向量检索与 BM25 检索的结果按倒数排名加权融合并去重。

    参数:
        vector_results: 向量检索结果列表（已按相关性排序）
        bm25_results: BM25 检索结果列表（已按相关性排序）
        vector_weight: 向量结果权重，默认 0.6
        bm25_weight: BM25 结果权重，默认 0.4
        k: RRF 平滑常数，默认 60（值越大越弱化排名差异）
    返回:
        List[Dict]: 按融合分数降序排列、去重后的文档列表
    """
    # 以文档 id 为键，记录每个文档及其累计 RRF 分数
    score_map: Dict[str, Dict[str, Any]] = {}

    # 遍历向量检索结果，按其排名累加向量侧 RRF 贡献
    for rank, r in enumerate(vector_results):
        # 当前文档 id
        rid = r["id"]
        # 首次出现时初始化条目（保存文档与初始 0 分）
        score_map.setdefault(rid, {"doc": r, "rrf": 0.0})
        # 累加 RRF 贡献：权重 / (k + 排名)，排名从 1 起算故 +1
        score_map[rid]["rrf"] += vector_weight / (k + rank + 1)

    # 遍历 BM25 检索结果，按其排名累加 BM25 侧 RRF 贡献
    for rank, r in enumerate(bm25_results):
        # 当前文档 id
        rid = r["id"]
        # 首次出现时初始化条目
        score_map.setdefault(rid, {"doc": r, "rrf": 0.0})
        # 累加 BM25 侧 RRF 贡献
        score_map[rid]["rrf"] += bm25_weight / (k + rank + 1)

    # 按累计 RRF 分数从高到低排序所有去重后的文档
    merged = sorted(score_map.values(), key=lambda x: x["rrf"], reverse=True)
    # 重新组装为统一结构的结果列表：以 RRF 作为最终 score，来源标记为 hybrid
    return [{"id": m["doc"]["id"], "text": m["doc"]["text"],
             "metadata": m["doc"].get("metadata", {}),
             "score": m["rrf"], "source": "hybrid"} for m in merged]


class HybridRetriever:
    """向量 + BM25 双路混合检索"""

    def __init__(self) -> None:
        """初始化混合检索器，分别构建向量与 BM25 两路子检索器"""
        # 向量语义检索器
        self.vector = VectorRetriever()
        # BM25 关键词检索器
        self.bm25 = BM25Retriever()

    def retrieve(self, query: str, top_k: int | None = None) -> List[Dict[str, Any]]:
        """执行混合检索：双路召回后 RRF 融合，返回前 top_k 条

        参数:
            query: 查询文本
            top_k: 最终返回条数；为 None 时取配置中的默认值
        返回:
            List[Dict]: 融合排序后的前 top_k 文档列表
        """
        # 未显式指定 top_k 时回退到全局配置默认值
        top_k = top_k or settings.rag_top_k
        # 向量侧多召回（2 倍 top_k），为融合提供更充足候选
        vec_results = self.vector.retrieve(query, top_k=top_k * 2)
        # BM25 侧同样多召回 2 倍 top_k
        bm25_results = self.bm25.retrieve(query, top_k=top_k * 2)
        # 记录两路召回数量（debug）
        logger.debug("Hybrid: vec={} bm25={}", len(vec_results), len(bm25_results))
        # 用配置中的权重对两路结果做 RRF 融合
        merged = reciprocal_rank_fusion(
            vec_results,
            bm25_results,
            vector_weight=settings.rag_vector_weight,  # 向量权重（来自配置）
            bm25_weight=settings.rag_bm25_weight,  # BM25 权重（来自配置）
        )
        # 截取融合结果的前 top_k 条返回
        return merged[:top_k]
