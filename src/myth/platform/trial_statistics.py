"""真实 Provider 对照的逐 Case 配对统计；同题重复试次只贡献一个独立比较单位。

本模块不访问 Provider、数据库或文件，也不发放发布许可；显著性只描述固定 Case 集，
不能代替独立 Oracle、真实模型版本核对和人工发布审批。
"""

from __future__ import annotations

from math import comb, isfinite
from typing import Any


# 固定发布前的独立性与显著性下限：六个非平手 Case、三次重复和单侧 5%。
MIN_INDEPENDENT_CASES = 6
MIN_REPEATS = 3
ONE_SIDED_ALPHA = 0.05
PRIMARY_COST_METER = "input_tokens"


# 将同 Case 的全部重复成本差归并为一个符号，排除同 Case 内伪独立造成的显著性幻觉。
def case_clustered_sign_test(
    pairs: list[dict[str, Any]],
    case_ids: tuple[str, ...],
    repeats: int,
    *,
    meter: str = PRIMARY_COST_METER,
) -> dict[str, Any]:
    if type(repeats) is not int or repeats < 1 or not case_ids or len(set(case_ids)) != len(case_ids):
        raise ValueError("sign test requires valid repeats and unique case identities")
    if not isinstance(meter, str) or not meter:
        raise ValueError("sign test requires a declared cost meter")

    # 固定完整 denominator，每个 Case/Repeat 必须出现且唯一；缺测成本不是零。
    expected = {(case_id, repeat) for case_id in case_ids for repeat in range(1, repeats + 1)}
    values: dict[tuple[str, int], float] = {}
    invalid = []
    for pair in pairs:
        key = (pair.get("case_id"), pair.get("repeat"))
        raw = ((pair.get("measured_cost") or {}).get(meter) or {}).get("delta")
        if (
            key not in expected
            or key in values
            or pair.get("status") != "PAIRED"
            or type(raw) not in (int, float)
            or not isfinite(raw)
        ):
            invalid.append({"case_id": key[0], "repeat": key[1]})
            continue
        values[key] = float(raw)

    missing = sorted(expected - values.keys())
    case_delta: dict[str, float] = {}
    if not invalid and not missing:
        for case_id in case_ids:
            value = sum(values[(case_id, repeat)] for repeat in range(1, repeats + 1))
            if not isfinite(value):
                invalid.append({"case_id": case_id, "repeat": None})
                break
            case_delta[case_id] = value

    wins = sum(value < 0 for value in case_delta.values())
    losses = sum(value > 0 for value in case_delta.values())
    ties = sum(value == 0 for value in case_delta.values())
    discordant_cases = wins + losses
    # 这是事先指定单一主指标的一侧精确二项符号检验；ties 不进入成功/失败。
    p_value = (
        sum(comb(discordant_cases, k) for k in range(wins, discordant_cases + 1))
        / (2 ** discordant_cases)
        if discordant_cases else None
    )
    coverage_ok = not invalid and not missing and len(case_delta) == len(case_ids)
    return {
        "method": "one-sided-exact-sign-by-case-v1",
        "primary_meter": meter,
        "case_count": len(case_ids),
        "repeats_per_case": repeats,
        "observed_pairs": len(values),
        "expected_pairs": len(expected),
        "invalid_pairs": invalid,
        "missing_pairs": [{"case_id": key[0], "repeat": key[1]} for key in missing],
        "case_cost_deltas": case_delta,
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "discordant_cases": discordant_cases,
        "p_one_sided": p_value,
        "alpha": ONE_SIDED_ALPHA,
        "min_case_clusters": MIN_INDEPENDENT_CASES,
        "min_repeats": MIN_REPEATS,
        "coverage_complete": coverage_ok,
        "passed": bool(
            coverage_ok
            and repeats >= MIN_REPEATS
            and discordant_cases >= MIN_INDEPENDENT_CASES
            and p_value is not None
            and p_value <= ONE_SIDED_ALPHA
            and wins > losses
        ),
        "limitations": (
            "Repeats are paired within one case, not independent tasks; case-level sign test "
            "assumes independent cases, and cannot prove generalization or randomized causality."
        ),
    }
