"""
Agent 基类：所有专职 Agent 的统一接口与公共能力
- 统一 run() 入口
- 统一 LLM 调用封装（基于 LangChain ChatTongyi）
- 统一日志 / 错误重试
"""
from __future__ import annotations

# ---------- 标准库 ----------
# json：解析 LLM 返回的 JSON 文本
import json
# abc：提供抽象基类 ABC 与 abstractmethod，强制子类实现 run()
from abc import ABC, abstractmethod
# typing：类型注解，提升可读性与静态检查能力
from typing import Any, Dict, List, Optional

# ---------- 第三方库 ----------
# LangChain 消息类型：构造发给 LLM 的系统消息 / 用户消息
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
# LangChain Prompt 模板：用于 build_prompt 渲染模板字符串
from langchain_core.prompts import ChatPromptTemplate
# ChatOpenAI：OpenAI 兼容的聊天模型客户端（此处用于调用通义千问兼容接口）
from langchain_openai import ChatOpenAI
# loguru：结构化日志库，便于按 agent 维度打标签
from loguru import logger
# tenacity：失败重试装饰器，应对 LLM 调用的瞬时网络/限流错误
from tenacity import retry, stop_after_attempt, wait_exponential

# ---------- 项目内部 ----------
# settings：全局配置（模型名、温度、API Key 等），集中管理
from config import settings


class BaseAgent(ABC):
    """所有 Agent 的抽象基类"""

    # 类级属性：Agent 的唯一名称（用于日志标签与编排识别），子类应覆盖
    name: str = "base"
    # 类级属性：Agent 的功能描述，子类应覆盖为具体说明
    description: str = ""

    def __init__(self) -> None:
        """初始化 Agent：构建底层 LLM 客户端与带名称标签的日志器。"""
        # 兼容 OpenAI 接口调用通义千问（通过 DashScope 兼容模式）
        # 用 ChatOpenAI 指向 DashScope 的 OpenAI 兼容端点，复用成熟的 OpenAI 协议
        self.llm = ChatOpenAI(
            # 模型名称：从全局配置读取，便于统一切换
            model=settings.llm_model,
            # 采样温度：控制生成随机性，配置化以适配不同场景
            temperature=settings.llm_temperature,
            # 最大生成 token 数：限制单次回复长度，控制成本
            max_tokens=settings.llm_max_tokens,
            # API 密钥：使用 DashScope 的密钥进行鉴权
            api_key=settings.dashscope_api_key,
            # 基础 URL：指向 DashScope 的 OpenAI 兼容模式接口地址
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        # 绑定 agent 名称到日志上下文，输出日志时可区分来源 Agent
        self.logger = logger.bind(agent=self.name)

    # ---------- 公共 LLM 调用（带重试） ----------
    # 使用 tenacity 装饰器为 LLM 调用增加自动重试，提升健壮性
    @retry(
        # 最多尝试 3 次后停止
        stop=stop_after_attempt(3),
        # 指数退避等待：首次 1s，逐次翻倍，最大 8s，避免雪崩式重试
        wait=wait_exponential(multiplier=1, min=1, max=8),
        # 重试耗尽后重新抛出原始异常，而非 tenacity 包装异常
        reraise=True,
    )
    def invoke_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: Optional[float] = None,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> str:
        """调用 LLM 并返回文本，自动重试

        参数：
            system_prompt：系统提示词，设定模型角色与约束
            user_prompt：用户输入内容
            temperature：可选，临时覆盖采样温度
            response_format：可选，指定返回格式（如 {"type": "json_object"}）
        返回：
            LLM 生成的文本内容（若为空则返回空字符串）
        """
        # 构造消息列表：系统消息在前设定角色，用户消息在后承载具体输入
        messages: List[BaseMessage] = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        # 默认使用实例的 LLM 客户端
        llm = self.llm
        # 若显式传入温度，则通过 bind 生成带新温度的客户端副本（不改动原实例）
        if temperature is not None:
            llm = self.llm.bind(temperature=temperature)
        # 若指定了返回格式，则绑定该参数（如强制 JSON 输出）
        if response_format:
            llm = llm.bind(response_format=response_format)  # type: ignore[attr-defined]
        # 发起同步调用，得到模型响应对象
        resp = llm.invoke(messages)
        # 返回响应文本内容；为 None 时用空字符串兜底，避免下游报错
        return resp.content or ""

    def invoke_llm_json(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        """调用 LLM 并强制返回 JSON

        在系统提示词后追加 JSON 约束，并解析返回结果为 dict；
        若解析失败则尝试截取首尾花括号兜底。
        参数：
            system_prompt：系统提示词
            user_prompt：用户输入内容
        返回：
            解析后的 JSON 字典
        """
        # 调用底层 invoke_llm：拼接 JSON 约束、降低温度以提高结构稳定性、强制 JSON 格式
        raw = self.invoke_llm(
            # 在原提示后追加强约束，提示模型只输出合法 JSON
            system_prompt + "\n\n请严格以合法 JSON 输出，不要任何多余文字。",
            user_prompt,
            # 低温度让输出更确定、更易解析
            temperature=0.2,
            # 启用 JSON 对象返回模式
            response_format={"type": "json_object"},
        )
        # 尝试直接解析为 JSON 字典
        try:
            return json.loads(raw)
        # 解析失败时进入兜底逻辑
        except json.JSONDecodeError:
            # 记录告警并打印前 200 字符便于排查
            self.logger.warning("LLM 返回非法 JSON，尝试提取：{}", raw[:200])
            # 兜底：尝试截取第一个 { ... }
            # 定位首个 '{' 与最后一个 '}'，截取其间内容再次解析
            start, end = raw.find("{"), raw.rfind("}") + 1
            # 若找到合理的花括号区间，则解析该子串
            if start >= 0 and end > start:
                return json.loads(raw[start:end])
            # 仍无法解析则抛出异常，交由上层（或重试机制）处理
            raise

    def build_prompt(self, template: str, **kwargs: Any) -> str:
        """用 LangChain 模板渲染提示词。

        参数：
            template：含占位符的模板字符串
            **kwargs：填充模板的键值对
        返回：
            渲染后的完整提示词字符串
        """
        # 由模板字符串创建 ChatPromptTemplate，并用关键字参数填充占位符
        return ChatPromptTemplate.from_template(template).format(**kwargs)

    # ---------- 统一入口 ----------
    # 抽象方法：强制每个子类实现自己的处理逻辑
    @abstractmethod
    def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """LangGraph 节点签名：state -> state

        统一入口约定：接收共享状态字典，处理后返回更新过的状态字典，
        以便在 LangGraph 编排图中作为节点串联。
        """
        # 抽象方法无实现体，由子类覆盖
        ...

    def __repr__(self) -> str:
        """返回便于调试的对象字符串表示，包含 Agent 名称。"""
        # 输出形如 <Agent name=xxx> 的可读表示
        return f"<Agent name={self.name}>"
