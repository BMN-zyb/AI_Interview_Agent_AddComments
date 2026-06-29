"""
BM25 关键词检索：
- 使用 rank_bm25 库
- 支持中英文分词（jieba）
"""
from __future__ import annotations

# 标准库：JSON 处理（语料以 JSON/字典结构组织）
import json
# 标准库：对象序列化，用于缓存语料到本地文件
import pickle
# 标准库：文件系统路径操作
from pathlib import Path
# 标准库：类型注解
from typing import Any, Dict, List

# loguru：结构化日志库
from loguru import logger
# rank_bm25：经典 BM25Okapi 关键词检索算法实现
from rank_bm25 import BM25Okapi

# 尝试导入 jieba 中文分词；缺失时降级为按空白切分（兼容纯英文环境）
try:
    import jieba
except ImportError:
    jieba = None  # type: ignore

# BM25 语料缓存文件路径（pickle 持久化，避免每次重建）
CACHE_PATH = Path("data/bm25_corpus.pkl")


def _tokenize(text: str) -> List[str]:
    """对文本分词，支持中英文

    参数:
        text: 待分词文本
    返回:
        List[str]: 分词后的 token 列表；有 jieba 时按中文分词并过滤空白，否则按空白小写切分
    """
    # 若 jieba 可用，使用其分词并剔除纯空白的 token
    if jieba is not None:
        return [t for t in jieba.cut(text) if t.strip()]
    # 否则回退为小写后按空白切分（适用于英文）
    return text.lower().split()


class BM25Retriever:
    """BM25 关键词检索器"""

    def __init__(self) -> None:
        """初始化检索器，并尝试从本地缓存加载语料与 BM25 索引"""
        # 原始语料列表（每项含 id/text/metadata）
        self.corpus: List[Dict[str, Any]] = []
        # 语料对应的分词结果（二维列表），作为 BM25 输入
        self.tokenized: List[List[str]] = []
        # BM25 索引对象，未加载时为 None
        self.bm25: BM25Okapi | None = None
        # 构造时立即尝试加载缓存
        self._load_cache()

    @staticmethod
    def build_corpus_cache(nodes: List[Dict[str, Any]]) -> None:
        """构建 BM25 语料缓存

        参数:
            nodes: 节点字典列表（来自 indexer 的切分结果）
        返回:
            None（语料以 pickle 形式写入 CACHE_PATH）
        """
        # 确保缓存文件所在目录存在（不存在则递归创建）
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        # 以二进制写模式打开缓存文件
        with open(CACHE_PATH, "wb") as f:
            # 将节点列表序列化写入
            pickle.dump(nodes, f)
        # 记录写入条数
        logger.info("BM25 语料缓存已写入：{} 条", len(nodes))

    def _load_cache(self) -> None:
        """从本地缓存加载语料并构建 BM25 索引

        说明:
            缓存不存在时仅告警，retriever 保持空状态（检索将返回空结果）。
        """
        # 缓存文件不存在时告警并直接返回，保持空检索器
        if not CACHE_PATH.exists():
            logger.warning("BM25 缓存不存在，retriever 为空")
            return
        # 以二进制读模式打开缓存文件
        with open(CACHE_PATH, "rb") as f:
            # 反序列化得到语料列表
            self.corpus = pickle.load(f)
        # 对每篇文档正文分词，得到 BM25 所需的分词语料
        self.tokenized = [_tokenize(n["text"]) for n in self.corpus]
        # 基于分词语料构建 BM25Okapi 索引
        self.bm25 = BM25Okapi(self.tokenized)
        # 记录加载文档数（debug 级别）
        logger.debug("BM25 加载 {} 条文档", len(self.corpus))

    def retrieve(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """按 BM25 关键词相关性检索文档

        参数:
            query: 查询文本
            top_k: 返回的最大条数，默认 5
        返回:
            List[Dict]: 命中文档列表（含 id/text/metadata/score/source）；索引为空时返回空列表
        """
        # 索引未构建（缓存缺失）时直接返回空结果
        if not self.bm25:
            return []
        # 对查询分词
        tokens = _tokenize(query)
        # 计算查询与每篇文档的 BM25 相关性分数
        scores = self.bm25.get_scores(tokens)
        # 按分数从高到低排序文档下标，并取前 top_k 个
        ranked_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        # 存放最终命中结果
        results = []
        # 遍历排名靠前的文档下标
        for i in ranked_idx:
            # 过滤掉分数非正（无关）的文档
            if scores[i] <= 0:
                continue
            # 组装统一的结果字典
            results.append({
                "id": self.corpus[i]["id"],  # 文档 id
                "text": self.corpus[i]["text"],  # 文档正文
                "metadata": self.corpus[i].get("metadata", {}),  # 元数据
                "score": float(scores[i]),  # BM25 分数（转 float）
                "source": "bm25",  # 标记来源为 bm25，便于后续融合区分
            })
        return results
