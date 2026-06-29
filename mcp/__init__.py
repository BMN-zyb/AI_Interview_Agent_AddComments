"""MCP 协议集成模块"""
# 模块级说明：本包负责集成 Model Context Protocol（MCP）协议相关能力。
# 从子模块 mcp_client 导入 MCPClient 类，作为本包对外暴露的主要入口。
from mcp.mcp_client import MCPClient

# __all__ 限定 `from mcp import *` 时仅导出 MCPClient，规范包的公开 API。
__all__ = ["MCPClient"]
