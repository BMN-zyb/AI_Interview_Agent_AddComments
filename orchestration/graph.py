"""
LangGraph 主面试流程 DAG 定义（StateGraph）
"""
# 启用未来注解特性，使类型注解延迟求值，避免前向引用问题
from __future__ import annotations

# 导入 lru_cache 装饰器，用于缓存编译后的图，避免重复编译开销
from functools import lru_cache

# 从 langgraph 导入构图核心组件：
#   END / START：图的虚拟起点与终点标记
#   StateGraph：基于共享状态的有向图构建器
from langgraph.graph import END, START, StateGraph

# 导入所有条件边（路由）函数，用于在节点间做动态分支
from orchestration.edges import (
    route_after_evaluate,  # 单题评估后的路由
    route_after_jd,        # JD 分析后的路由
    route_after_plan,      # 出题规划后的路由
    route_after_report,    # 报告生成后的路由
    route_after_resume,    # 简历分析后的路由
    route_by_intent,       # 按意图分流的入口路由
)
# 导入所有节点实现函数，每个函数对应图中的一个处理节点
from orchestration.nodes import (
    node_ask,              # 提问节点
    node_chat,             # 闲聊节点
    node_evaluate_one,     # 单题评估节点
    node_generate_report,  # 报告生成节点
    node_jd_analyze,       # JD 分析节点
    node_load_memory,      # 加载长期记忆节点
    node_plan_questions,   # 出题规划节点
    node_rag_retrieve,     # RAG 检索节点
    node_resume_analyze,   # 简历分析节点
    node_route,            # 意图路由节点
    node_save_memory,      # 保存长期记忆节点
    node_skill_dispatch,   # 技能分发节点
    node_study_plan,       # 复习计划节点
)
# 导入全局状态类型，作为 StateGraph 的状态模式
from orchestration.state import InterviewState


def build_interview_graph() -> StateGraph:
    """构建面试流程的状态图（StateGraph，未编译）。

    负责：注册所有节点、连接固定边与条件边，最终返回可供编译的图对象。

    返回:
        StateGraph: 以 InterviewState 为共享状态的有向图。
    """
    # 以 InterviewState 为共享状态创建状态图构建器
    graph = StateGraph(InterviewState)

    # 注册所有节点
    # 将每个处理函数注册为图中的命名节点（名称用于后续连边引用）
    graph.add_node("route", node_route)                      # 意图路由
    graph.add_node("jd_analyze", node_jd_analyze)            # JD 分析
    graph.add_node("resume_analyze", node_resume_analyze)    # 简历分析
    graph.add_node("rag_retrieve", node_rag_retrieve)        # RAG 检索
    graph.add_node("plan_questions", node_plan_questions)    # 出题规划
    graph.add_node("ask", node_ask)                          # 提问
    graph.add_node("evaluate_one", node_evaluate_one)        # 单题评估
    graph.add_node("generate_report", node_generate_report)  # 报告生成
    graph.add_node("study_plan", node_study_plan)            # 复习计划
    graph.add_node("chat", node_chat)                        # 闲聊
    graph.add_node("skill_dispatch", node_skill_dispatch)    # 技能分发
    graph.add_node("load_memory", node_load_memory)          # 加载记忆
    graph.add_node("save_memory", node_save_memory)          # 保存记忆

    # 入口 -> 路由
    # 从图的虚拟起点 START 连一条固定边到意图路由节点，作为流程入口
    graph.add_edge(START, "route")

    # 路由分流
    # 在 route 节点添加条件边：由 route_by_intent 返回值决定跳向的目标节点
    graph.add_conditional_edges(
        "route",
        route_by_intent,
        {
            # 路由函数返回值 -> 实际目标节点名 的映射
            "load_memory": "load_memory",
            "jd_analyze": "jd_analyze",
            "resume_analyze": "resume_analyze",
            "rag_retrieve": "rag_retrieve",
            "evaluate_one": "evaluate_one",
            "skill_dispatch": "skill_dispatch",
            "chat": "chat",
        },
    )

    # 面试启动链路
    # 加载记忆后固定进入 JD 分析
    graph.add_edge("load_memory", "jd_analyze")
    # JD 分析后按 route_after_jd 决定：有简历走简历分析，否则直接 RAG 检索
    graph.add_conditional_edges(
        "jd_analyze",
        route_after_jd,
        {"resume_analyze": "resume_analyze", "rag_retrieve": "rag_retrieve"},
    )
    # 简历分析后按 route_after_resume 决定：正常走 RAG 检索，出错则降级到聊天
    graph.add_conditional_edges(
        "resume_analyze",
        route_after_resume,
        {"rag_retrieve": "rag_retrieve", "chat": "chat"},
    )
    # RAG 检索后固定进入出题规划
    graph.add_edge("rag_retrieve", "plan_questions")
    # 出题规划后按 route_after_plan 决定：有题目走提问，否则降级到聊天
    graph.add_conditional_edges(
        "plan_questions",
        route_after_plan,
        {"ask": "ask", "chat": "chat"},
    )
    graph.add_edge("ask", END)  # 挂起等用户回答

    # 答题评估循环 (追问也会回到 ask)
    # 单题评估后按 route_after_evaluate 决定：继续提问/追问，或进入报告生成
    graph.add_conditional_edges(
        "evaluate_one",
        route_after_evaluate,
        {"ask": "ask", "generate_report": "generate_report"},
    )

    # 面试结束链路
    # 报告生成后按 route_after_report 决定（固定进入复习计划）
    graph.add_conditional_edges(
        "generate_report",
        route_after_report,
        {"study_plan": "study_plan"},
    )
    # 复习计划完成后保存记忆
    graph.add_edge("study_plan", "save_memory")
    # 保存记忆后到达终点 END，结束本次执行
    graph.add_edge("save_memory", END)

    # 其他出口
    # 聊天节点执行完直接结束
    graph.add_edge("chat", END)
    # 技能分发节点执行完直接结束
    graph.add_edge("skill_dispatch", END)

    # 返回构建完成、尚未编译的状态图
    return graph


# 使用 lru_cache 缓存结果：保证整个进程内只编译一次图并复用
@lru_cache
def get_compiled_graph():
    """构建并编译面试状态图，返回可执行的编译图对象（带进程级缓存）。"""
    # 先构建状态图，再调用 .compile() 得到可直接 invoke 的可执行图
    return build_interview_graph().compile()