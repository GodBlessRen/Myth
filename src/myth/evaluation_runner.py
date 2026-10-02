"""Executable evaluation runner for Myth's fixed foundation suites.

The runner calls real Myth components in isolated temporary roots. It does not
grant new runtime authority and it never auto-promotes policies.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import tempfile
import threading
import time
from typing import Iterable

from .conversation import calculate
from .domain import SimulatedCrash
from .platform.control import ControlCommand
from .platform.evaluation import (
    EvalCase,
    EvalObservation,
    EvalReport,
    EvalSuite,
    EvalVerdict,
    load_eval_suite,
    release_gate,
    summarize_observations,
)
from .runtime import MythRuntime
from .domains.information import InformationResolution
from .strategies import ResolutionPlan, RuleIntentPicker, RuleResolutionController
from .workspace import Workspace


_SETTINGS = {
    "provider": "ollama",
    "model": "eval-local",
    "ollama_url": "http://127.0.0.1:11434",
    "max_steps": 6,
    "max_output_tokens": 512,
    "thinking": False,
}


class FixedResolutionController:
    """Offline eval-only policy. Production defaults are never mutated."""

    strategy_id = "information_resolution"

    def __init__(self, resolution: InformationResolution):
        self.resolution=resolution

    def choose(self, text, *, route, sources, attached_document_ids=()):
        if not sources:
            return ResolutionPlan(InformationResolution.L0,0,0,"no admitted local source is available")
        chars={
            InformationResolution.L0:500,
            InformationResolution.L1:1800,
            InformationResolution.L2:6000,
        }[self.resolution]
        return ResolutionPlan(
            self.resolution,
            max(5,len(attached_document_ids)),
            chars,
            f"offline eval fixed resolution={self.resolution.value}",
        )


class FoundationEvalRunner:
    """Run deterministic foundation cases against real local components."""

    def __init__(
        self,
        suite: EvalSuite,
        *,
        policy_id: str = "production-default",
        intent_picker=None,
        resolution_controller=None,
    ):
        self.suite=suite
        self.policy_id=str(policy_id or "").strip() or "production-default"
        self.intent_picker=intent_picker or RuleIntentPicker()
        self.resolution_controller=resolution_controller or RuleResolutionController()

    @classmethod
    def from_path(
        cls,
        path: str | Path,
        *,
        policy_id: str = "production-default",
        resolution_policy: str = "default",
    ) -> "FoundationEvalRunner":
        controller=None
        if resolution_policy != "default":
            controller=FixedResolutionController(InformationResolution(resolution_policy.upper()))
        return cls(
            load_eval_suite(path),
            policy_id=policy_id,
            resolution_controller=controller,
        )

    def _workspace(self, runtime):
        return Workspace(
            runtime,
            intent_picker=self.intent_picker,
            resolution_controller=self.resolution_controller,
        )

    def run(self, case_ids: Iterable[str] | None = None) -> dict:
        selected=set(case_ids or ())
        observations=[]
        started=time.perf_counter()
        for case in self.suite.cases:
            if selected and case.case_id not in selected:
                continue
            observations.append(self._run_case(case))
        report=summarize_observations(self.suite.suite_id,observations)
        gate_ok,gate_reason=release_gate(report,min_pass_rate=1.0)
        return {
            "suite_id":self.suite.suite_id,
            "version":self.suite.version,
            "principle":self.suite.principle,
            "policy_id":self.policy_id,
            "observations":[self._observation_dict(item) for item in observations],
            "report":asdict(report),
            "release_gate":{"passed":gate_ok,"reason":gate_reason},
            "elapsed_ms":round((time.perf_counter()-started)*1000,3),
        }

    @staticmethod
    def _observation_dict(item: EvalObservation) -> dict:
        value=asdict(item)
        value["verdict"]=item.verdict.value
        return value

    def _run_case(self, case: EvalCase) -> EvalObservation:
        started=time.perf_counter()
        try:
            method=getattr(self,f"_case_{case.case_id.replace('-','_')}",None)
            if method is None:
                return EvalObservation(
                    case.case_id,
                    EvalVerdict.UNSUPPORTED,
                    "no executable evaluator is registered for this fixed case",
                    {"latency_ms":round((time.perf_counter()-started)*1000,3)},
                    safety_regression=case.safety_critical,
                    policy_id=self.policy_id,
                    comparison_key=case.case_id,
                )
            verdict,reason,evidence,metrics=method(case)
            metrics=dict(metrics or {})
            metrics.setdefault("latency_ms",round((time.perf_counter()-started)*1000,3))
            return EvalObservation(
                case.case_id,
                verdict,
                reason,
                metrics,
                tuple(evidence or ()),
                safety_regression=case.safety_critical and verdict is not EvalVerdict.PASS,
                policy_id=self.policy_id,
                comparison_key=case.case_id,
            )
        except Exception as exc:
            return EvalObservation(
                case.case_id,
                EvalVerdict.FAIL,
                f"{type(exc).__name__}: {exc}",
                {"latency_ms":round((time.perf_counter()-started)*1000,3)},
                (),
                safety_regression=case.safety_critical,
                policy_id=self.policy_id,
                comparison_key=case.case_id,
            )

    def _case_intent_arithmetic_local(self, case):
        pick=self.intent_picker.pick(case.input["text"],{})
        answer=str(calculate((pick.metadata or {}).get("expression","")))
        ok=(
            pick.route.value==case.expected["route"]
            and answer==case.expected["answer"]
            and case.expected["model_calls"]==0
        )
        return (
            EvalVerdict.PASS if ok else EvalVerdict.FAIL,
            f"route={pick.route.value}, answer={answer}, model_calls=0",
            ("strategy:intent_pick",),
            {"model_calls":0,"cost":0},
        )

    def _case_intent_ambiguous_fallback(self, case):
        pick=self.intent_picker.pick(case.input["text"],{})
        ok=pick.route.value==case.expected["route"]
        return (
            EvalVerdict.PASS if ok else EvalVerdict.FAIL,
            f"route={pick.route.value}",
            ("strategy:intent_pick",),
            {"cost":0},
        )

    def _case_intent_local_retrieval_explicit(self, case):
        with tempfile.TemporaryDirectory() as tmp, MythRuntime(tmp) as runtime:
            workspace=self._workspace(runtime)
            workspace.repository.save_settings(_SETTINGS)
            workspace.repository.import_document({
                "title":"eval knowledge",
                "content":case.input["document"],
            })
            sid=workspace.repository.create_session()["id"]
            rid=workspace.repository.create_turn(
                sid,
                case.input["text"],
                "eval-local-retrieval",
            )["run_id"]
            snapshot=workspace.repository.turn(rid)["snapshot"]
            route=snapshot["intent_pick"]["route"]
            resolution=snapshot["information_resolution"]["resolution"]
            ok=route==case.expected["route"] and resolution==case.expected["resolution"]
            return (
                EvalVerdict.PASS if ok else EvalVerdict.FAIL,
                f"route={route}, resolution={resolution}",
                tuple(item["source_ref"] for item in snapshot["knowledge"]),
                {"retrieval_scanned":snapshot["retrieval_report"]["scanned"]},
            )

    def _case_resolution_attached_l2(self, case):
        with tempfile.TemporaryDirectory() as tmp, MythRuntime(tmp) as runtime:
            workspace=self._workspace(runtime)
            workspace.repository.save_settings(_SETTINGS)
            count=int(case.input["attachments"])
            docs=[
                workspace.repository.import_document({
                    "title":f"attachment {index}",
                    "content":f"ATTACH-{index} "+("detail "*400),
                })
                for index in range(count)
            ]
            sid=workspace.repository.create_session()["id"]
            rid=workspace.repository.create_turn(
                sid,
                case.input["text"],
                "eval-attached-l2",
                document_ids=[item["id"] for item in docs],
            )["run_id"]
            snapshot=workspace.repository.turn(rid)["snapshot"]
            ids={item["document_id"] for item in snapshot["knowledge"]}
            all_preserved={item["id"] for item in docs} <= ids
            route=snapshot["intent_pick"]["route"]
            resolution=snapshot["information_resolution"]["resolution"]
            ok=(
                route==case.expected["route"]
                and resolution==case.expected["resolution"]
                and all_preserved==case.expected["all_attachments_preserved"]
            )
            return (
                EvalVerdict.PASS if ok else EvalVerdict.FAIL,
                f"route={route}, resolution={resolution}, all_attachments={all_preserved}",
                tuple(item["source_ref"] for item in snapshot["knowledge"]),
                {"attachments":count},
            )

    def _case_resolution_agent_l0(self, case):
        with tempfile.TemporaryDirectory() as tmp, MythRuntime(tmp) as runtime:
            workspace=self._workspace(runtime)
            workspace.repository.save_settings(_SETTINGS)
            sid=workspace.repository.create_session()["id"]
            rid=workspace.repository.create_turn(
                sid,
                case.input["text"],
                "eval-agent-l0",
            )["run_id"]
            snapshot=workspace.repository.turn(rid)["snapshot"]
            route=snapshot["intent_pick"]["route"]
            resolution=snapshot["information_resolution"]["resolution"]
            ok=route==case.expected["route"] and resolution==case.expected["resolution"]
            return (
                EvalVerdict.PASS if ok else EvalVerdict.FAIL,
                f"route={route}, resolution={resolution}",
                (),
                {"retrieval_scanned":snapshot["retrieval_report"]["scanned"]},
            )

    def _case_resolution_marker_presence(self, case):
        with tempfile.TemporaryDirectory() as tmp, MythRuntime(tmp) as runtime:
            workspace=self._workspace(runtime)
            workspace.repository.save_settings(_SETTINGS)
            marker=case.input["marker"]
            document=case.input["prefix"]+marker+case.input["suffix"]
            doc=workspace.repository.import_document({
                "title":"resolution calibration source",
                "content":document,
            })
            sid=workspace.repository.create_session()["id"]
            rid=workspace.repository.create_turn(
                sid,
                f"根据资料找到 {marker}",
                "eval-resolution-marker",
            )["run_id"]
            snapshot=workspace.repository.turn(rid)["snapshot"]
            projected="\n".join(item.get("content","") for item in snapshot["knowledge"])
            visible=marker in projected
            expected=bool(case.expected["marker_visible"])
            resolution=snapshot["information_resolution"]["resolution"]
            ok=visible==expected
            return (
                EvalVerdict.PASS if ok else EvalVerdict.FAIL,
                f"marker_visible={visible}, resolution={resolution}",
                (f"doc:{doc['id']}@{doc['digest']}",),
                {
                    "context_chars":sum(len(item.get("content","")) for item in snapshot["knowledge"]),
                    "retrieval_scanned":snapshot["retrieval_report"]["scanned"],
                },
            )

    def _case_knowledge_late_candidate(self, case):
        with tempfile.TemporaryDirectory() as tmp, MythRuntime(tmp) as runtime:
            workspace=self._workspace(runtime)
            workspace.repository.save_settings(_SETTINGS)
            doc=workspace.repository.import_document({"title":"bulk","content":"seed"})
            position=int(case.input["candidate_position"])
            rows=[(doc["id"],i,"noise") for i in range(1,position)]
            rows.append((doc["id"],position,"needle "+case.input["query"]))
            with runtime.store.tx() as db:
                db.executemany(
                    "INSERT INTO workspace_chunks(document_id,chunk_index,content) VALUES (?,?,?)",
                    rows,
                )
            result=workspace.repository.search_report(case.input["query"],limit=3)
            found=bool(result["sources"]) and result["sources"][0]["chunk_index"]==position
            ok=found and result["retrieval"]["truncated_before_ranking"] is False
            return (
                EvalVerdict.PASS if ok else EvalVerdict.FAIL,
                f"found={found}, scanned={result['retrieval']['scanned']}",
                (f"doc:{doc['id']}",),
                {"scanned":result["retrieval"]["scanned"]},
            )

    def _case_memory_late_candidate(self, case):
        with tempfile.TemporaryDirectory() as tmp, MythRuntime(tmp) as runtime:
            workspace=self._workspace(runtime)
            position=int(case.input["candidate_position"])
            with runtime.store.tx() as db:
                db.executemany(
                    "INSERT INTO workspace_memories(memory_id,kind,text,source_ref,scope_type,scope_id,fact_level) "
                    "VALUES (?,?,?,?,?,?,?)",
                    [
                        (f"eval_mem_{i}","semantic","noise",f"eval:{i}","global",None,"context")
                        for i in range(position-1)
                    ],
                )
                db.execute(
                    "INSERT INTO workspace_memories(memory_id,kind,text,source_ref,scope_type,scope_id,fact_level) "
                    "VALUES (?,?,?,?,?,?,?)",
                    ("eval_mem_target","semantic",case.input["query"],"eval:target","global",None,"verified"),
                )
            result=workspace.memory.search_report(case.input["query"],limit=3)
            found=bool(result["memories"]) and result["memories"][0]["memory_id"]=="eval_mem_target"
            ok=found and result["retrieval"]["truncated_before_ranking"] is False
            return (
                EvalVerdict.PASS if ok else EvalVerdict.FAIL,
                f"found={found}, scanned={result['retrieval']['scanned']}",
                ("memory:eval_mem_target",),
                {"scanned":result["retrieval"]["scanned"]},
            )

    def _case_knowledge_resolution_provenance(self, case):
        with tempfile.TemporaryDirectory() as tmp, MythRuntime(tmp) as runtime:
            workspace=self._workspace(runtime)
            workspace.repository.save_settings(_SETTINGS)
            doc=workspace.repository.import_document({
                "title":"guide",
                "content":"alpha\n"+("beta "*700),
            })
            sid=workspace.repository.create_session()["id"]
            rid=workspace.repository.create_turn(sid,"详细证据","eval-resolution",document_ids=[doc["id"]])["run_id"]
            turn=workspace.repository.turn(rid)
            views=[
                workspace.execution._resolve_knowledge(
                    turn,{"document_id":doc["id"],"resolution":level}
                )
                for level in case.input["levels"]
            ]
            same_ref=len({item["source_ref"] for item in views})==1
            same_digest=len({item["digest"] for item in views})==1
            ok=same_ref==case.expected["same_source_ref"] and same_digest==case.expected["same_digest"]
            return (
                EvalVerdict.PASS if ok else EvalVerdict.FAIL,
                f"same_source_ref={same_ref}, same_digest={same_digest}",
                tuple(item["source_ref"] for item in views),
                {"cost":0},
            )

    def _case_project_search_continuation(self, case):
        with tempfile.TemporaryDirectory() as tmp, MythRuntime(tmp) as runtime:
            root=Path(tmp)/"project";root.mkdir()
            for i in range(3):
                (root/f"{i}.txt").write_text("needle\n" if i==2 else "noise\n",encoding="utf-8")
            workspace=self._workspace(runtime)
            workspace.repository.save_settings(_SETTINGS)
            project=workspace.repository.create_project({"name":"eval","root":str(root)})
            sid=workspace.repository.create_session(project_id=project["id"])["id"]
            rid=workspace.repository.create_turn(sid,"find needle","eval-project-search")["run_id"]
            turn=workspace.repository.turn(rid)
            first=workspace.execution._search_project(
                turn,{"query":"needle","max_files":case.input["max_files"],"limit":5}
            )
            second=workspace.execution._search_project(
                turn,{"query":"needle","cursor":first["next_cursor"],"max_files":2,"limit":5}
            )
            ok=(
                first["has_more"]
                and first["next_cursor"] is not None
                and bool(second["matches"])
                and "scanned_files" in first
            )
            return (
                EvalVerdict.PASS if ok else EvalVerdict.FAIL,
                f"cursor={first['next_cursor']}, second_matches={len(second['matches'])}",
                ("project.search",),
                {"scanned_files":first["scanned_files"]+second["scanned_files"]},
            )

    def _case_control_revision_concurrency(self, case):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with MythRuntime(root) as runtime:
                workspace=self._workspace(runtime)
                workspace.repository.save_settings(_SETTINGS)
                sid=workspace.repository.create_session("control")["id"]
                turn=workspace.repository.create_turn(sid,"hello","eval-control")
                rid=turn["run_id"]
                workspace.control.ensure(rid,turn["settings"])

            barrier=threading.Barrier(int(case.input["concurrent_commands"]))
            errors=[]
            lock=threading.Lock()
            def issue(command,payload=None):
                try:
                    with MythRuntime(root) as runtime:
                        workspace=self._workspace(runtime)
                        barrier.wait(timeout=5)
                        workspace.control.command(rid,command,payload)
                except BaseException as exc:
                    with lock:errors.append(exc)
            threads=[
                threading.Thread(target=issue,args=(ControlCommand.STEER,"focus")),
                threading.Thread(target=issue,args=(ControlCommand.COMPACT,None)),
            ]
            for thread in threads:thread.start()
            for thread in threads:thread.join(5)
            with MythRuntime(root) as runtime:
                revisions=[
                    item["revision"]
                    for item in self._workspace(runtime).control.view(rid)["commands"]
                ]
            expected=list(case.expected["durable_revisions"])
            ok=not errors and revisions==expected
            return (
                EvalVerdict.PASS if ok else EvalVerdict.FAIL,
                f"revisions={revisions}, errors={len(errors)}",
                (f"run:{rid}",),
                {"concurrent_commands":len(threads)},
            )

    def _case_unknown_no_blind_replay(self, case):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/"input.txt";source.write_text("foo\n",encoding="utf-8")
            with MythRuntime(root) as runtime:
                rid=runtime.submit_patch(source,old_text="foo",new_text="bar",expected_count=1)
                try:
                    runtime.execute(rid,failpoint="after_write_before_receipt")
                except SimulatedCrash:
                    pass
            with MythRuntime(root) as runtime:
                [status]=runtime.recover(rid)
                accounts={item["meter"]:item for item in status["budgets"]}
                no_redispatch=(
                    status["state"]=="SUCCEEDED"
                    and accounts["tool_calls"]["settled"]==0
                    and accounts["tool_calls"]["unknown_held"]==1
                )
            ok=no_redispatch is (not case.expected["redispatch"])
            return (
                EvalVerdict.PASS if ok else EvalVerdict.FAIL,
                f"redispatch={not no_redispatch}, state={status['state']}",
                (f"run:{rid}",),
                {"tool_calls_settled":accounts["tool_calls"]["settled"]},
            )


def run_eval_suite(
    path: str | Path,
    case_ids: Iterable[str] | None = None,
    *,
    policy_id: str = "production-default",
    resolution_policy: str = "default",
) -> dict:
    return FoundationEvalRunner.from_path(
        path,
        policy_id=policy_id,
        resolution_policy=resolution_policy,
    ).run(case_ids)
