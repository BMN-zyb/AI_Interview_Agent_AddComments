"""
全局状态定义（TypedDict），LangGraph 各节点共享
"""
# 启用未来注解特性：使所有类型注解延迟求值（视为字符串），
# 避免前向引用问题，并允许使用新式泛型写法而无需运行时已定义。
from __future__ import annotations

# 从 typing 导入类型构造器：
#   Any 任意类型；Dict/List 容器泛型；Optional 可空类型；TypedDict 带字段名的字典类型基类
from typing import Any, Dict, List, Optional, TypedDict

# 导入 LangChain 的消息基类，用于在状态中保存对话消息流（人类/AI 消息等）
from langchain_core.messages import BaseMessage


# 定义面试流程的全局状态结构。
# 继承 TypedDict 使其表现为「带固定键名的字典」，便于 LangGraph 在节点间传递与合并；
# total=False 表示所有字段都是可选的（节点可只更新其中部分键，无需一次性提供全部）。
class InterviewState(TypedDict, total=False):
    """面试流程全局状态"""

    # ---- 会话 ID ----
    session_id: str  # 单次面试会话的唯一标识
    user_id: str  # 用户标识，用于区分不同用户的长期记忆

    # ---- 用户输入 / 意图 ----
    user_input: str  # 用户本轮输入的原始文本
    intent: str  # 识别出的用户意图（如 start_interview / answer_question 等）
    intent_confidence: float  # 意图识别的置信度分数

    # ---- JD / 简历 ----
    jd_text: str  # 职位描述（Job Description）原始文本
    jd_parsed: Dict[str, Any]  # JD 经 LLM 结构化解析后的结果（技术栈、核心能力等）
    resume_text: str  # 简历原始文本
    resume_parsed: Dict[str, Any]  # 简历经结构化解析后的结果

    # ---- RAG ----
    rag_context: str  # 检索增强生成（RAG）拼接后的上下文文本，供出题/评估参考
    rag_sources: List[Dict[str, Any]]  # RAG 检索命中的原始片段及其元数据列表

    # ---- 题目与问答 ----
    question_plan: List[Dict[str, Any]]  # 出题规划：本场面试的题目列表
    total_questions: int                  # ★ 补充：控制出题数量
    current_question_idx: int  # 当前正在进行的题目索引（从 0 开始）
    current_question: Dict[str, Any]  # 当前题目的结构化信息
    current_question_text: str  # 当前题目的可读文本（用于展示给用户）
    is_followup: bool  # 当前提问是否为追问（而非新题）
    qa_history: List[Dict[str, Any]]  # 问答历史记录（每条含问题、回答等）
    awaiting_answer: bool  # 是否正在等待用户作答（流程挂起标志）
    awaiting_evaluation: bool  # 是否正在等待对回答进行评估
    last_user_answer: str  # 用户最近一次提交的回答文本

    # ---- 追问控制 ----
    followup_count: int  # 当前题目已追问的次数
    max_followup: int  # 单题允许的最大追问次数
    should_followup: bool  # 评估后判定是否需要继续追问
    followup_question: str  # 生成的追问问题文本

    # ---- 评分与报告 ----
    score_records: List[Dict[str, Any]]  # 各题评分记录列表
    final_report: Dict[str, Any]  # 面试结束后生成的最终评估报告
    study_plan: Dict[str, Any]  # 基于薄弱点生成的复习/学习计划
    github_recommendations: List[Dict[str, Any]]  # 推荐的 GitHub 学习资源列表

    # ---- 难度 FSM ----
    current_difficulty: str  # 当前难度档位（easy / medium / hard）
    consecutive_correct: int  # 连续答对计数（用于难度自动升档）
    consecutive_wrong: int  # 连续答错计数（用于难度自动降档）

    # ---- 记忆 ----
    short_term_context: List[str]  # 短期上下文（本场会话内的临时记忆）
    long_term_weaknesses: List[str]  # 从长期记忆加载的历史薄弱点
    weaknesses_to_remember: List[str]  # 本场新发现、需写回长期记忆的薄弱点
    strengths: List[str]  # 本场总结的优势点
    weaknesses: List[str]  # 本场总结的薄弱点

    # ---- 技能 ----
    skill_name: str  # 要分发执行的技能名称（如 quiz）
    skill_state: Dict[str, Any]  # 技能运行所需/产生的状态数据

    # ---- 输出 ----
    agent_reply: str  # Agent 生成的、返回给用户的回复文本
    interviewer_comment: str  # 面试官针对回答给出的点评
    interview_finished: bool  # 面试是否已结束的标志
    error: Optional[str]  # 流程中出现的错误信息（无错误时为 None）

    # ---- LangGraph 消息流 ----
    messages: List[BaseMessage]  # LangGraph 维护的消息列表（人类/AI 消息序列）

    # ---- 强制结束标志 ----
    force_finish: bool  # 面试官主动判定提前结束面试的标志