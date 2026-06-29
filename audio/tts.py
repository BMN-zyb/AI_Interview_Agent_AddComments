"""
TTS 语音合成：通义千问 CosyVoice API
- 流式合成（AsyncIterator[bytes]）供 WebSocket 实时推送
- 同步合成（bytes）供 REST API 返回
- 自动降级：API 不可用时返回空字节，不中断主流程
"""
# 启用延迟注解求值，便于使用 AsyncIterator/Optional 等类型注解
from __future__ import annotations

# 标准库：异步事件循环支持（流式合成基于协程实现）
import asyncio
# 标准库：JSON 处理（此处导入备用，请求体由 httpx 自动序列化）
import json
# 标准库类型标注：异步迭代器与可选类型
from typing import AsyncIterator, Optional

# 第三方库：支持同步/异步的 HTTP 客户端，用于调用云端 TTS 接口与流式读取
import httpx
# 第三方库：统一日志记录
from loguru import logger

# 项目配置：从全局设置中读取 API Key 等参数
from config.settings import settings

# CosyVoice REST API 端点
# 阿里云 DashScope 文本转语音服务地址（CosyVoice 合成接口）
_COSYVOICE_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2audio/text-synthesis"
)

# 支持的音色列表（供前端选择）
# 预定义可选音色，前端据此展示选项，传给 API 的 voice 参数
AVAILABLE_VOICES = [
    "longxiaochun",   # 龙小淳（女，温柔）
    "longxiaoxia",    # 龙小夏（女，活泼）
    "longjiangwai",   # 龙江外（男，沉稳）
    "longyue",        # 龙悦（女，专业）
]


class TTSEngine:
    """
    TTS 引擎（CosyVoice 流式 + 同步双模式）

    Args:
        voice:       音色名称
        audio_format: 输出格式，mp3 / wav / pcm
        sample_rate:  采样率
    """

    def __init__(
        self,
        voice: str        = "longxiaochun",
        audio_format: str = "mp3",
        sample_rate: int  = 22050,
    ) -> None:
        """
        初始化 TTS 引擎并读取 API Key。

        Args:
            voice:        默认音色名称
            audio_format: 默认输出音频格式（mp3 / wav / pcm）
            sample_rate:  默认输出采样率
        """
        # 保存默认音色，合成时若未显式指定则使用该值
        self.voice        = voice
        # 保存默认输出音频格式
        self.audio_format = audio_format
        # 保存默认输出采样率
        self.sample_rate  = sample_rate
        # 从配置读取 DashScope API Key；缺失时回退为空字符串，便于后续判空
        self._api_key     = getattr(settings, "dashscope_api_key", "") or ""

        # 未配置 API Key 时告警，TTS 将处于不可用状态（合成返回空字节）
        if not self._api_key:
            logger.warning("DASHSCOPE_API_KEY 未配置，TTS 功能不可用")

    @property
    def available(self) -> bool:
        """是否具备调用条件（即是否已配置 API Key）。"""
        # 仅当 API Key 非空时视为可用
        return bool(self._api_key)

    # ── 流式合成（WebSocket 推流） ─────────────────────────────────────────────

    async def synthesize_stream(
        self,
        text: str,
        voice: Optional[str] = None,
    ) -> AsyncIterator[bytes]:
        """
        流式合成音频，逐块 yield bytes

        Usage:
            async for chunk in tts_engine.synthesize_stream(text):
                await websocket.send_bytes(chunk)
        """
        # API Key 缺失时跳过合成，直接结束生成器（不产出任何字节）
        if not self.available:
            logger.warning("TTS 不可用，跳过合成")
            return

        # 文本为空（或仅空白）时无需合成，直接结束
        if not text.strip():
            return

        # 构造请求头：Bearer 鉴权、JSON 内容类型，并开启 SSE 流式返回
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type":  "application/json",
            # 开启服务端事件流，使响应以分块方式推送
            "X-DashScope-SSE": "enable",
        }
        # 构造请求体：指定模型、输入文本及合成参数（音色/格式/采样率）
        payload = {
            "model": "cosyvoice-v1",
            "input": {"text": text},
            "parameters": {
                # 优先使用调用时传入的音色，否则用实例默认音色
                "voice":       voice or self.voice,
                "format":      self.audio_format,
                "sample_rate": self.sample_rate,
            },
        }

        # 包裹网络请求，任何异常都不应中断上层主流程
        try:
            # 创建异步 HTTP 客户端，设置 60 秒超时，with 结束自动关闭连接
            async with httpx.AsyncClient(timeout=60) as client:
                # 以流式方式发起 POST 请求，逐块读取响应体
                async with client.stream(
                    "POST", _COSYVOICE_URL,
                    headers=headers,
                    json=payload,
                ) as resp:
                    # 非 200 状态视为失败：读取并记录截断后的错误响应，然后结束
                    if resp.status_code != 200:
                        body = await resp.aread()
                        logger.error(
                            "TTS API 错误: {} {}", resp.status_code, body[:200]
                        )
                        return

                    # 按 4096 字节为单位异步读取音频块
                    async for chunk in resp.aiter_bytes(chunk_size=4096):
                        # 跳过空块，仅产出有数据的块给调用方实时推送
                        if chunk:
                            yield chunk

        # 请求超时单独记录，便于区分网络问题
        except httpx.TimeoutException:
            logger.error("TTS 请求超时")
        # 其他异常统一记录，保证流式生成器安全结束
        except Exception as e:
            logger.error("TTS 流式合成异常: {}", e)

    # ── 同步合成（REST API 返回） ──────────────────────────────────────────────

    def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
    ) -> bytes:
        """
        同步合成，返回完整音频字节

        适合 REST 接口：response = tts_engine.synthesize(text)
        """
        # 不可用或文本为空时直接返回空字节
        if not self.available or not text.strip():
            return b""

        # 用列表收集流式产出的各音频块，最后合并为完整字节
        chunks: list[bytes] = []

        # 定义内部协程：消费流式生成器并把每块追加到 chunks
        async def _collect() -> None:
            async for chunk in self.synthesize_stream(text, voice=voice):
                chunks.append(chunk)

        # 包裹事件循环调度逻辑，异常时降级返回空字节
        try:
            # 兼容已有事件循环（FastAPI 环境）和无事件循环（脚本环境）
            # 根据当前是否已有运行中的事件循环，选择不同的协程执行方式
            try:
                # 获取当前线程的事件循环
                loop = asyncio.get_event_loop()
                # 若事件循环正在运行（如处于 FastAPI 异步上下文中）
                if loop.is_running():
                    # 在 FastAPI 中，使用 asyncio.run_coroutine_threadsafe
                    # 借助线程安全调度把协程提交到运行中的循环执行，避免阻塞/重入报错
                    import concurrent.futures
                    future = asyncio.run_coroutine_threadsafe(_collect(), loop)
                    # 阻塞等待协程完成，最长 60 秒
                    future.result(timeout=60)
                # 事件循环存在但未运行（普通脚本环境）：直接运行至完成
                else:
                    loop.run_until_complete(_collect())
            # 无可用事件循环时（get_event_loop 抛 RuntimeError）：新建循环运行
            except RuntimeError:
                asyncio.run(_collect())
        # 任意失败都记录并返回空字节，保证调用方拿到可处理的结果
        except Exception as e:
            logger.error("TTS 同步合成失败: {}", e)
            return b""

        # 将所有音频块拼接为完整字节序列返回
        return b"".join(chunks)

    async def synthesize_async(
        self,
        text: str,
        voice: Optional[str] = None,
    ) -> bytes:
        """异步全量合成（FastAPI async 路由使用）"""
        # 在异步上下文中收集所有音频块
        chunks: list[bytes] = []
        # 逐块消费流式生成器并累积
        async for chunk in self.synthesize_stream(text, voice=voice):
            chunks.append(chunk)
        # 合并为完整音频字节返回
        return b"".join(chunks)


# 全局单例
# 模块加载即创建全局 TTS 引擎实例，供整个项目共享复用
tts_engine = TTSEngine()