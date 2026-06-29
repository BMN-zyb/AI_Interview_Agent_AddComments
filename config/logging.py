"""
日志配置：基于 loguru，统一输出格式，自动轮转
"""
# ---- 标准库 ----
# sys：用于拿到标准错误流 sys.stderr，作为控制台日志的输出目标
import sys
# Path：以面向对象方式处理文件系统路径（创建目录、拼接路径等）
from pathlib import Path

# ---- 第三方库 ----
# loguru 的全局 logger 对象，开箱即用、支持彩色与轮转
from loguru import logger

# ---- 项目内部 ----
# 导入全局配置单例，从中读取日志级别等参数
from config.settings import settings

# 日志文件统一存放目录（项目根下的 logs 文件夹）
LOG_DIR = Path("logs")
# 确保该目录存在；exist_ok=True 表示目录已存在时不报错
LOG_DIR.mkdir(exist_ok=True)

# 模块级标志位：记录 logger 是否已配置过，避免重复初始化导致日志重复输出
_configured = False


def setup_logger() -> None:
    """初始化全局 loguru logger（只配置一次）"""
    # 声明使用模块级变量 _configured（而非创建同名局部变量），以便在函数内修改它
    global _configured
    # 若已经配置过，则直接返回，保证整个进程内只初始化一次（幂等）
    if _configured:
        return

    logger.remove()  # 移除默认 handler

    # 控制台
    # 添加一个输出到控制台（标准错误）的日志处理器
    logger.add(
        sys.stderr,  # 输出目标：标准错误流
        level=settings.log_level,  # 控制台日志的最低级别，取自全局配置
        # 自定义日志格式，使用 loguru 的颜色标签让不同字段显示不同颜色
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "  # 绿色时间戳
            "<level>{level: <8}</level> | "  # 日志级别，左对齐占 8 字符宽
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "  # 来源：模块:函数:行号
            "<level>{message}</level>"  # 日志正文，颜色随级别变化
        ),
        colorize=True,  # 启用彩色输出（终端中以颜色区分级别/字段）
    )

    # 文件：每天轮转，保留 30 天
    # 再添加一个输出到日志文件的处理器
    logger.add(
        # 日志文件名按日期生成（如 interview_agent_2026-06-29.log）
        LOG_DIR / "interview_agent_{time:YYYY-MM-DD}.log",
        rotation="00:00",  # 每天 0 点切分（轮转）为新文件
        retention="30 days",  # 仅保留最近 30 天的日志，更早的自动清理
        encoding="utf-8",  # 文件以 UTF-8 写入，支持中文
        level="DEBUG",  # 文件记录更详细，最低级别设为 DEBUG（落盘比控制台更全）
        # 文件日志格式：不带颜色标签，时间精确到毫秒，便于排查
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
    )

    # 标记为已配置，后续再次调用 setup_logger 将直接返回
    _configured = True
    # 输出一条初始化完成日志，并打印当前生效的日志级别（便于确认配置是否正确）
    logger.info("Logger 初始化完成，级别: {}", settings.log_level)
