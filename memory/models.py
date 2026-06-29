"""SQLAlchemy ORM 模型定义（长期记忆）"""
# 启用 PEP 563 延迟注解求值，使类型注解以字符串形式存在，避免前向引用问题
from __future__ import annotations

# 导入 datetime，用于为时间字段提供默认值（创建/更新时间戳）
from datetime import datetime

# 从 SQLAlchemy 导入字段类型与列定义工具：
# JSON（存储 JSON 数据）、Column（定义列）、DateTime（日期时间）、Integer（整型）、String（变长字符串）、Text（长文本）
from sqlalchemy import JSON, Column, DateTime, Integer, String, Text
# 导入 DeclarativeBase，作为 SQLAlchemy 2.0 风格声明式模型的基类
from sqlalchemy.orm import DeclarativeBase


# 声明式模型基类：所有 ORM 模型都继承它，SQLAlchemy 通过它收集表元数据
class Base(DeclarativeBase):
    pass


class UserProfile(Base):
    """用户画像（长期记忆核心）"""
    # 指定该模型对应的数据库表名
    __tablename__ = "user_profiles"

    # 主键 id：整型、自增，作为每条记录的唯一标识
    id = Column(Integer, primary_key=True, autoincrement=True)
    # user_id：用户唯一标识，长度 64，建唯一索引并禁止为空（业务层用它定位用户）
    user_id = Column(String(64), unique=True, index=True, nullable=False)
    # created_at：记录创建时间，默认取当前 UTC 时间
    created_at = Column(DateTime, default=datetime.utcnow)
    # updated_at：记录更新时间，创建时默认 UTC 时间，每次更新时（onupdate）自动刷新
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # total_interviews：累计面试次数，默认 0
    total_interviews = Column(Integer, default=0)
    # average_score：平均得分，默认 0
    average_score = Column(Integer, default=0)
    persistent_weaknesses = Column(JSON, default=list)  # 持久化薄弱点
    tech_strengths = Column(JSON, default=list)          # 技术优势


class InterviewRecord(Base):
    """面试历史记录"""
    # 指定该模型对应的数据库表名
    __tablename__ = "interview_records"

    # 主键 id：整型、自增
    id = Column(Integer, primary_key=True, autoincrement=True)
    # user_id：所属用户标识，建索引并禁止为空（便于按用户查询历史记录）
    user_id = Column(String(64), index=True, nullable=False)
    # session_id：本次面试会话标识，唯一且禁止为空（一条记录对应一次会话）
    session_id = Column(String(64), unique=True, nullable=False)
    # interview_date：面试日期，默认当前 UTC 时间
    interview_date = Column(DateTime, default=datetime.utcnow)
    # jd_title：岗位 JD 标题，长度上限 200
    jd_title = Column(String(200))
    # overall_score：本次面试综合得分
    overall_score = Column(Integer)
    # recommendation：录用建议（如 hire/no_hire 等），长度上限 32
    recommendation = Column(String(32))
    # report_json：完整面试报告，以 JSON 形式整体存储
    report_json = Column(JSON)
    # study_plan_json：学习计划，以 JSON 形式整体存储
    study_plan_json = Column(JSON)
    # weaknesses：本次面试暴露的薄弱点列表，默认空列表
    weaknesses = Column(JSON, default=list)


class KnowledgeNote(Base):
    """知识点笔记（用户标注/收藏的面试知识点）"""
    # 指定该模型对应的数据库表名
    __tablename__ = "knowledge_notes"

    # 主键 id：整型、自增
    id = Column(Integer, primary_key=True, autoincrement=True)
    # user_id：所属用户标识，建索引并禁止为空
    user_id = Column(String(64), index=True, nullable=False)
    # topic：知识点主题，禁止为空，长度上限 200
    topic = Column(String(200), nullable=False)
    # content：知识点正文内容，使用 Text 存储长文本
    content = Column(Text)
    # created_at：笔记创建时间，默认当前 UTC 时间
    created_at = Column(DateTime, default=datetime.utcnow)
