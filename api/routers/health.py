"""
健康检查路由
GET /health  -> {"status": "ok", "version": "1.0.0"}
"""
# 启用 PEP 563 延迟注解求值：让本模块内的类型注解以字符串形式存储，
# 避免在导入期立即解析类型，兼容性更好（尤其是前向引用）。
from __future__ import annotations

# FastAPI 的路由器类，用于把一组接口聚合成可挂载的子路由。
from fastapi import APIRouter
# 健康检查接口的响应数据模型（Pydantic），约束并校验返回结构。
from api.schemas import HealthResponse

# 创建一个路由器实例；tags 用于在自动生成的 API 文档（Swagger）中分组归类。
router = APIRouter(tags=["健康检查"])


# 注册 GET /health 接口，并声明响应体须符合 HealthResponse 结构。
@router.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查接口：返回服务存活状态与版本号，供探针/前端检测服务可用性。"""
    # 固定返回 status="ok" 表示服务正常，version 标识当前服务版本。
    return HealthResponse(status="ok", version="1.0.0")