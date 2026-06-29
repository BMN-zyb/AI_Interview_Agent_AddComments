"""
Skill 基类：有状态的多轮交互能力模块
与无状态 Tool 不同，Skill 维护自己的会话状态。
"""
# 启用 PEP 563 延迟注解求值，使类型注解以字符串形式存储，支持前向引用并避免导入顺序问题
from __future__ import annotations

# 标准库：ABC 提供抽象基类支持，abstractmethod 用于标记子类必须实现的方法
from abc import ABC, abstractmethod
# 标准库：Any/Dict 用于类型注解，描述任意值与字典结构
from typing import Any, Dict

# 项目内部：复用 BaseAgent 的能力（如 self.logger、invoke_llm、invoke_llm_json）
from agents.base_agent import BaseAgent


# 同时继承 BaseAgent（获得 LLM 调用与日志能力）和 ABC（成为抽象基类，禁止直接实例化）
class BaseSkill(BaseAgent, ABC):
    """Skill 基类"""

    # 技能的唯一标识名，子类需覆盖；用于在 SkillRegistry 中作为注册键
    name: str = "base_skill"
    # 技能的功能描述，子类覆盖后用于展示/帮助信息
    description: str = ""
    # 触发该技能的关键词列表，子类覆盖后用于意图识别/路由
    trigger_keywords: list[str] = []

    def __init__(self) -> None:
        """初始化技能实例：调用父类构造完成日志与 LLM 客户端等基础设施的装配。"""
        # 调用 BaseAgent 的构造函数，完成 logger、模型客户端等公共初始化
        super().__init__()
        # skill_state 维护在 state["skill_state"] 中，由调用者注入

    def get_skill_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """从全局会话状态中读取本技能的私有状态。

        参数:
            state: 整个会话的状态字典。
        返回:
            技能私有状态字典；若不存在或为假值则返回空字典，保证调用方拿到可用的 dict。
        """
        # 取出 skill_state；用 "or {}" 兜底，避免值为 None 时返回 None 导致后续 .get 报错
        return state.get("skill_state", {}) or {}

    def set_skill_state(self, state: Dict[str, Any], new_state: Dict[str, Any]) -> None:
        """将本技能的私有状态写回全局会话状态，供下一轮交互读取。

        参数:
            state: 整个会话的状态字典（原地修改）。
            new_state: 要保存的技能私有状态。
        """
        # 直接覆盖 skill_state 字段，实现技能跨轮次的状态持久化
        state["skill_state"] = new_state

    # 抽象方法：强制每个具体技能子类实现自己的执行逻辑，否则无法实例化
    @abstractmethod
    def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """技能主入口（抽象）：接收会话状态，处理后返回更新过的会话状态。

        参数:
            state: 会话状态字典，通常含 user_input、skill_state 等字段。
        返回:
            更新后的会话状态字典（一般会写入 agent_reply）。
        """
        # 抽象方法无具体实现，省略号占位，由子类提供实际逻辑
        ...
