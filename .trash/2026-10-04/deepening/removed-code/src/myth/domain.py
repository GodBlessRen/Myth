以下是已淘汰片段，只作开发留档，不可导入。



class VerificationFailed(MythError):
    """缺少可信 PASS 时拒绝交付；模型完成声明不能替代报告。"""


# 绑定候选摘要与证据引用的独立验收结果；不会自行提交交付。
@dataclass(frozen=True)
class VerificationResult:
    # report_id：独立验收报告身份；不能拿其他候选报告交付。
    report_id: str
    # verdict：验收/评测结论；不足证据保留 INCONCLUSIVE。
    verdict: Verdict
    # candidate_digest：被验收候选的内容身份；报告只对该摘要有效。
    candidate_digest: str
    # evidence_ref：不可变证据引用；调用方必须核对它属于当前工作。
    evidence_ref: str
