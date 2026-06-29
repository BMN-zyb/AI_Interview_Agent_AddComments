"""
FastAPI 应用入口
启动命令：uvicorn api.main:app --host 0.0.0.0 --port 8000
"""
# 启用 PEP 563 延迟注解求值：让本文件中的类型注解以字符串形式存储，
# 避免前向引用导致的导入顺序问题，同时减少模块加载时的开销。
from __future__ import annotations

# ── 第三方库导入 ──────────────────────────────────────────────────────────────
# FastAPI 主类，用于创建应用实例并注册路由/中间件。
from fastapi import FastAPI
# 静态文件服务组件，用于挂载并对外提供 CSS / JS 等前端静态资源。
from fastapi.staticfiles import StaticFiles
# 文件响应对象，用于直接返回磁盘上的文件（如前端 index.html）。
from fastapi.responses import FileResponse
# loguru 日志库的全局 logger，用于输出结构化日志。
from loguru import logger
# 标准库 os，用于拼接文件路径、判断文件/目录是否存在等文件系统操作。
import os

# ── 项目内部模块导入 ──────────────────────────────────────────────────────────
# 中间件注册函数：统一为应用挂载 CORS、请求日志、全局异常处理等中间件。
from api.middleware import register_middlewares
# 各业务路由模块：健康检查、面试流程、文件上传、WebSocket 实时通信。
from api.routers import health, interview, upload, websocket
# 日志初始化函数：配置 loguru 的输出格式、级别、文件落盘等。
from config.logging import setup_logger

# 在创建应用前先初始化日志系统，确保后续所有日志按统一配置输出。
setup_logger()

# 创建 FastAPI 应用实例，并设置文档元信息（标题/描述/版本）与文档路由地址。
app = FastAPI(
    title="InterviewAgent API",            # 接口文档展示的标题
    description="AI 模拟面试官后端接口",     # 接口文档展示的描述
    version="1.0.0",                       # API 版本号
    docs_url="/docs",                      # Swagger UI 交互文档的访问路径
    redoc_url="/redoc",                    # ReDoc 文档的访问路径
)

# 注册中间件
# 调用统一注册函数，为应用挂载 CORS、请求日志与全局异常处理中间件。
register_middlewares(app)

# 注册路由
# 将健康检查路由（如 /health）并入应用。
app.include_router(health.router)
# 将面试相关路由（开始面试、提交回答、获取报告等）并入应用。
app.include_router(interview.router)
# 将文件上传路由（如简历上传解析）并入应用。
app.include_router(upload.router)
# 将 WebSocket 路由（实时语音/对话通道）并入应用。
app.include_router(websocket.router)

# 挂载静态文件（CSS / JS）
# 基于当前文件所在目录向上一级，定位到 frontend/static 静态资源目录的绝对路径。
_static_dir = os.path.join(os.path.dirname(__file__), "..", "frontend", "static")
# 仅当该静态目录确实存在时才挂载，避免目录缺失导致启动报错。
if os.path.isdir(_static_dir):
    # 将 /static 路径映射到本地静态目录，对外提供前端静态文件访问。
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

# 前端首页
# 定位前端单页应用入口 index.html 的绝对路径，供根路由返回。
_index_html = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")

# 注册根路径 GET 路由；include_in_schema=False 表示不在接口文档中展示该路由。
@app.get("/", include_in_schema=False)
async def serve_index():
    """返回前端首页"""
    # 若 index.html 存在，则直接以文件形式返回前端页面。
    if os.path.exists(_index_html):
        return FileResponse(_index_html)
    # 否则返回一段提示性 JSON，引导用户访问 /docs 查看接口文档。
    return {"message": "InterviewAgent API 运行中，访问 /docs 查看接口文档"}


# 注册应用启动事件回调：应用启动完成时触发。
@app.on_event("startup")
async def on_startup():
    # 记录服务启动成功的日志。
    logger.info("InterviewAgent API 启动成功")
    # 记录接口文档地址，方便开发者快速访问。
    logger.info("文档地址: http://0.0.0.0:8000/docs")


# 注册应用关闭事件回调：应用正常停止时触发。
@app.on_event("shutdown")
async def on_shutdown():
    # 记录服务已关闭的日志，便于排查生命周期问题。
    logger.info("InterviewAgent API 已关闭")