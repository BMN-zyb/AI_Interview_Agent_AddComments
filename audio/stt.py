"""
STT 语音识别：基于 faster-whisper 本地模型
支持 WAV / WebM / PCM，自动格式检测
"""
# 启用延迟注解求值，使类型提示（如 Optional[...]）以字符串形式处理，提升兼容性
from __future__ import annotations

# 标准库：内存字节流，供 soundfile/librosa 从内存读取音频
import io
# 标准库：调用外部进程（这里用于调用系统 ffmpeg 做格式转换）
import subprocess
# 标准库：创建临时文件，承接 ffmpeg 的输入/输出
import tempfile
# 标准库：文件路径与删除等操作（清理临时文件）
import os
# 标准库类型标注：Optional 表示可能返回 None
from typing import Optional

# 第三方库：数值计算，音频以 numpy float32 数组表示
import numpy as np
# 第三方库：统一日志记录
from loguru import logger

# 项目内工具：将音频字节统一转换为归一化 float32 数组
from audio.audio_manager import bytes_to_float32

# 尝试导入 faster-whisper 推理模型类
try:
    from faster_whisper import WhisperModel
    # 标记 whisper 可用，引擎初始化时据此决定是否加载模型
    _WHISPER_AVAILABLE = True
# 未安装时降级处理，避免导入失败导致整个模块不可用
except ImportError:
    # 将类名置空，便于类型注解引用且不报错
    WhisperModel = None
    # 标记 whisper 不可用，STT 功能将整体禁用
    _WHISPER_AVAILABLE = False


def _detect_format(audio_bytes: bytes) -> str:
    """
    通过魔数检测音频格式
    Returns: 'wav' | 'webm' | 'ogg' | 'mp4' | 'unknown'
    """
    # 字节过短（不足以容纳文件头）则无法判断格式
    if len(audio_bytes) < 12:
        return 'unknown'
    # 取前 12 字节作为文件头用于魔数比对
    header = audio_bytes[:12]
    # RIFF 开头是 WAV 容器的标志
    if header[:4] == b'RIFF':
        return 'wav'
    # EBML 头（0x1A45DFA3）通常对应 WebM/MKV（两侧条件相同为冗余写法，保持原逻辑）
    if header[:4] == b'\x1aE\xdf\xa3' or header[:4] == b'\x1aE\xdf\xa3':
        return 'webm'
    # WebM/MKV EBML 头
    # 再次以元组成员形式判断 EBML 头（与上保持一致的兜底判断）
    if header[:4] in (b'\x1aE\xdf\xa3',):
        return 'webm'
    # 更宽松的 WebM 检测（浏览器 MediaRecorder 输出）
    # 在前 64 字节里搜索 'webm' 关键字，兼容部分浏览器录制的非标准头
    if b'webm' in audio_bytes[:64].lower() if hasattr(audio_bytes[:64], 'lower') else False:
        return 'webm'
    # OGG
    # OggS 魔数对应 OGG 容器
    if header[:4] == b'OggS':
        return 'ogg'
    # MP4/M4A
    # 第 4-8 字节为 ftyp/moov/mdat 时判定为 MP4/M4A 容器
    if header[4:8] in (b'ftyp', b'moov', b'mdat'):
        return 'mp4'
    # EBML (WebM)
    # 仅匹配前两字节 0x1A45 的更宽松 EBML 判断，作为 WebM 的兜底
    if header[:2] == b'\x1a\x45':
        return 'webm'
    # 以上均不匹配则返回未知格式
    return 'unknown'


def _convert_to_wav_ffmpeg(audio_bytes: bytes, fmt: str = 'webm') -> Optional[bytes]:
    """
    用 ffmpeg 将任意格式转为 16kHz 单声道 WAV
    需要系统安装 ffmpeg
    """
    # 用 try 包裹整体流程，保证任何异常都不会向上抛出（统一降级为 None）
    try:
        # 创建带原始格式后缀的临时输入文件（delete=False 以便交给 ffmpeg 读取后手动清理）
        with tempfile.NamedTemporaryFile(suffix=f'.{fmt}', delete=False) as fin:
            # 把原始音频字节写入临时输入文件
            fin.write(audio_bytes)
            # 记录输入文件路径供 ffmpeg 使用
            in_path = fin.name

        # 由输入路径推导输出 WAV 路径（仅替换后缀）
        out_path = in_path.replace(f'.{fmt}', '.wav')

        # 调用 ffmpeg 进行转码
        result = subprocess.run(
            [
                # -y：覆盖已存在的输出文件
                'ffmpeg', '-y',
                # -i：指定输入文件
                '-i', in_path,
                # -ar 16000：重采样到 16kHz（Whisper 要求）
                '-ar', '16000',
                # -ac 1：混音为单声道
                '-ac', '1',
                # -f wav：强制输出 WAV 封装
                '-f', 'wav',
                # 输出文件路径
                out_path,
            ],
            # 捕获 stdout/stderr，便于失败时读取错误信息
            capture_output=True,
            # 限制 30 秒超时，避免异常输入导致进程长期挂起
            timeout=30,
        )

        # ffmpeg 返回非 0 表示转换失败
        if result.returncode != 0:
            # 记录截断后的错误输出（前 200 字符）以便排查
            logger.warning("ffmpeg 转换失败: {}", result.stderr.decode()[:200])
            return None

        # 读取转换得到的 WAV 文件全部字节
        with open(out_path, 'rb') as f:
            wav_bytes = f.read()

        # 返回转换后的 WAV 字节
        return wav_bytes

    # ffmpeg 可执行文件不存在（系统未安装）时降级
    except FileNotFoundError:
        logger.warning("ffmpeg 未安装，无法转换音频格式")
        return None
    # 捕获其他异常（如超时、IO 错误），记录并返回 None
    except Exception as e:
        logger.error("ffmpeg 转换异常: {}", e)
        return None
    # 无论成功失败都执行清理，删除临时输入/输出文件
    finally:
        # 遍历需要清理的两个临时文件路径
        for p in [in_path, out_path]:
            # 逐个删除，单个失败不影响其余清理
            try:
                # 仅当文件确实存在时才删除
                if os.path.exists(p):
                    os.unlink(p)
            # 忽略清理过程中的任何异常（尽力而为）
            except Exception:
                pass


def _convert_to_float32_universal(audio_bytes: bytes) -> Optional[np.ndarray]:
    """
    通用音频字节 -> float32，自动检测格式
    优先用 ffmpeg，降级用 soundfile/librosa
    """
    # 先用魔数检测音频容器格式
    fmt = _detect_format(audio_bytes)
    # 调试日志：记录检测到的格式与数据大小
    logger.debug("检测到音频格式: {}, 大小: {} bytes", fmt, len(audio_bytes))

    # WAV 直接解析
    # WAV 可被内部解析器直接处理，优先走这条最快路径
    if fmt == 'wav':
        try:
            # 注：此行先计算一次结果但只取并赋值给 audio（采样率固定写为 16000），随后真正以下一行的返回为准
            audio, _ = bytes_to_float32(audio_bytes, is_wav=True), 16000
            # 返回解析得到的归一化 float32 音频
            return bytes_to_float32(audio_bytes, is_wav=True)
        # WAV 解析失败时不直接放弃，转而尝试 ffmpeg 兜底
        except Exception as e:
            logger.warning("WAV 直接解析失败: {}, 尝试 ffmpeg", e)

    # 非 WAV 或 WAV 解析失败 -> ffmpeg 转换
    # 用 ffmpeg 转为 WAV；格式未知时默认按 webm 处理（浏览器最常见输出）
    wav_bytes = _convert_to_wav_ffmpeg(audio_bytes, fmt=fmt if fmt != 'unknown' else 'webm')
    # ffmpeg 转换成功则解析转换后的 WAV
    if wav_bytes:
        try:
            return bytes_to_float32(wav_bytes, is_wav=True)
        # 转换后仍解析失败则记录错误并放弃
        except Exception as e:
            logger.error("ffmpeg 转换后解析失败: {}", e)
            return None

    # ffmpeg 不可用 -> 尝试 soundfile
    # 第一降级方案：使用 soundfile 直接从内存读取音频
    try:
        import soundfile as sf
        # 读取音频样本与其采样率
        audio, sr = sf.read(io.BytesIO(audio_bytes))
        # 多声道则按列求均值混音为单声道
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        # 统一为 float32 类型
        audio = audio.astype(np.float32)
        # 采样率不是 16kHz 时重采样到 16kHz
        if sr != 16000:
            from audio.audio_manager import resample
            audio = resample(audio, sr, 16000)
        # 返回处理后的音频数组
        return audio
    # soundfile 不可用或解析失败则记录并进入下一降级
    except Exception as e:
        logger.warning("soundfile 解析失败: {}", e)

    # 最后降级：尝试 librosa
    # 第二降级方案：使用 librosa 加载（内部可借助音频后端解码更多格式）
    try:
        import librosa
        # 以 16kHz 单声道直接加载，librosa 自动完成重采样与混音
        audio, _ = librosa.load(io.BytesIO(audio_bytes), sr=16000, mono=True)
        # 返回 float32 音频
        return audio.astype(np.float32)
    # librosa 也失败则记录错误
    except Exception as e:
        logger.error("librosa 解析失败: {}", e)

    # 所有方案均失败，返回 None 表示无法解析
    return None


class STTEngine:
    """
    语音识别引擎（faster-whisper 本地推理）
    自动处理 WAV / WebM / OGG 等浏览器常见格式
    """

    def __init__(
        self,
        model_size:   str = "base",
        device:       str = "cpu",
        compute_type: str = "int8",
        language:     str = "zh",
    ) -> None:
        """
        初始化 STT 引擎并尝试加载 Whisper 模型。

        Args:
            model_size:   模型规模（如 tiny/base/small/medium/large）
            device:       推理设备（cpu / cuda）
            compute_type: 计算精度（如 int8 量化以省内存、提速）
            language:     默认识别语言（zh 表示中文）
        """
        # 保存默认识别语言，供推理时传给模型
        self.language = language
        # 预置模型句柄为 None，加载失败或不可用时保持 None
        self.model: Optional[WhisperModel] = None

        # 若未安装 faster-whisper，直接告警并返回，不再尝试加载
        if not _WHISPER_AVAILABLE:
            logger.warning("faster-whisper 未安装，STT 功能不可用")
            return

        # 尝试按给定参数加载本地 Whisper 模型
        try:
            self.model = WhisperModel(
                model_size,
                device=device,
                compute_type=compute_type,
            )
            # 加载成功记录模型规模/设备/精度信息
            logger.info(
                "STT 模型加载完成: {} / {} / {}",
                model_size, device, compute_type,
            )
        # 加载失败（如模型下载/显存问题）时记录错误，self.model 仍为 None
        except Exception as e:
            logger.error("STT 模型加载失败: {}", e)

    @property
    def available(self) -> bool:
        """模型是否成功加载（可用于外部判断 STT 是否可执行）。"""
        # 模型句柄非空即视为可用
        return self.model is not None

    # ── 核心接口 ──────────────────────────────────────────────────────────────

    def transcribe_bytes(
        self,
        audio_bytes: bytes,
        is_wav: bool = False,       # 保留参数兼容旧调用，但内部自动检测
        sample_rate: int = 16000,
    ) -> str:
        """
        通用入口：接收任意格式音频字节，返回识别文本
        自动检测格式，无需调用方指定
        """
        # 模型不可用时直接返回空字符串（功能降级，不抛异常）
        if not self.available:
            logger.warning("STT 不可用")
            return ""

        # 空字节直接返回空文本，避免无谓处理
        if not audio_bytes:
            return ""

        # 包裹整个识别流程，任何异常都降级为返回空字符串
        try:
            # 自动检测格式并统一转换为归一化 float32 数组
            audio = _convert_to_float32_universal(audio_bytes)
            # 转换失败或为空音频时无法识别，返回空文本
            if audio is None or len(audio) == 0:
                logger.warning("音频转换失败，无法识别")
                return ""
            # 调用内部 Whisper 推理得到文本
            return self._run_whisper(audio)
        # 记录异常详情并返回空文本，保证主流程不中断
        except Exception as e:
            logger.error("STT transcribe_bytes 失败: {}", e)
            return ""

    def transcribe_wav(self, wav_bytes: bytes) -> str:
        """WAV 格式快捷入口"""
        # 直接复用通用入口并标记为 WAV（实际仍走自动检测）
        return self.transcribe_bytes(wav_bytes, is_wav=True)

    def transcribe_pcm(self, pcm_bytes: bytes, sample_rate: int = 16000) -> str:
        """PCM 原始字节快捷入口"""
        # 模型不可用直接返回空文本
        if not self.available:
            return ""
        # 包裹处理流程，异常降级为空文本
        try:
            # 将 int16 裸 PCM 转为归一化 float32 数组
            audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            # 采样率不是 16kHz 时重采样到 Whisper 要求的 16kHz
            if sample_rate != 16000:
                from audio.audio_manager import resample
                audio = resample(audio, sample_rate, 16000)
            # 执行推理并返回文本
            return self._run_whisper(audio)
        # 记录异常并返回空文本
        except Exception as e:
            logger.error("STT transcribe_pcm 失败: {}", e)
            return ""

    def transcribe_array(self, audio: np.ndarray) -> str:
        """直接接收 float32 numpy 数组"""
        # 模型不可用直接返回空文本
        if not self.available:
            return ""
        # 已是 float32 数组，直接推理；异常降级为空文本
        try:
            return self._run_whisper(audio)
        except Exception as e:
            logger.error("STT transcribe_array 失败: {}", e)
            return ""

    # ── 内部方法 ──────────────────────────────────────────────────────────────

    def _run_whisper(self, audio: np.ndarray) -> str:
        """调用 faster-whisper 推理"""
        # 音频过短（小于 1600 个样本，约 0.1 秒）信息量不足，跳过识别
        if len(audio) < 1600:   # 少于 0.1 秒，跳过
            logger.debug("音频太短，跳过识别")
            return ""

        # 执行 Whisper 转写，返回分段迭代器与音频信息
        segments, info = self.model.transcribe(
            audio,
            # beam_size=5：束搜索宽度，越大越准但越慢
            beam_size=5,
            # 指定识别语言，避免自动语种判别带来的偏差
            language=self.language,
            # 启用 VAD（语音活动检测）过滤掉静音/噪声片段
            vad_filter=True,
            # VAD 参数：静音超过 300ms 视为分段间隔
            vad_parameters={"min_silence_duration_ms": 300},
        )
        # 拼接所有分段文本（各段去首尾空格后用空格连接，再整体去空格）
        text = " ".join(s.text.strip() for s in segments).strip()
        # 调试日志：记录识别语言、语言置信度及文本前 80 字
        logger.debug(
            "STT 识别完成: lang={} prob={:.2f} text={}",
            info.language,
            info.language_probability,
            text[:80],
        )
        # 返回最终识别文本
        return text


# 全局单例
# 模块加载时即创建全局 STT 引擎实例，供整个项目共享，避免重复加载模型
stt_engine = STTEngine()