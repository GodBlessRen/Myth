"""组件成熟度与职责的纯描述合同。
元数据只描述当前职责；成熟度声明必须与源码和验证证据一致。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


# 架构条目的成熟度；与 Run 生命周期是两个独立概念。
class Maturity(StrEnum):
    # EXISTS：合同/组件存在，尚不宣称完整产品装配。
    EXISTS = "exists"
    # CONNECTED：当前路径已经装配，真实验证范围另见证据。
    CONNECTED = "connected"
    # USABLE：已有明确可用路径；不能外推为所有场景稳定。
    USABLE = "usable"
    # HARDENED：声明的加固成熟度；需要对应测试和证据支持。
    HARDENED = "hardened"
    # PLANNED：规划中的能力/后端；不会因登记而自动执行。
    PLANNED = "planned"


# 组件身份、职责、成熟度和依赖的纯元数据；不保存真实执行状态。
@dataclass(frozen=True)
class ArchitectureItem:
    # item_id：架构元数据稳定身份；不是运行实例 ID。
    item_id: str
    # label：产品显示名称；不能替代执行状态。
    label: str
    # kind：当前合同的对象/记忆用途分类；需与所属枚举解释。
    kind: str
    # maturity：架构条目成熟度声明；与实际装配/验证保持一致。
    maturity: Maturity
    # responsibility：单一职责说明；描述不代表实现已经完成。
    responsibility: str
    # depends_on：显式前置依赖身份；不是已完成证明。
    depends_on: tuple[str, ...] = ()

    # 输出架构描述的 JSON 投影；依赖和成熟度是声明，不是执行收据。
    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.item_id,
            "label": self.label,
            "kind": self.kind,
            "maturity": self.maturity.value,
            "responsibility": self.responsibility,
            "depends_on": list(self.depends_on),
        }
