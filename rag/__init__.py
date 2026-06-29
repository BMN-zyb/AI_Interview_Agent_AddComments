"""RAG 模块：基于 LlamaIndex 的检索增强生成体系"""
# 从查询引擎子模块导入全局单例 query_engine，作为 RAG 模块对外的统一查询入口
from rag.query_engine import query_engine

# 显式声明本包对外导出的公共符号，仅暴露 query_engine（控制 from rag import * 的行为）
__all__ = ["query_engine"]
