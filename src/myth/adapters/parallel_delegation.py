"""有界并行委派的外圈协调器。

父游标只拥有一个批次；最多三个隔离子游标并行调用，各线程拥有自己的 SQLite
连接。全部 Ticket 原子准入，子收据各自持久；汇合按固定 ordinal，不按到达时间。
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import time

from ..domain import ExecutionDeferred, RecoveryRequired
from ..models import ProviderUnavailable
from ..runtime import MythRuntime
from .subagent_runtime import run_subagent


class ParallelDelegation:
    """一次 fork/join 最多三个独立子任务；父模型的规划、审核和状态仍只有一个写入游标。"""

    def __init__(self, execution):
        """绑定父线程执行器；只把冻结合同及 Provider 工厂传给工作线程。"""
        # execution：属于父线程的连接与收据协作者，不能传到子线程使用。
        self.execution = execution

    def execute(self, turn, decision_id, args):
        """全量校验后一次准入，再同时启动；恢复只重启缺少已知终态的子任务。"""
        repository = self.execution.repository
        batch = repository.operation(decision_id)
        if batch and batch["state"] == "RESOLVED":
            return batch["result"]
        if not batch:
            tasks = args.get("tasks")
            if not isinstance(tasks, list) or not 1 <= len(tasks) <= 3 or any(not isinstance(x, dict) for x in tasks):
                raise ValueError("agent.parallel tasks 须为 1–3 个独立任务")
            # 每个返回结果仍须独立审核；不能派发一个注定无步骤汇总的批次。
            if turn["settings"]["max_steps"] - turn["current_step"] < len(tasks) + 1:
                raise ValueError("剩余步骤不足以审核全部子任务并汇总")
            contracts, fallbacks = [], []
            for ordinal, task in enumerate(tasks, 1):
                child_id = f"{decision_id}_child_{ordinal}"
                contract = self.execution.delegation.prepare(turn, child_id, task)
                if contract.get("fallback_to_parent"):
                    fallbacks.append({**contract, "ordinal": ordinal})
                else:
                    contracts.append({**contract, "batch_id": decision_id, "ordinal": ordinal})
            batch = repository.start_parallel(turn["run_id"], decision_id, contracts, fallbacks)
        contracts = batch["intent"]["parallel"]
        pending = [c for c in contracts if repository.operation(c["delegation_id"])["state"] != "RESOLVED"]
        started = time.monotonic()
        errors = []
        # Future 完成顺序仅用于收集异常；子事实自己发布，批次结果始终按 ordinal 归位。
        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="myth-child") as pool:
            futures = [pool.submit(self._work, c) for c in pending]
            for future in as_completed(futures):
                try:
                    future.result()
                except BaseException as exc:
                    errors.append(exc)
        if errors:
            # 先等全部在途收据落定，再上交父共享恢复机制；成功兄弟无需重跑。
            priority = (RecoveryRequired, ProviderUnavailable, ExecutionDeferred)
            error = next((x for x in errors if not isinstance(x, Exception)),
                next((x for kind in priority for x in errors if isinstance(x, kind)), errors[0]))
            raise error
        result = self.result(batch, wall_ms=max(0, int((time.monotonic() - started) * 1000)))
        return self.execution._record_tool_receipt(batch, result, result["parallel"]["wall_ms"])

    def _work(self, contract):
        """在工作线程内装配/关闭连接和供应商；不跨线程复用父 Provider 或 SQLite。"""
        from .conversation_execution import LocalConversationExecution
        from .personal_store import SqlitePersonalState
        from .workspace_store import SqliteWorkspaceRepository
        from ..platform.control_store import SqliteControlService
        factory = self.execution.provider_factory
        with MythRuntime(self.execution.runtime.root) as runtime:
            repository = SqliteWorkspaceRepository(runtime, personal=SqlitePersonalState(runtime))
            control = SqliteControlService(runtime, repository)
            execution = LocalConversationExecution(runtime, repository, parent_control=control,
                provider_factory=factory, capability_registry=self.execution.registry,
                subagent_registry=self.execution.subagents)
            # delegate 读取原合同，工厂失败亦是明确零派发结果；这里不重新选择模型。
            turn = repository.turn(contract["run_id"])
            result = execution.delegation.delegate(turn, contract["delegation_id"], {}, None, force_factory=True)
            return execution._record_tool_receipt(repository.operation(contract["delegation_id"]), result)

    def result(self, batch, *, wall_ms=None):
        """从持久子收据生成有序批次；恢复缺测耗时保持 None，不能累加子耗时冒充等待时间。"""
        results = list(batch["intent"].get("fallbacks", []))
        for contract in batch["intent"]["parallel"]:
            op = self.execution.repository.operation(contract["delegation_id"])
            if op["state"] != "RESOLVED":
                raise ExecutionDeferred("parallel batch still has unfinished children")
            results.append({**op["result"], "ordinal": contract["ordinal"]})
        return {"capability_id": "agent.parallel", "batch_id": batch["decision_id"],
            "results": sorted(results, key=lambda x: x["ordinal"]),
            "parallel": {"max_workers": 3, "task_count": len(results), "wall_ms": wall_ms,
                         "wall_ms_scope": "current_driver_segment" if wall_ms is not None else "unreported"},
            "summary": "子任务按派发顺序汇合；每项内容与元数据须由主模型分别审核。"}

    def reconcile(self, batch):
        """只消费已有子模型事实并补收据；未启动/零派发中断的子任务留给正常续跑。"""
        for contract in batch["intent"]["parallel"]:
            op = self.execution.repository.operation(contract["delegation_id"])
            if op["state"] == "RESOLVED":
                continue
            state = self.execution.repository.delegation_state(contract["delegation_id"])
            if state is None:
                continue
            state = run_subagent(self.execution, contract, None, replay_only=True)
            if state["status"] in {"COMPLETED", "FAILED", "BUDGET_EXHAUSTED", "CANCELLED"}:
                result = self.execution.delegation.result(contract, state)
                self.execution._record_tool_receipt(op, result)
        if all(self.execution.repository.operation(c["delegation_id"])["state"] == "RESOLVED"
               for c in batch["intent"]["parallel"]):
            return self.execution._record_tool_receipt(batch, self.result(batch))
        return None
