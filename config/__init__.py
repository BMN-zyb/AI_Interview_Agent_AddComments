"""配置模块"""
# 本包对外的统一入口：把分散在各子模块中的配置对象与工具函数集中导出，
# 让其它模块只需 `from config import settings, setup_logger` 即可使用，
# 而无需关心它们具体定义在哪个子文件里。

# 从 settings 子模块导入全局配置单例 settings（已实例化的 Settings 对象）
from config.settings import settings
# 从 logging 子模块导入日志初始化函数 setup_logger（用于配置全局 loguru 日志器）
from config.logging import setup_logger

# 显式声明本包的公开 API：限定 `from config import *` 时仅导出这两个名称，
# 同时也作为给阅读者/IDE 的“对外接口”说明。
__all__ = ["settings", "setup_logger"]
