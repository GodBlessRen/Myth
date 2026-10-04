"""Skill 声明和版本的纯目录。
只登记可解释的规则资源，不能根据名称扩大 Runtime 权限，也不执行外部脚本。"""

from __future__ import annotations

from dataclasses import dataclass


# 可复用流程的声明合同；能力需求只描述前提，不授予需求中的能力。
@dataclass(frozen=True)
class SkillSpec:
    # skill_id：可复用流程身份；目录注册不产生权限。
    skill_id: str
    # description：显式说明文本；不作为能力授权。
    description: str
    # capability_requirements：流程要求的能力身份集合；需求不能自动变成授权。
    capability_requirements: tuple[str, ...] = ()
    # enabled：明确启用开关；只作用于未来目录/准入。
    enabled: bool = True


# 纯 Skill 目录；启用过滤用于导航，不执行资源内脚本。
class SkillRegistry:
    # 保存本实例的协作对象与配置；状态/I/O 边界见类合同，实例字段不能替代持久执行事实。
    def __init__(self) -> None:
        # _skills：已登记流程合同；能力需求仍需本地准入。
        self._skills: dict[str, SkillSpec] = {}

    # 按稳定身份登记显式合同；校验冲突以避免悄悄替换已存在定义。
    def register(self, skill: SkillSpec) -> None:
        if not skill.skill_id or skill.skill_id in self._skills:
            raise ValueError(f"duplicate/empty skill: {skill.skill_id}")
        self._skills[skill.skill_id] = skill

    # 返回当前目录/仓储的可见条目；排序和过滤只生成投影，不授予执行权。
    def list(self, *, enabled_only: bool = True) -> tuple[SkillSpec, ...]:
        values = tuple(sorted(self._skills.values(), key=lambda item: item.skill_id))
        return (
            tuple(item for item in values if item.enabled) if enabled_only else values
        )
