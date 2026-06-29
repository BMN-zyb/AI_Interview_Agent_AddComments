"""
面试 REST API 路由
POST /interview/start   -> 启动面试，返回第一题
POST /interview/answer  -> 提交回答，返回下一题或报告
POST /interview/skill   -> 触发技能模块
GET  /interview/report/{session_id} -> 获取完整报告
"""
# 启用延迟注解求值（PEP 563），使类型注解以字符串形式保存，便于前向引用与兼容性。
from __future__ import annotations

# 标准库：用于生成全局唯一的会话 ID（uuid4）。
import uuid

# FastAPI：路由器与标准 HTTP 异常类型（用于返回 4xx/5xx 错误）。
from fastapi import APIRouter, HTTPException
# loguru：结构化日志库，记录运行信息与错误。
from loguru import logger

# 导入本路由所需的请求/响应数据模型（Pydantic），用于入参校验与出参约束。
from api.schemas import (
    AnswerRequest,           # 提交回答的请求体
    AnswerResponse,          # 提交回答的响应体
    ReportResponse,          # 获取报告的响应体
    SkillRequest,            # 触发技能的请求体
    StartInterviewRequest,   # 启动面试的请求体
    StartInterviewResponse,  # 启动面试的响应体
)
# 记忆管理器：负责面试会话状态的持久化（保存/读取 state）。
from memory.memory_manager import memory_manager

# 创建面试路由器：所有接口统一加 /interview 前缀，并在文档中归入“面试”分组。
router = APIRouter(prefix="/interview", tags=["面试"])


def _get_graph():
    """惰性获取已编译的 LangGraph 工作流图。

    采用函数内延迟导入，避免在模块加载时即触发 orchestration.graph 的导入，
    从而打破潜在的循环依赖并加快启动速度。

    返回:
        已编译、可直接 invoke 的工作流图对象。
    """
    # 延迟导入：仅在真正需要图对象时才加载，规避循环依赖。
    from orchestration.graph import get_compiled_graph
    return get_compiled_graph()


# ── 启动面试 ──────────────────────────────────────────────────────────────────

# 注册 POST /interview/start 接口，响应体须符合 StartInterviewResponse。
@router.post("/start", response_model=StartInterviewResponse)
async def start_interview(req: StartInterviewRequest):
    """
    启动一场新面试：
    1. 分析 JD + 简历
    2. RAG 检索题库
    3. 生成题目计划
    4. 返回第一题
    """
    # 为本次面试生成唯一会话 ID，后续所有交互都以此 ID 关联状态。
    session_id = str(uuid.uuid4())
    # 获取编译好的工作流图，用于驱动整套面试流程。
    graph      = _get_graph()

    # 构造工作流的初始状态字典：囊括会话信息、JD/简历、流程控制标志位与默认配置。
    init_state = {
        "session_id":           session_id,        # 会话唯一标识
        "user_id":              req.user_id,        # 用户标识（用于长期记忆归属）
        "jd_text":              req.jd_text,        # 职位描述原文
        "resume_text":          req.resume_text,    # 简历原文
        "intent":               "start_interview",  # 当前意图：启动面试（供图路由）
        "user_input":           "开始面试",          # 模拟用户输入
        "current_difficulty":   "medium",           # 初始题目难度
        "current_question_idx": 0,                  # 当前题目索引（从 0 开始）
        "qa_history":           [],                 # 问答历史记录
        "score_records":        [],                 # 评分记录
        "awaiting_answer":      False,              # 是否在等待用户作答
        "awaiting_evaluation":  False,              # 是否在等待对回答评估
        "interview_finished":   False,              # 面试是否已结束
        "should_followup":      False,              # 是否需要追问
        "followup_count":       0,                  # 已追问次数
        "max_followup":         2,                  # 单题最大追问次数上限
        "force_finish":         False,              # 是否被强制结束
        "skill_state":          {},                 # 技能模块的内部状态
        "total_questions":      req.total_questions,# 计划出题总数
    }

    try:
        # 同步执行整条工作流：分析 JD/简历 -> RAG 检索 -> 生成题目计划 -> 产出第一题。
        state = graph.invoke(init_state)
    except Exception as e:
        # 工作流执行异常：记录错误并向客户端返回 500。
        logger.error("面试启动失败: {}", e)
        raise HTTPException(status_code=500, detail=f"面试启动失败: {e}")

    # 从执行后的状态中取出第一道题目文本。
    question = state.get("current_question_text", "")
    # 若题目为空，通常意味着 JD 内容不足以生成题目，返回 500 提示检查 JD。
    if not question:
        raise HTTPException(status_code=500, detail="题目生成失败，请检查 JD 内容")

    # 将本次面试的完整状态持久化，供后续 /answer、/skill、/report 接口续用。
    memory_manager.save_session(session_id, state)

    # 组装并返回启动响应：包含会话 ID、首题及其元信息。
    return StartInterviewResponse(
        session_id=session_id,                                      # 会话 ID
        question=question,                                          # 第一题题面
        question_index=state.get("current_question_idx", 0),        # 当前题目索引
        total_questions=len(state.get("question_plan", [])),        # 实际计划题目数量
        difficulty=state.get("current_difficulty", "medium"),       # 当前题目难度
        jd_title=state.get("jd_parsed", {}).get("title", ""),       # 从 JD 解析出的职位标题
    )


# ── 提交回答 ──────────────────────────────────────────────────────────────────

# 注册 POST /interview/answer 接口，响应体须符合 AnswerResponse。
@router.post("/answer", response_model=AnswerResponse)
async def submit_answer(req: AnswerRequest):
    """
    提交当前题目的回答：
    - 评估得分
    - 判断是否追问
    - 返回下一题或面试报告
    """
    # 根据会话 ID 读取已保存的面试状态。
    state = memory_manager.load_session(req.session_id)
    # 状态不存在（会话过期或 ID 错误）时返回 404。
    if not state:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")

    # 取出工作流图以推进流程。
    graph = _get_graph()

    # 将用户回答写入状态，并切换意图/标志位，驱动图进入“评估回答”分支。
    state["user_input"]          = req.answer   # 本轮用户输入（回答内容）
    state["last_user_answer"]    = req.answer   # 记录最近一次回答，供节点引用
    state["intent"]              = "answer_question"  # 意图：回答问题
    state["awaiting_evaluation"] = True         # 标记需要对该回答进行评估
    state["awaiting_answer"]     = False         # 不再处于等待作答状态

    try:
        # 执行工作流：评估回答 -> 决定追问/下一题/结束并生成报告。
        state = graph.invoke(state)
    except Exception as e:
        # 处理失败：记录日志并返回 500。
        logger.error("answer 处理失败: {}", e)
        raise HTTPException(status_code=500, detail=f"回答处理失败: {e}")

    # 持久化更新后的状态。
    memory_manager.save_session(req.session_id, state)

    # 取出题目计划，用于计算总题数。
    plan = state.get("question_plan", [])
    # 组装并返回响应：涵盖结束/追问标志、下一题信息，以及（结束时的）报告与建议。
    return AnswerResponse(
        session_id=req.session_id,                                  # 会话 ID
        interview_finished=state.get("interview_finished", False),  # 面试是否结束
        should_followup=state.get("should_followup", False),        # 是否触发追问
        question=state.get("current_question_text", ""),            # 下一题/追问题面
        question_index=state.get("current_question_idx", 0),        # 当前题目索引
        total_questions=len(plan),                                  # 题目总数
        difficulty=state.get("current_difficulty", "medium"),       # 当前难度
        final_report=state.get("final_report"),                     # 最终评估报告（结束时）
        study_plan=state.get("study_plan"),                         # 复习计划（结束时）
        github_recommendations=state.get("github_recommendations", []),  # GitHub 学习项目推荐
    )


# ── 触发技能 ──────────────────────────────────────────────────────────────────

# 注册 POST /interview/skill 接口（无固定响应模型，返回普通字典）。
@router.post("/skill")
async def use_skill(req: SkillRequest):
    """触发技能模块（quiz / teach / project / compare）"""
    # 读取当前会话状态。
    state = memory_manager.load_session(req.session_id)
    # 会话不存在则返回 404。
    if not state:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")

    # 取出工作流图。
    graph = _get_graph()

    # 设置意图为“使用技能”，并写入技能名与用户输入，驱动图进入技能分支。
    state["intent"]     = "use_skill"        # 意图：使用技能
    state["skill_name"] = req.skill_name     # 要触发的技能名称
    state["user_input"] = req.user_input     # 用户提供给技能的输入

    try:
        # 执行工作流以运行对应技能逻辑。
        state = graph.invoke(state)
    except Exception as e:
        # 技能执行失败：记录日志并返回 500。
        logger.error("skill 处理失败: {}", e)
        raise HTTPException(status_code=500, detail=f"技能调用失败: {e}")

    # 持久化更新后的状态。
    memory_manager.save_session(req.session_id, state)

    # 返回技能执行结果：包含会话 ID、技能名、智能体回复及技能内部状态。
    return {
        "session_id":  req.session_id,                  # 会话 ID
        "skill_name":  req.skill_name,                  # 本次触发的技能名
        "agent_reply": state.get("agent_reply", ""),    # 技能/智能体生成的回复文本
        "skill_state": state.get("skill_state", {}),    # 技能模块的最新内部状态
    }


# ── 获取报告 ──────────────────────────────────────────────────────────────────

# 注册 GET /interview/report/{session_id} 接口，响应体须符合 ReportResponse。
@router.get("/report/{session_id}", response_model=ReportResponse)
async def get_report(session_id: str):
    """获取已完成面试的评估报告和复习计划"""
    # 按会话 ID 读取状态。
    state = memory_manager.load_session(session_id)
    # 会话不存在则返回 404。
    if not state:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")

    # 取出最终报告；若尚未生成则说明面试未结束或报告仍在生成中。
    final_report = state.get("final_report")
    # 报告未就绪：返回 202（已接受、处理中），提示稍后再试。
    if not final_report:
        raise HTTPException(status_code=202, detail="面试尚未结束或报告生成中")

    # 报告已就绪：返回完整报告、复习计划与 GitHub 推荐。
    return ReportResponse(
        session_id=session_id,                                          # 会话 ID
        final_report=final_report,                                      # 最终评估报告
        study_plan=state.get("study_plan", {}),                         # 复习计划
        github_recommendations=state.get("github_recommendations", []), # GitHub 项目推荐
    )