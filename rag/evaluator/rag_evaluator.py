"""
RAG 质量评估：基于 RAGAS 的三维评估
- Faithfulness（忠实度）
- Answer Relevancy（相关性）
- Completeness（完整性）
"""
from __future__ import annotations

# 标准库：类型注解
from typing import Any, Dict, List

# loguru：结构化日志库
from loguru import logger


class RAGEvaluator:
    """RAG 质量评估器（封装 RAGAS）"""

    def __init__(self) -> None:
        """初始化评估器，延迟加载指标（首次评估时才真正导入 RAGAS）"""
        # 标记 RAGAS 指标是否已加载，避免重复初始化
        self._metrics_loaded = False

    def _load_metrics(self) -> None:
        """惰性加载 RAGAS 指标对象

        说明:
            RAGAS 依赖较重，采用懒加载；导入失败时降级为空指标列表而不抛异常。
        """
        # 已加载过则直接返回，保证只执行一次
        if self._metrics_loaded:
            return
        try:
            # 延迟导入 RAGAS 的三个核心指标
            from ragas.metrics import answer_relevancy, context_precision, faithfulness
            # 导入有害性评判指标（此处仅导入，未纳入下方指标列表）
            from ragas.metrics.critique import harmfulness

            # 选用忠实度、答案相关性、上下文精确率三项指标
            self.metrics = [faithfulness, answer_relevancy, context_precision]
            # 标记已加载完成
            self._metrics_loaded = True
            logger.info("RAGAS 指标加载完成")
        except ImportError as e:
            # 未安装 ragas 时记录错误，并以空指标列表降级，使后续 evaluate 返回空结果
            logger.error("ragas 未安装: {}", e)
            self.metrics = []
            self._metrics_loaded = True

    def evaluate(
        self,
        questions: List[str],
        answers: List[str],
        contexts: List[List[str]],
        ground_truths: List[str] | None = None,
    ) -> Dict[str, float]:
        """运行 RAGAS 评估，返回各指标均值

        参数:
            questions: 问题列表
            answers: 对应的答案列表
            contexts: 每个问题对应的上下文片段列表（二维列表）
            ground_truths: 标准答案列表，可选；缺省时用空串占位
        返回:
            Dict[str, float]: 各指标名到其在数据集上均值的映射；指标不可用时返回空字典
        """
        # 确保指标已加载
        self._load_metrics()
        # 指标为空（如未安装 ragas）时直接返回空结果
        if not self.metrics:
            return {}

        # 延迟导入 datasets 与 ragas 的评估入口（重依赖按需加载）
        from datasets import Dataset
        from ragas import evaluate as ragas_evaluate

        # 将四列数据组装为 HuggingFace Dataset，供 RAGAS 评估
        ds = Dataset.from_dict({
            "question": questions,
            "answer": answers,
            "contexts": contexts,
            # 无标准答案时，用与问题等长的空串列表占位
            "ground_truth": ground_truths or [""] * len(questions),
        })
        # 执行 RAGAS 评估，得到结果对象
        result = ragas_evaluate(ds, metrics=self.metrics)
        # 存放各指标均值
        scores: Dict[str, float] = {}
        # 将结果转换为 pandas DataFrame 便于逐列求均值
        df = result.to_pandas()
        # 遍历每一列
        for col in df.columns:
            # 跳过原始输入列，只保留指标得分列
            if col in ("question", "answer", "contexts", "ground_truth"):
                continue
            # 对该指标列求均值并转为 float 存入结果
            scores[col] = float(df[col].mean())
        # 记录评估结果日志
        logger.info("RAG 评估结果：{}", scores)
        return scores

    def evaluate_single(
        self, question: str, answer: str, context: str
    ) -> Dict[str, float]:
        """单条评估

        参数:
            question: 单个问题
            answer: 单个答案
            context: 单段上下文
        返回:
            Dict[str, float]: 该条样本的各指标得分
        """
        # 将单条样本包装为列表形式，复用批量评估逻辑
        return self.evaluate(
            [question], [answer], [[context]]
        )
