"""Agent 模块：所有专职 Agent 的统一入口"""
# 本文件作为 agents 包的入口，集中导入并重新导出所有专职 Agent，
# 让外部只需 `from agents import XxxAgent` 即可使用，屏蔽内部文件结构。

# 导入抽象基类：定义所有 Agent 的统一接口与公共能力（LLM 调用、重试等）
from agents.base_agent import BaseAgent
# 导入意图路由 Agent：编排层入口，判断用户请求走哪条链路
from agents.intent_router import IntentRouterAgent
# 导入 JD 解析 Agent：把岗位描述解析为结构化数据
from agents.jd_analyzer import JDAnalyzerAgent
# 导入简历分析 Agent：将简历与 JD 做匹配打分
from agents.resume_analyzer import ResumeAnalyzerAgent
# 导入出题规划 Agent：基于 JD/简历/题库规划面试题目
from agents.question_planner import QuestionPlannerAgent
# 导入面试官 Agent：多轮交互、追问深挖的核心
from agents.interviewer import InterviewerAgent
# 导入评估 Agent：单题打分 + 生成整场评估报告
from agents.evaluator import EvaluatorAgent
# 导入复习计划 Agent：根据薄弱点生成学习路径并推荐资源
from agents.study_planner import StudyPlannerAgent
# 导入闲聊 Agent：处理非面试主链路的日常对话
from agents.chat_agent import ChatAgent

# 显式声明包对外公开的符号集合：
# 使用 `from agents import *` 时只导出下列名称，同时作为对外 API 的清单
__all__ = [
    "BaseAgent",
    "IntentRouterAgent",
    "JDAnalyzerAgent",
    "ResumeAnalyzerAgent",
    "QuestionPlannerAgent",
    "InterviewerAgent",
    "EvaluatorAgent",
    "StudyPlannerAgent",
    "ChatAgent",
]
