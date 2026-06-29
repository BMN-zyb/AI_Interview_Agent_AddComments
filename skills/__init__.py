# skills 包的初始化模块：对外暴露技能注册器单例，作为整个技能子系统的统一入口
# 从技能注册器模块导入全局唯一的 skill_registry 单例（已在该模块中完成内置技能注册）
from skills.skill_registry import skill_registry

# __all__ 显式声明本包对外公开的符号，确保 from skills import * 只导出 skill_registry
__all__ = ["skill_registry"]
