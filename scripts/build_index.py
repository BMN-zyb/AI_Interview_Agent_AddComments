"""构建 RAG 向量索引"""
# 第三方日志库 loguru：用于输出带颜色/级别的日志（info/success 等），比标准 logging 更易用
from loguru import logger
# 从项目的 rag.indexer 模块导入构建全量索引的函数，封装了文档加载、切分、向量化与写入向量库的全流程
from rag.indexer import build_full_index


def main():
    """脚本入口：触发 RAG 向量索引的全量构建。

    无参数；无返回值。仅按顺序输出开始日志、执行索引构建、输出完成日志。
    """
    # 打印开始日志，提示用户索引构建任务已启动（便于在 CLI 中观察进度）
    logger.info("📚 开始构建 RAG 索引...")
    # 调用核心函数执行实际的索引构建工作（耗时操作，具体逻辑在 rag.indexer 中实现）
    build_full_index()
    # 使用 success 级别日志标记构建成功完成，区别于普通 info 以突出最终结果
    logger.success("✅ 索引构建完成")


# 仅当本文件作为脚本直接运行时才执行 main()，被其它模块 import 时不会自动触发
if __name__ == "__main__":
    # 调用入口函数，启动整个索引构建流程
    main()
