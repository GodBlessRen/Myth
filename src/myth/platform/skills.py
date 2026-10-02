"""Skill catalog: reusable procedures remain separate from tool authority."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SkillSpec:
    skill_id: str
    description: str
    capability_requirements: tuple[str, ...] = ()
    enabled: bool = True


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, SkillSpec] = {}

    def register(self, skill: SkillSpec) -> None:
        if not skill.skill_id or skill.skill_id in self._skills:
            raise ValueError(f"duplicate/empty skill: {skill.skill_id}")
        self._skills[skill.skill_id] = skill

    def list(self, *, enabled_only: bool = True) -> tuple[SkillSpec, ...]:
        values = tuple(sorted(self._skills.values(), key=lambda item: item.skill_id))
        return tuple(item for item in values if item.enabled) if enabled_only else values
