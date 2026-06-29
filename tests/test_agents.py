"""Agent 单元测试"""
# 引入 pytest，用于跳过等测试控制能力
import pytest
# 意图路由 Agent：负责判断用户输入属于哪种意图（开始面试 / 闲聊等）
from agents.intent_router import IntentRouterAgent
# JD 分析 Agent：负责解析职位描述（Job Description）文本，抽取技术栈等结构化信息
from agents.jd_analyzer import JDAnalyzerAgent


# 测试意图路由：当输入为命令 "/interview" 时，应被识别为开始面试意图
def test_intent_router_interview():
    # 实例化意图路由 Agent
    agent = IntentRouterAgent()
    # 构造输入状态，模拟用户输入了 "/interview" 命令
    state = {"user_input": "/interview"}
    # 运行 Agent，得到包含 intent 字段的结果状态
    result = agent.run(state)
    # 打印结果便于调试观察
    print(result)
    # 断言识别出的意图为 "start_interview"，验证命令式输入能被正确路由
    assert result["intent"] == "start_interview"


# 测试意图路由：当输入为普通寒暄 "你好" 时，应被识别为闲聊或未知意图（而非面试命令）
def test_intent_router_chat():
    # 实例化意图路由 Agent
    agent = IntentRouterAgent()
    # 构造输入状态，模拟用户发送了普通问候语
    state = {"user_input": "你好"}
    # 运行 Agent 得到意图判定结果
    result = agent.run(state)
    # 打印结果便于调试观察
    print(result)
    # 断言意图落在 chat 或 unknown 两类之一，验证非命令输入不会被误判为面试意图
    assert result["intent"] in ("chat", "unknown")


# 标记跳过：JD 分析依赖 LLM 接口，需要有效的 API Key，否则无法运行
@pytest.mark.skip(reason="需要 LLM API Key")
# 测试 JD 分析 Agent 能否从职位描述中解析出技术栈等结构化字段
def test_jd_analyzer():
    # 实例化 JD 分析 Agent
    agent = JDAnalyzerAgent()
    # 构造输入状态，提供一段中文职位描述文本
    state = {"jd_text": "招聘 Python 后端工程师，要求熟悉 FastAPI、MySQL、Redis"}
    # 运行 Agent，得到解析结果（应包含 jd_parsed 等字段）
    result = agent.run(state)
    # 打印结果便于调试观察
    print(result)
    # 断言解析结果 jd_parsed 中包含 tech_stack 键，验证技术栈抽取成功（get 默认空字典避免 KeyError）
    assert "tech_stack" in result.get("jd_parsed", {})


# 当脚本被直接运行时，依次手动执行三个测试函数，方便本地一次性调试
if __name__ == "__main__":
    # 执行：命令式输入的意图路由测试
    test_intent_router_interview()
    # 执行：寒暄输入的意图路由测试
    test_intent_router_chat()
    # 执行：JD 分析测试（注意：被 skip 装饰器跳过的是 pytest 收集场景，直接调用时仍会运行函数体）
    test_jd_analyzer()

    # 运行测试：pytest -v tests/test_agents.py
    # python -m tests.test_agents