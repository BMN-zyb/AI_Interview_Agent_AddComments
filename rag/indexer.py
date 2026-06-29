"""
文档加载、分块、向量化入库：
- 支持 Markdown / JSON / TXT 题库
- 使用 SentenceSplitter 分块
- 向量化到 Weaviate，同时构建 BM25 倒排索引
"""
from __future__ import annotations

# 标准库：用于跨平台的文件系统路径操作
from pathlib import Path
# 标准库：类型注解，List 用于标注列表元素类型
from typing import List

# LlamaIndex 核心：Document 文档对象、SimpleDirectoryReader 目录文档读取器
from llama_index.core import Document, SimpleDirectoryReader
# LlamaIndex 核心：SentenceSplitter 句子级文本分块器
from llama_index.core.node_parser import SentenceSplitter
# 阿里云 DashScope 的文本向量化模型封装（用于生成 embedding）
from llama_index.embeddings.dashscope import DashScopeEmbedding
# loguru：结构化日志库
from loguru import logger

# 项目全局配置（模型名、API Key 等）
from config import settings
# 向量检索模块中的 Weaviate 客户端获取函数（复用同一连接逻辑）
from rag.retrievers.vector_retriever import get_weaviate_client


def load_documents(kb_dir: str = "rag/knowledge_base") -> List[Document]:
    """递归加载知识库目录下的所有文档

    参数:
        kb_dir: 知识库根目录路径，默认 rag/knowledge_base
    返回:
        List[Document]: 加载到的文档对象列表；目录不存在时返回空列表
    """
    # 将字符串路径包装为 Path 对象，便于后续判断与传参
    kb_path = Path(kb_dir)
    # 若知识库目录不存在，记录警告并返回空列表，避免后续报错
    if not kb_path.exists():
        logger.warning("知识库目录不存在：{}", kb_path)
        return []
    # 构造目录读取器：递归遍历子目录，仅读取指定扩展名的文件
    reader = SimpleDirectoryReader(
        input_dir=str(kb_path),  # 读取器需要字符串路径
        recursive=True,  # 递归遍历所有子目录
        required_exts=[".md", ".txt", ".json", ".pdf"],  # 仅加载这几类题库文件
    )
    # 执行实际的磁盘读取，得到 Document 列表
    docs = reader.load_data()
    # 记录加载到的文档数量，便于排查
    logger.info("加载文档 {} 篇", len(docs))
    return docs


def split_documents(docs: List[Document], chunk_size: int = 512) -> List[dict]:
    """将文档切分为节点，返回节点列表

    参数:
        docs: 待切分的文档列表
        chunk_size: 每个分块的目标字符数，默认 512
    返回:
        List[dict]: 节点列表，每个元素包含 id/text/metadata 三个字段
    """
    # 创建句子级分块器：相邻分块重叠 64 字符，保证语义连续、避免边界信息丢失
    splitter = SentenceSplitter(chunk_size=chunk_size, chunk_overlap=64)
    # 将文档批量切分为 Node 对象列表
    nodes = splitter.get_nodes_from_documents(docs)
    # 将 Node 对象转换为轻量字典（id/正文/元数据），便于后续序列化与入库
    return [{"id": n.node_id, "text": n.text, "metadata": n.metadata} for n in nodes]


def build_vector_index(nodes: List[dict]) -> None:
    """将节点批量写入 Weaviate（向量索引）

    参数:
        nodes: split_documents 产出的节点字典列表
    返回:
        None（结果直接写入 Weaviate）
    """
    # 初始化向量化模型，使用配置中的模型名与 API Key
    embed_model = DashScopeEmbedding(
        model_name=settings.embedding_model,
        api_key=settings.dashscope_api_key,
    )
    # 获取 Weaviate 客户端连接
    client = get_weaviate_client()

    # 创建 / 复用 Collection
    # 固定的向量集合名称（相当于一张「表」）
    collection_name = "InterviewQuestions"
    # 若该 Collection 不存在则首次创建，存在则直接复用
    if not client.collections.exists(collection_name):
        # 延迟导入：仅在需要建表时才加载属性/数据类型定义
        from weaviate.classes.config import DataType, Property

        # 创建 Collection 并定义字段 schema
        client.collections.create(
            name=collection_name,
            properties=[
                Property(name="text", data_type=DataType.TEXT),  # 题目正文
                Property(name="source", data_type=DataType.TEXT),  # 来源文件路径
                Property(name="tech_stack", data_type=DataType.TEXT_ARRAY),  # 技术栈标签（数组）
                Property(name="difficulty", data_type=DataType.TEXT),  # 难度等级
            ],
            vectorizer_config=None,  # 使用外部 embedding
        )
        # 记录建表日志
        logger.info("创建 Weaviate collection: {}", collection_name)

    # 获取目标 Collection 句柄用于写入
    col = client.collections.get(collection_name)
    # 使用动态批处理上下文，自动按批量提交，提升写入吞吐
    with col.batch.dynamic() as batch:
        # 逐个节点向量化并加入批次
        for n in nodes:
            # 调用 embedding 模型，将文本转为向量
            vec = embed_model.get_text_embedding(n["text"])
            # 取出节点元数据；若为 None 则回退为空字典，避免 .get 报错
            meta = n.get("metadata", {}) or {}
            # 将一条记录（属性 + 向量）加入批次
            batch.add_object(
                properties={
                    "text": n["text"],  # 正文
                    "source": meta.get("file_path", ""),  # 来源路径，缺省为空串
                    "tech_stack": meta.get("tech_stack", []),  # 技术栈，缺省为空数组
                    "difficulty": meta.get("difficulty", "medium"),  # 难度，缺省为 medium
                },
                vector=vec,  # 该条记录对应的向量
            )
    # 全部写入完成后记录条数
    logger.info("向量索引写入完成：{} 条", len(nodes))


def build_full_index(kb_dir: str = "rag/knowledge_base") -> None:
    """构建完整索引：向量 + BM25

    参数:
        kb_dir: 知识库根目录路径
    返回:
        None（向量索引写入 Weaviate，BM25 语料缓存写入本地文件）
    """
    # 第一步：加载原始文档
    docs = load_documents(kb_dir)
    # 第二步：切分为节点
    nodes = split_documents(docs)
    # 第三步：写入向量索引
    build_vector_index(nodes)
    # BM25 索引由 BM25Retriever 运行时基于本地 JSON 构建
    # 延迟导入 BM25Retriever，避免顶层循环依赖
    from rag.retrievers.bm25_retriever import BM25Retriever

    # 第四步：基于相同节点构建 BM25 语料缓存（关键词检索用）
    BM25Retriever.build_corpus_cache(nodes)
    # 全部完成，输出成功日志
    logger.success("🎉 RAG 索引构建完成")
