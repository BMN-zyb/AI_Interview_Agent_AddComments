"""
FastAPI 中间件：CORS、请求日志、全局异常处理
"""
# 启用延迟注解求值，使类型注解以字符串保存，避免前向引用与导入顺序问题。
from __future__ import annotations

# ── 标准库导入 ────────────────────────────────────────────────────────────────
# time：用于高精度计时，统计单个请求的处理耗时。
import time
# traceback：用于在异常处理时格式化完整的调用栈，便于排查问题。
import traceback

# ── 第三方库导入 ──────────────────────────────────────────────────────────────
# FastAPI 应用类与 Request 请求对象，用于类型标注与读取请求信息。
from fastapi import FastAPI, Request
# CORS 跨域中间件，用于允许浏览器跨域访问后端接口。
from fastapi.middleware.cors import CORSMiddleware
# JSON 响应对象，用于在全局异常时返回结构化错误信息。
from fastapi.responses import JSONResponse
# loguru 全局 logger，用于输出请求日志与异常日志。
from loguru import logger


# 统一的中间件注册入口：接收应用实例，无返回值（仅产生副作用：挂载中间件）。
def register_middlewares(app: FastAPI) -> None:
    """注册所有中间件"""

    # ── CORS ──────────────────────────────────────────────────────────────────
    # 添加 CORS 中间件，处理浏览器的跨域请求与预检（OPTIONS）请求。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],          # 生产环境改为具体域名
        allow_credentials=True,       # 允许跨域请求携带 Cookie / 认证凭据
        allow_methods=["*"],          # 允许所有 HTTP 方法（GET/POST/...）
        allow_headers=["*"],          # 允许所有请求头
    )

    # ── 请求日志 ──────────────────────────────────────────────────────────────
    # 注册一个 HTTP 中间件，对每个请求记录方法、路径、状态码与耗时。
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        # 在调用后续处理前记录起始时间点（高精度计时器）。
        start = time.perf_counter()
        # 调用链路中的下一个处理器（其余中间件 + 路由处理函数），得到响应。
        response = await call_next(request)
        # 计算请求处理耗时并换算为毫秒。
        elapsed = (time.perf_counter() - start) * 1000
        # 输出一行请求日志：HTTP 方法、请求路径、响应状态码、耗时（毫秒，保留 1 位小数）。
        logger.info(
            "{} {} {} {:.1f}ms",
            request.method,            # 请求方法，如 GET / POST
            request.url.path,          # 请求路径，如 /interview/start
            response.status_code,      # 响应状态码，如 200 / 500
            elapsed,                   # 处理耗时（毫秒）
        )
        # 将响应原样返回给调用方，使中间件对业务结果保持透明。
        return response

    # ── 全局异常捕获 ──────────────────────────────────────────────────────────
    # 注册全局异常处理器：捕获所有未被业务代码处理的 Exception。
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        # 记录异常信息与完整堆栈，便于定位线上问题。
        logger.error("未捕获异常: {}\n{}", exc, traceback.format_exc())
        # 统一向客户端返回 500 错误及简要错误详情，避免泄露内部堆栈细节。
        return JSONResponse(
            status_code=500,           # HTTP 500 表示内部服务器错误
            content={"error": "内部服务器错误", "detail": str(exc)},  # 结构化错误体
        )