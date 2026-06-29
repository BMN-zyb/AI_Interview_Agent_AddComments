"""
短期记忆（Redis）：当前会话上下文
- 会话窗口（最近 N 轮对话）
- 当前面试状态快照
- 24 小时 TTL 自动过期
"""
# 启用延迟注解求值，便于在注解中使用尚未定义的类型而不报错
from __future__ import annotations

# 导入标准库 json，用于对话/状态的序列化与反序列化
import json
# 导入类型注解：Any（任意类型）、Dict/List（容器）、Optional（可空）
from typing import Any, Dict, List, Optional

# 导入 loguru 日志器，统一记录连接状态与异常信息
from loguru import logger

# 导入全局配置对象，读取 Redis 连接参数与 TTL 等设置
from config import settings


def _safe_serialize(obj: Any) -> Any:
    """
    JSON 序列化辅助：递归处理不可序列化的对象。
    - BaseMessage 等 LangChain 对象 → 转为 dict
    - 其余不可序列化对象 → 转为 str
    """
    # 若为字典：递归处理每个值，保留键不变
    if isinstance(obj, dict):
        return {k: _safe_serialize(v) for k, v in obj.items()}
    # 若为列表：递归处理每个元素
    if isinstance(obj, list):
        return [_safe_serialize(v) for v in obj]
    # LangChain BaseMessage
    # 尝试导入 LangChain 的消息基类；若未安装该库则跳过此分支
    try:
        from langchain_core.messages import BaseMessage
        # 若对象是 LangChain 消息，转为带标记的 dict（保留类型与内容，便于后续识别还原）
        if isinstance(obj, BaseMessage):
            return {"__lc_msg__": True, "type": obj.type, "content": obj.content}
    except ImportError:
        # 未安装 langchain_core 时忽略，继续走通用序列化逻辑
        pass
    # 其他不可 JSON 序列化的类型
    # 先试探该对象能否被 json 序列化：能则原样返回
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        # 无法序列化的对象（如自定义类实例）统一降级为字符串，保证整体可写入 Redis
        return str(obj)


class ShortTermMemory:
    """基于 Redis 的短期记忆（带容错）"""

    def __init__(self) -> None:
        # Redis 客户端句柄，惰性创建，初始为空
        self._client    = None
        self._available = None   # None=未检测
        # 从配置读取短期记忆的过期时间（TTL，单位秒）
        self.ttl        = settings.redis_short_term_ttl

    def _ensure_connected(self) -> bool:
        """惰性连接"""
        # 已确认可用：直接返回 True，避免重复连接
        if self._available is True:
            return True
        # 已确认不可用：直接返回 False，跳过重试（本进程内不再尝试）
        if self._available is False:
            return False
        # 首次调用：尝试建立 Redis 连接
        try:
            # 延迟导入 redis 库，避免未安装时在模块加载阶段就报错
            import redis
            # 按配置创建 Redis 客户端
            client = redis.Redis(
                host     = settings.redis_host,          # Redis 主机地址
                port     = settings.redis_port,          # Redis 端口
                password = settings.redis_password or None,  # 密码（空字符串则视为无密码）
                db       = settings.redis_db,            # 使用的数据库编号
                decode_responses = True,                 # 自动将返回的字节解码为字符串
                socket_connect_timeout = 3,              # 连接超时 3 秒，避免长时间阻塞
            )
            # 发送 PING 验证连通性（连接失败会在此抛异常）
            client.ping()
            # 连接成功：保存客户端并标记为可用
            self._client    = client
            self._available = True
            logger.info("Redis 短期记忆已连接")
            return True
        except Exception as e:
            # 连接失败：标记为不可用，并降级为内存存储
            self._available = False
            logger.warning("Redis 不可用，短期记忆降级为内存：{}", e)
            self._mem_store: Dict[str, Any] = {}   # 内存降级
            return False

    def _key(self, session_id: str, kind: str) -> str:
        # 统一拼接 Redis key，使用 iam:short: 前缀做命名空间隔离，kind 区分数据种类（turns/snapshot 等）
        return f"iam:short:{session_id}:{kind}"

    # ── 对话窗口 ──────────────────────────────────────────────────────────────

    def append_turn(
        self, session_id: str, role: str, content: str, max_turns: int = 20
    ) -> None:
        """向指定会话追加一轮对话。

        参数：
            session_id: 会话 ID
            role: 发言角色（如 user / assistant）
            content: 发言内容
            max_turns: 仅保留最近的轮数，默认 20
        返回：无
        """
        # 先把本轮对话序列化为 JSON 字符串（ensure_ascii=False 保留中文可读性）
        turn = json.dumps({"role": role, "content": content}, ensure_ascii=False)
        # 未连接（降级）时直接返回，不写入
        if not self._ensure_connected():
            return   # 降级时忽略
        try:
            # 计算该会话对话列表的 key
            key = self._key(session_id, "turns")
            # 将本轮对话追加到列表尾部
            self._client.rpush(key, turn)
            # 裁剪列表，仅保留最后 max_turns 条，实现滑动窗口
            self._client.ltrim(key, -max_turns, -1)
            # 刷新过期时间，保持窗口存活
            self._client.expire(key, self.ttl)
        except Exception as e:
            # 写入异常仅记录告警，不向上抛出（容错）
            logger.warning("append_turn 失败：{}", e)

    def get_turns(self, session_id: str) -> List[Dict[str, str]]:
        """读取指定会话的全部对话窗口，返回 [{role, content}, ...]。"""
        # 未连接（降级）时返回空列表
        if not self._ensure_connected():
            return []
        try:
            # 计算该会话对话列表的 key
            key = self._key(session_id, "turns")
            # 读取整个列表（0 到 -1 表示全部），为空时回退为空列表
            raw = self._client.lrange(key, 0, -1) or []
            # 将每条 JSON 字符串反序列化为字典后返回
            return [json.loads(r) for r in raw]
        except Exception as e:
            # 读取异常仅告警并返回空列表
            logger.warning("get_turns 失败：{}", e)
            return []

    # ── 状态快照 ──────────────────────────────────────────────────────────────

    def save_state_snapshot(self, session_id: str, snapshot: Dict[str, Any]) -> None:
        """保存指定会话的面试状态快照（Redis 不可用时降级到内存）。"""
        if not self._ensure_connected():
            # 降级到内存
            # 若已初始化内存存储，则把快照直接放入内存字典
            if hasattr(self, "_mem_store"):
                self._mem_store[session_id] = snapshot
            return
        try:
            # 计算该会话状态快照的 key
            key        = self._key(session_id, "snapshot")
            # ★ 用 _safe_serialize 处理 BaseMessage 等不可序列化对象
            safe_snap  = _safe_serialize(snapshot)
            # 将处理后的快照序列化为 JSON 字符串
            serialized = json.dumps(safe_snap, ensure_ascii=False)
            # 写入 Redis 并设置过期时间（ex=self.ttl）
            self._client.set(key, serialized, ex=self.ttl)
        except Exception as e:
            # 保存异常仅记录告警（容错）
            logger.warning("save_state_snapshot 失败：{}", e)

    def get_state_snapshot(self, session_id: str) -> Optional[Dict[str, Any]]:
        """读取指定会话的状态快照；无数据返回 None。"""
        if not self._ensure_connected():
            # 降级模式：若有内存存储则从内存读取
            if hasattr(self, "_mem_store"):
                return self._mem_store.get(session_id)
            # 既无 Redis 也无内存存储，返回 None
            return None
        try:
            # 计算该会话状态快照的 key
            key = self._key(session_id, "snapshot")
            # 从 Redis 读取原始 JSON 字符串
            raw = self._client.get(key)
            # 不存在则返回 None
            if not raw:
                return None
            # 反序列化为字典后返回
            return json.loads(raw)
        except Exception as e:
            # 读取异常仅告警并返回 None
            logger.warning("get_state_snapshot 失败：{}", e)
            return None

    def clear(self, session_id: str) -> None:
        """清除指定会话的全部短期记忆（对话窗口 + 状态快照等）。"""
        if not self._ensure_connected():
            # 降级模式：从内存存储中移除该会话（不存在则忽略）
            if hasattr(self, "_mem_store"):
                self._mem_store.pop(session_id, None)
            return
        try:
            # 构造匹配该会话所有 key 的通配模式（iam:short:<id>:*）
            pattern = self._key(session_id, "*")
            # 列出所有匹配的 key
            keys    = self._client.keys(pattern)
            # 若存在匹配项则批量删除
            if keys:
                self._client.delete(*keys)
                logger.info("清除短期记忆：{} 个 key", len(keys))
        except Exception as e:
            # 清除异常仅记录告警（容错）
            logger.warning("clear 失败：{}", e)