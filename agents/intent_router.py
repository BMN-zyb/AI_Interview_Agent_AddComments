"""
意图路由器 Agent：
根据用户输入，判断走哪条链路——面试/技能练习/闲聊/简历上传/JD 输入等
是整个编排层的入口。
"""
from __future__ import annotations

# typing：类型注解；Literal 用于把意图限定为有限的字面量集合
from typing import Any, Dict, Literal

# loguru：记录意图识别日志
from loguru import logger

# 导入基类：复用 LLM 调用能力
from agents.base_agent import BaseAgent

# 意图类型枚举：用 Literal 约束所有合法意图取值，便于静态检查与可读性
IntentType = Literal[
    "start_interview",   # 开始一次完整面试
    "answer_question",   # 回答当前面试题目
    "upload_resume",     # 上传简历
    "input_jd",          # 输入 JD
    "use_skill",         # 使用技能（quiz/teach/compare/project）
    "chat",              # 普通闲聊
    "unknown",
]

# ★ 修复1：JSON 示例中的花括号双写转义 {{ }}
# 系统提示词：指导 LLM 进行意图分类，并以严格 JSON 返回结果。
# 注意其中 {{ }} 为转义花括号，避免后续若用 format() 时被误当作占位符。
SYSTEM_PROMPT = """你是一个意图识别专家。根据用户输入，判断其意图类别。
候选类别：
- start_interview：用户想要开始一场模拟面试
- answer_question：用户正在回答上一道面试题
- upload_resume：用户表达了想上传/提交简历的意图
- input_jd：用户粘贴了岗位 JD 或描述
- use_skill：用户想使用某项技能（快速测验/知识讲解/项目亮点提炼/技术对比）
- chat：普通聊天、问候、咨询

输出格式（严格 JSON）：
{{"intent": "<类别>", "confidence": 0.0~1.0, "skill": "quiz|teach|project|compare|null"}}
"""


class IntentRouterAgent(BaseAgent):
    """意图路由器 Agent：判断用户请求应进入哪条业务链路，是编排层的入口。"""

    # Agent 名称：用于日志与编排识别
    name = "intent_router"
    # Agent 描述：标识其职责为请求分流
    description = "意图路由器：分流用户请求"

    def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """识别用户意图并写入状态。

        参数：
            state：共享状态字典，需包含 user_input
        返回：
            更新后的状态字典，写入 intent / intent_confidence / 可选 skill_name
        """
        # 取出用户输入并去除首尾空白
        user_input = state.get("user_input", "").strip()
        # 输入为空时直接归类为闲聊，避免无谓的 LLM 调用
        if not user_input:
            state["intent"] = "chat"
            return state

        # 快捷指令（不走 LLM，节省 token）
        # 以 /interview 开头：直接判定为开始面试
        if user_input.startswith("/interview"):
            state["intent"] = "start_interview"
            return state

        # 以 /skill 开头：直接判定为使用技能
        if user_input.startswith("/skill"):
            state["intent"] = "use_skill"
            return state

        # 以 /jd 开头：判定为输入 JD，并截掉前缀 "/jd" 取出真正的 JD 文本
        if user_input.startswith("/jd"):
            state["intent"] = "input_jd"
            # 去掉前 3 个字符（"/jd"）并去空白，得到 JD 正文
            state["jd_text"] = user_input[3:].strip()
            return state

        # ★ 修复2：避免 user_input 中含 { } 导致 format 报错
        # 直接用 f-string 拼接用户输入，绕开 format() 对花括号的解析问题
        user_prompt = f"用户输入：{user_input}"

        # 调用 LLM 进行意图分类，返回解析后的 JSON 字典
        parsed = self.invoke_llm_json(SYSTEM_PROMPT, user_prompt)

        # 取出识别到的意图，缺省回退为闲聊
        intent = parsed.get("intent", "chat")

        # 记录意图识别结果：截取输入前 50 字、识别意图与置信度，便于排查
        logger.info(
            "意图识别: {} -> {} (conf={})",
            user_input[:50],
            intent,
            parsed.get("confidence"),
        )

        # 写入识别到的意图
        state["intent"] = intent
        # 写入置信度，缺省为 0.0
        state["intent_confidence"] = parsed.get("confidence", 0.0)

        # 若识别出具体技能名，则记录到状态供技能链路使用
        if parsed.get("skill"):
            state["skill_name"] = parsed["skill"]

        # 返回更新后的状态
        return state