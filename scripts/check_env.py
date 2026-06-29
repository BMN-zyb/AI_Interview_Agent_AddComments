"""环境检查脚本"""
# 启用 PEP 563 延迟注解求值：让类型注解以字符串形式存储，避免前向引用问题并兼容旧版本写法
from __future__ import annotations

# 标准库
import shutil  # 提供文件/可执行程序查找等工具（如 shutil.which 定位命令）
import sys  # 访问解释器信息，这里用于读取 Python 版本号（sys.version_info）
from pathlib import Path  # 面向对象的路径操作，用于检查 .env 文件是否存在

# 第三方库
import redis  # Redis 客户端，用于测试与 Redis 服务的连通性
import requests  # HTTP 客户端，用于探测 Weaviate 与 DashScope 接口可用性
from loguru import logger  # 日志库，统一输出各项检查的成功/失败结果
from sqlalchemy import create_engine, text  # SQLAlchemy：create_engine 建立数据库引擎，text 包装原生 SQL


def check_all() -> None:
    """依次执行所有环境检查项，逐项打印成功或失败结果。

    无参数；无返回值。每个检查项独立捕获异常，单项失败不会中断其余检查，
    从而一次运行即可看到全部环境问题的全貌。
    """
    # 打印总起始日志，提示用户整体环境检查流程开始
    logger.info("🔍 开始环境检查...")
    # 定义检查项列表：每个元素为 (中文名称, 对应检查函数) 的元组，便于统一循环执行
    checks = [
        ("Python 版本", check_python),  # 校验解释器版本是否满足最低要求
        ("必要依赖", check_deps),  # 校验关键第三方依赖是否已安装
        (".env 文件", check_env_file),  # 校验配置文件 .env 是否存在
        ("MySQL 连接", check_mysql),  # 校验 MySQL 数据库是否可连接
        ("Redis 连接", check_redis),  # 校验 Redis 服务是否可连接
        ("Weaviate 连接", check_weaviate),  # 校验 Weaviate 向量库是否就绪
        ("DashScope API", check_dashscope),  # 校验 DashScope 大模型 API 是否可调用
    ]
    # 遍历每个检查项，解包出名称与对应的检查函数
    for name, fn in checks:
        # 用 try/except 包裹单项检查，确保某一项失败时其余项仍能继续执行
        try:
            # 调用检查函数，若检查不通过会抛出异常（断言失败或请求报错等）
            fn()
            # 检查通过时输出成功日志，{} 为 loguru 的占位符，由后续参数 name 填充
            logger.success("✅ {}", name)
        except Exception as e:  # 捕获任意异常，避免单点失败导致整个脚本崩溃
            # 检查失败时输出错误日志，同时打印检查项名称与具体异常信息便于排查
            logger.error("❌ {} - {}", name, e)


def check_python():
    """检查 Python 解释器版本是否 >= 3.10，不满足则抛出 AssertionError。"""
    # 使用断言校验版本下限：sys.version_info 是可比较的版本元组，低于 (3,10) 即报错并附带当前版本
    assert sys.version_info >= (3, 10), f"需要 Python 3.10+，当前 {sys.version}"


def check_deps():
    """检查项目运行所需的关键第三方依赖是否均已安装。

    任一依赖缺失时，__import__ 会抛出 ImportError，从而判定检查失败。
    """
    # 列出必须存在的核心依赖包名称（用于支撑 LLM/RAG/Web 等核心能力）
    required = ["langchain", "langgraph", "llama_index", "fastapi", "redis", "sqlalchemy"]
    # 逐个尝试导入依赖，验证其确实可用
    for dep in required:
        # 用 __import__ 动态导入；将包名中的 '-' 替换为 '_' 以匹配实际的可导入模块名
        __import__(dep.replace("-", "_"))


def check_env_file():
    """检查项目根目录下的 .env 配置文件是否存在，不存在则提示从模板复制。"""
    # 断言 .env 文件存在；若缺失则报错并提示用户复制 .env.example 作为起点
    assert Path(".env").exists(), ".env 文件不存在，请复制 .env.example"


def check_mysql():
    """检查能否成功连接 MySQL 数据库（执行一条最简查询验证连通性）。"""
    # 延迟导入配置，避免在缺少配置时影响其它检查；settings 提供各类连接参数
    from config import settings
    # 根据配置中的连接串创建数据库引擎（此步仅构建引擎，尚未真正连接）
    engine = create_engine(settings.mysql_url)
    # 使用 with 获取连接，确保用完后自动关闭、释放连接资源
    with engine.connect() as conn:
        # 执行最简单的 "SELECT 1" 探测查询，能成功返回即说明数据库连通正常
        conn.execute(text("SELECT 1"))


def check_redis():
    """检查能否成功连接 Redis（通过 PING 命令验证服务可用）。"""
    # 延迟导入配置，获取 Redis 主机、端口、密码等连接参数
    from config import settings
    # 创建 Redis 客户端实例并配置连接参数
    r = redis.Redis(
        host=settings.redis_host, port=settings.redis_port,  # 指定 Redis 的主机地址与端口
        password=settings.redis_password or None, decode_responses=True,  # 密码为空时传 None；自动将返回的字节解码为字符串
    )
    # 发送 PING 命令，正常应答返回 True；断言其为真以确认连接可用
    assert r.ping()


def check_weaviate():
    """检查 Weaviate 向量数据库是否就绪（请求其 readiness 健康检查端点）。"""
    # 延迟导入配置，获取 Weaviate 服务地址
    from config import settings
    # 请求 Weaviate 的就绪探针接口；设置 5 秒超时避免长时间阻塞
    resp = requests.get(f"{settings.weaviate_url}/v1/.well-known/ready", timeout=5)
    # 若 HTTP 状态码为 4xx/5xx 则抛出异常，判定服务未就绪
    resp.raise_for_status()


def check_dashscope():
    """检查 DashScope 大模型 API 是否可正常调用（发送一次最小化的对话请求）。

    采用 OpenAI 兼容接口（compatible-mode），用极小的 max_tokens 降低开销，
    仅验证鉴权与连通性，不关心实际回复内容。
    """
    # 延迟导入配置，获取 API Key 与模型名称
    from config import settings
    # 向 DashScope 的 OpenAI 兼容对话补全接口发起 POST 请求
    resp = requests.post(
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",  # DashScope 的 OpenAI 兼容端点
        headers={
            "Authorization": f"Bearer {settings.dashscope_api_key}",  # 以 Bearer Token 形式传入 API Key 进行鉴权
            "Content-Type": "application/json",  # 声明请求体为 JSON 格式
        },
        json={"model": settings.llm_model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 5},  # 最小化请求体：指定模型、发送一句简短消息，并限制返回 5 个 token 以节省调用成本
        timeout=10,  # 设置 10 秒超时，防止网络异常导致检查长时间挂起
    )
    # 若返回非 2xx 状态码（如鉴权失败/模型不存在）则抛出异常，判定 API 不可用
    resp.raise_for_status()


# 仅当本文件作为脚本直接运行时才执行检查，被其它模块 import 时不会自动触发
if __name__ == "__main__":
    # 调用总检查入口，依次执行并打印所有环境检查结果
    check_all()
