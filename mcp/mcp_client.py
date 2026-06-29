"""
MCP Client 实现：通过 Model Context Protocol 标准协议接入外部工具
支持连接本地 stdio 服务或 HTTP 服务。
"""
# 启用 PEP 563 延迟注解求值：使得类型注解以字符串形式存储，
# 从而允许在注解中使用尚未定义或可选依赖（如未安装的 MCP SDK 类型）。
from __future__ import annotations

# 标准库 asyncio：提供异步事件循环与协程运行能力。
import asyncio
# asynccontextmanager：将异步生成器函数装饰为异步上下文管理器（支持 async with）。
from contextlib import asynccontextmanager
# 类型注解工具：Any（任意类型）、AsyncGenerator（异步生成器）、Dict/List（容器类型）。
from typing import Any, AsyncGenerator, Dict, List

# loguru 的 logger：项目统一使用的日志器，便于结构化输出运行信息。
from loguru import logger

# 尝试导入 MCP 官方 SDK；该依赖为可选项，未安装时降级处理而非直接报错。
try:
    # ClientSession：MCP 客户端会话；StdioServerParameters：stdio 服务启动参数。
    from mcp import ClientSession, StdioServerParameters
    # stdio_client：基于标准输入输出与本地 MCP 服务通信的客户端工厂。
    from mcp.client.stdio import stdio_client
except ImportError:
    # 未安装 mcp SDK 时，将相关符号置为 None，便于后续运行时做存在性检查并友好报错。
    ClientSession = None  # type: ignore
    StdioServerParameters = None  # type: ignore
    stdio_client = None  # type: ignore


class MCPClient:
    """MCP 客户端封装

    对 MCP 官方 SDK 的轻量封装，统一提供连接 stdio 服务、
    列出工具、调用工具等高层方法，屏蔽底层会话细节。
    """

    def __init__(self) -> None:
        """初始化客户端，准备会话与上下文占位。"""
        # session：当前活跃的 MCP 会话；尚未连接时为 None。
        self.session: ClientSession | None = None  # type: ignore
        # _ctx：内部上下文占位（预留字段），当前未直接使用。
        self._ctx = None

    # 装饰为异步上下文管理器：调用方可用 `async with client.connect_stdio(...)` 获取会话。
    @asynccontextmanager
    async def connect_stdio(
        self, command: str, args: List[str], env: Dict[str, str] | None = None
    ) -> AsyncGenerator[ClientSession, None]:  # type: ignore
        """连接本地 stdio MCP 服务

        参数:
            command: 要启动的 MCP 服务可执行命令。
            args: 传给该命令的参数列表。
            env: 可选的环境变量字典，注入到子进程。
        产出:
            已完成初始化握手的 ClientSession，供 async with 块内使用。
        """
        # 若 SDK 未安装（StdioServerParameters 为 None），无法建立连接，直接抛出运行时错误。
        if StdioServerParameters is None:
            raise RuntimeError("mcp SDK 未安装")
        # 根据命令、参数与环境变量构造 stdio 服务启动参数对象。
        params = StdioServerParameters(command=command, args=args, env=env)
        # 启动并连接 stdio 服务，得到底层的读/写流（read, write）。
        async with stdio_client(params) as (read, write):  # type: ignore
            # 在读写流之上创建 MCP 客户端会话，自动管理会话生命周期。
            async with ClientSession(read, write) as session:  # type: ignore
                # 执行 MCP 初始化握手，协商协议版本与能力。
                await session.initialize()
                # 记录会话已成功建立，便于排障。
                logger.info("MCP stdio 会话已建立")
                # 将会话产出给调用方；async with 块结束后自动清理资源。
                yield session

    async def list_tools(self, session: ClientSession) -> List[Dict[str, Any]]:  # type: ignore
        """列出可用工具

        参数:
            session: 已建立的 MCP 会话。
        返回:
            工具信息列表，每项含 name 与 description。
        """
        # 通过会话向服务端请求其暴露的工具清单。
        result = await session.list_tools()  # type: ignore
        # 仅提取每个工具的名称与描述，简化为字典列表返回给上层。
        return [{"name": t.name, "description": t.description} for t in result.tools]

    async def call_tool(
        self, session: ClientSession, tool_name: str, arguments: Dict[str, Any]  # type: ignore
    ) -> Any:
        """调用工具

        参数:
            session: 已建立的 MCP 会话。
            tool_name: 目标工具名称。
            arguments: 传给工具的参数字典。
        返回:
            工具执行结果的内容部分（result.content）。
        """
        # 携带参数发起远程工具调用，等待服务端返回结果。
        result = await session.call_tool(tool_name, arguments)  # type: ignore
        # 仅返回结果中的内容字段，过滤掉外层元数据。
        return result.content


# 全局便捷函数
def run_async(coro):
    """同步包装器：在已有 event loop 下创建新 loop 运行

    用于在同步代码（如普通函数、脚本、框架同步回调）中安全地运行协程：
    - 若当前已有正在运行的事件循环，则切换到独立线程中用新循环执行，避免冲突；
    - 否则直接用 asyncio.run 在本线程运行。

    参数:
        coro: 待运行的协程对象。
    返回:
        协程的执行结果。
    """
    # 尝试获取当前线程正在运行的事件循环。
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # 当前线程没有运行中的事件循环时会抛 RuntimeError，置为 None 表示无活跃循环。
        loop = None
    # 若已有正在运行的循环，则不能在其上再次调用 asyncio.run（会报错）。
    if loop and loop.is_running():
        # 延迟导入线程池模块，仅在确需开线程时才加载，降低普通路径开销。
        import concurrent.futures

        # 新开一个单线程的线程池，在该独立线程中用 asyncio.run 运行协程。
        with concurrent.futures.ThreadPoolExecutor(1) as pool:
            # 提交任务并阻塞等待其结果，从而把异步执行转换为同步返回。
            return pool.submit(asyncio.run, coro).result()
    # 无活跃事件循环时，直接在当前线程运行协程并返回结果。
    return asyncio.run(coro)
