"""
条件边 / 路由逻辑：根据 state 动态选择下一个节点
"""
# 启用未来注解特性，使类型注解延迟求值，避免前向引用问题
from __future__ import annotations

# 导入全局状态类型，作为各路由函数的入参类型注解
from orchestration.state import InterviewState


def route_by_intent(state: InterviewState) -> str:
    """按意图分流"""
    # 读取已识别的用户意图，缺省为普通聊天 "chat"
    intent = state.get("intent", "chat")
    # 意图 -> 目标节点名的映射表，决定流程从路由节点跳向哪个处理节点
    mapping = {
        "start_interview": "load_memory",   # 开始面试：先加载长期记忆
        "input_jd": "jd_analyze",           # 录入 JD：进入 JD 分析
        "upload_resume": "resume_analyze",  # 上传简历：进入简历分析
        "answer_question": "evaluate_one",  # 回答问题：进入单题评估
        "use_skill": "skill_dispatch",      # 使用技能：进入技能分发
        "chat": "chat",                     # 闲聊：进入聊天节点
    }
    # 按意图取目标节点；若意图未知则兜底走 "chat"
    return mapping.get(intent, "chat")


def route_after_jd(state: InterviewState) -> str:
    """JD 分析完成后：有简历则分析简历，否则直接 RAG"""
    # 若 JD 分析阶段出错，跳过简历分析，直接进入 RAG 检索
    if state.get("error"):
        return "rag_retrieve"
    # 读取简历文本并去除首尾空白，用于判断用户是否提供了简历
    resume_text = state.get("resume_text", "").strip()
    # 有简历内容则先做简历分析
    if resume_text:
        return "resume_analyze"
    # 否则没有简历，直接进入 RAG 检索
    return "rag_retrieve"


def route_after_resume(state: InterviewState) -> str:
    """简历分析完成后：进入 RAG 检索"""
    # 若简历分析阶段出错，则降级回到聊天节点
    if state.get("error"):
        return "chat"
    # 正常情况下进入 RAG 检索，为出题准备上下文
    return "rag_retrieve"


def route_after_plan(state: InterviewState) -> str:
    """出题规划完成后：进入第一题提问"""
    # 若出题阶段出错，或没有生成任何题目计划，则降级回到聊天节点
    if state.get("error") or not state.get("question_plan"):
        return "chat"
    # 正常情况下进入提问节点，向用户抛出第一题
    return "ask"


def route_after_evaluate(state: InterviewState) -> str:
    """
    单题评估后路由：
    - 需要追问 -> ask（追问）
    - 面试结束 -> generate_report
    - 否则 -> ask（下一题）
    """
    # 若评估节点已标记面试结束，则进入报告生成节点
    if state.get("interview_finished", False):
        return "generate_report"
    # should_followup 或正常下一题，都走 ask
    # 无论是追问还是出下一题，统一回到提问节点 ask
    return "ask"


def route_after_report(state: InterviewState) -> str:
    """面试报告生成后：进入复习计划"""
    # 报告生成后固定进入复习/学习计划节点
    return "study_plan"