# 有来源、版本和可见性的纯记忆合同；文本是上下文而非权威执行指令。
@dataclass(frozen=True)
class MemoryRecord:
    # memory_id：有来源记忆的稳定身份；revision 改变内容版本。
    memory_id: str
    # kind：当前合同的对象/记忆用途分类；需与所属枚举解释。
    kind: MemoryKind
    # text：正文/模型输出文本；不是执行收据或验收结果。
    text: str
    # source_ref：固定资料/对象/Run 来源身份；分辨率改变时保留原来源。
    source_ref: str
    # revision：当前状态/记忆的单调版本；旧结果不能覆盖更新版本。
    revision: int = 1
    # active：当前是否参与未来查询；历史快照不倒写。
    active: bool = True


# 用于组件合同的内存记忆目录；版本必须增加，生产持久化由 MemoryStore 实现。
class MemoryCatalog:
    # 保存本实例的协作对象与配置；状态/I/O 边界见类合同，实例字段不能替代持久执行事实。
    def __init__(self) -> None:
        # _records：当前实例记忆目录；持久记忆由 MemoryStore 管理。
        self._records: dict[str, MemoryRecord] = {}

    # 要求同 memory_id 的 revision 严格增加后更新内存目录；不是持久数据库写入。
    def put(self, record: MemoryRecord) -> None:
        previous = self._records.get(record.memory_id)
        if previous and record.revision <= previous.revision:
            raise ValueError("memory revision must increase")
        self._records[record.memory_id] = record

    # 撤销条目在未来查询中的可见性；历史快照与已发生效果不被倒写。
    def revoke(self, memory_id: str, *, revision: int) -> None:
        current = self._records[memory_id]
        self.put(
            MemoryRecord(
                memory_id,
                current.kind,
                current.text,
                current.source_ref,
                revision,
                False,
            )
        )

    # 读取当前作用域的检索结果；相似度只用于排序，不升级为已验证事实。
    def search(
        self, query: str, *, kinds: set[MemoryKind] | None = None, limit: int = 8
    ) -> list[MemoryRecord]:
        terms = set(re.findall(r"[\w\u4e00-\u9fff]+", query.lower()))
        scored: list[tuple[int, MemoryRecord]] = []
        for record in self._records.values():
            if not record.active or (kinds and record.kind not in kinds):
                continue
            text_terms = set(re.findall(r"[\w\u4e00-\u9fff]+", record.text.lower()))
            score = len(terms & text_terms)
            if not terms or score:
                scored.append((score, record))
        scored.sort(key=lambda pair: (-pair[0], pair[1].memory_id))
        return [record for _, record in scored[:limit]]
