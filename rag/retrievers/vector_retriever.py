"""Weaviate 向量检索"""
from __future__ import annotations

# 标准库：类型注解
from typing import Any, Dict, List

# Weaviate 官方客户端库（向量数据库）
import weaviate
# 阿里云 DashScope 向量化模型封装（生成查询/文档 embedding）
from llama_index.embeddings.dashscope import DashScopeEmbedding
# loguru：结构化日志库
from loguru import logger
# Weaviate 查询元数据声明（用于请求返回距离等附加信息）
from weaviate.classes.query import MetadataQuery

# 项目全局配置（连接地址、API Key、模型名等）
from config import settings


def get_weaviate_client() -> weaviate.WeaviateClient:
    """获取 Weaviate 客户端（单例）

    根据是否配置了 API Key，自动选择云端（WCS）或自建实例的连接方式。

    返回:
        weaviate.WeaviateClient: 已建立连接的 Weaviate 客户端
    """
    # 若配置了 API Key，按云端 WCS 集群方式连接（带鉴权）
    if settings.weaviate_api_key:
        return weaviate.connect_to_wcs(
            cluster_url=settings.weaviate_url,  # 集群地址
            auth_credentials=weaviate.classes.init.Auth.api_key(settings.weaviate_api_key),  # API Key 鉴权
        )
    # 否则按自建实例方式连接：从配置 URL 解析出主机/端口/协议
    return weaviate.connect_to_custom(
        # 去掉 http:// 前缀后按冒号切分取主机名
        http_host=settings.weaviate_url.replace("http://", "").split(":")[0],
        # 取 URL 末段冒号后的端口并转为 int
        http_port=int(settings.weaviate_url.split(":")[-1]),
        # 根据 URL 是否以 https 开头判断是否启用安全连接
        http_secure=settings.weaviate_url.startswith("https"),
        # gRPC 主机名同样从 URL 解析
        grpc_host=settings.weaviate_url.replace("http://", "").split(":")[0],
        # gRPC 端口固定为 50051（Weaviate 默认）
        grpc_port=50051,
        # 自建场景默认不启用 gRPC 安全连接
        grpc_secure=False,
    )


class VectorRetriever:
    """基于 Weaviate 的向量检索"""

    def __init__(self, collection_name: str = "InterviewQuestions"):
        """初始化向量检索器

        参数:
            collection_name: 目标 Weaviate Collection 名称，默认 InterviewQuestions
        """
        # 获取 Weaviate 客户端连接
        self.client = get_weaviate_client()
        # 获取目标 Collection 句柄
        self.collection = self.client.collections.get(collection_name)
        # 初始化向量化模型，用于将查询文本转为向量
        self.embed = DashScopeEmbedding(
            model_name=settings.embedding_model,
            api_key=settings.dashscope_api_key,
        )

    def retrieve(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """向量近邻检索

        参数:
            query: 查询文本
            top_k: 返回的最近邻条数，默认 5
        返回:
            List[Dict]: 命中文档列表（含 id/text/metadata/score/source）
        """
        # 将查询文本编码为查询向量
        query_vec = self.embed.get_query_embedding(query)
        # 在 Collection 中执行向量近邻搜索，并要求返回距离信息
        resp = self.collection.query.near_vector(
            near_vector=query_vec,  # 查询向量
            limit=top_k,  # 返回条数上限
            return_metadata=MetadataQuery(distance=True),  # 附带返回距离
        )
        # 存放规整后的结果列表
        results: List[Dict[str, Any]] = []
        # 遍历返回的每个对象
        for obj in resp.objects:
            # 组装统一结构的结果字典
            results.append({
                "id": str(obj.uuid),  # 对象 UUID 作为 id
                "text": obj.properties.get("text", ""),  # 正文
                "metadata": obj.properties,  # 全部属性作为元数据
                # 距离转相似度：1 - 距离（距离缺省按 0 处理）
                "score": 1.0 - (obj.metadata.distance or 0.0),
                "source": "vector",  # 标记来源为向量检索
            })
        # 记录检索返回数量（debug）
        logger.debug("Vector 检索 top_k={} 返回 {} 条", top_k, len(results))
        return results
