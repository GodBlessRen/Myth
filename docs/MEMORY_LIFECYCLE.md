# Memory Lifecycle

Myth 的 Memory 继续是一个正交 Domain，不新增第二套 Runtime，也不把向量库升级成事实数据库。

## Stable shape

```text
source facts / Run / user assertion
        ↓
Memory revision
  + provenance
  + Evidence
        ↓
immutable revision snapshot
        ↓
freshness check
        ↓
L0 / L1 compact projection
        ↓ explicit EXPAND
L2 evidence projection
```

## Evidence

Evidence 只回答“这条 Memory 基于什么”，不等同 Verification，也不能授予执行权限。

两类 Evidence：

- `evidence_ref`：外部稳定来源，例如 run / commit / document。若没有可比较版本水位，freshness 保持 `untracked`。
- `source_memory_id`：引用另一条 Memory。写入时固定对方当前 revision；后续来源 revision 改变或被 revoke，依赖 Memory 的 freshness 变为 `stale`。

Myth 不把相似度、proof_count 或 freshness 直接升级成 `verified`。

## Immutable revision

`workspace_memories` 保存当前可见状态；`workspace_memory_revisions` 保存每个已经提交 revision 的不可变快照：

- text；
- fact_level；
- active；
- 当时的 Evidence JSON。

升级旧数据库时只为“当前已知 revision”补快照，不伪造无法恢复的历史 revision。

## Delta

模型或 Strategy 可以提出 Delta，但不能直接修改 Memory 表。

当前稳定操作：

```text
replace_text
add_evidence
remove_evidence
```

应用规则：

1. 调用方必须给 `expected_revision`；
2. Runtime 在 SQLite 写事务里重新核对当前 revision；
3. 所有操作先验证；
4. 任一操作失败则整批回滚；
5. 空操作列表是机械 no-op；
6. 成功后只产生一个新 revision 和一个新 immutable snapshot。

因此稳定原则是：

> LLM proposes delta; deterministic runtime validates and applies delta.

## Progressive disclosure

首次 Recall 不展开完整 Evidence。

- L0/L1：`proof_count`、`freshness`、`is_stale`
- L2：完整正文、Evidence、freshness report

这样 Evidence-backed Memory 不会反过来破坏 Context budget。

## Milvus boundary

Milvus 仍然只提供候选：

```text
Milvus candidate id/version
      ↓
SQLite hydration
      ↓
active / revision / scope / evidence / freshness
      ↓
Context projection
```

删除 Milvus 后，Memory revision、Evidence、freshness、Delta 和历史快照仍完整成立。


## Mental Model / Knowledge Page

Mental Model 是 **Materialized Memory View**，不是第五种 Memory Kind。

```text
source query + scope
        ↓
prepare_refresh()
        ↓ fixed Memory sources + observed_change_seq
        ↓
LLM / deterministic synthesis outside SQLite
        ↓
commit_refresh()
  - expected model revision
  - scope watermark check
  - evidence validation
        ↓
backing Semantic Memory
```

Mental Model 的正文唯一落在 backing Semantic Memory，因此原有 Evidence、revision、Milvus hydration、L0/L1/L2 和 revoke 语义全部复用，不复制一套内容生命周期。

Memory 每次 revision/revoke 都追加单调 `change_seq`。Mental Model 保存 `last_seen_change_seq`；自身作用域后来出现新变化就确定性变为 stale。刷新不会自动发生，避免后台隐式模型成本与不可观测副作用。

Knowledge Page 更薄：只保存 folder/page hierarchy 与 `mental_model_id`。树结构和内容状态分离，移动/重命名页面不会重写 Mental Model 正文。
