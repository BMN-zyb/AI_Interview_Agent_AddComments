"""
记忆管理器：统一封装短期 / 长期记忆的读写接口
新增：clear_weaknesses 方法
"""
# 启用延迟注解求值，便于在注解中使用尚未定义/前向引用的类型
from __future__ import annotations

# 导入类型注解：Any（任意类型）、Dict（字典）、List（列表）
from typing import Any, Dict, List

# 导入 loguru 日志器，用于统一记录降级与异常信息
from loguru import logger


def _coerce_bool(val: Any) -> bool:
    """
    ★ 将 Redis 反序列化后可能的字符串布尔值转为真正的 bool
    "True" / "true" / 1 / True -> True
    "False" / "false" / 0 / False / None -> False
    """
    # 已是布尔类型：直接返回，无需转换
    if isinstance(val, bool):
        return val
    # 整数：按 Python 真值规则转换（0->False，非 0->True）
    if isinstance(val, int):
        return bool(val)
    # 字符串：去空格转小写后，只有命中真值词集合才视为 True
    if isinstance(val, str):
        return val.strip().lower() in ("true", "1", "yes")
    # 其他类型：兜底用 bool() 转换（如 None -> False）
    return bool(val)


def _sanitize_state(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    ★ 从 Redis 加载 state 后，修正关键布尔字段的类型
    防止 JSON 序列化/反序列化导致 True -> "True" 的问题
    """
    # 需要强制修正为 bool 的字段清单（这些字段控制面试流程分支，类型错误会导致逻辑异常）
    bool_fields = [
        "interview_finished", "awaiting_answer", "awaiting_evaluation",
        "should_followup", "force_finish", "is_followup",
    ]
    # 逐个字段：存在则用 _coerce_bool 规范化为真正的布尔值
    for field in bool_fields:
        if field in state:
            state[field] = _coerce_bool(state[field])

    # 需要强制修正为 int 的字段清单（计数器/索引类字段）
    int_fields = [
        "current_question_idx", "followup_count", "max_followup",
        "total_questions", "consecutive_correct", "consecutive_wrong",
    ]
    # 逐个字段：存在则尝试转 int，转换失败时兜底为 0，保证类型安全
    for field in int_fields:
        if field in state:
            try:
                state[field] = int(state[field])
            except (TypeError, ValueError):
                state[field] = 0

    # 返回修正后的 state（原地修改并返回，便于链式使用）
    return state


class MemoryManager:
    """记忆统一入口（惰性初始化，任何一个存储不可用时自动降级）"""

    def __init__(self) -> None:
        # 短期记忆实例占位，首次访问时才创建（惰性初始化）
        self._short_term = None
        # 长期记忆实例占位，首次访问时才创建（惰性初始化）
        self._long_term  = None

    @property
    def short_term(self):
        """短期记忆访问器：首次访问时延迟创建 ShortTermMemory 实例并缓存。"""
        # 尚未创建则导入并实例化（延迟导入可避免循环依赖与启动开销）
        if self._short_term is None:
            from memory.short_term import ShortTermMemory
            self._short_term = ShortTermMemory()
        return self._short_term

    @property
    def long_term(self):
        """长期记忆访问器：首次访问时延迟创建 LongTermMemory 实例并缓存。"""
        # 尚未创建则导入并实例化
        if self._long_term is None:
            from memory.long_term import LongTermMemory
            self._long_term = LongTermMemory()
        return self._long_term

    # ── 短期记忆 ──────────────────────────────────────────────────────────────

    def save_session(self, session_id: str, state: Dict[str, Any]) -> None:
        """保存会话状态快照到短期记忆（失败仅告警，不影响主流程）。"""
        try:
            # 委托短期记忆保存状态快照
            self.short_term.save_state_snapshot(session_id, state)
        except Exception as e:
            # 任何异常都吞掉并告警，保证记忆失败不阻断业务
            logger.warning("save_session 失败（已忽略）：{}", e)

    def load_session(self, session_id: str) -> Dict[str, Any]:
        """★ 加载后自动修正布尔/整型字段类型"""
        try:
            # 读取原始快照，缺失时用空字典兜底
            raw = self.short_term.get_state_snapshot(session_id) or {}
            # 修正类型后返回（避免 JSON 往返导致的类型漂移）
            return _sanitize_state(raw)
        except Exception as e:
            # 异常时告警并返回空字典，保证调用方拿到可用结构
            logger.warning("load_session 失败（已忽略）：{}", e)
            return {}

    def add_turn(self, session_id: str, role: str, content: str) -> None:
        """向短期记忆追加一轮对话（失败仅告警）。"""
        try:
            # 委托短期记忆追加对话轮次
            self.short_term.append_turn(session_id, role, content)
        except Exception as e:
            # 异常吞掉并告警
            logger.warning("add_turn 失败（已忽略）：{}", e)

    # ── 长期记忆 ──────────────────────────────────────────────────────────────

    def get_weaknesses(self, user_id: str) -> List[str]:
        """读取用户的长期薄弱点列表（失败返回空列表）。"""
        try:
            # 委托长期记忆查询薄弱点
            return self.long_term.get_weaknesses(user_id)
        except Exception as e:
            # 异常告警并返回空列表
            logger.warning("get_weaknesses 失败（已忽略）：{}", e)
            return []

    def append_weaknesses(self, user_id: str, weaknesses: List[str]) -> None:
        """向用户长期记忆追加薄弱点（失败仅告警）。"""
        try:
            # 委托长期记忆写入薄弱点
            self.long_term.append_weaknesses(user_id, weaknesses)
        except Exception as e:
            # 异常吞掉并告警
            logger.warning("append_weaknesses 失败（已忽略）：{}", e)

    def clear_weaknesses(self, user_id: str) -> bool:
        """
        ★ 新增：清除用户所有历史薄弱点
        Returns: True 成功, False 失败
        """
        try:
            # 取长期记忆实例
            lt = self.long_term
            # 若数据库不可用则无法清除，直接返回 False
            if not lt._ensure_connected():
                logger.warning("MySQL 不可用，无法清除薄弱点")
                return False
            # 延迟导入查询构造器与 ORM 模型（按需加载）
            from sqlalchemy import select
            from memory.models import UserProfile
            # 复用长期记忆的会话工厂打开数据库会话（with 确保自动关闭）
            with lt._SessionLocal() as session:
                # 按 user_id 查询用户画像，至多一条（无则为 None）
                profile = session.execute(
                    select(UserProfile).where(UserProfile.user_id == user_id)
                ).scalar_one_or_none()
                # 找到画像：将薄弱点清空并提交事务
                if profile:
                    profile.persistent_weaknesses = []
                    session.commit()
                    logger.info("已清除用户 {} 的长期记忆薄弱点", user_id)
                else:
                    # 无画像记录：无需清除，仅记录信息
                    logger.info("用户 {} 无历史记录，无需清除", user_id)
            # 执行到此即视为成功
            return True
        except Exception as e:
            # 异常告警并返回 False 表示失败
            logger.warning("clear_weaknesses 失败：{}", e)
            return False

    def save_interview(
        self,
        user_id:    str,
        session_id: str,
        report:     Dict[str, Any],
        study_plan: Dict[str, Any],
    ) -> None:
        """保存一次完整面试结果到长期记忆（失败仅告警）。

        参数：
            user_id: 用户 ID
            session_id: 会话 ID
            report: 面试报告字典
            study_plan: 学习计划字典
        返回：无
        """
        try:
            # 委托长期记忆保存面试记录（此处不传 JD 标题，置为空串）
            self.long_term.save_interview_record(
                user_id, session_id, report, study_plan, jd_title=""
            )
        except Exception as e:
            # 异常吞掉并告警
            logger.warning("save_interview 失败（已忽略）：{}", e)


# 模块级全局单例：供整个应用通过 `from memory import memory_manager` 复用同一实例
memory_manager = MemoryManager()