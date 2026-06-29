"""
简历深度匹配 Agent：
- 输入：简历文本 + JD 解析结果
- 输出：匹配度评分、优势、短板、匹配明细
"""
from __future__ import annotations

# typing：类型注解，标注状态字典类型
from typing import Any, Dict

# 导入基类：复用 LLM 调用能力
from agents.base_agent import BaseAgent

# ★ 修复1：JSON 示例中所有花括号双写转义 {{ }}
# 系统提示词：引导 LLM 对比 JD 与简历，输出结构化匹配分析。
# 其中 {jd_summary} / {resume_text} 为待替换占位符，示例 JSON 的花括号均双写转义。
SYSTEM_PROMPT = """\
你是资深技术面试官。基于以下「岗位 JD」与「候选人简历」，输出结构化的匹配分析。

岗位 JD：
{jd_summary}

候选人简历：
{resume_text}

输出 JSON 结构（严格按此格式，不要输出其他内容）：
{{
  "overall_score": 0到100的整数,
  "match_level": "low或medium或high",
  "strengths": ["优势1", "优势2", "优势3"],
  "weaknesses": ["短板1", "短板2", "短板3"],
  "tech_match": {{
    "技术名": {{"matched": true, "evidence": "简历中的证据"}}
  }},
  "experience_fit": "under或fit或over",
  "highlights": ["值得深挖的点1", "值得深挖的点2"],
  "red_flags": ["潜在风险1"],
  "summary": "一句话总结"
}}
"""


class ResumeAnalyzerAgent(BaseAgent):
    """简历深度匹配 Agent：将简历与已解析的 JD 对比，输出匹配度、优势与短板。"""

    # Agent 名称：用于日志与编排识别
    name = "resume_analyzer"
    # Agent 描述：标识其职责为简历匹配
    description = "简历深度匹配：与 JD 对比打分"

    def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """对比简历与 JD 并写入匹配分析结果。

        参数：
            state：共享状态字典，需包含 resume_text 与 jd_parsed
        返回：
            更新后的状态字典，写入 resume_parsed / weaknesses_to_remember / strengths
        """
        # 取出简历文本并去除首尾空白
        resume_text = state.get("resume_text", "").strip()
        # 取出已解析的 JD（依赖前置 JD 解析步骤）
        jd_parsed = state.get("jd_parsed", {})

        # 简历为空：写入空结果与错误信息后返回
        if not resume_text:
            state["resume_parsed"] = {}
            state["error"] = "简历内容为空"
            return state
        # JD 未解析：提示需先解析 JD 后返回（保证有对比基准）
        if not jd_parsed:
            state["error"] = "请先解析 JD"
            return state

        # 将 JD 关键信息浓缩为一段摘要，作为对比基准注入提示词
        jd_summary = (
            f"岗位：{jd_parsed.get('title', '未知')}\n"
            f"技术栈：{', '.join(jd_parsed.get('tech_stack', []))}\n"
            f"核心能力：{', '.join(jd_parsed.get('core_competencies', []))}\n"
            f"经验要求：{jd_parsed.get('years_of_experience', '未知')} 年"
        )

        # ★ 修复2：jd_summary / resume_text 本身可能含 { }，改用模板替换而非 format
        # 用 replace 依次替换两个占位符，避免内容中的花括号触发 format 的 KeyError
        prompt = SYSTEM_PROMPT.replace("{jd_summary}", jd_summary).replace(
            "{resume_text}", resume_text
        )

        # 调用 LLM 进行匹配分析，得到 JSON 字典
        parsed = self.invoke_llm_json(prompt, "")

        # 写入完整的匹配分析结果
        state["resume_parsed"] = parsed
        # ★ 修复3：统一使用 weaknesses_to_remember（与 state.py / node_save_memory 对齐）
        # 抽取短板列表，键名与持久化记忆模块保持一致
        state["weaknesses_to_remember"] = parsed.get("weaknesses", [])
        # 抽取优势列表，供出题规划等下游使用
        state["strengths"] = parsed.get("strengths", [])
        # 返回更新后的状态
        return state