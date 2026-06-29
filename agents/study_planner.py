"""
个性化复习计划 Agent：
- 基于评估报告薄弱点生成复习路径
- 调用 GitHub API 推荐开源学习资源
"""
from __future__ import annotations

# typing：类型注解，标注状态字典与列表类型
from typing import Any, Dict, List

# 导入基类：复用 LLM 调用与日志能力
from agents.base_agent import BaseAgent

# 系统提示词：指导 LLM 基于薄弱点生成 4 周复习计划，并约定严格的 JSON 字段。
# 其中 __REPORT__/__HISTORY__ 为自定义占位符（后续用 replace 注入），
# 示例 JSON 的花括号均双写转义 {{ }}。
SYSTEM_PROMPT = """\
你是技术学习规划师。基于候选人的面试薄弱点，生成一份 4 周复习计划。

面试评估报告：
__REPORT__

长期记忆（历史薄弱点）：
__HISTORY__

输出严格 JSON，字段说明：
- overall_advice：字符串，一句话总体建议
- weeks：数组，每个元素包含：
    week（数字）、theme（字符串）、goals（字符串，一句话目标）、
    daily_hours（数字）、resources（字符串，逗号分隔的资源列表）
- practice_projects：数组，每个元素是一个完整的项目建议字符串（不要拆分单个字）
- mock_interview_tips：数组，每个元素是一条完整的面试技巧字符串（不要拆分单个字）

示例格式：
{{
  "overall_advice": "加强实战经验积累",
  "weeks": [
    {{
      "week": 1,
      "theme": "系统设计",
      "goals": "掌握分布式系统核心概念",
      "daily_hours": 2,
      "resources": "《设计数据密集型应用》, Designing Data-Intensive Applications"
    }}
  ],
  "practice_projects": [
    "构建一个完整的RAG问答系统，包含文档解析、向量检索和答案生成",
    "实现一个支持多路召回的混合检索引擎"
  ],
  "mock_interview_tips": [
    "回答技术问题时先说结论再展开细节",
    "准备3个能体现系统思维的项目案例"
  ]
}}
"""


def _ensure_list(val: Any) -> List[str]:
    """
    确保字段为字符串列表：
    - 已是列表 → 过滤空项后返回
    - 字符串 → 按分号或换行拆分
    - 其他 → 转 str 后包装为单元素列表
    """
    # 情况一：已经是列表，逐项去空白并过滤掉空字符串
    if isinstance(val, list):
        # 收集清洗后的结果
        result = []
        # 遍历列表中的每一项
        for item in val:
            # 转为字符串并去除首尾空白
            s = str(item).strip()
            # 仅保留非空项
            if s:
                result.append(s)
        return result
    # 情况二：是字符串，按分隔符拆分为列表
    if isinstance(val, str):
        # 去除首尾空白
        val = val.strip()
        # 空字符串直接返回空列表
        if not val:
            return []
        # 按中文分号、英文分号、换行拆分
        # 局部导入 re：仅在需要时加载正则模块，减少模块级依赖
        import re
        # 用正则按一个或多个 “；/;/换行” 进行切分
        parts = re.split(r"[；;\n]+", val)
        # 去空白并过滤空片段后返回
        return [p.strip() for p in parts if p.strip()]
    # 情况三：其它类型，非空则转字符串包装为单元素列表，否则返回空列表
    return [str(val)] if val else []


class StudyPlannerAgent(BaseAgent):
    """个性化复习计划 Agent：根据评估薄弱点生成复习路径并推荐 GitHub 学习资源。"""

    # Agent 名称：用于日志与编排识别
    name = "study_planner"
    # Agent 描述：标识其职责为复习规划 + 资源推荐
    description = "个性化复习计划 + GitHub 资源推荐"

    def _fetch_github_resources(
        self, weaknesses: List[str]
    ) -> List[Dict[str, Any]]:
        """为每个薄弱点搜索 GitHub 学习资源

        参数：
            weaknesses：薄弱点字符串列表
        返回：
            列表，每项为 {"weakness": 薄弱点, "repos": 仓库列表}
        """
        # 局部导入 GitHub 搜索工具：延迟加载，避免在不需要时引入 MCP 依赖
        from mcp.tools.github_tool import search_learning_repos

        # 收集每个薄弱点对应的推荐结果
        github_recs = []
        # 最多处理前 5 个薄弱点，控制外部 API 调用次数
        for weakness in weaknesses[:5]:   # 最多处理5个薄弱点
            # 单个薄弱点搜索失败不应中断整体流程，故逐个 try/except
            try:
                # 调用工具搜索与该薄弱点相关的学习仓库，最多取 3 个
                repos = search_learning_repos(weakness, max_results=3)
                # 有结果：记录仓库并打印成功日志
                if repos:
                    github_recs.append({"weakness": weakness, "repos": repos})
                    self.logger.info(
                        "GitHub 搜索成功：{} → {} 个仓库", weakness, len(repos)
                    )
                # 无结果：打印告警并记录空仓库列表（保持结构一致）
                else:
                    self.logger.warning("GitHub 搜索无结果：{}", weakness)
                    github_recs.append({"weakness": weakness, "repos": []})
            # 异常：打印告警并记录空仓库列表，保证流程不中断
            except Exception as e:
                self.logger.warning("GitHub 搜索异常：{} → {}", weakness, e)
                github_recs.append({"weakness": weakness, "repos": []})
        # 返回所有薄弱点的推荐汇总
        return github_recs

    def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """生成复习计划并附加 GitHub 资源推荐。

        参数：
            state：共享状态字典，可含 final_report / long_term_weaknesses /
                   weaknesses_to_remember
        返回：
            更新后的状态字典，写入 study_plan 与 github_recommendations
        """
        # 取出整场面试的评估报告（含薄弱点等）
        report  = state.get("final_report", {})
        # 取出历史长期薄弱点（跨会话记忆）
        history = state.get("long_term_weaknesses", [])

        # 注入占位符组装提示词：报告截断 3000 字、历史截断 500 字，控制长度
        prompt = (
            SYSTEM_PROMPT
            .replace("__REPORT__",  str(report)[:3000])
            .replace("__HISTORY__", str(history)[:500])
        )

        # 调用 LLM 生成复习计划，得到 JSON 字典
        parsed = self.invoke_llm_json(prompt, "")

        # ★ 规范化所有字段，防止 LLM 返回字符串导致逐字遍历
        # 取出每周计划数组
        weeks = parsed.get("weeks", [])
        # 仅当 weeks 为列表时才规范化其内部字段
        if isinstance(weeks, list):
            # 逐周处理
            for w in weeks:
                # 仅处理字典型的周计划项
                if isinstance(w, dict):
                    # goals 和 resources 统一为字符串（显示用）
                    # 若 goals 是列表，用中文分号拼成字符串，避免前端逐字遍历
                    if isinstance(w.get("goals"), list):
                        w["goals"] = "；".join(w["goals"])
                    # 若 resources 是列表，用中文逗号拼成字符串
                    if isinstance(w.get("resources"), list):
                        w["resources"] = "，".join(w["resources"])

        # 规范化实践项目字段为字符串列表
        parsed["practice_projects"]   = _ensure_list(parsed.get("practice_projects",   []))
        # 规范化模拟面试技巧字段为字符串列表
        parsed["mock_interview_tips"] = _ensure_list(parsed.get("mock_interview_tips", []))
        # 写回规范化后的周计划
        parsed["weeks"]               = weeks

        # 将复习计划写入状态
        state["study_plan"] = parsed

        # ── GitHub 资源推荐 ────────────────────────────────────────────────────
        # 优先使用评估报告中的薄弱点
        weaknesses = report.get("weaknesses", [])
        # 报告中无薄弱点时，回退到本会话记忆中的薄弱点
        if not weaknesses:
            weaknesses = state.get("weaknesses_to_remember", [])

        # 针对薄弱点检索 GitHub 学习资源
        github_recs = self._fetch_github_resources(weaknesses)
        # 写入推荐结果
        state["github_recommendations"] = github_recs

        # 返回更新后的状态
        return state