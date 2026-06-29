"""
智能出题规划 Agent：
- 基于 JD + 简历 + RAG 题库检索结果，规划一套面试题目
- 支持 total_questions 控制题目数量
"""
from __future__ import annotations

# typing：类型注解，标注状态字典与列表类型
from typing import Any, Dict, List

# 导入基类：复用 LLM 调用与日志能力
from agents.base_agent import BaseAgent

# 系统提示词：指导 LLM 基于 JD/简历/RAG 题库规划恰好 __TOTAL__ 道结构化面试题。
# 其中 __TOTAL__/__JD_SUMMARY__ 等为自定义占位符（后续用 replace 注入），
# 示例 {{"plan": [...]}} 的花括号双写转义。
SYSTEM_PROMPT = """\
你是资深技术面试官，正在规划一场结构化模拟面试。
根据岗位 JD、候选人简历、以及 RAG 检索到的参考题库，规划恰好 __TOTAL__ 道面试题。

岗位画像：
__JD_SUMMARY__

候选人画像（优势/短板）：
Strengths: __STRENGTHS__
Weaknesses: __WEAKNESSES__

RAG 检索到的参考题目片段：
__RAG_CONTEXT__

要求：
1. 必须严格输出恰好 __TOTAL__ 道题目，不多不少
2. 题目分布合理：基础题 30% / 中等题 50% / 高阶题 20%
3. 题型混合：概念题 / 场景设计 / 代码实现 / 行为面试 / 项目深挖
4. 针对候选人短板设计重点考察题
5. 每道题包含：topic（技术主题）、question_type（题型）、difficulty（easy/medium/hard）、focus（考察点）、prompt（具体问题文本）

输出 JSON：{{"plan": [...]}} 数组长度必须为 __TOTAL__
"""


class QuestionPlannerAgent(BaseAgent):
    """智能出题规划 Agent：综合 JD、简历与 RAG 题库，规划一套结构化面试题目。"""

    # Agent 名称：用于日志与编排识别
    name = "question_planner"
    # Agent 描述：标识其职责为出题规划
    description = "智能出题规划：基于 JD + 简历 + RAG 规划题目"

    def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """规划面试题目并写入状态。

        参数：
            state：共享状态字典，可含 jd_parsed / resume_parsed / rag_context /
                   total_questions / strengths / weaknesses
        返回：
            更新后的状态字典，写入 question_plan（题目列表）与 current_question_idx（当前题索引）
        """
        # 取出已解析的 JD
        jd = state.get("jd_parsed", {})
        # 取出已解析的简历
        resume = state.get("resume_parsed", {})
        # 取出 RAG 检索到的参考题库上下文
        rag = state.get("rag_context", "")

        # ★ 读取 total_questions，默认 5
        # 题目总数：从状态读取并转为 int，缺省 5 题
        total = int(state.get("total_questions", 5))

        # 将 JD 关键信息浓缩为画像文本，注入提示词
        jd_summary = (
            f"岗位：{jd.get('title')} / {jd.get('level')}\n"
            f"技术栈：{jd.get('tech_stack')}\n"
            f"核心能力：{jd.get('core_competencies')}"
        )
        # 把优势列表拼成带项目符号的多行文本；为空时用占位符“（无）”
        strengths = "\n".join("- " + s for s in state.get("strengths", [])) or "（无）"
        # 把短板列表拼成带项目符号的多行文本；为空时用占位符“（无）”
        weaknesses = "\n".join("- " + w for w in state.get("weaknesses", [])) or "（无）"

        # ★ 用 replace 注入，避免 format() 与花括号冲突
        # 依次替换各占位符，组装最终提示词；RAG 上下文截断到 4000 字控制长度
        prompt = (
            SYSTEM_PROMPT
            .replace("__TOTAL__", str(total))
            .replace("__JD_SUMMARY__", jd_summary)
            .replace("__STRENGTHS__", strengths)
            .replace("__WEAKNESSES__", weaknesses)
            .replace("__RAG_CONTEXT__", rag[:4000])
        )

        # 调用 LLM 生成题目规划，得到 JSON 字典
        parsed = self.invoke_llm_json(prompt, "")
        # 从结果中取出题目数组，缺省为空列表
        plan: List[Dict[str, Any]] = parsed.get("plan", [])

        # ★ 截断或补全，保证恰好 total 道题
        # 题目过多：截断到目标数量
        if len(plan) > total:
            plan = plan[:total]
        # 题目不足但非空：仅记录告警（不强行补题），按实际数量使用
        elif len(plan) < total and len(plan) > 0:
            # 不足时重复最后一题的结构补位（极少发生）
            self.logger.warning(f"LLM 只生成了 {len(plan)} 题，期望 {total} 题，截断使用")

        # 规范化字段
        # 遍历每道题，补全缺失的关键字段，保证下游消费时结构完整
        for i, q in enumerate(plan):
            # 缺省题目 ID 为 Q1、Q2……
            q.setdefault("id", f"Q{i + 1}")
            # 缺省难度为 medium
            q.setdefault("difficulty", "medium")
            # 缺省题型为 concept（概念题）
            q.setdefault("question_type", "concept")

        # 写入最终题目计划
        state["question_plan"] = plan
        # 初始化当前题目索引为 0（从第一题开始）
        state["current_question_idx"] = 0
        # 记录规划完成日志：实际题数与目标题数
        self.logger.info(f"出题规划完成，共 {len(plan)} 题（目标 {total} 题）")
        # 返回更新后的状态
        return state