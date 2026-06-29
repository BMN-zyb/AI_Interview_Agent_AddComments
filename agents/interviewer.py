"""
AI 面试官 Agent：多轮交互核心
- 支持追问深挖（followup）
- 支持面试官主动判断结束
- 评估后给出点评再出下一题
"""
from __future__ import annotations

# typing：类型注解，标注状态字典与列表类型
from typing import Any, Dict, List

# 导入基类：复用 LLM 调用与日志能力
from agents.base_agent import BaseAgent

# ── 正常出题 Prompt ──────────────────────────────────────────────────────────
# 出题提示词：指导 LLM 以面试官口吻自然地提出当前计划题目。
# 其中 __TITLE__ 等为自定义占位符（后续 replace 注入），末尾约定输出 JSON。
ASK_PROMPT_TEMPLATE = """\
你是资深技术面试官，正在进行一场真实的模拟面试对话。

岗位：__TITLE__（__LEVEL__）
当前题目（ID: __QID__，第 __CUR__ / __TOTAL__ 题）：
- 主题：__TOPIC__
- 题型：__QUESTION_TYPE__
- 难度：__DIFFICULTY__
- 考察点：__FOCUS__
- 预设问题：__PROMPT__

候选人简历摘要：__RESUME_SUMMARY__
当前面试难度状态：__DIFFICULTY_STATE__
近期问答记录：
__HISTORY__

【任务】请你以面试官身份，自然地向候选人提出这道题。
要求：
1. 语言口语化、专业，像真实面试场景的对话
2. 可以在正式提问前，用一句话简短衔接（如"好的，接下来我们聊一个系统设计的问题"）
3. 不要加「面试官：」前缀
4. 问题控制在 120 字以内

输出 JSON：{"question": "完整提问内容", "is_followup": false}
"""

# ── 追问 Prompt ───────────────────────────────────────────────────────────────
# 追问提示词：指导 LLM 针对候选人回答的薄弱点提出一个有针对性的追问。
FOLLOWUP_PROMPT_TEMPLATE = """\
你是资深技术面试官，正在对候选人的回答进行深挖追问。

刚才的问题：__ORIGINAL_Q__
候选人的回答：__CANDIDATE_ANSWER__
评估发现的不足：__KEY_MISSING__

【任务】请根据候选人回答中的不足或值得深挖的点，提出一个追问。
要求：
1. 追问要有针对性，直接切入候选人回答的薄弱环节
2. 语气自然，像真实面试官追问
3. 不要加「面试官：」前缀
4. 控制在 80 字以内

输出 JSON：{"question": "追问内容", "is_followup": true}
"""

# ── 点评 Prompt ───────────────────────────────────────────────────────────────
# 点评提示词：指导 LLM 对刚评估的回答给出一句简短点评并自然过渡到下一题。
COMMENT_PROMPT_TEMPLATE = """\
你是资深技术面试官，刚才评估了候选人对一道题的回答。

题目：__QUESTION__
候选人回答：__ANSWER__
评分结果：__SCORE__
遗漏的关键点：__MISSING__

【任务】给候选人一句简短的点评（肯定亮点或指出不足），然后自然过渡到下一题。
要求：
1. 点评控制在 60 字以内，口语化
2. 不要直接说"你的回答得了X分"
3. 不要加「面试官：」前缀
4. 只输出点评语，不要输出下一道题

输出 JSON：{"comment": "点评内容"}
"""

# ── 结束语 Prompt ─────────────────────────────────────────────────────────────
# 结束语提示词：指导 LLM 在面试结束时生成一段温和自然的收尾语。
FINISH_PROMPT_TEMPLATE = """\
你是资深技术面试官，本场面试已经结束。

岗位：__TITLE__
面试共 __TOTAL__ 题，整体表现印象：__IMPRESSION__

【任务】请给出一段自然的结束语，感谢候选人参与，并简短说明接下来的安排。
要求：
1. 控制在 80 字以内，口语化温和
2. 不要加「面试官：」前缀

输出 JSON：{"farewell": "结束语内容"}
"""


class InterviewerAgent(BaseAgent):
    """AI 面试官 Agent：负责多轮交互核心——出题、追问深挖、点评与结束语。"""

    # Agent 名称：用于日志与编排识别
    name = "interviewer"
    # Agent 描述：标识其职责为多轮追问深挖
    description = "AI 面试官：多轮追问深挖"

    # ── 内部工具方法 ─────────────────────────────────────────────────────────

    def _build_history_text(self, qa_history: List[Dict[str, Any]], last_n: int = 3) -> str:
        """将最近若干轮问答拼成文本，作为出题时的上下文。

        参数：
            qa_history：完整问答记录列表
            last_n：取最近的轮数，默认 3
        返回：
            拼接好的历史文本；无记录时返回“（无）”
        """
        # 无历史记录时返回占位符，避免提示词出现空白
        if not qa_history:
            return "（无）"
        # 仅取最近 last_n 轮，控制上下文长度
        recent = qa_history[-last_n:]
        # 逐行收集“问/答”文本
        lines = []
        # 遍历最近的问答记录
        for i, h in enumerate(recent):
            # 追加该轮问题
            lines.append(f"[问] {h.get('question', '')}")
            # 追加该轮回答
            lines.append(f"[答] {h.get('answer', '')}")
        # 以换行连接为完整历史文本
        return "\n".join(lines)

    def ask_question(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """出下一道计划题目"""
        # 取出题目计划列表
        plan: List[Dict[str, Any]] = state.get("question_plan", [])
        # 取出当前题目索引
        idx: int = state.get("current_question_idx", 0)
        # 取出已解析的 JD（提供岗位/职级信息）
        jd = state.get("jd_parsed", {})
        # 取出已解析的简历（提供候选人摘要）
        resume = state.get("resume_parsed", {})
        # 构造最近问答历史文本，作为出题上下文
        history_text = self._build_history_text(state.get("qa_history", []))

        # 定位当前要提问的题目对象
        current_q = plan[idx]
        # 用 replace 逐一注入题目元数据与上下文，组装出题提示词
        prompt = (
            ASK_PROMPT_TEMPLATE
            # 岗位标题，缺省“技术岗”
            .replace("__TITLE__", str(jd.get("title", "技术岗")))
            # 职级，缺省 mid
            .replace("__LEVEL__", str(jd.get("level", "mid")))
            # 题目 ID，缺省用序号 idx+1
            .replace("__QID__", str(current_q.get("id", idx + 1)))
            # 当前题序（从 1 计）
            .replace("__CUR__", str(idx + 1))
            # 题目总数
            .replace("__TOTAL__", str(len(plan)))
            # 技术主题
            .replace("__TOPIC__", str(current_q.get("topic", "")))
            # 题型
            .replace("__QUESTION_TYPE__", str(current_q.get("question_type", "")))
            # 难度
            .replace("__DIFFICULTY__", str(current_q.get("difficulty", "")))
            # 考察点
            .replace("__FOCUS__", str(current_q.get("focus", "")))
            # 预设问题文本
            .replace("__PROMPT__", str(current_q.get("prompt", "")))
            # 简历摘要，截断到 300 字控制长度
            .replace("__RESUME_SUMMARY__", str(resume.get("summary", ""))[:300])
            # 当前难度状态，缺省 medium
            .replace("__DIFFICULTY_STATE__", str(state.get("current_difficulty", "medium")))
            # 近期问答历史
            .replace("__HISTORY__", history_text)
        )

        # 调用 LLM 生成自然语言提问（JSON 形式）
        parsed = self.invoke_llm_json(prompt, "")
        # 记录当前题目对象
        state["current_question"] = current_q
        # 记录最终提问文本；LLM 未给出时回退到预设 prompt
        state["current_question_text"] = parsed.get("question", current_q.get("prompt", ""))
        # 标记本题非追问
        state["is_followup"] = False
        # 将提问作为本轮 Agent 回复输出
        state["agent_reply"] = state["current_question_text"]
        # 标记正在等待候选人作答
        state["awaiting_answer"] = True
        state["followup_count"] = 0          # 重置追问计数
        # 清除追问标志，进入正常作答流程
        state["should_followup"] = False
        # 返回更新后的状态
        return state

    def ask_followup(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """基于上一轮回答进行追问"""
        # 取出最近一条问答记录；为空时用含空 dict 的列表兜底，避免索引报错
        last_qa = (state.get("qa_history") or [{}])[-1]
        # 取出该轮的评分结果
        score = last_qa.get("score", {})
        # 取出评分中标记的遗漏关键点，作为追问切入点
        missing = score.get("key_missing", [])

        # 用 replace 注入原题、候选人回答(截断 500 字)与遗漏点(截断 300 字)
        prompt = (
            FOLLOWUP_PROMPT_TEMPLATE
            .replace("__ORIGINAL_Q__", str(state.get("current_question_text", "")))
            .replace("__CANDIDATE_ANSWER__", str(state.get("last_user_answer", ""))[:500])
            .replace("__KEY_MISSING__", str(missing)[:300])
        )

        # 调用 LLM 生成追问问题
        parsed = self.invoke_llm_json(prompt, "")
        # 取出追问文本
        followup_q = parsed.get("question", "")

        # 用追问替换当前题目文本
        state["current_question_text"] = followup_q
        # 标记本轮为追问
        state["is_followup"] = True
        # 将追问作为本轮 Agent 回复输出
        state["agent_reply"] = followup_q
        # 标记正在等待候选人作答
        state["awaiting_answer"] = True
        # 追问计数 +1，用于限制连续追问次数
        state["followup_count"] = state.get("followup_count", 0) + 1
        # 重置追问标志，等待下一次评估再决定是否继续追问
        state["should_followup"] = False
        # 返回更新后的状态
        return state

    def make_comment(self, state: Dict[str, Any]) -> str:
        """对刚才的回答给出简短点评

        参数：
            state：共享状态字典
        返回：
            一句点评文本（LLM 未给出时返回空字符串）
        """
        # 取出最近一条问答记录（带空 dict 兜底）
        last_qa = (state.get("qa_history") or [{}])[-1]
        # 取出该轮评分结果
        score = last_qa.get("score", {})
        # 取出遗漏关键点
        missing = score.get("key_missing", [])

        # 用 replace 注入题目、回答(截断 400 字)、评分与遗漏点(截断 200 字)
        prompt = (
            COMMENT_PROMPT_TEMPLATE
            .replace("__QUESTION__", str(state.get("current_question_text", "")))
            .replace("__ANSWER__", str(state.get("last_user_answer", ""))[:400])
            .replace("__SCORE__", str(score))
            .replace("__MISSING__", str(missing)[:200])
        )
        # 调用 LLM 生成点评
        parsed = self.invoke_llm_json(prompt, "")
        # 返回点评文本，缺省空字符串
        return parsed.get("comment", "")

    def make_farewell(self, state: Dict[str, Any]) -> str:
        """生成结束语

        根据平均得分推断整体印象，再由 LLM 生成一段收尾语。
        参数：
            state：共享状态字典
        返回：
            结束语文本（LLM 未给出时返回默认寄语）
        """
        # 取出已解析的 JD（提供岗位标题）
        jd = state.get("jd_parsed", {})
        # 取出题目计划（用于统计题目总数）
        plan = state.get("question_plan", [])
        # 根据平均分给出印象
        # 取出全部单题评分记录
        records = state.get("score_records", [])
        # 有评分记录时，计算各题平均分进而推断整体印象
        if records:
            # 收集每题的平均维度分
            scores = []
            # 遍历每条评分记录
            for r in records:
                # 取出该题的评分字典
                s = r.get("score", {})
                # 仅处理字典型评分
                if isinstance(s, dict):
                    # 抽取其中的数值型维度分
                    vals = [v for v in s.values() if isinstance(v, (int, float))]
                    # 若存在数值，计算该题平均分并收集
                    if vals:
                        scores.append(sum(vals) / len(vals))
            # 计算所有题目的总体平均分；无有效分时回退为 5
            avg = sum(scores) / len(scores) if scores else 5
            # 平均分 >=7 视为表现不错，否则提示有提升空间
            impression = "整体表现不错" if avg >= 7 else "有一些提升空间"
        # 无评分记录时给出中性印象
        else:
            impression = "感谢参与"

        # 用 replace 注入岗位标题、题目总数与整体印象，组装结束语提示词
        prompt = (
            FINISH_PROMPT_TEMPLATE
            .replace("__TITLE__", str(jd.get("title", "技术岗")))
            .replace("__TOTAL__", str(len(plan)))
            .replace("__IMPRESSION__", impression)
        )
        # 调用 LLM 生成结束语
        parsed = self.invoke_llm_json(prompt, "")
        # 返回结束语，缺省时给出固定的礼貌寄语
        return parsed.get("farewell", "感谢你参与本次模拟面试，祝你面试顺利！")

    # ── 主入口 ────────────────────────────────────────────────────────────────

    def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """面试官主入口：判断结束/追问/正常出题三种分支。

        参数：
            state：共享状态字典
        返回：
            更新后的状态字典
        """
        # 取出题目计划
        plan: List[Dict[str, Any]] = state.get("question_plan", [])
        # 取出当前题目索引
        idx: int = state.get("current_question_idx", 0)

        # 索引越界说明题目已出完：标记面试结束并生成结束语
        if idx >= len(plan):
            state["interview_finished"] = True
            state["agent_reply"] = self.make_farewell(state)
            return state

        # 判断是否需要追问
        # 读取追问标志（由评估 Agent 设置）
        should_followup = state.get("should_followup", False)
        # 当前已追问次数
        followup_count = state.get("followup_count", 0)
        # 单题最大追问次数，缺省 2
        max_followup = state.get("max_followup", 2)

        # 需要追问且未超上限 → 走追问分支
        if should_followup and followup_count < max_followup:
            return self.ask_followup(state)
        # 否则 → 出下一道计划题目
        else:
            return self.ask_question(state)