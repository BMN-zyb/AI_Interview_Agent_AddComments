"""音视频处理模块"""

# 从 stt 子模块导入全局 STT（语音转文字）引擎单例，方便外部统一从 audio 包引用
from audio.stt import stt_engine
# 从 tts 子模块导入全局 TTS（文字转语音）引擎单例
from audio.tts import tts_engine
# 从 audio_manager 子模块导入常用音频处理工具函数：PCM 转 WAV、重采样、归一化
from audio.audio_manager import pcm_to_wav, resample, normalize_audio

# 显式声明本包对外公开的符号，控制 `from audio import *` 的导出范围，也作为对外 API 清单
__all__ = ["stt_engine", "tts_engine", "pcm_to_wav", "resample", "normalize_audio"]