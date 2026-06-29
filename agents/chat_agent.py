"""
闲聊 Agent：处理非面试主链路的日常聊天
"""
from __future__ import annotations

# typing：类型注解，标注状态字典的类型
from typing import Any, Dict

# 导入基类：复用统一的 LLM 调用与日志能力
from agents.base_agent import BaseAgent

# 系统提示词：设定闲聊助手的人设与回复约束（友好、专业、简短）
SYSTEM_PROMPT = (
    "你是 InterviewAgent 的助手，一位友好、专业的 AI 伙伴。"
    "用户不是在正式面试，而是闲聊/提问/咨询。请简短回复（100 字以内）。"
)


class ChatAgent(BaseAgent):
    """闲聊 Agent：处理非面试主链路的日常对话，直接调用 LLM 生成简短回复。"""

    # Agent 名称：用于日志标签与编排识别
    name = "chat"
    # Agent 描述：标识其职责为闲聊
    description = "闲聊 Agent"

    def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """处理一次闲聊请求。

        参数：
            state：共享状态字典，需包含 user_input（用户输入）
        返回：
            更新后的状态字典，写入 agent_reply（助手回复）
        """
        # 从状态中取出用户输入，缺省为空字符串
        user_input = state.get("user_input", "")
        # ★ 修复：invoke_llm 不接受 temperature 参数，temperature 在构造时设置
        # 用闲聊系统提示词与用户输入调用 LLM，获取回复文本
        reply = self.invoke_llm(SYSTEM_PROMPT, user_input)
        # 将回复写回状态，供下游/前端展示
        state["agent_reply"] = reply
        # 返回更新后的状态，符合 LangGraph 节点 state -> state 约定
        return state