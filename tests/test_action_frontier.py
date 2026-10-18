"""Dynamic Action Frontier 的固定回归：识别同名目标、伪造选择与执行前失效。

这里的 Provider 是脚本替身，不证明真实模型节省 Token、时延或成本。
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from myth.models import ModelResult, ProviderStatus
from myth.platform.action_frontier import (
    MAX_ACTION_CANDIDATES,
    build_action_frontier,
    select_action_candidate,
)
from myth.runtime import MythRuntime
from myth.workspace import Workspace


# 构造同 Run 已结算的真实形状 Observation，不让自由文本冒充权限事实。
def knowledge_activity(decision_id, document_id, digest="a" * 64, title="同名资料"):
    return {
        "state": "DONE",
        "decision_id": decision_id,
        "decision": {"capability_id": "knowledge.search", "arguments": {"query": "test"}},
        "result": {
            "capability_id": "knowledge.search",
            "sources": [{"document_id": document_id, "digest": digest,
                         "title": title, "content": "有界预览"}],
        },
    }


# 构造完整的 Provider wire；输出只影响模型决定，不绕开 Tool Admission。
def wire(kind, capability="", arguments=None, claim="已完成"):
    return json.dumps({
        "decision_type": kind,
        "reason": "fixture",
        "capability_id": capability,
        "arguments_json": json.dumps(arguments or {}),
        "question": "",
        "missing_info_category": "",
        "claim": claim,
        "goal_coverage": "answer",
        "evidence_refs": [],
        "remaining": [],
    }, ensure_ascii=False)


# 每次从真实 ModelRequest 提取当前候选 ID，确保测试覆盖 Prompt → 决策 → Ticket 的整条调用路径。
class FrontierProvider:
    provider_id = "ollama"

    # 保存受控工作区与是否在第二次模型决定后撤销来源的故障注入开关。
    def __init__(self, workspace, *, archive_before_choice=False):
        self.workspace = workspace
        self.archive_before_choice = archive_before_choice
        self.calls = []
        self.document_id = None

    # 连接可用性为夹具结果；不表示外部供应商可用。
    def check(self):
        return ProviderStatus("ollama", True, details={"models": ["test"]})

    # 第二步选择实际 Prompt 所示候选；可在模型返回后、Tool Ticket 前撤销来源。
    def invoke(self, request):
        self.calls.append(request)
        if len(self.calls) == 1:
            body = wire("tool_call", "knowledge.search", {"query": "MYTH-FRONTIER", "limit": 3})
        elif len(self.calls) == 2:
            text = "\n".join(message.content for message in request.messages)
            match = re.search(r"af_[a-f0-9]{24}", text)
            if match is None:
                raise AssertionError("action frontier candidate missing from ModelRequest")
            if self.archive_before_choice:
                self.workspace.repository.knowledge.archive_document(self.document_id)
            body = wire("tool_call", "knowledge.resolve", {"candidate_id": match.group(0)})
        else:
            body = wire("request_completion", claim="已读取来源")
        return ModelResult(body, {"model_calls": 1, "input_tokens": 30, "output_tokens": 20},
                           {"fixture": True})


# 防回归重点是候选身份及原 Runtime 事务，而非第三方模型输出偏好。
class ActionFrontierTests(unittest.TestCase):
    # 同名资料应有两个不同候选；跨 Run/Observation/版本也不能复用 ID。
    def test_identity_not_positional_and_bounded(self):
        rows = [knowledge_activity("d1", "doc1"), knowledge_activity("d2", "doc2")]
        first = build_action_frontier("runA", rows)
        self.assertEqual(len(first), 2)
        self.assertNotEqual(first[0].candidate_id, first[1].candidate_id)
        self.assertNotEqual(first[0].candidate_id, build_action_frontier("runB", rows)[0].candidate_id)
        changed = knowledge_activity("d2", "doc2", "b" * 64)
        self.assertNotEqual(first[0].candidate_id, build_action_frontier("runA", [rows[0], changed])[0].candidate_id)
        self.assertLessEqual(len(build_action_frontier("runA", [knowledge_activity(f"d{i}", f"doc{i}") for i in range(20)])), MAX_ACTION_CANDIDATES)

    # 选择必须严格为单个候选 ID，不接受新增自由参数或其他工具冒领。
    def test_rejects_fake_cross_capability_and_extra_arguments(self):
        candidates = build_action_frontier("runA", [knowledge_activity("d1", "doc1")])
        good = candidates[0].candidate_id
        with self.assertRaises(ValueError):
            select_action_candidate(candidates, "knowledge.resolve", {"candidate_id": "af_" + "f" * 24})
        with self.assertRaises(ValueError):
            select_action_candidate(candidates, "memory.resolve", {"candidate_id": good})
        with self.assertRaises(ValueError):
            select_action_candidate(candidates, "knowledge.resolve", {"candidate_id": good, "document_id": "doc2"})
        self.assertEqual(select_action_candidate(candidates, "knowledge.resolve", {"candidate_id": good}).arguments["document_id"], "doc1")

    # 真实 Runtime 模型/工具调用链：候选选择最终以 knowledge.resolve 真正身份签 Ticket。
    def test_receipt_backed_integration(self):
        with tempfile.TemporaryDirectory() as tmp:
            with MythRuntime(Path(tmp)) as runtime:
                workspace = Workspace(runtime)
                repository = workspace.repository
                repository.save_settings({"provider": "ollama", "model": "test"})
                doc = repository.knowledge.import_document({"title": "测试", "content": "MYTH-FRONTIER"})
                session = repository.create_session()["id"]
                run = repository.create_turn(session, "检索并展开资料", "frontier-integration")["run_id"]
                provider = FrontierProvider(workspace)
                provider.document_id = doc["id"]
                workspace.run(run, provider)
                self.assertEqual(repository.turn(run)["status"], "COMPLETED")
                ops = repository.operations(run)
                self.assertEqual([o["capability"] for o in ops], ["knowledge.search", "knowledge.resolve"])
                self.assertEqual(ops[1]["result"]["document_id"], doc["id"])
                self.assertEqual(ops[1]["state"], "RESOLVED")

    # 模型选择后撤销来源：必须在 Ticket 前拒绝，不能把陈旧候选执行成旧文档泄露。
    def test_archive_before_ticket_fails_without_resolve_ticket(self):
        with tempfile.TemporaryDirectory() as tmp:
            with MythRuntime(Path(tmp)) as runtime:
                workspace = Workspace(runtime)
                repository = workspace.repository
                repository.save_settings({"provider": "ollama", "model": "test"})
                doc = repository.knowledge.import_document({"title": "即将归档", "content": "MYTH-FRONTIER"})
                session = repository.create_session()["id"]
                run = repository.create_turn(session, "检索并读取资料", "frontier-archive")["run_id"]
                provider = FrontierProvider(workspace, archive_before_choice=True)
                provider.document_id = doc["id"]
                workspace.run(run, provider)
                self.assertEqual([o["capability"] for o in repository.operations(run)], ["knowledge.search"])
                self.assertTrue(any((a.get("result") or {}).get("failure") for a in repository.turn(run)["activities"]))


if __name__ == "__main__":
    unittest.main()
