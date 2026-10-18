"""可执行、受限的语义合同：定义、JSON Pointer 映射、单位与值约束。

本模块只做纯验证；不把来源关联视作事实正确、因果证明或执行权限。
Memory 的 revision/scope/freshness 由已有权威仓储判断，合同本身不拥有另一套事实库。
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any

# TERM_ID：稳定的命名空间术语身份；不使用来源正文或 LLM 同义词猜测主键。
_TERM_ID = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){1,4}$")
# MEMORY_ID：只接受现有 Memory 仓储的持久身份，不接受可变描述或模糊引用。
_MEMORY_ID = re.compile(r"^mem_[0-9a-f]{32}$")
# UNIT：单位必须是可比的明确标识，不能在映射时从自由文本默默推导。
_UNIT = re.compile(r"^[A-Za-z][A-Za-z0-9_/%.-]{0,19}$")
# CONTRACT_VERSION：结构自身的固定版本；未知结构不能自动按当前版本解释。
CONTRACT_VERSION = "myth.semantic-contract/v1"
# 可执行聚合只有确定性的有限数组操作；不暗示 SQL 分组/时间粒度推断。
_AGGREGATIONS = {"none", "sum", "avg", "count"}
# 可执行值类型与 Python bool/int 边界明确区分。
_TYPES = {"number", "string", "boolean"}


# _number：JSON 数值必须有限且不能把 bool 当 0/1 混入定量结论。
def _number(value: object) -> bool:
    if type(value) not in {int, float}:
        return False
    # 超大整数可能使 math.isfinite 的隐式 float 转换溢出，拒绝而不是变成异常绕过。
    if type(value) is int and value.bit_length() > 256:
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, ValueError):
        return False


# _string：字段长度/内容在输入阶段限制，避免存入无界的描述或模糊身份。
def _string(value: object, *, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{label} must be a nonempty bounded string")
    return value.strip()


# _pointer_tokens：只解析有界 RFC6901 Pointer；不执行 Python/SQL 表达式和任意索引代码。
def _pointer_tokens(value: object) -> tuple[str, ...]:
    if not isinstance(value, str) or not value.startswith("/") or len(value) > 160:
        raise ValueError("semantic JSON pointer must be a bounded absolute pointer")
    segments = value[1:].split("/")
    if len(segments) > 12 or any(re.search(r"~(?![01])", segment) for segment in segments):
        raise ValueError("semantic JSON pointer has unsupported escaping/depth")
    return tuple(part.replace("~1", "/").replace("~0", "~") for part in segments)


# _constraint：只容许有限数值界限与枚举约束；无动态表达式、正则执行或 LLM 断言。
def _constraint(raw: object, value_type: str) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError("semantic constraint must be an object")
    kind = raw.get("kind")
    if kind in {"min", "max"}:
        if value_type != "number" or set(raw) != {"kind", "value"} or not _number(raw["value"]):
            raise ValueError("numeric semantic constraint requires a finite number")
        return {"kind": kind, "value": raw["value"]}
    if kind == "enum":
        if set(raw) != {"kind", "values"} or value_type == "number":
            raise ValueError("semantic enum is limited to string or boolean types")
        values = raw["values"]
        if not isinstance(values, list) or not 1 <= len(values) <= 12:
            raise ValueError("semantic enum values must be a bounded list")
        correct = (lambda item: isinstance(item, str) and 0 < len(item) <= 200) if value_type == "string" else (lambda item: type(item) is bool)
        if not all(correct(item) for item in values) or len({repr(v) for v in values}) != len(values):
            raise ValueError("semantic enum has invalid or duplicate values")
        return {"kind": "enum", "values": sorted(values, key=str)}
    raise ValueError("unknown semantic constraint kind")


# normalize_contract：在任何数据库写入前固定跨模型可复现的术语、映射与约束形状。
def normalize_contract(raw: Mapping[str, Any]) -> dict[str, Any]:
    """返回严格 JSON 形状；无默认事实等级，也不接受模型附带的 verified/confidence。"""
    allowed = {"schema", "term_id", "definition", "value_type", "unit", "mappings", "constraints"}
    if not isinstance(raw, Mapping) or set(raw) - allowed or not {"term_id", "definition", "value_type", "mappings"} <= set(raw):
        raise ValueError("semantic contract has missing or unsupported fields")
    if raw.get("schema", CONTRACT_VERSION) != CONTRACT_VERSION:
        raise ValueError("unsupported semantic contract schema")
    term_id = _string(raw["term_id"], label="term_id", maximum=96)
    if _TERM_ID.fullmatch(term_id) is None:
        raise ValueError("term_id requires a dotted lowercase namespace")
    definition = _string(raw["definition"], label="definition", maximum=500)
    value_type = raw["value_type"]
    if not isinstance(value_type, str) or value_type not in _TYPES:
        raise ValueError("unsupported semantic value_type")
    unit = raw.get("unit")
    if unit is not None and (
        value_type != "number" or not isinstance(unit, str) or _UNIT.fullmatch(unit) is None
    ):
        raise ValueError("unit is only allowed for a numeric value with an explicit unit id")
    mappings = raw["mappings"]
    if not isinstance(mappings, list) or not 1 <= len(mappings) <= 4:
        raise ValueError("semantic mappings must contain 1-4 entries")
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw_mapping in mappings:
        if not isinstance(raw_mapping, Mapping) or set(raw_mapping) - {"source_memory_id", "pointer", "aggregation", "unit_pointer"}:
            raise ValueError("semantic mapping has unsupported fields")
        source_id = raw_mapping.get("source_memory_id")
        if not isinstance(source_id, str) or _MEMORY_ID.fullmatch(source_id) is None:
            raise ValueError("semantic mapping requires an exact source Memory id")
        pointer = raw_mapping.get("pointer")
        _pointer_tokens(pointer)
        aggregation = raw_mapping.get("aggregation", "none")
        if aggregation not in _AGGREGATIONS or (aggregation != "none" and value_type != "number"):
            raise ValueError("semantic aggregation requires a supported numeric operation")
        unit_pointer = raw_mapping.get("unit_pointer")
        if (unit is None) != (unit_pointer is None):
            raise ValueError("a declared unit requires a source unit_pointer, and vice versa")
        if unit_pointer is not None:
            _pointer_tokens(unit_pointer)
            if unit_pointer == pointer:
                raise ValueError("unit pointer must differ from the value pointer")
        identity = (source_id, pointer)
        if identity in seen:
            raise ValueError("semantic mapping source/pointer must be unique")
        seen.add(identity)
        normalized.append({
            "source_memory_id": source_id,
            "pointer": pointer,
            "aggregation": aggregation,
            "unit_pointer": unit_pointer,
        })
    constraints = raw.get("constraints", [])
    if not isinstance(constraints, list) or len(constraints) > 3:
        raise ValueError("semantic constraints must be a bounded list")
    compiled = [_constraint(item, value_type) for item in constraints]
    if len({row["kind"] for row in compiled}) != len(compiled):
        raise ValueError("duplicate semantic constraint kind")
    limits = {row["kind"]: row["value"] for row in compiled if row["kind"] in {"min", "max"}}
    if "min" in limits and "max" in limits and limits["min"] > limits["max"]:
        raise ValueError("semantic min exceeds max")
    return {
        "schema": CONTRACT_VERSION,
        "term_id": term_id,
        "definition": definition,
        "value_type": value_type,
        "unit": unit,
        "mappings": sorted(normalized, key=lambda row: (row["source_memory_id"], row["pointer"])),
        "constraints": sorted(compiled, key=lambda row: row["kind"]),
    }


# _at_pointer：只遍历 JSON 对象/数组；越界、缺键或类型错误均是已知拒绝。
def _at_pointer(document: object, pointer: str) -> object:
    value = document
    for token in _pointer_tokens(pointer):
        if isinstance(value, dict):
            if token not in value:
                raise ValueError("semantic mapping pointer is missing")
            value = value[token]
        elif isinstance(value, list):
            if not token.isdigit() or (len(token) > 1 and token.startswith("0")) or int(token) >= len(value):
                raise ValueError("semantic mapping array index is invalid")
            value = value[int(token)]
        else:
            raise ValueError("semantic mapping traverses a non-container")
    return value


# value_violations：返回稳定失败原因；类型、数值范围和枚举是不同的合同条件。
def value_violations(value: object, contract: Mapping[str, Any]) -> list[str]:
    kind = contract["value_type"]
    accepted = (
        _number(value) if kind == "number"
        else isinstance(value, str) if kind == "string"
        else type(value) is bool
    )
    if not accepted:
        return ["value_type_mismatch"]
    reasons = []
    for rule in contract["constraints"]:
        if rule["kind"] == "min" and value < rule["value"]:
            reasons.append("below_min")
        elif rule["kind"] == "max" and value > rule["value"]:
            reasons.append("above_max")
        elif rule["kind"] == "enum" and value not in rule["values"]:
            reasons.append("outside_enum")
    return reasons


# evaluate_json_mapping：精确执行一条有界 JSON 来源映射，语义值仍不自动成为验证过的事实。
def evaluate_json_mapping(document: object, contract: Mapping[str, Any], mapping: Mapping[str, Any]) -> object:
    value = _at_pointer(document, mapping["pointer"])
    operation = mapping["aggregation"]
    if operation != "none":
        if not isinstance(value, list) or len(value) > 1024:
            raise ValueError("semantic aggregate needs a bounded JSON array")
        if operation == "count":
            value = len(value)
        else:
            if not value or not all(_number(item) for item in value):
                raise ValueError("semantic numeric aggregate needs finite numeric members")
            value = sum(value)
            if operation == "avg":
                value = value / len(_at_pointer(document, mapping["pointer"]))
            if not _number(value):
                raise ValueError("semantic aggregate overflows finite numeric range")
    if contract["unit"] is not None:
        observed_unit = _at_pointer(document, mapping["unit_pointer"])
        if observed_unit != contract["unit"]:
            raise ValueError("semantic source unit does not match contract")
    return value
