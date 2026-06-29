"""记忆系统测试"""
# 引入 pytest，用于使用其装饰器（如 skip）和测试框架能力
import pytest


# 标记跳过该测试：短期记忆依赖 Redis + MySQL 等外部服务，未配置环境时无法运行
@pytest.mark.skip(reason="需要 Redis + MySQL")
# 测试短期记忆（ShortTermMemory）的写入、读取与清空全流程
def test_short_term():
    # 在函数内部延迟导入，避免缺少 Redis/MySQL 依赖时模块加载即失败
    from memory.short_term import ShortTermMemory

    # 实例化短期记忆对象（内部会连接 Redis 等存储）
    stm = ShortTermMemory()
    # 打印测试开始提示
    print("Testing short-term memory...")
    # 读取一个全新会话的历史轮次，预期为空，验证初始状态干净
    print(stm.get_turns("test_session"))  # 应该是空的

    # 向该会话追加一条 user 角色、内容为 "hello" 的对话轮次
    stm.append_turn("test_session", "user", "hello")
    # 重新读取该会话的全部轮次
    turns = stm.get_turns("test_session")
    # 断言追加后至少有 1 条记录，验证写入生效
    assert len(turns) >= 1
    # 打印追加后的轮次内容，便于人工核对
    print("Turns after appending:", turns)

    # 清空该会话的全部短期记忆
    stm.clear("test_session")
    # 再次读取应为空，验证清空操作生效
    print("Turns after clearing:", stm.get_turns("test_session"))  # 应该是空的

    # 全流程通过后打印成功提示
    print("Short-term memory test passed!")

# 当脚本被直接运行时手动执行测试，方便本地调试
if __name__ == "__main__":
    # 直接调用短期记忆测试函数
    test_short_term()

    # python -m tests.test_memory
    # pytest -s tests/test_memory.py