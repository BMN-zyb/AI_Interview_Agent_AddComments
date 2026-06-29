"""
DAG 节点函数实现：每个节点对应一个 Agent.run() 调用
"""
# 启用未来注解特性，使类型注解延迟求值，避免前向引用问题
from __future__ import annotations

# 导入类型构造器：Any 任意类型、Dict 字典泛型（用于注解）
from typing import Any, Dict

# 导入 loguru 日志器，用于在各节点打印调试/信息日志
from loguru import logger

# 从 agents 包导入所有 Agent 类，每个 Agent 封装一类 LLM 任务
from agents import (
    ChatAgent,           # 闲聊 Agent
    EvaluatorAgent,      # 答案评估 / 报告生成 Agent
    IntentRouterAgent,   # 意图识别 Agent
    InterviewerAgent,    # 面试官（提问/追问）Agent
    JDAnalyzerAgent,     # JD 解析 Agent
    QuestionPlannerAgent,  # 出题规划 Agent
    ResumeAnalyzerAgent,   # 简历解析 Agent
    StudyPlannerAgent,     # 复习计划 Agent
)
# 导入全局状态类型，作为各节点函数的入参/返回值类型注解
from orchestration.state import InterviewState

# 单例（避免重复初始化 LLM）
# 在模块加载时一次性实例化各 Agent，后续节点复用同一实例，
# 避免每次调用都重新构建 LLM 客户端带来的开销。
_intent_router = IntentRouterAgent()
_jd_analyzer = JDAnalyzerAgent()
_resume_analyzer = ResumeAnalyzerAgent()
_question_planner = QuestionPlannerAgent()
_interviewer = InterviewerAgent()
_evaluator = EvaluatorAgent()
_study_planner = StudyPlannerAgent()
_chat = ChatAgent()


def node_route(state: InterviewState) -> InterviewState:
    """
    意图路由节点。
    如果调用方已经设置了 intent（CLI/API 直接注入），则跳过 LLM 识别。
    """
    # 打印进入该节点的调试日志
    logger.debug(">> node_route")
    # 若上游已显式注入明确意图，则无需再用 LLM 识别，直接透传状态
    if state.get("intent") in (
        "start_interview", "answer_question",
        "input_jd", "upload_resume", "use_skill",
    ):
        # 记录跳过 LLM 路由的调试信息
        logger.debug(f"  intent 已预设为 {state['intent']}，跳过 LLM 路由")
        return dict(state)  # type: ignore[return-value]
    # 否则交由意图识别 Agent 推断意图（传入状态副本以避免就地修改原状态）
    return _intent_router.run(dict(state))  # type: ignore[arg-type, return-value]


def node_jd_analyze(state: InterviewState) -> InterviewState:
    """JD 分析节点：调用 JDAnalyzerAgent 解析职位描述并写回状态。"""
    # 打印进入该节点的调试日志
    logger.debug(">> node_jd_analyze")
    # 调用 JD 解析 Agent 处理（传入状态副本），返回更新后的状态
    return _jd_analyzer.run(dict(state))  # type: ignore[arg-type, return-value]


def node_resume_analyze(state: InterviewState) -> InterviewState:
    """简历分析节点：调用 ResumeAnalyzerAgent 解析简历并写回状态。"""
    # 打印进入该节点的调试日志
    logger.debug(">> node_resume_analyze")
    # 调用简历解析 Agent 处理（传入状态副本），返回更新后的状态
    return _resume_analyzer.run(dict(state))  # type: ignore[arg-type, return-value]


def node_rag_retrieve(state: InterviewState) -> InterviewState:
    """调用 RAG 混合检索器，注入 rag_context"""
    # 打印进入该节点的调试日志
    logger.debug(">> node_rag_retrieve")
    # 延迟导入查询引擎（局部导入可避免模块级循环依赖、加快启动）
    from rag.query_engine import query_engine

    # 取出已解析的 JD 结构（缺省为空字典）
    jd = state.get("jd_parsed", {})
    # 用 JD 的技术栈与核心能力拼成检索查询串
    query = " ".join(jd.get("tech_stack", []) + jd.get("core_competencies", []))
    # 若没有任何可检索的关键词，则清空 RAG 结果并直接返回，跳过检索
    if not query:
        state["rag_context"] = ""
        state["rag_sources"] = []
        return state
    # 执行混合检索（向量 + 关键词等），取相关度最高的 top_k=10 条结果
    results = query_engine.hybrid_query(query, top_k=10)
    # 将各命中片段的正文用分隔符拼接成上下文文本，供后续出题/评估使用
    state["rag_context"] = "\n---\n".join(r.get("text", "") for r in results)
    # 同时保留原始检索结果（含来源元数据），供溯源/引用
    state["rag_sources"] = results
    # 返回更新后的状态
    return state


def node_plan_questions(state: InterviewState) -> InterviewState:
    """出题规划节点：调用 QuestionPlannerAgent 生成题目计划并写回状态。"""
    # 打印进入该节点的调试日志
    logger.debug(">> node_plan_questions")
    # 调用出题规划 Agent 处理（传入状态副本），返回更新后的状态
    return _question_planner.run(dict(state))  # type: ignore[arg-type, return-value]


def node_ask(state: InterviewState) -> InterviewState:
    """提问节点：调用 InterviewerAgent 向用户抛出当前题目或追问。"""
    # 打印进入该节点的调试日志
    logger.debug(">> node_ask")
    # 调用面试官 Agent 生成提问/追问（传入状态副本），返回更新后的状态
    return _interviewer.run(dict(state))  # type: ignore[arg-type, return-value]


def node_evaluate_one(state: InterviewState) -> InterviewState:
    """评估单题回答，根据追问判断决定是否推进题目索引"""
    # 打印进入该节点的调试日志
    logger.debug(">> node_evaluate_one")
    # 延迟导入难度更新函数（局部导入避免循环依赖）
    from orchestration.difficulty_fsm import update_difficulty

    # 调用评估 Agent 对当前回答打分/分析，得到新状态
    new_state = _evaluator.run(dict(state))
    # 根据本题对错动态调整难度档位与连续计数
    update_difficulty(new_state)

    # 取出题目计划列表（缺省为空列表）
    plan = new_state.get("question_plan", [])
    # 取出当前题目索引（缺省为 0）
    idx = new_state.get("current_question_idx", 0)

    # 如果需要追问，不推进索引
    # 评估判定需要追问时，保持当前题目索引不变，并明确标记面试未结束
    if new_state.get("should_followup", False):
        logger.info(f"题目 {idx + 1} 需要追问，保持当前索引")
        new_state["interview_finished"] = False
        return new_state  # type: ignore[return-value]

    # 检查是否强制结束
    # 面试官主动判定提前结束时，直接标记面试结束并返回
    if new_state.get("force_finish", False):
        new_state["interview_finished"] = True
        logger.info("面试官主动判断结束面试")
        return new_state  # type: ignore[return-value]

    # 正常推进索引
    # 若当前已是最后一题（下一索引越界），则标记面试结束
    if idx + 1 >= len(plan):
        new_state["interview_finished"] = True
        logger.info(f"面试结束，共 {len(plan)} 题全部完成")
    else:
        # 否则推进到下一题索引，并标记面试尚未结束
        new_state["current_question_idx"] = idx + 1
        new_state["interview_finished"] = False
        logger.info(f"推进到第 {idx + 2}/{len(plan)} 题")

    # 返回更新后的状态
    return new_state  # type: ignore[return-value]


def node_generate_report(state: InterviewState) -> InterviewState:
    """报告生成节点：复用 EvaluatorAgent，在面试结束时产出最终评估报告。"""
    # 打印进入该节点的调试日志
    logger.debug(">> node_generate_report")
    # 触发报告生成（interview_finished=True 时 evaluator 生成报告）
    # 复用评估 Agent：当状态标记面试已结束时，其内部逻辑会生成总结报告
    return _evaluator.run(dict(state))  # type: ignore[arg-type, return-value]


def node_study_plan(state: InterviewState) -> InterviewState:
    """复习计划节点：调用 StudyPlannerAgent 基于薄弱点生成学习计划。"""
    # 打印进入该节点的调试日志
    logger.debug(">> node_study_plan")
    # 调用复习计划 Agent 处理（传入状态副本），返回更新后的状态
    return _study_planner.run(dict(state))  # type: ignore[arg-type, return-value]


def node_chat(state: InterviewState) -> InterviewState:
    """闲聊节点：调用 ChatAgent 处理与面试流程无关的普通对话。"""
    # 打印进入该节点的调试日志
    logger.debug(">> node_chat")
    # 调用闲聊 Agent 生成回复（传入状态副本），返回更新后的状态
    return _chat.run(dict(state))  # type: ignore[arg-type, return-value]


def node_save_memory(state: InterviewState) -> InterviewState:
    """将本轮薄弱点写入长期记忆"""
    # 打印进入该节点的调试日志
    logger.debug(">> node_save_memory")
    # 延迟导入记忆管理器（局部导入避免循环依赖）
    from memory.memory_manager import memory_manager

    # 取用户标识，缺省为 "default"
    user_id = state.get("user_id", "default")
    # 取出本场需要记住的薄弱点列表（缺省为空）
    weaknesses = state.get("weaknesses_to_remember", [])
    # 仅当存在薄弱点时才追加写入长期记忆，避免无意义写操作
    if weaknesses:
        memory_manager.append_weaknesses(user_id, weaknesses)
    # 返回（未改动键的）状态
    return state


def node_load_memory(state: InterviewState) -> InterviewState:
    """加载用户长期记忆到状态"""
    # 打印进入该节点的调试日志
    logger.debug(">> node_load_memory")
    # 延迟导入记忆管理器（局部导入避免循环依赖）
    from memory.memory_manager import memory_manager

    # 取用户标识，缺省为 "default"
    user_id = state.get("user_id", "default")
    # 读取该用户历史积累的薄弱点并写入状态，供出题/评估参考
    state["long_term_weaknesses"] = memory_manager.get_weaknesses(user_id)
    # 返回更新后的状态
    return state


def node_skill_dispatch(state: InterviewState) -> InterviewState:
    """分发到 Skill 技能系统"""
    # 打印进入该节点的调试日志
    logger.debug(">> node_skill_dispatch")
    # 延迟导入技能注册表（局部导入避免循环依赖）
    from skills.skill_registry import skill_registry

    # 取要执行的技能名，缺省为 "quiz"
    skill_name = state.get("skill_name", "quiz")
    # 从注册表按名称查找对应技能实例
    skill = skill_registry.get(skill_name)
    # 若技能不存在，则写入错误提示并直接返回，避免后续空对象调用
    if skill is None:
        state["agent_reply"] = f"未找到技能：{skill_name}"
        return state
    # 执行该技能（传入状态副本），返回其更新后的状态
    return skill.run(dict(state))  # type: ignore[arg-type, return-value]