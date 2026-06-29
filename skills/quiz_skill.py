"""
快速测验技能：出题 -> 收答 -> 即时评分
使用方式：
  /quiz <主题>     → 出题（如 /quiz RAG）
  /quiz <你的答案> → 提交答案评分（在已出题之后）
"""
# 启用延迟注解求值，支持前向引用并避免导入顺序问题
from __future__ import annotations

# 标准库类型注解：Any 任意类型、Dict 字典、List 列表
from typing import Any, Dict, List

# 导入技能基类，本技能继承它以复用 LLM 调用与日志能力
from skills.base_skill import BaseSkill

# 出题提示词模板：要求 LLM 根据主题与难度出一道可口头作答的题，并以 JSON 返回题目与标准答案
# __TOPIC__/__DIFFICULTY__ 为占位符；{{ }} 为字面花括号转义
ASK_PROMPT = """\
请出一道关于「__TOPIC__」的面试测验题，难度 __DIFFICULTY__。
要求：题目清晰、有明确答案、适合口头作答（不要出选择题）。
输出 JSON：
{{
  "question": "题目内容",
  "answer": "标准答案要点（字符串，2-3条要点用分号分隔）",
  "difficulty": "easy或medium或hard"
}}
"""

# 评分提示词模板：给定题目、标准答案与候选人回答，要求 LLM 按 0~10 分制评分并以 JSON 返回点评
# __QUESTION__/__REFERENCE__/__ANSWER__ 为占位符
GRADE_PROMPT = """\
请评判候选人的回答质量。

题目：__QUESTION__
标准答案要点：__REFERENCE__
候选人回答：__ANSWER__

评分标准（0~10）：
- 10分：完全正确且有延伸
- 7~9分：基本正确，有小缺漏
- 4~6分：部分正确
- 0~3分：明显错误或不知道

输出 JSON：
{{
  "score": 分数整数,
  "feedback": "一句话点评",
  "correct_points": ["答对的点1", "答对的点2"],
  "missing_points": ["遗漏的点1", "遗漏的点2"]
}}
"""

# 使用提示文本：在无法判断意图或缺少题目时返回，指导用户两步交互的用法
USAGE_HINT = """\
📝 快速测验使用方式：
  /quiz              → 出一道 Python 基础题
  /quiz RAG          → 出一道关于 RAG 的题目
  （出题后）再次输入 /quiz <你的答案> 提交回答
"""


def _to_str(val: Any) -> str:
    """将任意类型安全转为字符串（处理 LLM 可能返回 list 的情况）"""
    # 若为列表（LLM 有时把要点返回成数组），用中文分号把各元素连接成单个字符串
    if isinstance(val, list):
        return "；".join(str(v) for v in val)
    # None 统一转为空串，避免出现字面量 "None"
    if val is None:
        return ""
    # 其他类型直接用 str() 转换
    return str(val)


class QuizSkill(BaseSkill):
    # 技能名，作为注册表查找键
    name = "quiz"
    # 技能描述，用于帮助/展示
    description = "快速测验：出题+即时评分（两步交互）"
    # 触发关键词，用于意图识别路由到本技能
    trigger_keywords = ["测验", "quiz", "考我", "出题"]

    def _is_new_quiz_request(self, user_input: str, skill_state: Dict[str, Any]) -> bool:
        """
        判断是否为新出题请求：
        - phase == "ask"（没有待答题目）→ 一定是出题请求
        - user_input 非常短（<=8字）→ 视为主题关键词，出新题
        """
        # 读取当前阶段，默认 "ask"（出题阶段）
        phase = skill_state.get("phase", "ask")
        # 处于出题阶段时，无论输入什么都按新出题处理
        if phase == "ask":
            return True
        # phase == "answer" 时，输入很短才视为新出题请求
        # 已有待答题目时，短输入（≤8字）更像主题词而非作答，故判定为再次出题
        return len(user_input.strip()) <= 8

    def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """执行快速测验：依据当前阶段进行出题或对回答评分，并维护跨轮次的技能状态。

        参数:
            state: 会话状态字典，含 user_input、skill_state、current_difficulty 等。
        返回:
            更新后的会话状态字典，agent_reply 为题目或评分结果。
        """
        # 读取本技能的私有状态（保存上一轮的题目/答案/阶段等）
        skill_state = self.get_skill_state(state)
        # 读取用户原始输入并去除首尾空白；缺失时用空串兜底
        user_input  = state.get("user_input", "").strip()

        # 移除 /quiz 前缀
        # 若以 /quiz 开头（忽略大小写），切掉前 5 个字符前缀并去空白，得到主题或答案文本
        if user_input.lower().startswith("/quiz"):
            user_input = user_input[5:].strip()

        # 读取当前阶段，默认 "ask"（出题）
        phase = skill_state.get("phase", "ask")

        # ── 出题阶段 ──────────────────────────────────────────────────────────
        # 通过启发式判断本次是否为新出题请求
        if self._is_new_quiz_request(user_input, skill_state):
            # 主题取用户输入；为空时默认出 "Python 基础" 题
            topic      = user_input if user_input else "Python 基础"
            # 从会话状态读取当前难度（默认 medium），并安全转为字符串
            difficulty = _to_str(state.get("current_difficulty", "medium"))

            # 依次替换主题与难度占位符，生成最终出题提示（链式 replace 拼成同一表达式）
            prompt = (
                ASK_PROMPT
                .replace("__TOPIC__", topic)
                .replace("__DIFFICULTY__", difficulty)
            )
            # 调用 LLM 并解析为 JSON 字典
            parsed   = self.invoke_llm_json(prompt, "")
            # 取出题目文本并安全转字符串
            question = _to_str(parsed.get("question", ""))
            # ★ 关键：answer 字段强制转 str，防止 LLM 返回 list
            reference = _to_str(parsed.get("answer", ""))

            # 构建新的技能状态：切换到 answer 阶段并保存题目、参考答案与主题，供下一轮评分使用
            new_skill_state = {
                "phase":     "answer",
                "question":  question,
                "reference": reference,   # 始终是 str
                "topic":     topic,
            }
            # 将新状态写回会话，实现跨轮次持久化
            self.set_skill_state(state, new_skill_state)

            # 组装出题回复：展示主题、题目，并提示如何提交答案
            state["agent_reply"] = (
                f"📝 测验题目（主题：{topic}）：\n\n"
                f"{question}\n\n"
                f"💡 出题后请输入 /quiz <你的答案> 提交评分"
            )
            # 记录出题日志，题目截断到前 50 字防止过长
            self.logger.info(f"QuizSkill 出题：topic={topic}, question={question[:50]}")

        # ── 评分阶段 ──────────────────────────────────────────────────────────
        else:
            # 从技能状态恢复上一轮题目，安全转字符串
            question  = _to_str(skill_state.get("question",  ""))
            # 恢复标准答案要点
            reference = _to_str(skill_state.get("reference", ""))
            # 恢复主题（用于日志）
            topic     = _to_str(skill_state.get("topic",     ""))
            # 候选人的回答即为本轮用户输入
            answer    = user_input

            # 异常兜底：若状态里没有待答题目，返回使用提示并重置回出题阶段后结束
            if not question:
                state["agent_reply"] = USAGE_HINT
                self.set_skill_state(state, {"phase": "ask"})
                return state

            # 依次替换题目、参考答案、候选人回答占位符，生成最终评分提示（链式 replace）
            prompt = (
                GRADE_PROMPT
                .replace("__QUESTION__",  question)
                .replace("__REFERENCE__", reference)
                .replace("__ANSWER__",    answer)
            )
            # 调用 LLM 并解析为 JSON 字典
            parsed       = self.invoke_llm_json(prompt, "")
            # 取出分数，缺失时默认 0
            score        = parsed.get("score", 0)
            # 取出一句话点评并安全转字符串
            feedback     = _to_str(parsed.get("feedback", ""))
            # 取出答对要点列表，缺失时为空列表
            correct_pts  = parsed.get("correct_points", [])
            # 取出遗漏要点列表，缺失时为空列表
            missing_pts  = parsed.get("missing_points", [])

            # 保证是列表
            # LLM 可能把单个要点返回成字符串，这里统一包成单元素列表，便于后续遍历
            if isinstance(correct_pts, str): correct_pts = [correct_pts]
            if isinstance(missing_pts, str): missing_pts = [missing_pts]

            # 初始化输出行列表，首行展示分数与点评
            lines = [f"✅ 得分：{score}/10    {feedback}"]
            # 若有答对要点，逐条以 ✓ 列出
            if correct_pts:
                lines.append("\n答对的点：")
                lines += [f"  ✓ {p}" for p in correct_pts]
            # 若有遗漏要点，逐条以 ✗ 列出
            if missing_pts:
                lines.append("\n遗漏的点：")
                lines += [f"  ✗ {p}" for p in missing_pts]
            # 追加引导语，提示如何开始下一题
            lines.append("\n💡 输入 /quiz <主题> 继续下一题")

            # 用换行拼接所有行作为最终回复写入状态
            state["agent_reply"] = "\n".join(lines)
            # 重置为出题阶段
            # 评分完成后清空题目状态，回到出题阶段以便开始新一轮
            self.set_skill_state(state, {"phase": "ask"})
            # 记录评分日志，标明主题与得分
            self.logger.info(f"QuizSkill 评分：topic={topic}, score={score}")

        # 返回更新后的会话状态（出题与评分两分支共用此返回）
        return state