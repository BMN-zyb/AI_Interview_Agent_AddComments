"""API 接口测试"""
# FastAPI 官方提供的测试客户端，可在不真正启动 HTTP 服务的情况下直接对 app 发起请求
from fastapi.testclient import TestClient


# 测试健康检查接口 /api/health 是否正常返回，用于验证服务可用性（最基础的冒烟测试）
def test_health():
    # 在函数内部延迟导入 app，避免模块加载阶段就触发 app 的初始化副作用（如连接数据库等）
    from api.main import app
    # 用 app 构造测试客户端；raise_server_exceptions=False 表示服务端异常不直接抛出，而是返回 500，便于断言状态码
    client = TestClient(app, raise_server_exceptions=False)
    # 向健康检查路由发起 GET 请求，获取响应对象
    resp = client.get("/api/health")
    # 断言 HTTP 状态码为 200，验证接口可正常访问、未报错
    assert resp.status_code == 200
    # 断言响应 JSON 中的 status 字段为 "ok"，验证业务层面健康状态正确
    assert resp.json()["status"] == "ok"


# 当脚本被直接运行（而非被 pytest 收集）时，手动执行测试函数，方便本地快速调试
if __name__ == "__main__":
    # 直接调用健康检查测试
    test_health()
    # 全部断言通过后打印提示信息
    print("All tests passed!")

    # python -m tests.test_api