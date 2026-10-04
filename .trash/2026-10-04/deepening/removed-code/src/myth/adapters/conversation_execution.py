以下是已淘汰片段，只作开发留档，不可导入。


    # 读取该作用域知识文档的 L2 分页证据；固定来源摘要随结果返回。
    def _read_knowledge(self, turn, args):
        value = self._resolve_knowledge(
            turn,
            {
                "document_id": args.get("document_id"),
                "resolution": "L2",
                "cursor": args.get("offset", 0),
                "limit": args.get("max_chars", 6000),
            },
        )
        # 旧 knowledge.read 的 offset/next_offset 保留线协议兼容；新分页仍固定 document/digest 来源。
        return {
            **value,
            "offset": value["cursor"],
            "next_offset": value["next_cursor"],
        }
