"""Pure domain types and deterministic helpers.

This module owns no database, filesystem, model, network, or process I/O. It
contains the small vocabulary that the runtime uses to distinguish business
intent (Action), execution opportunity (Attempt), launch authorization
(StartTicket), execution fact (Receipt), and completion authority
(VerificationReport).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from typing import Any


class RunState(StrEnum):
    READY = "READY"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    WAITING = "WAITING"
    VERIFYING = "VERIFYING"
    RECOVERING = "RECOVERING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"


class AttemptState(StrEnum):
    INTENT = "INTENT"
    TICKETED = "TICKETED"
    UNKNOWN = "UNKNOWN"
    RESOLVED = "RESOLVED"
    NOT_STARTED = "NOT_STARTED"


class Outcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class Verdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


class MythError(RuntimeError):
    """Base class for errors whose meaning is part of the runtime contract."""


class IdentityConflict(MythError):
    """A stable identity was reused for different content."""


class BudgetExceeded(MythError):
    """A durable intent could not reserve all required resource meters."""


class InvalidTransition(MythError):
    """A persisted state does not permit the requested transition."""


class RecoveryRequired(MythError):
    """Execution truth is uncertain; the runtime must reconcile before retrying."""


class VerificationFailed(MythError):
    """A result cannot be delivered because trusted verification did not PASS."""


class PatchContractError(MythError):
    """The exact patch request is invalid for the fixed baseline."""


class SimulatedCrash(BaseException):
    """Test-only abrupt boundary injection; not used as a business failure."""


@dataclass(frozen=True)
class PatchPlan:
    before: bytes
    after: bytes
    before_digest: str
    after_digest: str
    replacement_count: int


@dataclass(frozen=True)
class ReceiptData:
    """Execution fact published before SQLite settlement.

    Usage is an independent dimension. `usage` may be empty even when the
    effect succeeded; empty never means zero cost.
    """

    receipt_id: str
    attempt_id: str
    envelope_digest: str
    outcome: Outcome
    evidence_ref: str
    usage: dict[str, int]


@dataclass(frozen=True)
class VerificationResult:
    report_id: str
    verdict: Verdict
    candidate_digest: str
    evidence_ref: str


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def exact_patch(data: bytes, old_text: str, new_text: str, expected_count: int) -> PatchPlan:
    """Compute an exact UTF-8 replacement without newline/Unicode normalization."""

    if not isinstance(old_text, str) or not old_text:
        raise PatchContractError("old_text must be a non-empty string")
    if not isinstance(new_text, str):
        raise PatchContractError("new_text must be a string")
    if type(expected_count) is not int or expected_count <= 0:
        raise PatchContractError("expected_count must be a positive integer")

    bom = b"\xef\xbb\xbf"
    has_bom = data.startswith(bom)
    body_bytes = data[len(bom) :] if has_bom else data
    try:
        body = body_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PatchContractError("v1 exact patch accepts UTF-8 text only") from exc

    actual_count = body.count(old_text)
    if actual_count != expected_count:
        raise PatchContractError(
            f"expected {expected_count} non-overlapping matches, found {actual_count}"
        )

    patched = body.replace(old_text, new_text)
    after = (bom if has_bom else b"") + patched.encode("utf-8")
    return PatchPlan(
        before=data,
        after=after,
        before_digest=sha256_bytes(data),
        after_digest=sha256_bytes(after),
        replacement_count=actual_count,
    )
