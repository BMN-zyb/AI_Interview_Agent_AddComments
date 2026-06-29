"""RAG 评估子模块：对外暴露 RAGEvaluator 评估器"""
# 从评估器实现模块导入 RAGEvaluator 类，作为本子包的统一入口
from rag.evaluator.rag_evaluator import RAGEvaluator

# 声明对外导出的公共符号，仅暴露 RAGEvaluator
__all__ = ["RAGEvaluator"]
