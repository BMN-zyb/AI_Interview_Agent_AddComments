"""
长期记忆（MySQL）：用户画像 + 历史薄弱点 + 面试记录
"""
# 启用延迟注解求值，便于在注解中使用尚未定义/前向引用的类型
from __future__ import annotations

# 导入类型注解：Any（任意类型）、Dict/List（容器）、Optional（可空）
from typing import Any, Dict, List, Optional

# 导入 loguru 日志器，统一记录连接状态与异常信息
from loguru import logger

# 导入全局配置对象，读取 MySQL 连接串等设置
from config import settings
# 导入 ORM 基类与模型：Base（建表元数据）、InterviewRecord（面试记录表）、UserProfile（用户画像表）
from memory.models import Base, InterviewRecord, UserProfile


def _make_engine_and_session():
    """延迟导入，避免 MySQL 未启动时崩溃"""
    # 在函数内部导入 SQLAlchemy 组件，确保模块加载阶段不强依赖数据库可用
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    # 创建数据库引擎，并配置连接池参数
    engine = create_engine(
        settings.mysql_url,    # 数据库连接串
        pool_pre_ping=True,    # 取连接前先 ping 一次，自动剔除失效连接
        pool_size=5,           # 连接池常驻连接数
        max_overflow=10,       # 允许超出池大小临时创建的最大连接数
    )
    # 基于该引擎创建会话工厂，后续用它生成 Session
    SessionLocal = sessionmaker(bind=engine)
    # 返回引擎与会话工厂，供上层缓存复用
    return engine, SessionLocal


class LongTermMemory:
    """基于 MySQL 的长期记忆（带容错）"""

    def __init__(self) -> None:
        # 数据库引擎句柄，惰性创建，初始为空
        self._engine      = None
        # 会话工厂占位，惰性创建，初始为空
        self._SessionLocal = None
        self._available   = None   # None=未检测, True/False=已检测

    def _ensure_connected(self) -> bool:
        """惰性连接，首次调用时尝试连接，失败则标记不可用"""
        # 已确认可用：直接返回 True
        if self._available is True:
            return True
        # 已确认不可用：直接返回 False（本进程内不再重试）
        if self._available is False:
            return False
        # 首次检测
        try:
            # 创建引擎与会话工厂
            self._engine, self._SessionLocal = _make_engine_and_session()
            # 测试连通性
            # 打开一条连接并执行 SELECT 1 验证数据库可达（这里用 __import__ 动态取 sqlalchemy.text 构造 SQL 文本）
            with self._engine.connect() as conn:
                conn.execute(__import__("sqlalchemy").text("SELECT 1"))
            # 连通成功：标记为可用
            self._available = True
            logger.info("MySQL 长期记忆已连接")
            return True
        except Exception as e:
            # 连接失败：标记为不可用，长期记忆能力整体降级（读返回空、写直接跳过）
            self._available = False
            logger.warning("MySQL 不可用，长期记忆降级为空：{}", e)
            return False

    def create_tables(self) -> None:
        """根据 ORM 模型在数据库中创建所有表（数据库不可用时直接跳过）。"""
        # 未连接则不执行建表
        if not self._ensure_connected():
            return
        try:
            # 依据 Base 收集的所有模型元数据创建表（已存在的表会自动跳过）
            Base.metadata.create_all(self._engine)
            logger.info("长期记忆表已创建")
        except Exception as e:
            # 建表异常仅告警，不抛出
            logger.warning("创建表失败：{}", e)

    # ── 用户画像 ──────────────────────────────────────────────────────────────

    def get_or_create_profile(self, user_id: str) -> Optional[UserProfile]:
        """获取用户画像，不存在则创建；返回脱离会话的安全副本（数据库不可用返回 None）。"""
        # 未连接则返回 None
        if not self._ensure_connected():
            return None
        try:
            # 延迟导入查询构造器
            from sqlalchemy import select
            # 打开数据库会话（with 确保自动提交/关闭资源）
            with self._SessionLocal() as session:
                # 按 user_id 查询画像，至多一条
                profile = session.execute(
                    select(UserProfile).where(UserProfile.user_id == user_id)
                ).scalar_one_or_none()
                # 画像不存在：新建一条并落库，再刷新拿到数据库生成的字段
                if profile is None:
                    profile = UserProfile(user_id=user_id)
                    session.add(profile)
                    session.commit()
                    session.refresh(profile)
                # ★ 关键：在 session 关闭前 eager 读取所有需要的字段
                # 把 JSON 字段复制成新的列表，避免会话关闭后再访问触发懒加载
                weaknesses = list(profile.persistent_weaknesses or [])
                strengths  = list(profile.tech_strengths or [])
                # 读取累计面试次数，None 时兜底为 0
                total      = profile.total_interviews or 0
                # 构造一个普通对象返回，避免 detached instance 问题
                # 用 __new__ 绕过 __init__ 创建空壳 UserProfile，仅承载已读取的数据（非 ORM 托管对象）
                result = UserProfile.__new__(UserProfile)
                # 逐字段填充快照值
                result.user_id                = user_id
                result.persistent_weaknesses  = weaknesses
                result.tech_strengths         = strengths
                result.total_interviews       = total
                # 返回脱离会话的安全对象
                return result
        except Exception as e:
            # 异常告警并返回 None
            logger.warning("get_or_create_profile 失败：{}", e)
            return None

    def append_weaknesses(self, user_id: str, new_weaknesses: List[str]) -> None:
        """向用户画像追加新的薄弱点（去重并限制上限），数据库不可用时跳过。"""
        # 未连接则跳过
        if not self._ensure_connected():
            return
        try:
            # 延迟导入查询构造器
            from sqlalchemy import select
            # 打开数据库会话
            with self._SessionLocal() as session:
                # 查询用户画像
                profile = session.execute(
                    select(UserProfile).where(UserProfile.user_id == user_id)
                ).scalar_one_or_none()
                # 画像不存在则新建并 flush（拿到对象但暂不提交，后续统一 commit）
                if not profile:
                    profile = UserProfile(user_id=user_id)
                    session.add(profile)
                    session.flush()
                # ★ 在 session 内操作，不依赖懒加载
                # 取出现有薄弱点列表副本
                existing: List[str] = list(profile.persistent_weaknesses or [])
                # 逐个合并新薄弱点：非空且尚未存在才追加（去重）
                for w in new_weaknesses:
                    if w and w not in existing:
                        existing.append(w)
                # 回写薄弱点，最多保留前 50 条，防止无限增长
                profile.persistent_weaknesses = existing[:50]
                # 提交事务持久化
                session.commit()
                logger.info("薄弱点已写入长期记忆：{} 条", len(existing))
        except Exception as e:
            # 异常仅告警
            logger.warning("append_weaknesses 失败：{}", e)

    def get_weaknesses(self, user_id: str) -> List[str]:
        """读取用户画像中的薄弱点列表（数据库不可用或无记录时返回空列表）。"""
        # 未连接则返回空列表
        if not self._ensure_connected():
            return []
        try:
            # 延迟导入查询构造器
            from sqlalchemy import select
            # 打开数据库会话
            with self._SessionLocal() as session:
                # 查询用户画像
                profile = session.execute(
                    select(UserProfile).where(UserProfile.user_id == user_id)
                ).scalar_one_or_none()
                # 无画像则返回空列表
                if not profile:
                    return []
                # ★ 在 session 内读取，避免 detached instance
                # 在会话内复制成新列表返回，规避会话关闭后的懒加载问题
                return list(profile.persistent_weaknesses or [])
        except Exception as e:
            # 异常告警并返回空列表
            logger.warning("get_weaknesses 失败：{}", e)
            return []

    # ── 面试记录 ──────────────────────────────────────────────────────────────

    def save_interview_record(
        self,
        user_id:    str,
        session_id: str,
        report:     Dict[str, Any],
        study_plan: Dict[str, Any],
        jd_title:   str = "",
    ) -> None:
        """保存一次面试记录，并同步累加用户画像的面试次数。

        参数：
            user_id: 用户 ID
            session_id: 会话 ID
            report: 面试报告字典（含总分、建议、薄弱点等）
            study_plan: 学习计划字典
            jd_title: 岗位 JD 标题，默认空串
        返回：无
        """
        # 未连接则跳过
        if not self._ensure_connected():
            return
        try:
            # 延迟导入查询构造器
            from sqlalchemy import select
            # 打开数据库会话
            with self._SessionLocal() as session:
                # 根据入参构造面试记录对象，从 report 中按需取值（缺失时给默认值）
                record = InterviewRecord(
                    user_id        = user_id,                          # 用户 ID
                    session_id     = session_id,                       # 会话 ID
                    jd_title       = jd_title,                         # 岗位标题
                    overall_score  = report.get("overall_score", 0),   # 综合得分，缺省 0
                    recommendation = report.get("recommendation", ""), # 录用建议，缺省空串
                    report_json    = report,                           # 完整报告 JSON
                    study_plan_json= study_plan,                       # 学习计划 JSON
                    weaknesses     = report.get("weaknesses", []),     # 薄弱点列表，缺省空列表
                )
                # 将新记录加入会话
                session.add(record)
                # 同时更新画像
                # 查询对应用户画像，准备累加面试次数
                profile = session.execute(
                    select(UserProfile).where(UserProfile.user_id == user_id)
                ).scalar_one_or_none()
                # 画像存在则累加总面试次数（None 兜底为 0 再 +1）
                if profile:
                    profile.total_interviews = (profile.total_interviews or 0) + 1
                # 提交事务，记录与画像更新一并持久化
                session.commit()
                logger.info("面试记录已保存：session_id={}", session_id)
        except Exception as e:
            # 异常仅告警，不抛出（容错）
            logger.warning("save_interview_record 失败：{}", e)