"""初始化 MySQL 数据库表结构"""
# 第三方日志库 loguru：用于输出初始化过程的提示日志
from loguru import logger
# 从项目的 memory.long_term 模块导入长期记忆类，其内部封装了数据库连接与 ORM 表结构定义
from memory.long_term import LongTermMemory


def main():
    """脚本入口：创建长期记忆所需的 MySQL 数据表。

    无参数；无返回值。实例化 LongTermMemory 并调用其建表方法，完成表结构初始化。
    """
    # 打印开始日志，提示用户数据库表初始化任务已启动
    logger.info("正在初始化数据库表...")
    # 实例化长期记忆对象（建立数据库连接），并调用 create_tables() 根据 ORM 模型创建所有表
    LongTermMemory().create_tables()
    # 使用 success 级别日志标记表结构初始化成功完成
    logger.success("✅ 数据库表初始化完成")


# 仅当本文件作为脚本直接运行时才执行 main()，被其它模块 import 时不会自动触发
if __name__ == "__main__":
    # 调用入口函数，启动数据库表初始化流程
    main()
