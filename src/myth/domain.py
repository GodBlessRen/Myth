"""纯领域词汇与字节级确定性规则。
Run/Action/Attempt、授权 Ticket、效果 Receipt 与验收 Verdict 分别表达不同事实；本文件不拥有数据库、文件、网络或模型 I/O。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from typing import Any


# Core Run 生命周期；与 Conversation 的产品状态不同，终态和预算耗尽由持久仓储记录。
class RunState(StrEnum):
    # READY：准入已就绪，尚未代表实际效果发生。
    READY = "READY"
    # RUNNING：当前用例正在推进；具体外部机会仍看 Ticket/Receipt。
    RUNNING = "RUNNING"
    # PAUSED：暂停未来派发；晚到调用仍保留真实收据。
    PAUSED = "PAUSED"
    # WAITING：等待明确外部输入/依赖；不能自行补造答案。
    WAITING = "WAITING"
    # VERIFYING：进入固定合同验收；模型完成声明不能代替报告。
    VERIFYING = "VERIFYING"
    # RECOVERING：正在核对持久执行事实；不盲重发旧机会。
    RECOVERING = "RECOVERING"
    # SUCCEEDED：所属执行合同已确认成功；与语义验收结论分开解释。
    SUCCEEDED = "SUCCEEDED"
    # FAILED：所属合同已知失败；不能拿它表示未知效果。
    FAILED = "FAILED"
    # CANCELLED：用例取消未来工作；已发出效果的事实仍保存。
    CANCELLED = "CANCELLED"
    # BUDGET_EXHAUSTED：硬计量上限不足；不能通过换身份绕过。
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"


# 一次执行机会的状态；INTENT 尚未派发，Ticket 后结果不明必须核对，不能另开机会绕过。
class AttemptState(StrEnum):
    # INTENT：已持久登记意图/预留，尚无发出授权。
    INTENT = "INTENT"
    # TICKETED：唯一 StartTicket 已签发；后续不确定需核对。
    TICKETED = "TICKETED"
    # UNKNOWN：已有机会的执行结果不明；不得当作未开始直接重放。
    UNKNOWN = "UNKNOWN"
    # RESOLVED：机会已由可信收据/核对解决。
    RESOLVED = "RESOLVED"
    # NOT_STARTED：有证据确认未开始；仅此状态可按合同安排后续机会。
    NOT_STARTED = "NOT_STARTED"


# 执行效果事实；UNKNOWN 与已知失败不同，不能用于完成验收。
class Outcome(StrEnum):
    # SUCCEEDED：所属执行合同已确认成功；与语义验收结论分开解释。
    SUCCEEDED = "SUCCEEDED"
    # FAILED：所属合同已知失败；不能拿它表示未知效果。
    FAILED = "FAILED"
    # UNKNOWN：已有机会的执行结果不明；不得当作未开始直接重放。
    UNKNOWN = "UNKNOWN"


# 独立验收结论；INCONCLUSIVE 表示证据不足，不等于 PASS。
class Verdict(StrEnum):
    # PASS：固定验收/评测合同通过；资格只对当前证据身份有效。
    PASS = "PASS"
    # FAIL：固定验收/评测合同失败；不是供应商失联的替代状态。
    FAIL = "FAIL"
    # INCONCLUSIVE：证据不足以判定，保持显式不确定。
    INCONCLUSIVE = "INCONCLUSIVE"


class MythError(RuntimeError):
    """具有 Runtime 合同意义的异常基类；调用方按具体错误区分拒绝、预算、恢复与验收。"""


class IdentityConflict(MythError):
    """相同稳定身份对应不同内容；拒绝复用，不能覆盖历史事实。"""


class BudgetExceeded(MythError):
    """无法同时预留所需资源；效果开始前拒绝，已有 UNKNOWN 占用仍计入可用额度。"""


class InvalidTransition(MythError):
    """持久状态不允许本次迁移；调用方应重新读取事实而不是强改状态。"""


class RecoveryRequired(MythError):
    """执行事实需核对或有 Driver 竞争；不授权盲目重发。"""


class PatchContractError(MythError):
    """固定基线或精确参数不符合合同；发生于效果前时是已知拒绝，允许纠正参数。"""


class SimulatedCrash(BaseException):
    """测试专用强制退出注入；继承 BaseException 以越过业务错误分支。"""


# 不可变的精确替换计划；前后字节和摘要固定，保留 BOM/换行，不承担 I/O。
@dataclass(frozen=True)
class PatchPlan:
    # before：冻结基线原始字节，含原 BOM/换行。
    before: bytes
    # after：计算后的候选原始字节，尚不表示文件效果已发生。
    after: bytes
    # before_digest：基线字节 SHA-256；恢复与验收的固定身份。
    before_digest: str
    # after_digest：候选字节 SHA-256；必须与实际对象一致。
    after_digest: str
    # replacement_count：实际非重叠替换次数；单位为匹配项。
    replacement_count: int


@dataclass(frozen=True)
class ReceiptData:
    """结算前的执行事实合同；usage 空值表示未测量，不能当作零成本。"""

    # receipt_id：收据的稳定身份；与 Attempt/envelope 共同绑定执行事实。
    receipt_id: str
    # attempt_id：单次执行机会身份；恢复不换身份来重发未知效果。
    attempt_id: str
    # envelope_digest：Run/Action/Attempt/合同组合摘要；阻止收据跨机会串用。
    envelope_digest: str
    # outcome：效果是否已知成功/失败/不明；不等于验收 Verdict。
    outcome: Outcome
    # evidence_ref：不可变证据引用；调用方必须核对它属于当前工作。
    evidence_ref: str
    # usage：供应商/执行器测得的各 meter 用量；缺项表示未测量而非零成本。
    usage: dict[str, int]


# 计算原始字节 SHA-256；身份不做换行、BOM 或 Unicode 归一化。
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# 把数据编码为排序且紧凑的 JSON；稳定编码用于内容身份，不承诺深冻结可变输入。
def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


# 对规范 JSON 的 UTF-8 字节取摘要；同身份必须对应同内容。
def digest_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def exact_patch(
    data: bytes, old_text: str, new_text: str, expected_count: int
) -> PatchPlan:
    """先校验文本/次数并严格解码 UTF-8，再构造保留 BOM/换行的前后字节计划；不访问文件。"""

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
