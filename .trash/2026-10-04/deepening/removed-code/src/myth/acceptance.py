以下是已淘汰片段，只作开发留档，不可导入。



# 一组候选只有全部绑定同一固定来源时才可继续；任一失败即返回 None，保留原始来源。
def validated_source_evidence_or_none(
    source_text: str,
    candidates: Iterable[SourceEvidence],
) -> tuple[SourceEvidence, ...] | None:
    values = tuple(candidates)
    if any(not validate_source_evidence(source_text, item).accepted for item in values):
        return None
    return values
