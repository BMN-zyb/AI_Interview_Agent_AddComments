"""
音频管理器：
- 格式转换（PCM <-> WAV）
- 采样率重采样
- 音频归一化
"""
# 启用未来注解特性：让函数签名中的类型注解（如 tuple[bytes, int]）以字符串形式延迟求值，
# 从而在较低版本 Python 上也能使用 PEP 585 风格的泛型写法
from __future__ import annotations

# 标准库：提供内存字节流 BytesIO，用于在内存中读写 WAV 而不落盘
import io
# 标准库：WAV 文件读写（封装/解析 WAV 容器格式）
import wave
# 标准库：最大公约数函数，用于计算重采样的上下采样比例
from math import gcd

# 第三方库：数值计算，音频以 numpy 数组形式处理
import numpy as np
# 第三方库：日志记录器，统一项目日志输出
from loguru import logger

# 尝试导入 scipy 的多相重采样函数（质量高、性能好）
try:
    from scipy.signal import resample_poly
    # scipy 可用标志置为 True，供 resample 函数判断是否能执行重采样
    _SCIPY_AVAILABLE = True
# 若环境未安装 scipy，则捕获导入错误，避免模块加载失败
except ImportError:
    # 标记 scipy 不可用，重采样功能将降级（直接返回原音频）
    _SCIPY_AVAILABLE = False
    # 打印警告，提示运行环境缺少 scipy 导致重采样不可用
    logger.warning("scipy 未安装，重采样功能不可用")


def pcm_to_wav(
    pcm_bytes: bytes,
    sample_rate: int = 16000,
    channels: int = 1,
    sampwidth: int = 2,
) -> bytes:
    """
    PCM 原始字节 -> WAV 格式字节

    Args:
        pcm_bytes:   PCM 原始数据
        sample_rate: 采样率，默认 16000
        channels:    声道数，默认 1（单声道）
        sampwidth:   采样位宽（字节），默认 2（16-bit）
    """
    # 创建内存字节缓冲区，作为 WAV 写入目标（避免写临时文件）
    buf = io.BytesIO()
    # 以写模式打开 WAV 容器，写入完成后自动关闭并刷新头部
    with wave.open(buf, "wb") as wf:
        # 设置声道数（如单声道=1，立体声=2）
        wf.setnchannels(channels)
        # 设置每个采样点的字节宽度（2 字节即 16-bit 量化）
        wf.setsampwidth(sampwidth)
        # 设置采样率（每秒采样点数）
        wf.setframerate(sample_rate)
        # 写入原始 PCM 数据帧，wave 会自动补全 WAV 文件头
        wf.writeframes(pcm_bytes)
    # 将缓冲区指针重置到起始位置，便于后续完整读取
    buf.seek(0)
    # 返回缓冲区中完整的 WAV 字节内容
    return buf.getvalue()


def wav_to_pcm(wav_bytes: bytes) -> tuple[bytes, int, int]:
    """
    WAV -> PCM 原始字节

    Returns:
        (pcm_bytes, sample_rate, channels)
    """
    # 以读模式打开内存中的 WAV 字节流并解析其头部
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        # 读取采样率
        sample_rate = wf.getframerate()
        # 读取声道数
        channels    = wf.getnchannels()
        # 读取全部采样帧，得到去掉头部的原始 PCM 数据
        pcm_bytes   = wf.readframes(wf.getnframes())
    # 返回（PCM 数据、采样率、声道数）三元组
    return pcm_bytes, sample_rate, channels


def wav_to_float32(wav_bytes: bytes) -> tuple[np.ndarray, int]:
    """
    WAV -> float32 numpy 数组（归一化到 [-1, 1]）

    Returns:
        (audio_array, sample_rate)
    """
    # 先把 WAV 解析为原始 PCM 字节及其采样率、声道数
    pcm_bytes, sample_rate, channels = wav_to_pcm(wav_bytes)
    # 将 16-bit 整型 PCM 转为 float32，并除以 32768（int16 满量程）归一化到 [-1, 1)
    audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    # 多声道转单声道
    # 若为多声道，将交错排列的样本重塑为 (帧数, 声道) 后按声道求均值，混音为单声道
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    # 返回浮点音频数组与采样率
    return audio, sample_rate


def resample(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """
    音频重采样

    Args:
        audio:    float32 音频数组
        src_rate: 源采样率
        dst_rate: 目标采样率
    """
    # 源采样率与目标采样率相同则无需处理，直接返回原数组
    if src_rate == dst_rate:
        return audio
    # scipy 不可用时无法重采样，记录错误并退回原始音频（功能降级而非崩溃）
    if not _SCIPY_AVAILABLE:
        logger.error("scipy 未安装，无法重采样，返回原始音频")
        return audio
    # 求两采样率的最大公约数，用于把比例化简为最简整数比，减小多相滤波器计算量
    g = gcd(src_rate, dst_rate)
    # 多相重采样：上采样因子=dst//g，下采样因子=src//g；结果转回 float32 保持类型一致
    return resample_poly(audio, dst_rate // g, src_rate // g).astype(np.float32)


def normalize_audio(audio: np.ndarray) -> np.ndarray:
    """音频归一化到 [-1, 1]"""
    # 取绝对值最大的样本作为峰值，用于按峰值缩放
    max_val = np.max(np.abs(audio))
    # 峰值近似为 0（接近静音）时直接返回，避免除以极小值造成数值放大/溢出
    if max_val < 1e-8:
        return audio
    # 按峰值缩放使最大幅度对齐到 1，并保证输出为 float32
    return (audio / max_val).astype(np.float32)


def bytes_to_float32(
    audio_bytes: bytes,
    sample_rate: int = 16000,
    is_wav: bool = False,
    target_rate: int = 16000,
) -> np.ndarray:
    """
    通用音频字节 -> float32 数组，自动处理重采样

    Args:
        audio_bytes:  音频字节（PCM 或 WAV）
        sample_rate:  PCM 模式下的采样率（WAV 模式自动读取）
        is_wav:       是否为 WAV 格式
        target_rate:  目标采样率（Whisper 需要 16000）
    """
    # WAV 模式：直接从 WAV 头解析音频与真实采样率
    if is_wav:
        audio, src_rate = wav_to_float32(audio_bytes)
    # 非 WAV（裸 PCM）模式：手动按 int16 解析并归一化，采样率取调用方传入值
    else:
        audio    = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        src_rate = sample_rate

    # 源采样率与目标采样率不一致时进行重采样（如 Whisper 要求 16kHz）
    if src_rate != target_rate:
        audio = resample(audio, src_rate, target_rate)

    # 最终再做一次峰值归一化后返回，保证幅度范围统一
    return normalize_audio(audio)