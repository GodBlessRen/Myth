以下是已淘汰片段，只作开发留档，不可导入。


    # 兼容调用只取 L0 结果；完整观测使用 search_view_report，避免把正文直接塞进初始 Context。
    def search_views(
        self,
        query: str,
        *,
        kinds: Iterable[str | MemoryKind] | None = None,
        limit: int = 6,
        project_id: str | None = None,
        session_id: str | None = None,
    ) -> list[dict]:
        return self.search_view_report(
            query,
            kinds=kinds,
            limit=limit,
            project_id=project_id,
            session_id=session_id,
        )["memories"]
