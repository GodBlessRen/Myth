"""Memory-backed Semantic Catalog：复用唯一修订/权限/证据所有者，不建立第二套事实仓储。

操作者显式提出 Term/Mapping/Constraint；Agent 仅可经准入后的只读工具发现/求值。
结构性来源有效、类型约束通过，都不能自动获得 verified 或 Evolution Promote 资格。
"""

from __future__ import annotations

import json
import re
from contextlib import nullcontext
from typing import Any

from ..domain import canonical_json
from .memory_lifecycle import MemoryDeltaError
from .semantic_contract import (
    CONTRACT_VERSION,
    evaluate_json_mapping,
    normalize_contract,
    value_violations,
)


# _TERM：只接受规范稳定术语身份；未知词项不得降级成模糊 SQL 匹配。
_TERM = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){1,4}$")
# _PREFIX：单一 Memory identity 命名空间；可从通用检索中区分结构化 Mapping 草案。
_PREFIX = "semantic-contract:v1:"


# 把结构化术语、字段映射和 Evidence 生命周期集中到一个深模块，对话方无须知晓存储格式。
class SemanticCatalog:
    # Memory 是唯一事实写入者；本模块不建 schema、不分配第二个事实 revision。
    def __init__(self, memory) -> None:
        # memory：注入当前 Runtime 连接拥有的 Memory Store；事务与版本由它负责。
        self.memory = memory
        # store：仅用于有界索引投影和一致性读取；不在本模块直接写入业务表。
        self.store = memory.store

    # _key：冻结 scope + term 双重身份，长度前缀避免项目名中的分隔符造成碰撞。
    @staticmethod
    def _key(term_id: str, scope_type: str, scope_id: str | None) -> str:
        if not isinstance(term_id, str) or len(term_id) > 96 or _TERM.fullmatch(term_id) is None:
            raise ValueError("semantic term_id requires a dotted lowercase namespace")
        if scope_type not in {"global", "project", "session"}:
            raise ValueError("semantic scope must be global/project/session")
        if scope_type == "global":
            if scope_id is not None:
                raise ValueError("global semantic terms cannot carry scope_id")
            value = ""
        else:
            if not isinstance(scope_id, str) or not 1 <= len(scope_id.strip()) <= 200:
                raise ValueError("scoped semantic term requires scope_id")
            value = scope_id.strip()
        return f"{_PREFIX}{scope_type}:{len(value)}:{value}:{term_id}"

    # _current：按确定身份读取 Memory 投影，绝不根据相似度猜测另一条术语。
    def _current(self, key: str) -> dict[str, Any] | None:
        row = self.store.db.execute(
            "SELECT * FROM workspace_memories WHERE kind='semantic' AND source_ref=?",
            (key,),
        ).fetchone()
        return None if row is None else dict(row)

    # propose：仅供受信本机调用；新增用 ADD 唯一约束，修改用 CAS Delta，两个场景都复用 Memory Evidence 准入。
    def propose(
        self,
        contract: dict[str, Any],
        *,
        scope_type: str = "global",
        scope_id: str | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        """写入 context-level 草案并冻结来源 Revision；操作不是模型自动发布或事实认证。"""
        normalized = normalize_contract(contract)
        key = self._key(normalized["term_id"], scope_type, scope_id)
        # 证据只来自显式 Mapping，且用 Memory 原生 source_memory_id 自动冻结版本。
        ids = tuple(sorted({item["source_memory_id"] for item in normalized["mappings"]}))
        evidence = [{"source_memory_id": item} for item in ids]
        content = canonical_json(normalized)
        if len(content.encode("utf-8")) > 16_000:
            raise ValueError("semantic contract exceeds Memory text budget")

        if expected_revision is None:
            self.memory.apply_actions([{
                "op": "ADD", "kind": "semantic", "text": content,
                "source_ref": key, "scope_type": scope_type,
                "scope_id": scope_id, "evidence": evidence,
            }])
        else:
            if type(expected_revision) is not int or expected_revision < 1:
                raise ValueError("semantic expected_revision must be a positive integer")
            existing = self._current(key)
            if existing is None:
                raise KeyError(normalized["term_id"])
            # 总是移除/重绑旧证据：同 ID 的源已换 revision 时，也不能沿用上一版证据水位。
            updates = [{"op": "replace_text", "text": content}]
            updates += [
                {"op": "remove_evidence", "evidence_ref": str(item["evidence_ref"])}
                for item in self.memory.evidence(str(existing["memory_id"]))
            ]
            updates += [{"op": "add_evidence", "evidence": item} for item in evidence]
            self.memory.apply_actions([{
                "op": "UPDATE", "memory_id": existing["memory_id"],
                "expected_revision": expected_revision, "operations": updates,
            }])
        return self._resolve_exact(key, scope_type, scope_id)

    # _resolve_exact：一套 read-side 校验保护旧版本、来源不匹配和外部通过通用 Memory 接口写入的篡改。
    def _resolve_exact(self, key: str, scope_type: str, scope_id: str | None) -> dict[str, Any]:
        row = self._current(key)
        term_id = key.rsplit(":", 1)[-1]
        if row is None:
            return {"status": "not_found", "term_id": term_id}
        result = {
            "term_id": term_id,
            "revision": int(row["revision"]),
            "scope_type": scope_type,
            "scope_id": scope_id,
            "memory_ref": f"memory:{row['memory_id']}@{row['revision']}",
            "fact_level": "context",
            "verified": False,
        }
        if (
            not row["active"]
            or row["scope_type"] != scope_type
            or row["scope_id"] != scope_id
            or row["fact_level"] != "context"
        ):
            return {**result, "status": "invalid", "reason": "contract_identity_or_scope_changed"}
        try:
            memory = self.memory.resolve(
                str(row["memory_id"]), resolution="L2",
                project_id=scope_id if scope_type == "project" else None,
                session_id=scope_id if scope_type == "session" else None,
            )
        except (KeyError, PermissionError):
            return {**result, "status": "invalid", "reason": "evidence_unavailable"}
        if memory["is_stale"]:
            return {**result, "status": "stale", "reason": "source_revision_or_support_changed"}
        try:
            contract = normalize_contract(json.loads(memory["text"]))
        except (ValueError, TypeError, json.JSONDecodeError):
            return {**result, "status": "invalid", "reason": "contract_shape_invalid"}
        # 当前正文须为唯一规范编码；不能将模型随意追加的字段解释成已验收的 Mapping。
        if contract["term_id"] != term_id or canonical_json(contract) != memory["text"]:
            return {**result, "status": "invalid", "reason": "contract_identity_or_encoding_changed"}
        linked = [item for item in memory["evidence"] if item.get("source_memory_id")]
        required = {mapping["source_memory_id"] for mapping in contract["mappings"]}
        if (
            {str(item["source_memory_id"]) for item in linked} != required
            or len(linked) != len(required)
            or len(memory["evidence"]) != len(required)
        ):
            return {**result, "status": "invalid", "reason": "mapping_evidence_mismatch"}
        return {
            **result, "status": "ready", "schema": CONTRACT_VERSION,
            "contract": contract,
            "source_refs": [
                f"memory:{entry['source_memory_id']}@{entry['source_revision']}"
                for entry in linked
            ],
            "release_eligible": False,
        }

    # resolve：指定 Term 在同一 Snapshot 下按 session/project/global 的明确优先级查询，失效的覆盖项不回退。
    def resolve(
        self,
        term_id: str,
        *,
        project_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(term_id, str) or _TERM.fullmatch(term_id) is None:
            raise ValueError("semantic term_id requires a dotted lowercase namespace")
        scopes = []
        if session_id is not None:
            scopes.append(("session", session_id))
        if project_id is not None:
            scopes.append(("project", project_id))
        scopes.append(("global", None))
        snapshot = nullcontext(self.store.db) if self.store.db.in_transaction else self.store.read_snapshot()
        with snapshot:
            for scope_type, scope_id in scopes:
                key = self._key(term_id, scope_type, scope_id)
                if self._current(key) is not None:
                    return self._resolve_exact(key, scope_type, scope_id)
        return {"status": "not_found", "term_id": term_id}

    # evaluate：只基于已固定的 JSON Pointer 与冻结来源执行纯计算；多来源冲突/单位不符不选择一个随意胜者。
    def evaluate(
        self,
        term_id: str,
        *,
        project_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        snapshot = nullcontext(self.store.db) if self.store.db.in_transaction else self.store.read_snapshot()
        with snapshot:
            definition = self.resolve(term_id, project_id=project_id, session_id=session_id)
            if definition["status"] != "ready":
                return {**definition, "value": None, "verified": False}
            contract = definition["contract"]
            values = []
            for mapping in contract["mappings"]:
                source_id = mapping["source_memory_id"]
                try:
                    source = self.memory.resolve(
                        source_id, resolution="L2",
                        project_id=project_id, session_id=session_id,
                    )
                    if source["is_stale"]:
                        return {**definition, "status": "stale", "value": None,
                                "reason": "mapping_source_support_changed"}
                    document = json.loads(source["text"])
                    value = evaluate_json_mapping(document, contract, mapping)
                except (ValueError, TypeError, KeyError, PermissionError, json.JSONDecodeError):
                    return {**definition, "status": "invalid", "value": None,
                            "reason": "mapping_source_or_value_invalid"}
                problems = value_violations(value, contract)
                if problems:
                    return {**definition, "status": "constraint_violation", "value": None,
                            "violations": problems}
                values.append(value)
            if any(type(value) is not type(values[0]) or value != values[0] for value in values[1:]):
                return {**definition, "status": "conflict", "value": None,
                        "reason": "independent_mappings_disagree"}
            return {**definition, "status": "resolved", "value": values[0],
                    "unit": contract["unit"], "verified": False}

    # browse：有界扫描已存结构化记录；范围判断发生在解析私有正文之前，命中只作导航不验证结论。
    def browse(
        self,
        query: str,
        *,
        limit: int = 6,
        project_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 120:
            raise ValueError("semantic browse query must contain 1-120 characters")
        if type(limit) is not int or not 1 <= limit <= 8:
            raise ValueError("semantic browse limit must be 1-8")
        snapshot = nullcontext(self.store.db) if self.store.db.in_transaction else self.store.read_snapshot()
        with snapshot:
            candidates = self.store.db.execute(
                "SELECT memory_id,source_ref,scope_type,scope_id,text,active FROM workspace_memories "
                "WHERE kind='semantic' AND source_ref LIKE ? ORDER BY rowid DESC LIMIT 257",
                (_PREFIX + "%",),
            ).fetchall()
            found = []
            for row in candidates[:256]:
                current = dict(row)
                if not current["active"] or not self.memory._visible(current, project_id, session_id):
                    continue
                try:
                    raw = normalize_contract(json.loads(current["text"]))
                except (ValueError, TypeError, json.JSONDecodeError):
                    continue
                needle = query.strip().casefold()
                if needle not in raw["term_id"].casefold() and needle not in raw["definition"].casefold():
                    continue
                key = self._key(raw["term_id"], current["scope_type"], current["scope_id"])
                if current["source_ref"] != key:
                    continue
                admission = self._resolve_exact(key, current["scope_type"], current["scope_id"])
                if admission["status"] != "ready":
                    continue
                found.append({
                    "term_id": raw["term_id"], "definition": raw["definition"][:180],
                    "scope_type": current["scope_type"], "scope_id": current["scope_id"],
                    "memory_ref": admission["memory_ref"], "status": "ready",
                })
                if len(found) >= limit:
                    break
        return {
            "terms": found,
            "retrieval": {
                "scanned": min(len(candidates), 256),
                "exhausted": len(candidates) <= 256,
                "bounded": True,
            },
        }
