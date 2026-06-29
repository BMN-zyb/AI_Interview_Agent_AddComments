"""
实时评估打分 Agent：
- 对候选人的单题回答即时打分
- 维度：正确性 / 深度 / 表达 / 举例
- 判断是否需要追问
- 面试结束后生成多维度评估报告
"""
from __future__ import annotations

# typing：类型注解，标注状态字典与列表类型
from typing import Any, Dict, List

# 导入基类：复用 LLM 调用与日志能力
from agents.base_agent import BaseAgent

# 单题评分提示词：指导 LLM 从正确性/深度/结构/举例四维度为单题回答打分，
# 并判断是否需要追问。其中 __QUESTION__ 等为自定义占位符，后续用 replace 注入。
SINGLE_SCORE_PROMPT = """\
你是严谨的技术面试官。请对候选人的回答进行评分。

题目：__QUESTION__
标准答案要点（如有）：__REFERENCE__
候选人回答：__ANSWER__
是否为追问（followup）：__IS_FOLLOWUP__

评分维度（每项 0-10）：
- correctness：事实正确性
- depth：技术深度
- structure：表达结构
- example：是否举出实际例子

综合判断：
- is_correct：综合是否达标（true/false，correctness>=6 且 depth>=5 视为 true）
- key_missing：遗漏的关键点列表（最多3条，没有则空列表）
- followup_needed：是否建议追问（true/false）
  - 当 key_missing 非空 且 correctness < 8 时建议追问
  - 当候选人回答"不知道"/"不清楚"/"跳过"等时设为 false（无追问意义）
- followup_reason：如果需要追问，说明追问方向（一句话）

输出严格 JSON，不要多余文字。
"""

# 整场报告提示词：指导 LLM 综合全部问答与单题评分，生成多维度评估报告。
# 其中 __JD_TITLE__ 等为自定义占位符（后续 replace 注入）；下方为期望的 JSON 结构示例。
REPORT_PROMPT = """\
你是资深技术面试官。根据一场完整面试的全部问答记录，生成一份详细的多维度评估报告。

岗位：__JD_TITLE__（__JD_LEVEL__）
单题评分记录：
__SCORES__

完整问答记录：
__QA_HISTORY__

请输出以下 JSON 格式的评估报告：
{
  "overall_score": 0到100的整数,
  "recommendation": "strong_hire或hire或weak_hire或no_hire",
  "dimension_scores": {
    "technical_knowledge": 0到10的数字（技术知识掌握度）,
    "problem_solving": 0到10的数字（问题解决能力）,
    "system_design": 0到10的数字（系统设计能力）,
    "communication": 0到10的数字（表达与沟通能力）,
    "practical_experience": 0到10的数字（实战经验丰富度）,
    "learning_ability": 0到10的数字（学习潜力与适应力）
  },
  "strengths": ["优势1", "优势2", "优势3"],
  "weaknesses": ["薄弱点1", "薄弱点2", "薄弱点3"],
  "highlights": ["亮点表现1", "亮点表现2"],
  "concerns": ["担忧点1", "担忧点2"],
  "topic_performance": [
    {"topic": "技术主题", "performance": "good或average或weak", "comment": "一句话评价"}
  ],
  "summary": "200字以内的总评",
  "interviewer_comment": "面试官寄语（鼓励+建议，100字以内）"
}
"""


class EvaluatorAgent(BaseAgent):
    """实时评估打分 Agent：对单题回答即时打分、判断是否追问，并在面试结束后生成报告。"""

    # Agent 名称：用于日志与编排识别
    name = "evaluator"
    # Agent 描述：标识其职责为实时评分 + 报告生成
    description = "实时评估打分 + 生成多维度报告"

    def score_one(
        self,
        question: str,
        answer: str,
        reference: str = "",
        is_followup: bool = False,
    ) -> Dict[str, Any]:
        """对单道题目的回答进行评分。

        参数：
            question：题目文本
            answer：候选人回答
            reference：标准答案要点（可选）
            is_followup：该题是否为追问
        返回：
            含各维度分数与追问判断的 JSON 字典
        """
        # 用 replace 把四个占位符注入提示词；reference 为空时填“（无）”，
        # is_followup 布尔值转为中文“是/否”
        prompt = (
            SINGLE_SCORE_PROMPT
            .replace("__QUESTION__", question)
            .replace("__ANSWER__", answer)
            .replace("__REFERENCE__", reference or "（无）")
            .replace("__IS_FOLLOWUP__", "是" if is_followup else "否")
        )
        # 调用 LLM 进行评分并返回 JSON 结果
        return self.invoke_llm_json(prompt, "")

    def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """统一入口：根据状态标志执行“单题评估”或“生成整场报告”。

        参数：
            state：共享状态字典
        返回：
            更新后的状态字典
        """

        # ── 单题评估 ──────────────────────────────────────────────────────────
        # 当状态标记为“等待评估”时，对刚收到的回答进行评分
        if state.get("awaiting_evaluation"):
            # 当前题目文本
            q = state.get("current_question_text", "")
            # 候选人最近一次回答
            a = state.get("last_user_answer", "")
            # 当前题目是否为追问
            is_followup = state.get("is_followup", False)

            # 候选人明确表示不会/跳过，不追问
            # 定义一组“放弃/听不清”类关键词，命中则视为跳过
            skip_keywords = ("不知道", "不清楚", "不会", "跳过", "pass", "不懂",
                             "没接触过", "可以再说一遍", "再说一遍")
            # 将回答转小写并去空白，便于关键词匹配
            answer_lower = a.lower().strip()
            # 命中任一关键词，或回答过短（<10 字符）即判定为跳过
            is_skip = any(kw in answer_lower for kw in skip_keywords) or len(a.strip()) < 10

            # 调用 LLM 对本题回答打分
            score = self.score_one(q, a, is_followup=is_followup)

            # 如果候选人明确跳过，强制不追问
            # 跳过场景下覆盖模型结果：关闭追问并清空遗漏点（追问无意义）
            if is_skip:
                score["followup_needed"] = False
                score["key_missing"] = []

            # 把本题评分追加到 score_records（不存在则先初始化为空列表）
            state.setdefault("score_records", []).append(
                {"question": q, "answer": a, "score": score}
            )
            # 同步把本轮问答与评分追加到完整问答记录 qa_history
            state["qa_history"] = state.get("qa_history", []) + [
                {"question": q, "answer": a, "score": score}
            ]
            # 评估完成，清除“等待评估”标志
            state["awaiting_evaluation"] = False
            # 记录本题是否达标，供编排层决策使用
            state["last_correctness"] = score.get("is_correct", False)

            # ── 追问判断 ──────────────────────────────────────────────────────
            # 模型是否建议追问
            followup_needed = score.get("followup_needed", False)
            # 当前已追问次数
            followup_count = state.get("followup_count", 0)
            # 单题最大追问次数，缺省 2
            max_followup = state.get("max_followup", 2)

            # 情况一：原始题需要追问且未超上限 → 触发追问（不推进题目索引）
            if followup_needed and not is_followup and followup_count < max_followup:
                # 本题需要追问，不推进索引
                state["should_followup"] = True
            # 情况二：本身已是追问、仍需追问且未超上限 → 继续追问
            elif followup_needed and is_followup and followup_count < max_followup:
                # 已是追问，还可以继续追问
                state["should_followup"] = True
            # 情况三：其余情况 → 不追问，进入下一题
            else:
                # 不追问，推进到下一题
                state["should_followup"] = False

            # 单题评估处理完毕，返回状态
            return state

        # ── 生成整场报告 ──────────────────────────────────────────────────────
        # 当面试结束标志为真时，汇总全部记录生成评估报告
        if state.get("interview_finished"):
            # 取出已解析的 JD（用于报告中的岗位信息）
            jd = state.get("jd_parsed", {})

            # 把所有单题评分记录拼成文本：题号、题目、回答摘要(<=200字)、评分详情
            scores_text = "\n".join(
                f"[Q{i+1}] 题目: {r['question']}\n"
                f"回答摘要: {str(r['answer'])[:200]}\n"
                f"评分详情: {r['score']}\n"
                for i, r in enumerate(state.get("score_records", []))
            )

            # 把完整问答记录拼成文本：题号、问、答(<=300字)
            qa_text = "\n".join(
                f"[Q{i+1}] 问: {h['question']}\n"
                f"     答: {str(h['answer'])[:300]}\n"
                for i, h in enumerate(state.get("qa_history", []))
            )

            # 用 replace 注入岗位标题/职级与上面拼好的两段文本，组装报告提示词
            prompt = (
                REPORT_PROMPT
                .replace("__JD_TITLE__", str(jd.get("title", "技术岗")))
                .replace("__JD_LEVEL__", str(jd.get("level", "mid")))
                .replace("__SCORES__", scores_text)
                .replace("__QA_HISTORY__", qa_text)
            )

            # 调用 LLM 生成多维度评估报告
            report = self.invoke_llm_json(prompt, "")
            # 写入最终报告
            state["final_report"] = report
            # 抽取报告中的薄弱点，供后续复习计划/长期记忆使用
            state["weaknesses_to_remember"] = report.get("weaknesses", [])

        # 返回更新后的状态
        return state