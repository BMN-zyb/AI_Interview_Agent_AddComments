"""
技能注册器：可插拔扩展
"""
# 启用延迟注解求值，便于使用前向引用并降低导入耦合
from __future__ import annotations

# 标准库类型注解：Dict 描述注册表的键值映射，Optional 表示查询结果可能为 None
from typing import Dict, Optional

# 导入技能基类，作为注册表中所有技能的统一类型
from skills.base_skill import BaseSkill
# 导入各个具体技能类，下方用于实例化并注册到全局注册表
from skills.compare_skill import CompareSkill
from skills.project_skill import ProjectSkill
from skills.quiz_skill import QuizSkill
from skills.teach_skill import TeachSkill


class SkillRegistry:
    """技能注册表"""

    def __init__(self) -> None:
        """初始化空注册表，内部用字典以技能名为键保存技能实例。"""
        # 内部存储：技能名 -> 技能实例的映射，下划线前缀表示私有，不对外直接访问
        self._skills: Dict[str, BaseSkill] = {}

    def register(self, skill: BaseSkill) -> None:
        """注册一个技能实例。

        参数:
            skill: 技能实例；以其 name 属性作为键存入注册表（同名会覆盖）。
        """
        # 以技能的 name 作为键写入字典，实现按名查找；重名时后注册者覆盖前者
        self._skills[skill.name] = skill

    def get(self, name: str) -> Optional[BaseSkill]:
        """按名称查询技能实例。

        参数:
            name: 技能名称。
        返回:
            对应的技能实例；若未注册则返回 None。
        """
        # 使用 dict.get 安全查询，未命中返回 None 而非抛出 KeyError
        return self._skills.get(name)

    def list_skills(self) -> list[str]:
        """列出所有已注册技能的名称。

        返回:
            技能名称组成的列表。
        """
        # 将字典所有键转为 list 返回，供上层展示可用技能清单
        return list(self._skills.keys())


# 创建全局唯一的技能注册表单例，供整个应用共享使用
skill_registry = SkillRegistry()
# 注册内置技能
# 遍历内置技能类元组，逐个实例化并注册，实现"可插拔"的集中注册
for _cls in (QuizSkill, TeachSkill, ProjectSkill, CompareSkill):
    # 实例化技能并注册；type: ignore 抑制将抽象基类子类当可调用对象的类型检查告警
    skill_registry.register(_cls())  # type: ignore[operator]
