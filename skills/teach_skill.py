"""
知识讲解技能：针对某个概念深入浅出讲解
★ 使用方式：/teach <概念>
"""
# 启用延迟注解求值，支持前向引用并避免导入顺序问题
from __future__ import annotations

# 标准库类型注解：Any 表示任意类型，Dict 描述会话状态字典
from typing import Any, Dict

# 导入技能基类，本技能继承它以复用 LLM 调用与日志能力
from skills.base_skill import BaseSkill

# 讲解提示词模板：要求 LLM 用"面试官讲解"口吻分 3 层输出，__TOPIC__ 为占位符，运行时替换为实际概念
PROMPT = """\
请用「面试官讲解」的口吻，对以下概念进行 3 层讲解：
1. 一句话定义
2. 核心原理（用生动类比解释）
3. 面试高频追问点（列出 3 个）

概念：__TOPIC__

要求：300 字以内，条理清晰，语言通俗易懂。
"""

# 使用提示文本：当用户未提供概念时，返回该说明指导其正确用法
USAGE_HINT = """\
📖 知识讲解使用方式：
  /teach RAG           → 讲解 RAG 概念
  /teach LoRA          → 讲解 LoRA 概念
  /teach 注意力机制     → 讲解 Attention 机制
"""


class TeachSkill(BaseSkill):
    # 技能名，作为注册表查找键
    name = "teach"
    # 技能描述，用于帮助/展示
    description = "知识讲解：深入浅出讲解某个技术概念"
    # 触发关键词，用于意图识别路由到本技能
    trigger_keywords = ["讲解", "teach", "解释", "什么是"]

    def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """执行知识讲解：解析用户输入的概念，调用 LLM 生成讲解文本并写回状态。

        参数:
            state: 会话状态字典，需包含 user_input。
        返回:
            更新后的会话状态字典，agent_reply 为讲解结果或使用提示。
        """
        # 读取用户原始输入并去除首尾空白；缺失时用空串兜底
        user_input = state.get("user_input", "").strip()

        # 移除 /teach 前缀
        # 若输入以 /teach 开头（忽略大小写），切掉前 6 个字符的前缀并去空白，得到纯概念文本
        if user_input.lower().startswith("/teach"):
            user_input = user_input[6:].strip()

        # 概念为空：返回使用提示并提前结束，避免向 LLM 发送无意义请求
        if not user_input:
            state["agent_reply"] = USAGE_HINT
            return state

        # 将清洗后的输入作为待讲解的概念主题
        topic = user_input
        # 用实际概念替换提示词模板中的占位符，生成最终提示
        prompt = PROMPT.replace("__TOPIC__", topic)
        # 调用 LLM 生成讲解；temperature=0.7 让表达更自然多样，system_prompt 传空串
        reply = self.invoke_llm(prompt, "", temperature=0.7)

        # 组装带标题的回复文本并写入状态，供上层返回给用户
        state["agent_reply"] = f"📖 **{topic}** 讲解：\n\n{reply}"
        # 记录日志，便于追踪本次讲解的概念
        self.logger.info(f"TeachSkill 讲解概念：{topic}")
        # 返回更新后的会话状态
        return state