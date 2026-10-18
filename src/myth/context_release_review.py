"""Context Discovery/held-out 发布前复核：从完整原始 Trial 重算门槛，不信任报告缓存。

只读两个本地 Benchmark 目录，不执行模型/工具、不切换活动策略；READY 仅表示可以
递交人工审核，不是生产发布许可、外部收据真实性证明或全任务 SOTA 宣称。
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from .domain import digest_json
from .task_benchmark import CONTEXT_BENCHMARK_ARMS, summarize_context_ablation


# 固定工作流接受的完整 Arm 集与三次配对试次，缺测或筛题绝不进入最终评审。
_REQUIRED_ARMS = frozenset(CONTEXT_BENCHMARK_ARMS)
_SOURCE_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


# 从一个本地评测目录校验原始 Suite/Trial 身份，并独立重算所有配对统计。
def _validated_bundle(directory: str | Path) -> dict[str, Any]:
    root = Path(directory).resolve()
    report = json.loads((root / "report.json").read_text(encoding="utf-8"))
    suite = json.loads((root / "suite.json").read_text(encoding="utf-8"))
    if not isinstance(report, dict) or not isinstance(suite, dict):
        raise ValueError("benchmark report/suite must be JSON objects")
    cases = suite.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("benchmark suite must have a nonempty fixed case list")
    ids = [row.get("id") for row in cases if isinstance(row, dict)]
    if len(ids) != len(cases) or not all(isinstance(value, str) and value for value in ids):
        raise ValueError("benchmark suite contains invalid case identities")
    if len(set(ids)) != len(ids):
        raise ValueError("benchmark suite has duplicate case identities")
    if report.get("suite_digest") != digest_json(suite) or report.get("suite_id") != suite.get("suite_id"):
        raise ValueError("benchmark suite digest or identity mismatch")

    repeats = report.get("repeats")
    arms = report.get("arms")
    observations = report.get("trials")
    expected = len(ids) * repeats * len(_REQUIRED_ARMS) if type(repeats) is int else 0
    if (
        type(repeats) is not int or not 3 <= repeats <= 10
        or not isinstance(arms, list) or len(arms) != len(_REQUIRED_ARMS)
        or frozenset(arms) != _REQUIRED_ARMS
        or report.get("kind") != "real_provider"
        or report.get("provider") in ("scripted", None, "")
        or report.get("complete_suite") is not True
        or type(report.get("planned_trials")) is not int or report["planned_trials"] != expected
        or type(report.get("suite_case_count")) is not int or report["suite_case_count"] != len(ids)
        or type(report.get("selected_case_count")) is not int or report["selected_case_count"] != len(ids)
        or not isinstance(observations, list) or len(observations) != expected
    ):
        raise ValueError("benchmark must contain complete real-provider four-arm repeated trials")

    expected_cells = {(case_id, repeat, arm)
                      for case_id in ids for repeat in range(1, repeats + 1)
                      for arm in _REQUIRED_ARMS}
    seen = set()
    for trial in observations:
        if not isinstance(trial, dict):
            raise ValueError("benchmark trial must be a JSON object")
        case_id, repeat, arm = trial.get("case_id"), trial.get("repeat"), trial.get("arm")
        if not isinstance(case_id, str) or type(repeat) is not int or not isinstance(arm, str):
            raise ValueError("benchmark trial has invalid case/repeat/arm identity")
        cell = (case_id, repeat, arm)
        if cell not in expected_cells or cell in seen:
            raise ValueError("benchmark trial grid has missing, foreign or duplicate cells")
        seen.add(cell)
        if type(trial.get("success")) is not bool:
            raise ValueError("benchmark trial must have an explicit independent oracle verdict")
        evidence_root = trial.get("evidence_root")
        if not isinstance(evidence_root, str):
            raise ValueError("benchmark trial is missing its durable evidence directory")
        resolved = Path(evidence_root).resolve()
        if not resolved.is_relative_to(root) or not resolved.is_dir():
            raise ValueError("benchmark trial durable evidence is missing or outside bundle")
    if seen != expected_cells:
        raise ValueError("benchmark trial grid is incomplete")
    source = report.get("source_digest")
    if not isinstance(source, str) or not _SOURCE_DIGEST.fullmatch(source):
        raise ValueError("benchmark is missing its source version digest")

    # 以真实 Trial 而非可修改的 context_ablation 缓存重新计算全部安全、成本与统计结论。
    calculated = summarize_context_ablation(
        observations, tuple(arms), tuple(ids), repeats,
        kind=report["kind"], complete_suite=True,
    )
    if report.get("context_ablation") != calculated:
        raise ValueError("benchmark context summary differs from original trials")
    return {
        "directory": str(root),
        "suite": suite,
        "report": report,
        "case_ids": tuple(ids),
        "calculated": calculated,
    }


# 按两个独立已完成基准作研究级发布复核；任何不确定身份/统计结果均 HOLD。
def review_context_release(discovery_dir: str | Path, heldout_dir: str | Path) -> dict[str, Any]:
    discovery = _validated_bundle(discovery_dir)
    final = _validated_bundle(heldout_dir)
    first, second = discovery["report"], final["report"]
    reasons: list[str] = []

    if first.get("partition") != "discovery" or discovery["suite"].get("partition", "discovery") != "discovery":
        reasons.append("discovery suite partition is not discovery")
    if second.get("partition") != "declared_heldout" or final["suite"].get("partition") != "heldout":
        reasons.append("heldout suite partition is not declared_heldout")
    if first["suite_digest"] == second["suite_digest"] or first["suite_id"] == second["suite_id"]:
        reasons.append("discovery and heldout must have distinct suite identities")
    if set(discovery["case_ids"]) & set(final["case_ids"]):
        reasons.append("discovery and heldout case identities overlap")

    # 两套实验必须绑定同一源码、模型与设置；供应商别名不证明底层权重版本相同。
    for field in ("source_digest", "runtime_version", "provider", "model", "settings"):
        if not first.get(field) or first[field] != second.get(field):
            reasons.append(f"discovery/heldout frozen environment differs: {field}")
    model_a, model_b = first.get("model_metadata"), second.get("model_metadata")
    digest_a = model_a.get("digest") if isinstance(model_a, dict) else None
    digest_b = model_b.get("digest") if isinstance(model_b, dict) else None
    if not digest_a or not digest_b or digest_a != digest_b:
        reasons.append("model weight digest is unavailable or changed; manual identity proof required")
    if not discovery["calculated"]["ready_for_separate_heldout_review"]:
        reasons.append("discovery paired quality/cost/statistical gate did not pass")
    if not final["calculated"]["ready_for_separate_heldout_review"]:
        reasons.append("heldout paired quality/cost/statistical gate did not pass")

    # 摘要用于复核时确认输入未换；无法抵御同时篡改 report 和摘要的有权限攻击者。
    evidence_digest = "sha256:" + digest_json({
        "format": "context-release-review-v1",
        "discovery": first,
        "heldout": second,
    })
    return {
        "status": "HOLD" if reasons else "READY_FOR_MANUAL_REVIEW",
        "promotion_eligible": False,
        "evidence_digest": evidence_digest,
        "provider": first.get("provider"),
        "model": first.get("model"),
        "model_digest": digest_a if digest_a and digest_a == digest_b else None,
        "discovery": {
            "suite_id": first["suite_id"],
            "case_count": len(discovery["case_ids"]),
            "repeats": first["repeats"],
            "paired_significance": discovery["calculated"]["paired_significance"],
        },
        "heldout": {
            "suite_id": second["suite_id"],
            "case_count": len(final["case_ids"]),
            "repeats": second["repeats"],
            "paired_significance": final["calculated"]["paired_significance"],
        },
        "reasons": reasons,
        "limits": (
            "This is a report-and-directory consistency review, not third-party oracle "
            "attestation. Known public heldout cases, possible case correlation and "
            "provider provenance limit generalization. No policy is automatically promoted."
        ),
    }
