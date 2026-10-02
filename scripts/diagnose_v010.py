"""Reproduce review findings in disposable databases; no model/network calls.

Run with PYTHONPATH=src. These probes report observed limitations rather than
asserting that all probes are supposed to pass. Regression tests live in tests/.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from myth.conversation import conversation_request
from myth.runtime import MythRuntime
from myth.web_workspace import ConversationWebService
from myth.workspace import Workspace


SETTINGS = {"provider": "ollama", "model": "test"}


def diagnose(root):
    report = {}
    with MythRuntime(root) as runtime:
        workspace = Workspace(runtime)
        repo = workspace.repository
        repo.save_settings(SETTINGS)
        a = repo.create_project({"name": "A"})
        b = repo.create_project({"name": "B"})
        sid_a = repo.create_session(project_id=a["id"])["id"]
        rid_a = repo.create_turn(sid_a, "ORCHID source", "memory-origin")["run_id"]
        step = repo.begin_step(rid_a)
        repo.finish_reply(rid_a, step["step"], "ORCHID belongs to project A")
        workspace.memory.record_episode(rid_a, "ORCHID source", "ORCHID belongs to project A")
        sid_b = repo.create_session(project_id=b["id"])["id"]
        service = ConversationWebService(root)
        with patch.object(service, "connection", return_value={"ready": True, "details": {"models": ["test"]}}), \
             patch.object(service, "_spawn"):
            result = service.send(sid_b, {"text": "ORCHID source?", "request_id": "cross-project"})
        recalled = repo.turn(result["run_id"])["snapshot"]["memory"]
        report["global_episodic_memory"] = {
            "other_project_episode_recalled": any(m["source_ref"] == f"run:{rid_a}" for m in recalled),
            "interpretation": "Memory is workspace-global; Knowledge project filtering does not apply to episodes.",
        }

        sid = repo.create_session()["id"]
        rid = repo.create_turn(sid, "control", "control")["run_id"]
        with MythRuntime(root) as second_runtime:
            other = Workspace(second_runtime)
            apply = workspace.control.machine.apply

            def interleave(state, command, payload):
                other.control.command(rid, "switch_thinking", True)
                return apply(state, command, payload)

            try:
                with patch.object(workspace.control.machine, "apply", side_effect=interleave):
                    workspace.control.command(rid, "steer", "retain this steering")
                error = None
            except Exception as exc:
                error = type(exc).__name__ + ": " + str(exc)
        report["control_command_interleaving"] = {
            "first_command_error": error,
            "steering_persisted": workspace.control.view(rid)["steering_note"] is not None,
            "interpretation": "Two connections interleaved after snapshot read and before command transaction.",
        }

        sid = repo.create_session()["id"]
        with patch.object(service, "connection", return_value={"ready": True, "details": {"models": ["test"]}}), \
             patch.object(service, "_spawn") as spawn:
            try:
                service.send(sid, {"text": "goal task", "request_id": "bad-goal", "goal_id": "missing"})
                error = None
            except Exception as exc:
                error = type(exc).__name__
        turns = repo.session(sid)["turns"]
        report["goal_binding_submission"] = {
            "error": error, "created_turns": len(turns),
            "turn_status": turns[0]["status"] if turns else None,
            "worker_started": spawn.called,
        }

        doc = repo.import_document({"title": "Synthetic recall fixture", "content": "ordinary material"})
        with runtime.store.tx() as db:
            db.executemany(
                "INSERT INTO workspace_chunks(document_id,chunk_index,content) VALUES (?,?,?)",
                [(doc["id"], i, "ordinary material") for i in range(1, 10000)]
                + [(doc["id"], 10000, "ZEUSUNIQUE987")],
            )
        report["knowledge_candidate_cutoff"] = {
            "synthetic_chunks": 10001,
            "matching_chunk_index": 10000,
            "hits": len(repo.search("ZEUSUNIQUE987")),
            "interpretation": "Candidate LIMIT is applied before lexical ranking.",
        }

    snapshot = {
        "messages": [{"role": "user", "content": "CURRENT-TASK"}],
        "memory": [{"memory_id": f"m{i}", "text": "旧资料" * 880,
                    "source_ref": f"run:{i}", "revision": 1} for i in range(6)],
    }
    request = conversation_request(SETTINGS, snapshot, snapshot["messages"], [])
    report["context_pressure_after_fix"] = {
        "recalled_memory_bytes": sum(len(m["text"].encode("utf-8")) for m in snapshot["memory"]),
        "model_context_bytes": request.context_report["bytes_used"],
        "max_bytes": request.context_report["max_bytes"],
        "selected_memory_count": sum(ref.startswith("memory:") for ref in request.context_report["selected"]),
        "dropped_count": len(request.context_report["dropped"]),
    }
    return report


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="myth-diagnosis-") as directory:
        print(json.dumps(diagnose(Path(directory)), ensure_ascii=False, indent=2))
