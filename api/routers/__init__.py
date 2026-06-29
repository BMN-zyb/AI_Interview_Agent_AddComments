"""API 路由模块

本包聚合了对外暴露的所有 FastAPI 路由子模块，统一在此处导入，
方便上层（如 app 入口）通过 `from api.routers import health, ...` 一次性引用，
也作为本目录被识别为 Python 包的标志文件。
"""
# 一次性导入本包内的各路由子模块：
#   health    - 健康检查接口
#   interview - 面试 REST 接口（开始/答题/技能/报告）
#   upload    - 简历文件上传与解析接口
#   websocket - 实时面试 WebSocket 接口
from api.routers import health, interview, upload, websocket

# 显式声明包的公开导出名单：当外部使用 `from api.routers import *` 时，
# 仅导出下列四个子模块，避免泄露其它内部名称。
__all__ = ["health", "interview", "upload", "websocket"]