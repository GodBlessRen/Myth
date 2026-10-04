# Milvus Retrieval Adapter

Myth 的 Milvus 集成遵守一个边界：

> **Milvus 提供候选，不拥有事实。**

## 运行形态

```text
SQLite / immutable objects
        ↓ source version
EmbeddingPort
        ↓
Milvus Adapter
  Lite / Standalone / Distributed
        ↓ candidate ids
SQLite hydration
  scope / active / revision / digest
        ↓
RRF with lexical baseline
        ↓
Information Resolution
        ↓
bounded Context
```

## 配置

普通安装不强迫下载向量依赖。启用可选依赖后，适配器按首次真实向量使用延迟加载。

环境变量：

- `MYTH_MILVUS_ENABLED=auto|true|false`
- `MYTH_MILVUS_URI`：远端 Milvus URI；未设置时非 Windows 环境使用 Runtime 目录下的 Lite 文件
- `MYTH_MILVUS_TOKEN`：远端认证，只从环境读取，不进入 SQLite / UI
- `MYTH_MILVUS_COLLECTION`：collection 前缀，默认 `myth`
- `MYTH_MILVUS_MODEL`：SentenceTransformer 模型
- `MYTH_MILVUS_DEVICE`：默认 `cpu`

可选安装组：

```text
pip install -e ".[milvus]"
```

## 不变量

1. SQLite 文档、Memory revision 和 immutable object 是 source of truth。
2. Milvus 写入失败不能回滚已经成功提交的业务事实。
3. Milvus 搜索失败降级到 lexical，并在 retrieval report 中标记 degraded。
4. vector hit 必须回 SQLite 检查当前 digest/revision、archive/revoke 和 scope。
5. lexical score 与 cosine distance 不直接加权；第一版使用 Reciprocal Rank Fusion。
6. Memory 初始检索只返回 L0；`memory.timeline` 做上下文导航，`memory.resolve` 按需提升到 L1/L2。
7. Context Observatory 统计 delivered，而不只统计 retrieved。
8. 删除 Milvus Adapter 后，Myth 仍保持完整的词面检索、权限、Memory、恢复与验证语义。

## 当前刻意没有做的事

- 不把 Milvus 升格为 Core / Domain / 新 Runtime Layer。
- 不让向量相似度直接驱动 Information Gain 或自动 Promote。
- 不把 coding-agent 特有的 memory type 固化进通用 Memory schema。
- 不把 raw Memory 全量塞回首次 Context。
- 不用 Vector DB 取代 SQLite 的 durable state / Receipt / Verification。

后续是否让 vector/hybrid 成为默认 Champion，应通过固定 retrieval/e2e eval 证明 recall、任务成功率、token、延迟与成本，而不是因为“用了向量库”就默认更先进。
