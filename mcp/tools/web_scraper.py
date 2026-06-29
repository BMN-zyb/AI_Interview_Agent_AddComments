"""
WebSocket 路由：/ws/{session_id}
"""
# 启用延迟注解求值，简化类型注解并避免前向引用问题。
from __future__ import annotations

# 标准库 json：用于解析前端发来的文本消息与序列化下行 JSON。
import json
# 标准库 uuid：当客户端使用 "new" 时生成唯一会话 ID。
import uuid
# 类型注解工具：标注函数参数与返回值类型。
from typing import Any, Dict, Optional

# FastAPI 提供的 WebSocket 路由器与连接相关类型/异常。
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
# loguru 的 logger：统一日志输出。
from loguru import logger

# 语音转文字（STT）引擎：将前端上行音频帧转写为文本。
from audio.stt import stt_engine
# 文字转语音（TTS）引擎：将面试官回复合成为音频流下发。
from audio.tts import tts_engine
# 记忆管理器：负责会话状态的加载与持久化。
from memory.memory_manager import memory_manager

# 创建 WebSocket 路由器，并打上 "WebSocket" 标签便于在 API 文档中归类。
router = APIRouter(tags=["WebSocket"])


def _get_graph():
    """延迟获取已编译的对话编排图（LangGraph）。

    采用函数内导入以打破模块间循环依赖，并延后图的构建时机。

    返回:
        已编译、可直接 invoke 的编排图对象。
    """
    # 在函数内导入，避免模块加载期的循环依赖。
    from orchestration.graph import get_compiled_graph
    # 返回编译好的编排图实例。
    return get_compiled_graph()


async def _send_json(ws: WebSocket, data: Dict[str, Any]) -> bool:
    """安全发送 JSON，返回是否成功

    参数:
        ws: 目标 WebSocket 连接。
        data: 待发送的数据字典。
    返回:
        发送成功返回 True，发生异常返回 False。
    """
    # 发送过程可能因连接已断开而抛异常，因此整体包裹 try。
    try:
        # 序列化为 JSON 文本发送；ensure_ascii=False 以保留中文等非 ASCII 字符。
        await ws.send_text(json.dumps(data, ensure_ascii=False))
        # 发送成功。
        return True
    except Exception as e:
        # 发送失败（通常是连接已关闭）：记录告警并返回 False，由调用方决定后续处理。
        logger.warning("WebSocket 发送失败: {}", e)
        return False


async def _send_tts(ws: WebSocket, text: str, voice: Optional[str] = None) -> None:
    """TTS 合成并推流

    参数:
        ws: 目标 WebSocket 连接。
        text: 需要合成为语音的文本。
        voice: 可选的音色标识。
    返回:
        无（音频以二进制帧形式直接推送给客户端）。
    """
    # 文本为空或 TTS 引擎不可用时直接跳过，避免无意义的合成与下发。
    if not text.strip() or not tts_engine.available:
        return
    # 先发送 tts_start 信号，提示前端开始接收音频帧。
    await _send_json(ws, {"type": "tts_start"})
    # 合成与推流过程包裹 try，任一异常不影响后续的 tts_end 通知。
    try:
        # 以流式方式逐块合成音频。
        async for chunk in tts_engine.synthesize_stream(text, voice=voice):
            # 将每个音频块以二进制帧发送给前端。
            await ws.send_bytes(chunk)
    except Exception as e:
        # 合成/推流异常：记录错误，但仍走 finally 通知前端结束。
        logger.error("TTS 推流异常: {}", e)
    finally:
        # 无论成功与否，都发送 tts_end 信号，告知前端本段语音结束。
        await _send_json(ws, {"type": "tts_end"})


def _build_short_term_snapshot(state: Dict) -> Dict:
    """
    ★ 从 state 中提取短期记忆快照，透传给前端记忆面板
    包含：qa_history、当前题目索引、难度、score_records

    参数:
        state: 当前会话的完整状态字典。
    返回:
        精简后的短期记忆快照字典，用于前端展示记忆面板。
    """
    # 取出问答历史（无则为空列表）。
    qa_history = state.get("qa_history", [])
    # 组装并返回前端记忆面板所需的关键字段子集。
    return {
        "qa_history":            qa_history,                                  # 问答历史
        "current_question_idx":  state.get("current_question_idx", 0),       # 当前题目索引
        "current_difficulty":    state.get("current_difficulty", "medium"),  # 当前难度
        "score_records":         state.get("score_records", []),             # 评分记录
        "total_questions":       state.get("total_questions", 0),            # 题目总数
        "long_term_weaknesses":  state.get("long_term_weaknesses", []),      # 长期薄弱项
    }


async def _handle_start(
    ws: WebSocket,
    data: Dict[str, Any],
    session_id: str,
    graph,
) -> Optional[Dict]:
    """处理 start 消息：初始化面试并下发首道题目。

    参数:
        ws: 当前 WebSocket 连接。
        data: 前端发来的启动数据（含 JD、简历、题目数等）。
        session_id: 会话 ID。
        graph: 已编译的编排图。
    返回:
        初始化并执行一轮后的会话状态字典；失败时返回 None。
    """
    # 读取并清洗职位描述（JD）文本。
    jd_text         = data.get("jd_text", "").strip()
    # 读取并清洗候选人简历文本。
    resume_text     = data.get("resume_text", "").strip()
    # 读取计划的题目总数（默认 5），转为整数。
    total_questions = int(data.get("total_questions", 5))
    # 读取用户标识（默认 web_user）。
    user_id         = data.get("user_id", "web_user")
    # 读取可选的 TTS 音色设置。
    voice           = data.get("voice")

    # JD 是面试生成的必要输入，缺失则回送错误并终止本次启动。
    if not jd_text:
        await _send_json(ws, {"type": "error", "message": "JD 内容不能为空"})
        return None

    # 构造编排图所需的初始状态字典，集中设置一次面试的全部初值。
    init_state = {
        "session_id":           session_id,        # 会话 ID
        "user_id":              user_id,           # 用户 ID
        "jd_text":              jd_text,           # JD 原文
        "resume_text":          resume_text,       # 简历原文
        "intent":               "start_interview", # 意图：开始面试
        "user_input":           "开始面试",         # 初始用户输入文本
        "current_difficulty":   "medium",          # 初始难度：中等
        "current_question_idx": 0,                 # 当前题目索引从 0 开始
        "qa_history":           [],                # 问答历史，初始为空
        "score_records":        [],                # 评分记录，初始为空
        "awaiting_answer":      False,             # 是否在等待用户作答
        "awaiting_evaluation":  False,             # 是否在等待评估
        "interview_finished":   False,             # 面试是否结束
        "should_followup":      False,             # 是否需要追问
        "followup_count":       0,                 # 已追问次数
        "max_followup":         2,                 # 单题最大追问次数
        "force_finish":         False,             # 是否强制结束
        "skill_state":          {},                # 技能子状态，初始为空
        "total_questions":      total_questions,   # 题目总数
        "_voice":               voice,             # 透传音色（下划线前缀表内部字段）
    }

    # 调用编排图执行初始化流程；异常时回送错误并终止。
    try:
        # 同步 invoke 编排图，得到推进一步后的状态。
        state = graph.invoke(init_state)
    except Exception as e:
        # 启动失败：记录错误并通知前端。
        logger.error("面试启动失败: {}", e)
        await _send_json(ws, {"type": "error", "message": f"面试启动失败: {e}"})
        return None

    # 将启动后的状态持久化，便于断线重连或后续轮次复用。
    memory_manager.save_session(session_id, state)

    # 取出生成的首道题目文本。
    question = state.get("current_question_text", "")
    # 题目为空说明生成失败，回送错误并终止。
    if not question:
        await _send_json(ws, {"type": "error", "message": "题目生成失败"})
        return None

    # 取出题目计划列表，用于计算题目总数。
    plan = state.get("question_plan", [])
    # 向前端下发首道题目及相关元信息。
    await _send_json(ws, {
        "type":           "question",                                   # 消息类型：题目
        "text":           question,                                     # 题目文本
        "index":          state.get("current_question_idx", 0) + 1,     # 题号（从 1 计数展示）
        "total":          len(plan),                                    # 题目总数
        "difficulty":     state.get("current_difficulty", "medium"),    # 当前难度
        "jd_title":       state.get("jd_parsed", {}).get("title", ""),  # 解析出的职位标题
        # ★ 透传短期记忆快照
        "memory_snapshot": _build_short_term_snapshot(state),           # 短期记忆快照
    })
    # 将首道题目合成为语音并推流给前端。
    await _send_tts(ws, question, voice=voice)
    # 返回当前会话状态，供主循环保存与后续轮次使用。
    return state


async def _handle_answer(
    ws: WebSocket,
    answer_text: str,
    state: Dict,
    graph,
) -> Dict:
    """处理 answer 消息：提交用户回答并根据图的输出分支（结束/追问/下一题）。

    参数:
        ws: 当前 WebSocket 连接。
        answer_text: 用户本轮回答文本。
        state: 当前会话状态。
        graph: 已编译的编排图。
    返回:
        推进后的会话状态字典。
    """
    # 从状态中取出会话 ID。
    session_id = state.get("session_id", "")
    # 取出之前透传保存的音色设置。
    voice      = state.get("_voice")

    # 将用户回答写入多个状态字段，供编排图各节点读取。
    state["user_input"]          = answer_text   # 通用用户输入
    state["last_user_answer"]    = answer_text   # 记录最近一次回答
    state["intent"]              = "answer_question"  # 意图：回答问题
    state["awaiting_evaluation"] = True          # 标记进入待评估
    state["awaiting_answer"]     = False         # 不再等待作答

    # 调用编排图处理本轮回答；异常时回送错误并返回当前状态。
    try:
        # 同步推进编排图，得到处理后的新状态。
        state = graph.invoke(state)
    except Exception as e:
        # 回答处理失败：记录并通知前端。
        logger.error("回答处理失败: {}", e)
        await _send_json(ws, {"type": "error", "message": f"处理失败: {e}"})
        return state

    # 持久化最新状态。
    memory_manager.save_session(session_id, state)

    # ── 面试结束 ──────────────────────────────────────────────────────────
    # 分支一：编排图判定面试已结束，则下发结业信息与报告。
    if state.get("interview_finished", False):
        # 取出结束语（无则用默认致谢语）。
        farewell = state.get("agent_reply", "感谢参与本次模拟面试！")
        # 下发结束消息，附带最终报告、学习计划、GitHub 推荐与记忆快照。
        await _send_json(ws, {
            "type":                   "finished",                            # 消息类型：结束
            "farewell":               farewell,                              # 结束语
            "report":                 state.get("final_report", {}),         # 最终评估报告
            "study_plan":             state.get("study_plan", {}),           # 学习计划
            "github_recommendations": state.get("github_recommendations", []),  # GitHub 仓库推荐
            # ★ 透传完整记忆快照（含 qa_history）
            "memory_snapshot":        _build_short_term_snapshot(state),     # 记忆快照
            "long_term_weaknesses":   state.get("long_term_weaknesses", []), # 长期薄弱项
        })
        # 若有结束语则合成语音播报。
        if farewell:
            await _send_tts(ws, farewell, voice=voice)
        # 面试结束，返回最终状态。
        return state

    # ── 追问 ──────────────────────────────────────────────────────────────
    # 分支二：需要对当前题目追问，则下发追问问题。
    if state.get("should_followup", False):
        # 取出追问问题文本（复用当前题目字段）。
        followup_q = state.get("current_question_text", "")
        # 下发追问消息及记忆快照。
        await _send_json(ws, {
            "type":            "followup",                       # 消息类型：追问
            "text":            followup_q,                       # 追问文本
            # ★ 透传记忆快照
            "memory_snapshot": _build_short_term_snapshot(state),  # 记忆快照
        })
        # 合成追问语音并推流。
        await _send_tts(ws, followup_q, voice=voice)
        # 返回当前状态，等待用户回答追问。
        return state

    # ── 下一题 ────────────────────────────────────────────────────────────
    # 分支三：既未结束也无需追问，则进入并下发下一道题目。
    next_q = state.get("current_question_text", "")
    # 取出题目计划用于计算总数。
    plan   = state.get("question_plan", [])
    # 下发下一题及其元信息。
    await _send_json(ws, {
        "type":            "question",                                # 消息类型：题目
        "text":            next_q,                                    # 题目文本
        "index":           state.get("current_question_idx", 0) + 1,  # 题号（从 1 展示）
        "total":           len(plan),                                 # 题目总数
        "difficulty":      state.get("current_difficulty", "medium"), # 当前难度
        # ★ 透传记忆快照
        "memory_snapshot": _build_short_term_snapshot(state),         # 记忆快照
    })
    # 合成下一题语音并推流。
    await _send_tts(ws, next_q, voice=voice)
    # 返回推进后的状态。
    return state


async def _handle_skill(
    ws: WebSocket,
    data: Dict[str, Any],
    state: Dict,
    graph,
) -> Dict:
    """处理 skill 消息：在不影响主面试状态的前提下调用某项技能（如刷题/小测）。

    参数:
        ws: 当前 WebSocket 连接。
        data: 前端发来的技能调用数据（技能名、用户输入等）。
        state: 当前会话状态。
        graph: 已编译的编排图。
    返回:
        更新了技能子状态后的会话状态字典。
    """
    # 取出会话 ID。
    session_id = state.get("session_id", "")
    # 取出要调用的技能名（默认 quiz）。
    skill_name = data.get("skill_name", "quiz")
    # 取出用户为本次技能提供的输入。
    user_input = data.get("user_input", "")
    # 取出音色设置。
    voice      = state.get("_voice")

    # 复制一份状态用于技能调用，避免污染主面试状态。
    skill_state             = dict(state)
    skill_state["intent"]     = "use_skill"   # 意图：使用技能
    skill_state["skill_name"] = skill_name    # 目标技能名
    skill_state["user_input"] = user_input    # 技能输入

    # 调用编排图执行技能；异常时回送错误并返回原状态。
    try:
        # 在副本状态上推进编排图，得到技能执行结果。
        result = graph.invoke(skill_state)
    except Exception as e:
        # 技能调用失败：通知前端，并返回未受影响的原状态。
        await _send_json(ws, {"type": "error", "message": f"技能调用失败: {e}"})
        return state

    # 取出技能回复文本。
    reply = result.get("agent_reply", "")
    # 下发技能回复消息。
    await _send_json(ws, {
        "type":       "skill_reply",  # 消息类型：技能回复
        "skill_name": skill_name,     # 技能名
        "text":       reply,          # 回复文本
    })
    # 合成技能回复语音并推流。
    await _send_tts(ws, reply, voice=voice)

    # 仅把技能子状态回写到主状态，保持主面试流程其余字段不变。
    state["skill_state"] = result.get("skill_state", {})
    # 持久化更新后的状态。
    memory_manager.save_session(session_id, state)
    # 返回更新后的状态。
    return state


# ── WebSocket 主处理器 ────────────────────────────────────────────────────────

# 注册 WebSocket 端点，路径参数 session_id 用于标识/恢复一次面试会话。
@router.websocket("/ws/{session_id}")
async def websocket_endpoint(ws: WebSocket, session_id: str):
    """WebSocket 主入口：建立连接并循环分发各类消息（ping/start/answer/skill）。

    参数:
        ws: 客户端 WebSocket 连接。
        session_id: 路径中的会话 ID；为 "new" 时自动生成新 ID。
    """
    # 接受 WebSocket 握手，建立连接。
    await ws.accept()

    # 客户端用 "new" 表示请求新建会话。
    if session_id == "new":
        # 生成一个全新的唯一会话 ID。
        session_id = str(uuid.uuid4())
        # 将新会话 ID 回送给前端，便于后续重连复用。
        await _send_json(ws, {"type": "session_id", "session_id": session_id})

    # 记录连接建立日志。
    logger.info("WebSocket 连接建立: {}", session_id)

    # 获取已编译的编排图，供后续各处理函数复用。
    graph       = _get_graph()
    # 尝试加载既有会话状态以支持断线重连；无则初始化为空字典。
    state: Dict = memory_manager.load_session(session_id) or {}
    _connected  = True   # ★ 本地连接标志，避免断开后继续操作

    # 主消息循环：持续接收并分发消息，直到断开或异常。
    try:
        while True:
            # 阻塞接收下一条 WebSocket 消息（可能是文本/二进制/断开事件）。
            message = await ws.receive()

            # ── 连接已关闭 ────────────────────────────────────────────────
            # 收到断开事件：标记未连接并退出循环。
            if message.get("type") == "websocket.disconnect":
                logger.info("WebSocket 客户端主动断开: {}", session_id)
                _connected = False
                break

            # ── 二进制音频帧 ──────────────────────────────────────────────
            # 收到非空二进制数据，按音频帧处理。
            if "bytes" in message and message["bytes"]:
                # 取出音频字节。
                audio_bytes = message["bytes"]
                # 记录收到的音频帧大小，便于调试。
                logger.debug("收到音频帧: {} bytes", len(audio_bytes))

                # ★ STT 识别，仅回传文字到输入框，不自动发送回答
                # 将音频转写为文本（is_wav=False 表示非 WAV 容器的原始音频）。
                text = stt_engine.transcribe_bytes(audio_bytes, is_wav=False)
                # 回送识别结果；无识别结果时附带提示信息。
                await _send_json(ws, {
                    "type":    "stt_result",  # 消息类型：语音识别结果
                    "text":    text,          # 识别出的文本
                    "message": "" if text else "未识别到语音，请重试",  # 失败提示
                })
                # 音频帧处理完毕，继续接收下一条消息。
                continue

            # ── 文本 JSON 消息 ────────────────────────────────────────────
            # 既非断开也非音频；若没有有效文本内容则跳过。
            if "text" not in message or not message["text"]:
                continue

            # 解析文本为 JSON；格式非法则回送错误并跳过。
            try:
                data = json.loads(message["text"])
            except json.JSONDecodeError:
                await _send_json(ws, {"type": "error", "message": "JSON 格式错误"})
                continue

            # 读取消息类型字段，作为分发依据。
            msg_type = data.get("type", "")

            # 心跳 ping：回送 pong 以保活连接。
            if msg_type == "ping":
                await _send_json(ws, {"type": "pong"})

            # 启动面试：调用 _handle_start；返回 None 时回退为空状态。
            elif msg_type == "start":
                state = await _handle_start(ws, data, session_id, graph) or {}

            # 提交回答：需已存在会话状态（即已 start 过）。
            elif msg_type == "answer":
                # 未初始化会话则提示先发送 start。
                if not state:
                    await _send_json(ws, {"type": "error", "message": "请先发送 start 消息"})
                    continue
                # 读取并清洗回答文本。
                answer_text = data.get("text", "").strip()
                # 回答为空则提示并跳过。
                if not answer_text:
                    await _send_json(ws, {"type": "error", "message": "回答不能为空"})
                    continue
                # 处理本轮回答并更新状态。
                state = await _handle_answer(ws, answer_text, state, graph)

            # 调用技能：同样需已存在会话状态。
            elif msg_type == "skill":
                # 未初始化会话则提示先发送 start。
                if not state:
                    await _send_json(ws, {"type": "error", "message": "请先发送 start 消息"})
                    continue
                # 处理技能调用并更新状态。
                state = await _handle_skill(ws, data, state, graph)

            # 其他未知类型：回送错误提示。
            else:
                await _send_json(ws, {"type": "error", "message": f"未知消息类型: {msg_type}"})

    except WebSocketDisconnect:
        # 框架抛出的断开异常：标记未连接并记录。
        _connected = False
        logger.info("WebSocket 断开: {}", session_id)
    except Exception as e:
        # 其他未预期异常：标记未连接并记录错误。
        _connected = False
        logger.error("WebSocket 异常: {} {}", session_id, e)
        # ★ 只在连接仍有效时才尝试发送错误
        # 仅当连接仍有效时才尝试向前端发送错误（此处 _connected 已为 False，作为防御保留）。
        if _connected:
            try:
                await _send_json(ws, {"type": "error", "message": str(e)})
            except Exception:
                # 发送错误本身再次失败时静默忽略，避免异常套异常。
                pass
    finally:
        # 无论如何退出，若有状态则持久化，保证进度不丢失。
        if state:
            memory_manager.save_session(session_id, state)
        # 记录连接关闭日志。
        logger.info("WebSocket 连接关闭: {}", session_id)