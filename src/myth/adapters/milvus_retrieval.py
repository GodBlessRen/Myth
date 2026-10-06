"""Milvus 向量检索适配器。
SQLite/对象库仍是知识与 Memory 的权威来源；Milvus 只保存向量与来源身份元数据。
适配器按需加载 PyMilvus/embedding 依赖，失败只使语义召回降级，不修改 Core、权限、Receipt 或 UNKNOWN 语义。
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import re
import threading
from typing import Any


_DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_CACHE_LOCK = threading.Lock()
_INDEX_CACHE: dict[tuple[str, str, str, str], "MilvusVectorIndex"] = {}


def _plain_vector(value: Any) -> list[float]:
    """把 numpy/list 向量收敛为普通 float 列表；Milvus 之外不传播第三方数组类型。"""
    if hasattr(value, "tolist"):
        value = value.tolist()
    return [float(item) for item in value]


def _safe_prefix(value: str) -> str:
    """限制 collection 前缀为 Milvus 可接受的稳定标识符，配置错误回退到本地默认。"""
    text = str(value or "").strip()
    return text if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,80}", text) else "myth"


class MilvusVectorIndex:
    """进程内共享的 Milvus derived-index 适配器；正文不写入 Milvus，命中必须回权威仓储 hydration。"""

    # backend_id：稳定适配器身份；用于观测/路由，不代表连接健康。
    backend_id = "milvus"

    # 保存延迟连接配置与可注入测试替身；构造本身不访问网络、不下载模型、不创建 collection。
    def __init__(
        self,
        *,
        uri: str,
        token: str | None = None,
        collection_prefix: str = "myth",
        model_name: str = _DEFAULT_MODEL,
        device: str = "cpu",
        client: Any | None = None,
        embedder: Any | None = None,
    ) -> None:
        # uri：Milvus Lite 文件或远端 endpoint；只由配置提供，不写入业务 SQLite。
        self.uri = str(uri)
        # token：远端认证材料；仅保存在当前 Adapter 实例内，status 不回显。
        self.token = token
        # collection_prefix：限制后的命名空间；避免不同 Myth 实例误用同名 collection。
        self.collection_prefix = _safe_prefix(collection_prefix)
        # model_name：embedding 模型身份；改变模型必须使用不同索引语义/重建数据。
        self.model_name = str(model_name or _DEFAULT_MODEL)
        # device：embedding 计算设备；只是 Adapter 配置，不进入 Core。
        self.device = str(device or "cpu")
        # knowledge_collection：知识 chunk 派生向量集合，不保存权威正文。
        self.knowledge_collection = f"{self.collection_prefix}_knowledge_v1"
        # memory_collection：Memory revision 派生向量集合，不拥有 active/scope 真相。
        self.memory_collection = f"{self.collection_prefix}_memory_v1"
        # _client：延迟创建的 PyMilvus 客户端；测试可显式注入替身。
        self._client = client
        # _embedder：延迟创建的文本向量器；测试可注入确定性替身。
        self._embedder = embedder
        # _lock：保护同进程首次初始化与 collection 创建，不能替代跨进程数据库一致性。
        self._lock = threading.RLock()
        # _collections_ready：当前实例已确认 collection 存在的缓存，不是持久事实。
        self._collections_ready = False
        # _healthy：最近一次真实 Adapter 操作是否成功；只用于观测，不授予业务成功。
        self._healthy = bool(client is not None and embedder is not None)
        # _last_error：脱敏错误类别；不保存 endpoint token 或第三方异常正文。
        self._last_error: str | None = None
        # _synced_versions：进程内重复 embedding 优化；丢失后重新 upsert 仍保持正确。
        self._synced_versions: dict[tuple[str, str], str] = {}

    @property
    def configured(self) -> bool:
        """配置/依赖允许尝试该 Adapter；不把远端连通性冒充已成功查询。"""
        return True

    def status(self) -> dict[str, Any]:
        """返回无秘钥的后端投影；healthy 只由最近一次真实初始化/调用更新。"""
        return {
            "backend": self.backend_id,
            "configured": True,
            "healthy": self._healthy,
            "mode": "remote" if "://" in self.uri else "lite",
            "model": self.model_name,
            "collections": [self.knowledge_collection, self.memory_collection],
            "last_error": self._last_error,
        }

    def _ensure(self) -> None:
        """按首次真实使用加载 PyMilvus、embedding model 和 collections；Workspace 构造不偷偷下载模型。"""
        # 先加载可选依赖与模型，再建缺失集合；每阶段失败只标投影不可用，SQLite 来源事实保持权威。
        with self._lock:
            if self._client is None or self._embedder is None:
                try:
                    from pymilvus import MilvusClient, model
                except ImportError as exc:
                    self._last_error = "dependency_unavailable"
                    self._healthy = False
                    raise RuntimeError("Milvus optional dependency is unavailable") from exc
                try:
                    self._embedder = model.dense.SentenceTransformerEmbeddingFunction(
                        model_name=self.model_name,
                        device=self.device,
                        normalize_embeddings=True,
                    )
                    kwargs = {"uri": self.uri}
                    if self.token:
                        kwargs["token"] = self.token
                    self._client = MilvusClient(**kwargs)
                except Exception as exc:
                    self._last_error = "initialization_failed"
                    self._healthy = False
                    raise RuntimeError("Milvus initialization failed") from exc
            if not self._collections_ready:
                try:
                    for name in (self.knowledge_collection, self.memory_collection):
                        if not self._client.has_collection(collection_name=name):
                            self._client.create_collection(
                                collection_name=name,
                                dimension=int(self._embedder.dim),
                                primary_field_name="record_id",
                                id_type="string",
                                vector_field_name="vector",
                                metric_type="COSINE",
                                auto_id=False,
                                max_length=512,
                                enable_dynamic_field=True,
                            )
                    self._collections_ready = True
                    self._healthy = True
                    self._last_error = None
                except Exception as exc:
                    self._last_error = "collection_unavailable"
                    self._healthy = False
                    raise RuntimeError("Milvus collection setup failed") from exc

    def _sync(self, collection: str, rows: list[dict[str, Any]]) -> dict[str, int]:
        """仅对当前进程未见过的 source version 做 embedding/upsert；正文不作为 Milvus metadata 保存。"""
        # 过滤已同步版本后按 64 条编码；只有 upsert 成功才推进版本缓存，失败后仍可完整补建。
        self._ensure()
        pending = [
            row
            for row in rows
            if self._synced_versions.get((collection, str(row["record_id"])))
            != str(row["source_version"])
        ]
        upserted = 0
        for start in range(0, len(pending), 64):
            batch = pending[start : start + 64]
            if not batch:
                continue
            try:
                vectors = self._embedder.encode_documents(
                    [str(row.get("text") or "") for row in batch]
                )
                data = []
                for row, vector in zip(batch, vectors):
                    item = {
                        "record_id": str(row["record_id"]),
                        "vector": _plain_vector(vector),
                        "source_version": str(row["source_version"]),
                    }
                    for key, value in row.items():
                        if key not in {"record_id", "text", "source_version"} and value is not None:
                            item[key] = value
                    data.append(item)
                self._client.upsert(collection_name=collection, data=data)
                for row in batch:
                    self._synced_versions[
                        (collection, str(row["record_id"]))
                    ] = str(row["source_version"])
                upserted += len(batch)
                self._healthy = True
                self._last_error = None
            except Exception as exc:
                self._last_error = "upsert_failed"
                self._healthy = False
                raise RuntimeError("Milvus vector upsert failed") from exc
        return {"received": len(rows), "upserted": upserted, "skipped": len(rows) - upserted}

    # 将知识 chunk 当前 source version 投影到派生 collection；写失败由调用方降级处理。
    def sync_knowledge(self, rows: list[dict[str, Any]]) -> dict[str, int]:
        return self._sync(self.knowledge_collection, rows)

    # 将 active Memory 当前 revision 投影到派生 collection；不拥有 revoke/scope 状态。
    def sync_memories(self, rows: list[dict[str, Any]]) -> dict[str, int]:
        return self._sync(self.memory_collection, rows)

    def _search(self, collection: str, query: str, *, limit: int) -> list[dict[str, Any]]:
        """向量库只返回候选身份/版本/距离；调用者必须回 SQLite hydration 并重新检查 scope/freshness。"""
        self._ensure()
        text = str(query or "").strip()
        if not text:
            return []
        try:
            vector = _plain_vector(self._embedder.encode_queries([text])[0])
            rows = self._client.search(
                collection_name=collection,
                data=[vector],
                limit=max(1, min(int(limit), 256)),
                output_fields=["source_version"],
                search_params={"metric_type": "COSINE"},
            )
            hits = rows[0] if rows else []
            result = []
            for rank, hit in enumerate(hits, 1):
                entity = hit.get("entity") or {}
                result.append(
                    {
                        "record_id": str(hit.get("id") or entity.get("record_id") or ""),
                        "source_version": str(entity.get("source_version") or ""),
                        "distance": float(hit.get("distance") or 0.0),
                        "rank": rank,
                    }
                )
            self._healthy = True
            self._last_error = None
            return [item for item in result if item["record_id"]]
        except Exception as exc:
            self._last_error = "search_failed"
            self._healthy = False
            raise RuntimeError("Milvus vector search failed") from exc

    # 返回知识向量候选身份；正文、digest 与可见范围必须由 SQLite 仓储重新核对。
    def search_knowledge(self, query: str, *, limit: int = 64) -> list[dict[str, Any]]:
        return self._search(self.knowledge_collection, query, limit=limit)

    # 返回 Memory 向量候选身份；revision、active 与 scope 仍由 MemoryStore 最终判定。
    def search_memories(self, query: str, *, limit: int = 64) -> list[dict[str, Any]]:
        return self._search(self.memory_collection, query, limit=limit)


def create_milvus_vector_index(runtime) -> MilvusVectorIndex | None:
    """按环境/平台装配可选 Milvus；Lite 不支持的系统在未给远端 URI 时明确退回 lexical。"""
    flag = str(os.environ.get("MYTH_MILVUS_ENABLED", "auto")).strip().lower()
    if flag in {"0", "false", "off", "no"}:
        return None
    uri = str(os.environ.get("MYTH_MILVUS_URI", "")).strip()
    if not uri:
        if os.name == "nt":
            return None
        uri = str(Path(runtime.runtime_dir) / "milvus.db")
    if importlib.util.find_spec("pymilvus") is None:
        return None

    prefix = _safe_prefix(os.environ.get("MYTH_MILVUS_COLLECTION", "myth"))
    model_name = str(os.environ.get("MYTH_MILVUS_MODEL", _DEFAULT_MODEL)).strip() or _DEFAULT_MODEL
    device = str(os.environ.get("MYTH_MILVUS_DEVICE", "cpu")).strip() or "cpu"
    token = os.environ.get("MYTH_MILVUS_TOKEN") or None
    key = (str(Path(runtime.runtime_dir).resolve()), uri, prefix, model_name + "@" + device)
    with _CACHE_LOCK:
        index = _INDEX_CACHE.get(key)
        if index is None:
            index = MilvusVectorIndex(
                uri=uri,
                token=token,
                collection_prefix=prefix,
                model_name=model_name,
                device=device,
            )
            _INDEX_CACHE[key] = index
        return index
