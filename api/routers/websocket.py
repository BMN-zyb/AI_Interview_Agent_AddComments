"""
WebSocket 路由：/ws/{session_id}

消息协议：
  客户端->服务端:
    {"type":"start", "jd_text":"...", "resume_text":"...",
     "total_questions":5, "voice":"longxiaochun", "user_id":"web_user"}
    {"type":"answer",  "text":"用户回答"}
    {"type":"force_finish"}           - 强制结束面试生成报告
    {"type":"get_memory"}             - 主动拉取记忆数据
    {"type":"clear_long_memory"}      - 清除长期记忆薄弱点
    {"type":"get_rag"}                - 查看RAG检索结果
    {"type":"tts_speak", "text":"...", "voice":"..."} - 朗读指定文本
    {"type":"skill", "skill_name":"...", "user_input":"..."}
    {"type":"ping"}

  服务端->客户端:
    {"type":"question",  "text":"...", "index":1, "total":5,
                         "difficulty":"medium", "memory_snapshot":{...}}
    {"type":"followup",  "text":"...", "memory_snapshot":{...}}
    {"type":"finished",  "farewell":"...", "report":{},
                         "study_plan":{}, "github_recommendations":[],
                         "memory_snapshot":{...}}
    {"type":"skill_reply", "skill_name":"...", "text":"..."}
    {"type":"stt_result",  "text":"...", "message":""}
    {"type":"memory_data", "short_term":{...}, "long_term":{...}}
    {"type":"rag_data",    "rag_sources":[...], "rag_context":"...", "total":N}
    {"type":"toast",       "msg":"...", "level":"success|warning|error|info"}
    {"type":"tts_start"}  {"type":"tts_end"}
    {"type":"error",       "message":"..."}
    {"type":"pong"}

  服务端->客户端(二进制): TTS 音频数据块
"""
from __future__ import annotations

# 标准库 json：序列化/反序列化 WebSocket 文本消息（前后端约定为 JSON）。
import json
# 标准库 uuid：当客户端连接 /ws/new 时为其生成新的会话 ID。
import uuid
# 类型注解：标注消息/状态等结构的类型，提升可读性与静态检查能力。
from typing import Any, Dict, List, Optional

# FastAPI：WebSocket 路由器、WebSocket 连接对象与断开异常类型。
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
# loguru：日志库。
from loguru import logger

# 语音引擎：stt 负责语音转文字（识别用户语音），tts 负责文字转语音（朗读回复）。
from audio.stt import stt_engine
from audio.tts import tts_engine
# 记忆管理器：负责会话状态持久化与长期记忆（薄弱点）的读写。
from memory.memory_manager import memory_manager

# 创建 WebSocket 路由器（不加前缀），在文档中归入“WebSocket”分组。
router = APIRouter(tags=["WebSocket"])


def _get_graph():
    """惰性获取已编译的工作流图。

    通过函数内延迟导入打破与 orchestration.graph 之间的潜在循环依赖。

    返回:
        已编译、可 invoke 的工作流图对象。
    """
    # 延迟导入，避免模块加载期的循环依赖。
    from orchestration.graph import get_compiled_graph
    return get_compiled_graph()


# ── 基础发送 ──────────────────────────────────────────────────────────────────

async def _send_json(ws: WebSocket, data: Dict[str, Any]) -> bool:
    """安全发送 JSON

    将字典序列化为 JSON 文本并通过 WebSocket 发送；发送失败时不抛异常，
    仅记录告警并返回 False，便于上层判断连接是否仍可用。

    参数:
        ws: 目标 WebSocket 连接。
        data: 待发送的数据字典。
    返回:
        发送成功返回 True，失败返回 False。
    """
    try:
        # ensure_ascii=False 以保留中文等非 ASCII 字符的原始形态，避免被转义。
        await ws.send_text(json.dumps(data, ensure_ascii=False))
        return True
    except Exception as e:
        # 发送异常（通常是连接已断开）：记录告警并返回 False。
        logger.warning("WebSocket 发送失败: {}", e)
        return False


async def _send_tts(ws: WebSocket, text: str, voice: Optional[str] = None) -> None:
    """
    TTS 合成推流。
    无论是否有音频数据，都发 tts_start / tts_end，
    确保前端 TtsPlayer 指示器正确关闭。

    参数:
        ws: 目标 WebSocket 连接。
        text: 待朗读的文本。
        voice: 可选的音色名称。
    """
    # 先发 tts_start：通知前端开始播放，点亮“朗读中”指示器。
    await _send_json(ws, {"type": "tts_start"})

    # 文本为空：直接发 tts_end 收尾并返回（无需合成）。
    if not text or not text.strip():
        await _send_json(ws, {"type": "tts_end"})
        return

    # TTS 引擎不可用（如未配置 DASHSCOPE_API_KEY）：跳过合成，仅发 tts_end 收尾。
    if not tts_engine.available:
        logger.debug("TTS 不可用（DASHSCOPE_API_KEY 未配置），跳过合成")
        await _send_json(ws, {"type": "tts_end"})
        return

    try:
        # 统计已推送的音频块数量，便于日志排查。
        chunk_count = 0
        # 异步流式合成：逐块拿到音频字节并以二进制帧发送给前端边收边播。
        async for chunk in tts_engine.synthesize_stream(text, voice=voice):
            await ws.send_bytes(chunk)
            chunk_count += 1
        logger.debug("TTS 推流完成: {} 块, voice={}", chunk_count, voice)
    except Exception as e:
        # 合成/推流异常：记录错误（不向前端抛出，避免中断会话）。
        logger.error("TTS 推流异常: {}", e)
    finally:
        # 无论成功与否，都发 tts_end：确保前端结束播放状态、关闭指示器。
        await _send_json(ws, {"type": "tts_end"})


# ── State 辅助 ────────────────────────────────────────────────────────────────

def _safe_extract_qa_history(state: Dict) -> List[Dict]:
    """
    安全提取 qa_history，确保每条记录完全可 JSON 序列化。
    qa_history 格式: [{"question": str, "answer": str, "score": dict}]

    参数:
        state: 当前面试状态字典。
    返回:
        清洗后的问答历史列表，所有字段均为基础类型，可安全 JSON 序列化。
    """
    # 取出原始问答历史（缺失时为空列表）。
    raw = state.get("qa_history", [])
    # 收集清洗后的结果。
    result = []
    # 逐条遍历原始记录。
    for item in raw:
        # 非字典的脏数据直接跳过，保证结构稳定。
        if not isinstance(item, dict):
            continue
        # 取出该条的评分子结构。
        score = item.get("score", {})
        # 评分若非字典（脏数据），重置为空字典以便后续安全取值。
        if not isinstance(score, dict):
            score = {}
        # 将该条记录的字段强制转换为基础类型后追加，确保可 JSON 序列化。
        result.append({
            "question": str(item.get("question", "")),   # 题面（转为字符串）
            "answer":   str(item.get("answer", "")),      # 回答（转为字符串）
            "score": {
                # 四个维度评分统一转 int，缺失按 0。
                "correctness":     int(score.get("correctness", 0)),   # 正确性
                "depth":           int(score.get("depth", 0)),         # 深度
                "structure":       int(score.get("structure", 0)),     # 结构性
                "example":         int(score.get("example", 0)),       # 举例
                # 布尔类字段统一转 bool。
                "is_correct":      bool(score.get("is_correct", False)),       # 是否答对
                "followup_needed": bool(score.get("followup_needed", False)),  # 是否需要追问
                # 缺失要点列表：逐项转字符串，保证元素均为字符串。
                "key_missing":     [str(k) for k in score.get("key_missing", [])],
            },
        })
    return result


def _build_short_term_snapshot(state: Dict) -> Dict:
    """构建短期记忆快照，随每条 WS 消息透传给前端

    参数:
        state: 当前面试状态字典。
    返回:
        包含问答历史、当前进度、难度等关键信息的短期记忆快照字典。
    """
    return {
        # 清洗后的问答历史。
        "qa_history":           _safe_extract_qa_history(state),
        # 当前题目索引（转 int）。
        "current_question_idx": int(state.get("current_question_idx", 0)),
        # 当前难度（转 str）。
        "current_difficulty":   str(state.get("current_difficulty", "medium")),
        # 已产生的评分记录数量。
        "score_records_count":  len(state.get("score_records", [])),
        # 计划出题总数（转 int）。
        "total_questions":      int(state.get("total_questions", 0)),
        # 当前已知的长期薄弱点列表（拷贝为新 list，避免外部共享引用）。
        "long_term_weaknesses": list(state.get("long_term_weaknesses", [])),
    }


async def _get_fresh_long_term(user_id: str, fallback: list) -> list:
    """从 MySQL 获取最新长期记忆，失败时用 fallback

    参数:
        user_id: 用户标识。
        fallback: 获取失败或无结果时使用的回退列表。
    返回:
        最新的长期薄弱点列表，异常时返回 fallback。
    """
    try:
        # 从持久层查询该用户的长期薄弱点。
        result = memory_manager.get_weaknesses(user_id)
        # 查询到结果则使用之，None 表示无数据时退回 fallback。
        return result if result is not None else fallback
    except Exception:
        # 持久层异常（如 MySQL 不可用）：静默退回 fallback，避免影响主流程。
        return fallback


async def _send_memory_data(ws: WebSocket, state: Dict, user_id: str) -> None:
    """主动推送完整记忆数据给前端

    参数:
        ws: 目标 WebSocket 连接。
        state: 当前面试状态字典。
        user_id: 用户标识，用于拉取最新长期记忆。
    """
    # 拉取最新长期薄弱点；失败时回退到 state 中已有的副本。
    fresh_weaknesses = await _get_fresh_long_term(
        user_id, list(state.get("long_term_weaknesses", []))
    )
    # 构建短期记忆快照。
    snapshot = _build_short_term_snapshot(state)
    # 用最新结果覆盖快照中的长期薄弱点，保证前端拿到最新数据。
    snapshot["long_term_weaknesses"] = fresh_weaknesses
    # 推送 memory_data 消息：同时携带短期快照与长期记忆。
    await _send_json(ws, {
        "type":       "memory_data",                    # 消息类型
        "short_term": snapshot,                         # 短期记忆快照
        "long_term":  {"weaknesses": fresh_weaknesses}, # 长期记忆（薄弱点）
    })


# ── 业务处理函数 ──────────────────────────────────────────────────────────────

async def _handle_start(
    ws: WebSocket,
    data: Dict[str, Any],
    session_id: str,
    graph,
) -> Optional[Dict]:
    """处理 start 消息，初始化面试

    参数:
        ws: WebSocket 连接。
        data: 客户端 start 消息体（含 jd_text/resume_text 等）。
        session_id: 当前会话 ID。
        graph: 已编译的工作流图。
    返回:
        初始化并产出首题后的状态字典；若失败（JD 为空、生成失败等）返回 None。
    """
    # 从消息体中提取各字段并做基本清洗/默认值处理。
    jd_text         = data.get("jd_text", "").strip()       # 职位描述（去空白）
    resume_text     = data.get("resume_text", "").strip()   # 简历文本（去空白）
    total_questions = int(data.get("total_questions", 5))   # 计划题数，默认 5
    user_id         = data.get("user_id", "web_user")       # 用户标识，默认 web_user
    voice           = data.get("voice")                     # 朗读音色（可选）

    # JD 为必填：为空则回送 error 并终止启动。
    if not jd_text:
        await _send_json(ws, {"type": "error", "message": "JD 内容不能为空"})
        return None

    # 加载历史长期记忆
    # 拉取该用户的历史薄弱点，作为本场面试的先验上下文（失败回退空列表）。
    long_term_weaknesses = await _get_fresh_long_term(user_id, [])

    # 构造工作流初始状态（含语音设置 _voice 与历史长期记忆）。
    init_state = {
        "session_id":           session_id,         # 会话 ID
        "user_id":              user_id,            # 用户标识
        "jd_text":              jd_text,            # JD 原文
        "resume_text":          resume_text,        # 简历原文
        "intent":               "start_interview",  # 意图：启动面试
        "user_input":           "开始面试",          # 模拟用户输入
        "current_difficulty":   "medium",           # 初始难度
        "current_question_idx": 0,                  # 当前题目索引
        "qa_history":           [],                 # 问答历史
        "score_records":        [],                 # 评分记录
        "awaiting_answer":      False,              # 是否等待作答
        "awaiting_evaluation":  False,              # 是否等待评估
        "interview_finished":   False,              # 是否结束
        "should_followup":      False,              # 是否追问
        "followup_count":       0,                  # 追问次数
        "max_followup":         2,                  # 最大追问次数
        "force_finish":         False,              # 是否强制结束
        "skill_state":          {},                 # 技能状态
        "total_questions":      total_questions,    # 计划题数
        "_voice":               voice,              # 朗读音色（贯穿全程，供后续 TTS 使用）
        "long_term_weaknesses": long_term_weaknesses,  # 历史长期薄弱点
    }

    try:
        # 执行工作流：完成 JD/简历分析、RAG 检索、出题计划并生成首题。
        state = graph.invoke(init_state)
    except Exception as e:
        # 启动失败：记录日志并回送 error，返回 None 终止。
        logger.error("面试启动失败: {}", e)
        await _send_json(ws, {"type": "error", "message": f"面试启动失败: {e}"})
        return None

    # 保持长期记忆
    # 若工作流未回填长期记忆，则用启动时拉取的历史值补上，避免前端丢失该信息。
    if not state.get("long_term_weaknesses"):
        state["long_term_weaknesses"] = long_term_weaknesses

    # 持久化初始状态。
    memory_manager.save_session(session_id, state)

    # 取出首题文本。
    question = state.get("current_question_text", "")
    # 首题为空：回送 error 并终止。
    if not question:
        await _send_json(ws, {"type": "error", "message": "题目生成失败"})
        return None

    # 取题目计划用于计算总题数。
    plan = state.get("question_plan", [])
    # 向前端推送 question 消息：携带题面、序号、总数、难度、职位标题与短期记忆快照。
    await _send_json(ws, {
        "type":            "question",                                       # 消息类型
        "text":            question,                                         # 题面
        "index":           int(state.get("current_question_idx", 0)) + 1,    # 题号（1 起，便于展示）
        "total":           len(plan),                                        # 总题数
        "difficulty":      state.get("current_difficulty", "medium"),        # 难度
        "jd_title":        state.get("jd_parsed", {}).get("title", ""),      # 职位标题
        "memory_snapshot": _build_short_term_snapshot(state),                # 短期记忆快照
    })
    # 朗读首题（按指定音色）。
    await _send_tts(ws, question, voice=voice)
    # 返回最新状态，供主循环更新。
    return state


async def _handle_answer(
    ws: WebSocket,
    answer_text: str,
    state: Dict,
    graph,
) -> Dict:
    """处理用户回答

    驱动工作流评估回答，并据结果向前端推送三类消息之一：
    finished（面试结束）/ followup（追问）/ question（下一题）。

    参数:
        ws: WebSocket 连接。
        answer_text: 用户回答文本。
        state: 当前面试状态。
        graph: 已编译的工作流图。
    返回:
        更新后的状态字典。
    """
    # 从状态中取出会话 ID 与朗读音色。
    session_id = state.get("session_id", "")
    voice      = state.get("_voice")

    # 写入回答并切换意图/标志位，驱动图进入“评估回答”分支。
    state["user_input"]          = answer_text       # 本轮用户输入
    state["last_user_answer"]    = answer_text       # 记录最近回答
    state["intent"]              = "answer_question"  # 意图：回答问题
    state["awaiting_evaluation"] = True              # 需要评估
    state["awaiting_answer"]     = False              # 不再等待作答

    try:
        # 执行工作流：评估并决定后续走向（结束/追问/下一题）。
        state = graph.invoke(state)
    except Exception as e:
        # 处理失败：回送 error 并返回当前状态。
        logger.error("回答处理失败: {}", e)
        await _send_json(ws, {"type": "error", "message": f"处理失败: {e}"})
        return state

    # 持久化更新后的状态。
    memory_manager.save_session(session_id, state)
    # 预构建短期记忆快照，随后续消息一并下发。
    snapshot = _build_short_term_snapshot(state)

    # ── 面试结束 ──────────────────────────────────────────────────────────
    # 工作流标记面试结束：推送 finished 消息（报告 + 复习计划 + 推荐）。
    if bool(state.get("interview_finished", False)):
        # ★ 如果 interviewer 没有生成结束语，主动生成一个
        # 取出面试官生成的结束语；若缺失则使用兜底文案，保证有结束语朗读。
        farewell = state.get("agent_reply", "")
        if not farewell:
            farewell = "感谢你参与本次模拟面试！报告已生成，祝你面试顺利！"

        # 拉取最新长期薄弱点（结束时回写记忆后的最新值），失败回退本地副本。
        fresh_w = await _get_fresh_long_term(
            state.get("user_id", "web_user"),
            list(state.get("long_term_weaknesses", []))
        )
        # 用最新值覆盖快照中的长期薄弱点。
        snapshot["long_term_weaknesses"] = fresh_w

        # 推送结束消息：结束语、最终报告、复习计划、GitHub 推荐与记忆快照。
        await _send_json(ws, {
            "type":                   "finished",                                # 消息类型
            "farewell":               farewell,                                  # 结束语
            "report":                 state.get("final_report", {}),             # 最终报告
            "study_plan":             state.get("study_plan", {}),               # 复习计划
            "github_recommendations": state.get("github_recommendations", []),   # GitHub 推荐
            "memory_snapshot":        snapshot,                                  # 记忆快照
        })
        # 朗读结束语。
        await _send_tts(ws, farewell, voice=voice)
        return state

    # ── 追问 ──────────────────────────────────────────────────────────────
    # 工作流判定需要追问：推送 followup 消息（追问题面）。
    if bool(state.get("should_followup", False)):
        # 追问题面即当前题目文本（已被更新为追问）。
        followup_q = state.get("current_question_text", "")
        await _send_json(ws, {
            "type":            "followup",      # 消息类型：追问
            "text":            followup_q,      # 追问题面
            "memory_snapshot": snapshot,        # 记忆快照
        })
        # 朗读追问。
        await _send_tts(ws, followup_q, voice=voice)
        return state

    # ── 下一题 ────────────────────────────────────────────────────────────
    # 既未结束也无需追问：推送下一题。
    next_q = state.get("current_question_text", "")  # 下一题题面
    plan   = state.get("question_plan", [])          # 题目计划（用于总数）
    await _send_json(ws, {
        "type":            "question",                                    # 消息类型
        "text":            next_q,                                        # 题面
        "index":           int(state.get("current_question_idx", 0)) + 1, # 题号（1 起）
        "total":           len(plan),                                     # 总题数
        "difficulty":      state.get("current_difficulty", "medium"),     # 难度
        "memory_snapshot": snapshot,                                      # 记忆快照
    })
    # 朗读下一题。
    await _send_tts(ws, next_q, voice=voice)
    return state


async def _handle_force_finish(
    ws: WebSocket,
    state: Dict,
    graph,
) -> Dict:
    """强制结束面试，直接生成报告（跳过剩余题目）

    参数:
        ws: WebSocket 连接。
        state: 当前面试状态。
        graph: 已编译的工作流图（此处不走图路由，仅为签名一致而保留）。
    返回:
        生成报告后的状态字典。
    """
    # 取出会话 ID 与朗读音色。
    session_id = state.get("session_id", "")
    voice      = state.get("_voice")

    logger.info("强制结束面试: session={}", session_id)

    # 标记结束
    # 设置结束相关标志位：标记面试结束、强制结束，并取消待评估状态。
    state["interview_finished"] = True
    state["force_finish"]       = True
    state["awaiting_evaluation"] = False

    # 如果当前题未作答，补一条空记录
    # 取当前题面，若其尚未出现在评分记录中，则补一条“未作答”记录以保证报告完整。
    cur_q = state.get("current_question_text", "")
    if cur_q and not any(
        r.get("question") == cur_q
        for r in state.get("score_records", [])
    ):
        # 向评分记录追加一条全 0、标记未作答的记录。
        state.setdefault("score_records", []).append({
            "question": cur_q,                              # 题面
            "answer":   "（候选人主动结束，未作答）",          # 占位回答
            "score": {
                "correctness": 0, "depth": 0, "structure": 0,
                "example": 0, "is_correct": False,
                "followup_needed": False, "key_missing": [],
            },
        })
        # 同步向问答历史追加该条（新建列表拼接，避免就地修改共享引用）。
        state["qa_history"] = state.get("qa_history", []) + [{
            "question": cur_q,
            "answer":   "（候选人主动结束，未作答）",
            "score":    {"is_correct": False},
        }]

    # 直接调节点函数，跳过 graph 路由
    # 强制结束场景无需经过图的路由判断，直接顺序调用相关节点函数生成产物。
    try:
        # 延迟导入所需节点函数，避免循环依赖。
        from orchestration.nodes import (
            node_generate_report,  # 生成评估报告
            node_study_plan,       # 生成复习计划
            node_save_memory,      # 回写长期记忆
        )
        # 依次执行：先出报告，再出复习计划，最后保存记忆。
        state = node_generate_report(state)
        state = node_study_plan(state)
        state = node_save_memory(state)
    except Exception as e:
        # 生成失败：回送 error 并返回当前状态。
        logger.error("强制结束生成报告失败: {}", e)
        await _send_json(ws, {"type": "error", "message": f"生成报告失败: {e}"})
        return state

    # 持久化状态。
    memory_manager.save_session(session_id, state)

    # 拉取最新长期薄弱点（保存记忆后的最新值），失败回退本地副本。
    fresh_w = await _get_fresh_long_term(
        state.get("user_id", "web_user"),
        list(state.get("long_term_weaknesses", []))
    )
    # 构建快照并用最新长期薄弱点覆盖。
    snapshot = _build_short_term_snapshot(state)
    snapshot["long_term_weaknesses"] = fresh_w

    # 固定的强制结束结束语。
    farewell = "面试已结束，感谢你的参与！评估报告已生成，请查看。"
    # 推送 finished 消息（与正常结束一致：报告 + 复习计划 + 推荐 + 快照）。
    await _send_json(ws, {
        "type":                   "finished",                                # 消息类型
        "farewell":               farewell,                                  # 结束语
        "report":                 state.get("final_report", {}),             # 最终报告
        "study_plan":             state.get("study_plan", {}),               # 复习计划
        "github_recommendations": state.get("github_recommendations", []),   # GitHub 推荐
        "memory_snapshot":        snapshot,                                  # 记忆快照
    })
    # 朗读结束语。
    await _send_tts(ws, farewell, voice=voice)
    return state


async def _handle_skill(
    ws: WebSocket,
    data: Dict[str, Any],
    state: Dict,
    graph,
) -> Dict:
    """处理技能调用

    参数:
        ws: WebSocket 连接。
        data: 客户端 skill 消息体（含 skill_name/user_input）。
        state: 当前面试状态。
        graph: 已编译的工作流图。
    返回:
        更新后的状态字典（仅回写 skill_state，不污染主面试流程字段）。
    """
    # 取会话 ID、技能名（默认 quiz）、用户输入与朗读音色。
    session_id = state.get("session_id", "")
    skill_name = data.get("skill_name", "quiz")
    user_input = data.get("user_input", "")
    voice      = state.get("_voice")

    # 基于当前状态拷贝出一份技能专用状态，避免技能调用直接改写主面试状态字段。
    skill_state             = dict(state)
    skill_state["intent"]     = "use_skill"   # 意图：使用技能
    skill_state["skill_name"] = skill_name    # 技能名
    skill_state["user_input"] = user_input    # 技能输入

    try:
        # 在技能专用状态上执行工作流。
        result = graph.invoke(skill_state)
    except Exception as e:
        # 技能调用失败：回送 error 并返回原状态（不改动主流程）。
        await _send_json(ws, {"type": "error", "message": f"技能调用失败: {e}"})
        return state

    # 取出技能回复文本。
    reply = result.get("agent_reply", "")
    # 推送 skill_reply 消息：包含技能名与回复文本。
    await _send_json(ws, {
        "type":       "skill_reply",   # 消息类型
        "skill_name": skill_name,      # 技能名
        "text":       reply,           # 技能回复
    })
    # 朗读技能回复。
    await _send_tts(ws, reply, voice=voice)

    # 仅将技能内部状态回写主状态，其余主面试字段保持不变。
    state["skill_state"] = result.get("skill_state", {})
    # 持久化主状态。
    memory_manager.save_session(session_id, state)
    return state


# ── WebSocket 主处理器 ────────────────────────────────────────────────────────

# 注册 WebSocket 端点 /ws/{session_id}：session_id 为路径参数（可为 "new"）。
@router.websocket("/ws/{session_id}")
async def websocket_endpoint(ws: WebSocket, session_id: str):
    """WebSocket 主处理器：接受连接并进入消息循环，按消息类型分派到各处理函数。

    参数:
        ws: 客户端 WebSocket 连接。
        session_id: 路径中的会话 ID；传 "new" 时由服务端新建并回告客户端。
    """
    # 接受 WebSocket 握手，建立连接。
    await ws.accept()

    # 若客户端使用占位符 "new"，服务端生成新会话 ID 并回告，便于后续复用。
    if session_id == "new":
        session_id = str(uuid.uuid4())
        await _send_json(ws, {"type": "session_id", "session_id": session_id})

    logger.info("WebSocket 连接建立: {}", session_id)

    # 取出工作流图。
    graph      = _get_graph()
    # 尝试加载已有会话状态；无则以空字典起步（等待 start 初始化）。
    state: Dict = memory_manager.load_session(session_id) or {}
    # 连接存活标志，控制消息循环。
    _alive     = True

    try:
        # 主消息循环：持续接收客户端消息直至断开或异常。
        while _alive:
            try:
                # 接收一帧原始消息（可能含 text 或 bytes）。
                message = await ws.receive()
            except Exception:
                # 接收异常（通常是连接断开）：跳出循环。
                break

            # 连接断开
            # 收到断开事件：置存活标志为假并退出循环。
            if message.get("type") == "websocket.disconnect":
                _alive = False
                break

            # ── 二进制音频（STT）─────────────────────────────────────────
            # 若帧中含二进制音频数据，走语音识别分支。
            if "bytes" in message and message["bytes"]:
                # 取出音频字节并记录长度。
                audio_bytes = message["bytes"]
                logger.debug("收到音频帧: {} bytes", len(audio_bytes))
                # ★ 只识别，结果回传给前端填入输入框，不自动提交
                # 调用 STT 将音频转写为文本（is_wav=False：非 WAV 容器的原始数据）。
                text = stt_engine.transcribe_bytes(audio_bytes, is_wav=False)
                # 回送识别结果；未识别到内容时附带提示文案。
                await _send_json(ws, {
                    "type":    "stt_result",                                 # 消息类型
                    "text":    text,                                         # 识别文本
                    "message": "" if text else "未识别到语音，请重试",          # 提示
                })
                # 该帧处理完毕，继续下一轮接收。
                continue

            # ── 文本 JSON 消息 ────────────────────────────────────────────
            # 取出文本负载；为空则忽略本帧。
            raw_text = message.get("text", "")
            if not raw_text:
                continue

            try:
                # 解析 JSON 文本为字典。
                data = json.loads(raw_text)
            except json.JSONDecodeError:
                # 非法 JSON：回送 error 并继续。
                await _send_json(ws, {"type": "error", "message": "JSON 格式错误"})
                continue

            # 取出消息类型，作为后续分派依据。
            msg_type = data.get("type", "")

            # ping/pong 心跳
            # 心跳探测：收到 ping 立即回 pong，用于保活与连通性检测。
            if msg_type == "ping":
                await _send_json(ws, {"type": "pong"})

            # 启动面试
            # start：初始化面试；成功（返回非 None）时更新本地 state。
            elif msg_type == "start":
                result = await _handle_start(ws, data, session_id, graph)
                if result is not None:
                    state = result

            # 提交回答
            # answer：提交回答。需先有 state（已 start），且回答非空。
            elif msg_type == "answer":
                # 尚未开始面试：提示先发 start。
                if not state:
                    await _send_json(ws, {
                        "type": "error", "message": "请先发送 start 消息"
                    })
                    continue
                # 取回答文本并去空白。
                answer_text = data.get("text", "").strip()
                # 回答为空：提示不能为空。
                if not answer_text:
                    await _send_json(ws, {
                        "type": "error", "message": "回答不能为空"
                    })
                    continue
                # 交由回答处理函数推进流程并更新 state。
                state = await _handle_answer(ws, answer_text, state, graph)

            # 强制结束面试
            # force_finish：跳过剩余题目直接出报告。需先有 state。
            elif msg_type == "force_finish":
                if not state:
                    await _send_json(ws, {
                        "type": "error", "message": "请先发送 start 消息"
                    })
                    continue
                state = await _handle_force_finish(ws, state, graph)

            # 主动拉取记忆数据
            # get_memory：客户端主动请求记忆数据。
            elif msg_type == "get_memory":
                # 确定 user_id：优先用 state 中的，否则取消息体（兼容未开始面试的场景）。
                user_id = (state.get("user_id", "web_user") if state
                           else data.get("user_id", "web_user"))
                # 已有会话：推送完整短期 + 长期记忆。
                if state:
                    await _send_memory_data(ws, state, user_id)
                else:
                    # 无会话：仅拉取长期薄弱点并以最小结构回送。
                    weaknesses = await _get_fresh_long_term(user_id, [])
                    await _send_json(ws, {
                        "type":       "memory_data",
                        "short_term": {
                            "qa_history": [],                       # 无短期问答历史
                            "long_term_weaknesses": weaknesses,     # 长期薄弱点
                        },
                        "long_term": {"weaknesses": weaknesses},
                    })

            # 清除长期记忆
            # clear_long_memory：清除该用户的长期薄弱点。
            elif msg_type == "clear_long_memory":
                # 确定 user_id（来源同 get_memory）。
                user_id = (state.get("user_id", "web_user") if state
                           else data.get("user_id", "web_user"))
                # 调持久层清除，返回是否成功。
                ok = memory_manager.clear_weaknesses(user_id)
                if ok:
                    # 同步更新本地 state
                    # 清除成功：本地 state 中的长期薄弱点也一并清空，保持一致。
                    if state:
                        state["long_term_weaknesses"] = []
                    # 推送更新后的记忆数据
                    # 构建快照（无 state 则空字典）并将长期薄弱点置空后回送。
                    snapshot = _build_short_term_snapshot(state) if state else {}
                    snapshot["long_term_weaknesses"] = []
                    await _send_json(ws, {
                        "type":       "memory_data",
                        "short_term": snapshot,
                        "long_term":  {"weaknesses": []},
                    })
                    # 额外回送一条成功提示（前端以 toast 展示）。
                    await _send_json(ws, {
                        "type":  "toast",
                        "msg":   "长期记忆已清除 ✅",
                        "level": "success",
                    })
                else:
                    # 清除失败（如 MySQL 不可用）：回送 error。
                    await _send_json(ws, {
                        "type":    "error",
                        "message": "清除失败，MySQL 可能不可用",
                    })

            # 查看 RAG 检索结果
            # get_rag：返回本场面试 RAG 检索到的来源与上下文，供前端查看。
            elif msg_type == "get_rag":
                # 未开始面试则无检索结果：提示先开始。
                if not state:
                    await _send_json(ws, {
                        "type": "error", "message": "请先开始面试"
                    })
                    continue
                # 取出 RAG 来源列表与拼接上下文。
                rag_sources = state.get("rag_sources", [])
                rag_context = state.get("rag_context", "")
                # 回送 rag_data：来源截断前 10 条、上下文截断前 3000 字符以控制体积；total 为完整条数。
                await _send_json(ws, {
                    "type":        "rag_data",
                    "rag_sources": rag_sources[:10],
                    "rag_context": rag_context[:3000],
                    "total":       len(rag_sources),
                })

            # 手动朗读指定文本
            # tts_speak：按需朗读任意文本（如重播题目）。
            elif msg_type == "tts_speak":
                # 取待朗读文本并去空白。
                text_to_speak  = data.get("text", "").strip()
                # 音色优先用消息体指定，否则回退到 state 中的全局音色。
                voice_override = (data.get("voice") or
                                  (state.get("_voice") if state else None))
                # 记录一条信息日志，便于排查 TTS 是否可用及参数。
                logger.info(
                    "tts_speak: available={}, text_len={}, voice={}",
                    tts_engine.available,
                    len(text_to_speak),
                    voice_override,
                )
                # 执行朗读推流。
                await _send_tts(ws, text_to_speak, voice=voice_override)

            # 技能调用
            # skill：触发技能模块。需先有 state。
            elif msg_type == "skill":
                if not state:
                    await _send_json(ws, {
                        "type": "error", "message": "请先发送 start 消息"
                    })
                    continue
                state = await _handle_skill(ws, data, state, graph)

            else:
                # 未识别的消息类型：回送 error 并附带原类型，便于前端定位。
                await _send_json(ws, {
                    "type":    "error",
                    "message": f"未知消息类型: {msg_type}",
                })

    except WebSocketDisconnect:
        # 客户端正常断开：置存活标志为假并记录日志。
        _alive = False
        logger.info("WebSocket 断开: {}", session_id)
    except Exception as e:
        # 其它未预期异常：终止循环并记录错误。
        _alive = False
        logger.error("WebSocket 异常: {} {}", session_id, e)
    finally:
        # 无论如何退出：若存在状态则最后再持久化一次，避免数据丢失。
        if state:
            memory_manager.save_session(session_id, state)
        logger.info("WebSocket 连接关闭: {}", session_id)