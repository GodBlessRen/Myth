以下是已淘汰片段，只作开发留档，不可导入。



# 在已给可见候选中按稳定键排序 top-k；调用方负责完整候选覆盖。
def rank_chunks(query, candidates, limit=5):
    scored = [
        value for item in candidates if (value := score_chunk(query, item)) is not None
    ]
    return sorted(
        scored, key=lambda x: (-x["score"], x["document_id"], x["chunk_index"])
    )[:limit]
