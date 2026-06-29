"""编排层：LangGraph DAG 定义"""
# 该模块是 orchestration（编排层）包的入口文件。
# 编排层负责用 LangGraph 把各个 Agent 节点组织成有向无环图（DAG），驱动整个面试流程。

# 从 graph 子模块导入两个对外公开的工厂函数：
#   build_interview_graph：构建（但未编译）StateGraph 图对象
#   get_compiled_graph：返回已编译并带缓存的可执行图
from orchestration.graph import build_interview_graph, get_compiled_graph

# 声明本包对外暴露的公共 API（即 `from orchestration import *` 时会导出的名字），
# 仅公开上述两个图构建函数，隐藏其余内部实现细节。
__all__ = ["build_interview_graph", "get_compiled_graph"]
