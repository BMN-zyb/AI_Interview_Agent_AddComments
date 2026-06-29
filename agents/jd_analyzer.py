"""
JD 智能解析 Agent：
输入：岗位 JD 文本或招聘链接（链接由 MCP web_scraper 先抓成文本）
输出：结构化的 JD 解析结果（技术栈、职级、核心能力项）
"""
from __future__ import annotations

# typing：类型注解，标注状态字典与列表类型
from typing import Any, Dict, List

# 导入基类：复用 LLM 调用能力
from agents.base_agent import BaseAgent

# ★ 修复：不用 str.format()，改为占位符 __JD_TEXT__，避免 jd_text 含花括号时崩溃
# 系统提示词：引导 LLM 把 JD 文本解析为结构化字段并以 JSON 输出。
# 使用自定义占位符 __JD_TEXT__（而非 {} ），后续用 replace 注入文本，避免花括号冲突。
SYSTEM_PROMPT = """\
你是资深技术面试官。请对下面的岗位 JD 进行深度解析，提取以下信息并以 JSON 输出：
1. title：岗位名称
2. level：职级（junior / mid / senior / staff / principal）
3. years_of_experience：最低经验要求（年，纯数字）
4. tech_stack：核心技术栈列表（按重要度降序）
5. nice_to_have：加分项技术栈
6. core_competencies：核心能力项（如系统设计、算法、沟通能力等）
7. industry：所属行业/领域
8. key_responsibilities：关键职责摘要（3-5 条）
9. summary：一句话岗位画像

严格 JSON 输出，不要有多余文字。

JD 内容：
__JD_TEXT__
"""


class JDAnalyzerAgent(BaseAgent):
    """JD 智能解析 Agent：将岗位描述解析为结构化数据（技术栈、职级、核心能力等）。"""

    # Agent 名称：用于日志与编排识别
    name = "jd_analyzer"
    # Agent 描述：标识其职责为 JD 解析
    description = "JD 智能解析：提取技术栈、职级、核心能力"

    def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """解析 JD 文本并写入结构化结果。

        参数：
            state：共享状态字典，需包含 jd_text（JD 原文）
        返回：
            更新后的状态字典，写入 jd_parsed（结构化结果）与 tech_stack（小写技术栈列表）
        """
        # 取出 JD 文本并去除首尾空白
        jd_text = state.get("jd_text", "").strip()
        # JD 为空时写入空结果与错误信息并直接返回，避免无意义的 LLM 调用
        if not jd_text:
            state["jd_parsed"] = {}
            state["error"] = "JD 文本为空"
            return state

        # ★ 用 replace 替换，彻底规避 jd_text 含 { } 导致的 KeyError
        # 把占位符 __JD_TEXT__ 替换为真实 JD 文本，组装最终提示词
        prompt = SYSTEM_PROMPT.replace("__JD_TEXT__", jd_text)
        # 调用 LLM 解析并获得 JSON 字典结果
        parsed = self.invoke_llm_json(prompt, "")

        # 规范化字段
        # 为关键字段设置默认值，防止下游因缺字段而出错
        parsed.setdefault("tech_stack", [])
        parsed.setdefault("core_competencies", [])
        parsed.setdefault("level", "mid")
        parsed.setdefault("title", "未知岗位")

        # 写入结构化解析结果
        state["jd_parsed"] = parsed
        # 额外存一份小写化的技术栈列表，便于后续做大小写无关的匹配
        state["tech_stack"] = [t.lower() for t in parsed.get("tech_stack", [])]
        # 返回更新后的状态
        return state


def jd_to_markdown(jd: Dict[str, Any]) -> str:
    """将 JD 解析结果转为可读的 Markdown（用于报告展示）

    参数：
        jd：JD 解析结果字典
    返回：
        组装好的 Markdown 字符串
    """
    # 逐行收集 Markdown 文本片段
    lines: List[str] = []
    # 标题行：岗位名称（职级），字段缺失时给出占位默认值
    lines.append(f"### {jd.get('title', '未知岗位')} ({jd.get('level', '-')})")
    # 行业信息行
    lines.append(f"- 行业：{jd.get('industry', '-')}")
    # 经验要求行
    lines.append(f"- 经验要求：{jd.get('years_of_experience', '-')} 年")
    # 技术栈行：用逗号拼接列表
    lines.append(f"- 技术栈：{', '.join(jd.get('tech_stack', []))}")
    # 仅当存在加分项时才输出该行
    if jd.get("nice_to_have"):
        lines.append(f"- 加分项：{', '.join(jd['nice_to_have'])}")
    # 核心能力行：用逗号拼接列表
    lines.append(f"- 核心能力：{', '.join(jd.get('core_competencies', []))}")
    # 以换行连接所有片段，返回完整 Markdown
    return "\n".join(lines)