# memory 包的初始化文件：对外统一暴露记忆系统的入口对象
# 从 memory_manager 模块导入已实例化的全局单例 memory_manager（记忆统一入口）
from memory.memory_manager import memory_manager

# __all__ 显式声明 `from memory import *` 时对外导出的符号，仅暴露 memory_manager
__all__ = ["memory_manager"]
