"""
全局配置：通过 pydantic-settings 读取 .env 环境变量
"""
# ---- 标准库 ----
# lru_cache：函数结果缓存装饰器，这里用于让配置只构建一次（单例）
from functools import lru_cache
# Optional：类型注解，表示某字段可以为对应类型或 None（即“可选/可缺省”）
from typing import Optional

# ---- 第三方库（pydantic 数据校验/配置框架）----
# Field：用于为模型字段附加元信息（如是否必填、默认值、描述等）
from pydantic import Field
# BaseSettings：可从环境变量/.env 自动加载的配置基类；SettingsConfigDict：其配置项容器
from pydantic_settings import BaseSettings, SettingsConfigDict


# 定义应用的全局配置模型，继承 BaseSettings 以获得“自动读取环境变量”的能力
class Settings(BaseSettings):
    """应用全局配置（自动从 .env 加载）"""

    # 配置 pydantic-settings 的加载行为
    model_config = SettingsConfigDict(
        env_file=".env",  # 指定从项目根目录的 .env 文件读取变量
        env_file_encoding="utf-8",  # .env 文件按 UTF-8 解码，避免中文/特殊字符乱码
        case_sensitive=False,  # 环境变量名大小写不敏感（DASHSCOPE_API_KEY 与 dashscope_api_key 等价）
        extra="ignore",  # 忽略 .env 中未在本类声明的多余变量，而不是抛错
    )

    # ---- LLM ----
    # 通义千问 API Key：用 Field(...) 中的省略号 ... 标记为“必填”，缺失时启动即报错
    dashscope_api_key: str = Field(..., description="通义千问 API Key")
    # 默认使用的对话大模型名称
    llm_model: str = "qwen-max"
    # 默认使用的文本向量化（embedding）模型名称，供 RAG 检索等场景使用
    embedding_model: str = "text-embedding-v3"
    # LLM 采样温度：值越高输出越随机/有创造性，越低越确定
    llm_temperature: float = 0.7
    # 单次生成的最大 token 数，限制模型输出长度
    llm_max_tokens: int = 4096

    # ---- MySQL ----
    # MySQL 服务器地址，默认本机回环地址
    mysql_host: str = "127.0.0.1"
    # MySQL 端口，默认 3306
    mysql_port: int = 3306
    # 连接 MySQL 使用的用户名
    mysql_user: str = "interview_agent"
    # 连接 MySQL 使用的密码（默认空串，实际值应在 .env 中提供）
    mysql_password: str = ""
    # 默认连接的数据库名
    mysql_database: str = "interview_agent"

    # 只读属性：根据上面的各项 MySQL 配置动态拼出 SQLAlchemy 连接串
    @property
    def mysql_url(self) -> str:
        """组装并返回 MySQL 的 SQLAlchemy 连接 URL（使用 pymysql 驱动）。

        返回值: 形如 mysql+pymysql://user:pwd@host:port/db?charset=utf8mb4 的连接字符串。
        """
        # 使用 f-string 拼接：第一段为驱动协议 + 用户名密码鉴权信息
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            # 第二段为主机、端口与数据库名
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
            # 第三段固定使用 utf8mb4 字符集，以完整支持中文及 emoji 等四字节字符
            "?charset=utf8mb4"
        )

    # ---- Redis ----
    # Redis 服务器地址
    redis_host: str = "127.0.0.1"
    # Redis 端口，默认 6379
    redis_port: int = 6379
    # Redis 密码：可选，无密码时为 None
    redis_password: Optional[str] = None
    # 使用的 Redis 逻辑库编号（0~15），默认 0 号库
    redis_db: int = 0
    redis_short_term_ttl: int = 86400  # 短期记忆 24 小时过期

    # ---- Weaviate ----
    # Weaviate 向量数据库的访问地址
    weaviate_url: str = "http://localhost:8080"
    # Weaviate API Key：可选，本地无鉴权部署时为 None
    weaviate_api_key: Optional[str] = None

    # ---- MCP / GitHub ----
    # GitHub 访问令牌：用于 MCP / GitHub 集成，可选
    github_token: Optional[str] = None

    # ---- App ----
    # 应用监听的主机地址，0.0.0.0 表示监听所有网卡（便于容器/外部访问）
    app_host: str = "0.0.0.0"
    # 应用监听端口
    app_port: int = 8000
    # 日志级别（如 DEBUG/INFO/WARNING），供日志模块读取
    log_level: str = "INFO"
    # 对外公开访问的基础 URL，用于生成回调/分享链接等
    public_url: str = "http://localhost:8000"

    # ---- RAG ----
    # RAG 检索返回的候选文档数量上限（取 Top-K 条）
    rag_top_k: int = 5
    # 混合检索中 BM25（关键词检索）得分的权重
    rag_bm25_weight: float = 0.4
    # 混合检索中向量（语义检索）得分的权重；与 BM25 权重共同决定融合排序
    rag_vector_weight: float = 0.6

    # ---- Difficulty FSM ----
    # 面试难度的有限状态机（FSM）档位，从易到难依次为 easy/medium/hard
    difficulty_levels: tuple = ("easy", "medium", "hard")
    # 连续答对多少题后升高难度
    consecutive_correct_to_upgrade: int = 2
    # 连续答错多少题后降低难度
    consecutive_wrong_to_downgrade: int = 2


# 用 lru_cache 缓存返回值，确保整个进程内 Settings 只被构造一次（单例模式）
@lru_cache
def get_settings() -> Settings:
    """构造并返回全局配置对象；借助 lru_cache 保证只初始化一次。

    返回值: 已从环境变量/.env 加载完成的 Settings 实例。
    """
    # 实例化 Settings 会触发其从 .env / 环境变量读取并校验各字段
    return Settings()  # type: ignore[call-arg]


# 模块加载时即生成全局配置单例，供其它模块直接导入使用
settings = get_settings()
