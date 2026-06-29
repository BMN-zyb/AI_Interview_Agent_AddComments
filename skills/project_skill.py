"""
项目亮点提炼技能：帮候选人从简历项目中提炼 STAR 表达
★ 使用方式：/project <项目描述>
"""
# 启用延迟注解求值，支持前向引用并避免导入顺序问题
from __future__ import annotations

# 标准库类型注解：Any 表示任意类型，Dict 描述会话状态字典
from typing import Any, Dict

# 导入技能基类，本技能继承它以复用 LLM 调用与日志能力
from skills.base_skill import BaseSkill

# 提炼提示词模板：要求 LLM 输出 3 条 STAR 亮点的 JSON；__PROJECT_DESC__ 为项目描述占位符
# 注意模板中 {{ }} 为字面花括号转义，配合 .format 风格使用时不会被当作替换字段
PROMPT = """\
基于候选人的项目描述，提炼 3 条 STAR（情境/任务/行动/结果）表达，便于面试中展示亮点。

项目描述：
__PROJECT_DESC__

要求：
1. 每条 STAR 要突出技术难点和个人贡献
2. 结果部分尽量量化（如"性能提升40%"）
3. 提炼面试中最容易被追问的关键词

输出 JSON：
{{
  "highlights": [
    {{
      "title": "亮点标题",
      "star": "S(情境): ... T(任务): ... A(行动): ... R(结果): ...",
      "keyword": "核心关键词",
      "likely_followup": "面试官可能的追问"
    }}
  ],
  "elevator_pitch": "30秒电梯演讲版本（用于自我介绍）"
}}
"""

# 使用提示文本：当用户未提供项目描述时返回，指导其正确用法
USAGE_HINT = """\
💼 项目亮点提炼使用方式：
  /project 我负责开发了一个RAG知识库系统，使用Weaviate向量数据库...
  （粘贴你的项目描述，AI帮你提炼STAR亮点）
"""


class ProjectSkill(BaseSkill):
    # 技能名，作为注册表查找键
    name = "project"
    # 技能描述，用于帮助/展示
    description = "项目亮点提炼：从项目描述中提炼 STAR 表达"
    # 触发关键词，用于意图识别路由到本技能
    trigger_keywords = ["项目", "project", "亮点"]

    def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """执行项目亮点提炼：解析项目描述，调用 LLM 生成 STAR 亮点并格式化写回状态。

        参数:
            state: 会话状态字典，需包含 user_input（项目描述）。
        返回:
            更新后的会话状态字典，agent_reply 为亮点列表或使用提示。
        """
        # 读取用户原始输入并去除首尾空白；缺失时用空串兜底
        user_input = state.get("user_input", "").strip()

        # 移除 /project 前缀
        # 若输入以 /project 开头（忽略大小写），切掉前 8 个字符的前缀并去空白，得到纯项目描述
        if user_input.lower().startswith("/project"):
            user_input = user_input[8:].strip()

        # 项目描述为空：返回使用提示并提前结束
        if not user_input:
            state["agent_reply"] = USAGE_HINT
            return state

        # 将项目描述（截断至前 2000 字防止超出上下文）替换进模板，生成最终提示
        prompt = PROMPT.replace("__PROJECT_DESC__", user_input[:2000])
        # 调用 LLM 并解析为 JSON 字典；system_prompt 传空串
        parsed = self.invoke_llm_json(prompt, "")

        # 从解析结果取出亮点列表；缺失时默认空列表
        highlights = parsed.get("highlights", [])
        # 从解析结果取出电梯演讲文本；缺失时默认空串
        elevator   = parsed.get("elevator_pitch", "")

        # 初始化输出文本行列表，首行为亮点数量概述
        lines = [f"💼 为你提炼了 {len(highlights)} 个项目亮点：\n"]
        # 枚举每个亮点，序号从 1 开始，逐条格式化追加到输出
        for i, h in enumerate(highlights, 1):
            # 亮点序号与标题
            lines.append(f"【亮点 {i}】{h.get('title', '')}")
            # STAR 正文（缩进展示）
            lines.append(f"  {h.get('star', '')}")
            # 核心关键词
            lines.append(f"  🏷️  关键词：{h.get('keyword', '')}")
            # 面试官可能的追问点
            lines.append(f"  ❓ 可能追问：{h.get('likely_followup', '')}")
            # 追加空行，分隔不同亮点，提升可读性
            lines.append("")

        # 若存在电梯演讲内容，追加到末尾
        if elevator:
            lines.append(f"🎤 30秒电梯演讲：\n{elevator}")

        # 用换行拼接所有行作为最终回复写入状态
        state["agent_reply"] = "\n".join(lines)
        # 记录日志，输入描述截断到前 30 字以避免日志过长
        self.logger.info(f"ProjectSkill 提炼亮点：{user_input[:30]}...")
        # 返回更新后的会话状态
        return state