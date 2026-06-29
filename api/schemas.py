"""
Pydantic 请求/响应数据模型
"""
# 启用延迟注解求值，使类型注解以字符串保存，避免前向引用与导入顺序问题。
from __future__ import annotations

# ── 标准库导入 ────────────────────────────────────────────────────────────────
# typing：提供通用类型标注（任意类型、字典、列表、可选值），用于精确描述数据结构。
from typing import Any, Dict, List, Optional
# ── 第三方库导入 ──────────────────────────────────────────────────────────────
# pydantic：数据校验与序列化框架；BaseModel 为模型基类，Field 用于声明字段约束与元信息。
from pydantic import BaseModel, Field


# ── 请求模型 ──────────────────────────────────────────────────────────────────

# 开始面试请求体：客户端发起一场新面试时提交的参数。
class StartInterviewRequest(BaseModel):
    # 岗位 JD 文本，必填（... 表示必填，无默认值）。
    jd_text:         str            = Field(..., description="岗位 JD 文本")
    # 简历文本，选填，默认空字符串。
    resume_text:     str            = Field("",  description="简历文本（可选）")
    # 用户标识，默认 "web_user"，用于区分不同来源的用户。
    user_id:         str            = Field("web_user", description="用户 ID")
    # 出题数量，默认 5，并限制取值范围在 1~20 之间（ge=大于等于，le=小于等于）。
    total_questions: int            = Field(5,   ge=1, le=20, description="出题数量")
    # TTS 语音音色，选填；None 表示使用默认音色。
    voice:           Optional[str]  = Field(None, description="TTS 音色")


# 提交回答请求体：客户端针对当前问题作答时提交的参数。
class AnswerRequest(BaseModel):
    # 会话 ID，必填，用于定位该回答所属的面试会话。
    session_id:  str = Field(..., description="会话 ID")
    # 用户回答的文本内容，必填。
    answer:      str = Field(..., description="用户回答文本")


# 技能调用请求体：在面试中触发某项辅助技能（出题/讲解/项目/对比）时使用。
class SkillRequest(BaseModel):
    # 会话 ID，必填，用于定位所属面试会话。
    session_id:  str = Field(..., description="会话 ID")
    # 技能名称，必填，取值如 quiz/teach/project/compare。
    skill_name:  str = Field(..., description="技能名称: quiz/teach/project/compare")
    # 技能输入内容，选填，默认空字符串。
    user_input:  str = Field("",  description="技能输入内容")


# ── 响应模型 ──────────────────────────────────────────────────────────────────

# 开始面试响应体：返回新建会话与第一道题目的相关信息。
class StartInterviewResponse(BaseModel):
    # 新建的会话 ID。
    session_id:           str
    # 当前（第一道）题目的文本。
    question:             str
    # 当前题目的序号索引。
    question_index:       int
    # 本场面试的题目总数。
    total_questions:      int
    # 当前题目的难度等级。
    difficulty:           str
    # 解析出的岗位标题，默认空字符串。
    jd_title:             str = ""


# 提交回答响应体：返回作答后的状态、下一题/追问及（结束时的）报告等信息。
class AnswerResponse(BaseModel):
    # 所属会话 ID。
    session_id:           str
    # 面试是否已结束的标志。
    interview_finished:   bool
    # 是否需要对当前回答进行追问的标志。
    should_followup:      bool
    question:             str            = ""   # 下一题或追问
    # 下一题的序号索引，默认 0。
    question_index:       int            = 0
    # 题目总数，默认 0。
    total_questions:      int            = 0
    # 难度等级，默认 "medium"。
    difficulty:           str            = "medium"
    # 最终面试报告，选填；仅在面试结束时返回。
    final_report:         Optional[Dict[str, Any]] = None
    # 学习计划，选填；仅在面试结束时返回。
    study_plan:           Optional[Dict[str, Any]] = None
    # GitHub 项目推荐列表，默认空列表。
    github_recommendations: List[Dict[str, Any]]   = []


# 报告响应体：单独查询某场面试的最终报告与学习建议时返回。
class ReportResponse(BaseModel):
    # 所属会话 ID。
    session_id:             str
    # 最终面试报告内容。
    final_report:           Dict[str, Any]
    # 学习计划内容。
    study_plan:             Dict[str, Any]
    # GitHub 项目推荐列表，默认空列表。
    github_recommendations: List[Dict[str, Any]] = []


# 健康检查响应体：用于探活接口返回服务状态。
class HealthResponse(BaseModel):
    # 服务状态，默认 "ok"。
    status:  str = "ok"
    # 服务版本号，默认 "1.0.0"。
    version: str = "1.0.0"


# 文件上传响应体：返回上传文件的解析结果。
class UploadResponse(BaseModel):
    # 上传的文件名。
    filename:    str
    # 从文件中解析出的文本内容。
    text:        str
    # 解析文本的字符数。
    char_count:  int


# 错误响应体：统一的错误返回结构。
class ErrorResponse(BaseModel):
    # 错误简述（必填字段，无默认值）。
    error:   str
    # 错误详情，默认空字符串。
    detail:  str = ""