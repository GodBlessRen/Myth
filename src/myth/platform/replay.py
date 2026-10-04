"""历史 Replay World：把同一冻结条件下已发生的 SOTA Route 合并为可重放的已实现搜索空间。

Replay 只读取历史可观察动作和已测量终点指标；未出现过的动作保持 UNOBSERVED，
不会调用模型、工具、Verification，也不会产生 Policy Promote 资格。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import Any, Callable, Iterable

from ..domain import canonical_json


# ReplayStatus：离线重放结果；UNOBSERVED 明确表示历史没有覆盖该分支，不等同失败或预测结果。
class ReplayStatus(StrEnum):
    # TERMINAL：策略到达历史中真实存在的终点。
    TERMINAL = "TERMINAL"
    # STOPPED：策略在没有历史终点证据的前缀主动停止。
    STOPPED = "STOPPED"
    # UNOBSERVED：策略选择了历史没有执行过的动作。
    UNOBSERVED = "UNOBSERVED"
    # STEP_LIMIT：达到离线重放步数上限，未继续消费历史边。
    STEP_LIMIT = "STEP_LIMIT"


# ReplayAction：历史中真实出现过的下一动作；key 由可观察动作内容确定，不包含隐藏推理。
@dataclass(frozen=True)
class ReplayAction:
    # key：可观察动作的稳定摘要键；同内容动作跨 Run 可合并。
    key: str
    # kind：SOTA Route 可观察动作类别，例如 tool / ask / reply。
    kind: str
    # label：面向策略和诊断的简短动作名。
    label: str
    # payload：去除 step/decision_id 后的可观察动作内容；不包含隐藏推理。
    payload: dict[str, Any]
    # visits：有多少真实历史 Run 走过该下一边。
    visits: int


# ReplayObservation：某个历史前缀的只读视图；terminal_* 只引用真实已验收 Run 的终点事实。
@dataclass(frozen=True)
class ReplayObservation:
    # node_id：历史前缀节点的确定性身份。
    node_id: str
    # depth：已经消费的可观察动作数量。
    depth: int
    # available_actions：仅历史真实出现过的下一动作。
    available_actions: tuple[ReplayAction, ...]
    # terminal_run_ids：恰好在当前前缀结束的真实 Run 身份。
    terminal_run_ids: tuple[str, ...]
    # terminal_metrics：对应终点 Run 已测量的成本事实。
    terminal_metrics: tuple[dict[str, Any], ...]
    # covered_runs：经过当前前缀的历史 Run 数量。
    covered_runs: int


# ReplayResult：一次候选策略在单个历史世界中的离线轨迹；不包含发布或线上质量声明。
@dataclass(frozen=True)
class ReplayResult:
    # status：本次离线重放的证据状态。
    status: ReplayStatus
    # reason：人类可读的停止或边界原因。
    reason: str
    # steps：实际沿历史边前进的步数。
    steps: int
    # action_keys：候选策略实际选择的历史动作键。
    action_keys: tuple[str, ...]
    # terminal_run_ids：若到达历史终点，对应真实 Run 身份。
    terminal_run_ids: tuple[str, ...]
    # terminal_metrics：终点 Run 的原始已测量指标，不重算神秘总分。
    terminal_metrics: tuple[dict[str, Any], ...]
    # covered_runs：该 World 总共包含的真实历史 Run 数量。
    covered_runs: int


# ReplayPolicyReport：同一候选策略跨多个历史世界的证据汇总；刻意不压成神秘总分。
@dataclass(frozen=True)
class ReplayPolicyReport:
    # policy_id：研究候选身份；不会自动注册为生产 Active Policy。
    policy_id: str
    # worlds：本次离线评估覆盖的 Replay World 数量。
    worlds: int
    # terminal_worlds：候选策略到达真实历史终点的世界数。
    terminal_worlds: int
    # stopped_worlds：候选策略提前停止且没有终点证据的世界数。
    stopped_worlds: int
    # unobserved_worlds：候选策略越出历史已实现搜索空间的世界数。
    unobserved_worlds: int
    # step_limited_worlds：达到离线步数上限的世界数。
    step_limited_worlds: int
    # selected_run_ids：候选策略最终命中的真实历史 Run 身份。
    selected_run_ids: tuple[str, ...]
    # results：逐 World 原始结果；Evaluation 可据此形成进一步固定证据。
    results: tuple[ReplayResult, ...]


# UnobservedReplayAction：策略选择了历史从未执行的边；Replay 必须停在证据边界，不能补造结果。
class UnobservedReplayAction(ValueError):
    pass


# _ReplayNode：构建期前缀树节点；只在 ReplayWorld 内拥有，外部只读取 ReplayObservation。
class _ReplayNode:
    # 初始化一个前缀节点；covered_runs 统计有多少历史 Run 经过该前缀。
    def __init__(self, node_id: str, depth: int) -> None:
        # node_id：当前前缀节点的确定性身份。
        self.node_id = node_id
        # depth：该节点代表的动作前缀长度。
        self.depth = depth
        # children：action key 到下一历史前缀节点的映射。
        self.children: dict[str, str] = {}
        # actions：每条历史边对应的去身份化可观察动作。
        self.actions: dict[str, dict[str, Any]] = {}
        # terminals：恰好在当前前缀结束的真实 Run 及其指标。
        self.terminals: list[dict[str, Any]] = []
        # covered_runs：经过当前节点的真实 Run 数量。
        self.covered_runs = 0


# 规范化 SOTA Route 的可观察动作；忽略 step/decision_id，避免运行身份阻止相同动作前缀合并。
def _normalize_action(raw: dict[str, Any]) -> tuple[str, str, str, dict[str, Any]]:
    kind = str(raw.get("kind") or "unknown").strip().lower() or "unknown"
    if kind == "tool":
        capability = str(raw.get("capability") or "tool").strip() or "tool"
        arguments = raw.get("arguments") if isinstance(raw.get("arguments"), dict) else {}
        payload = {
            "kind": "tool",
            "capability": capability,
            "arguments": dict(arguments),
        }
        label = capability
    elif kind == "ask":
        payload = {"kind": "ask"}
        label = "ask_user"
    elif kind == "reply":
        payload = {"kind": "reply"}
        label = "reply"
    else:
        payload = {"kind": kind}
        label = kind
    digest = sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:16]
    return f"{label}:{digest}", kind, label, payload


# ReplayWorld：把同一 comparison_key 的多个真实成功轨迹合并为前缀树，并提供确定性只读 replay。
class ReplayWorld:
    # 从已筛选 episode 构建世界；调用方通常使用 from_sota_group，避免绕过比较条件校验。
    def __init__(self, *, comparison_key: str, episodes: Iterable[dict[str, Any]]) -> None:
        # comparison_key：固定任务/模型/环境比较身份；不同键不得混树。
        self.comparison_key = str(comparison_key or "")
        # _nodes：内存前缀树；它是历史派生投影，不拥有新的 durable truth。
        self._nodes: dict[str, _ReplayNode] = {"root": _ReplayNode("root", 0)}
        # _episode_count：成功加入世界的真实历史 Run 数。
        self._episode_count = 0
        for episode in episodes:
            self._add_episode(episode)
        if self._episode_count <= 0:
            raise ValueError("Replay World requires at least one eligible historical route")

    # 从 SOTA Route 同组快照构建世界；不同 comparison_key 禁止混入同一历史环境。
    @classmethod
    def from_sota_group(cls, group: Iterable[dict[str, Any]]) -> "ReplayWorld":
        values = tuple(group)
        eligible = [item for item in values if bool(item.get("eligible"))]
        keys = {
            str(item.get("comparison_key") or "")
            for item in eligible
            if str(item.get("comparison_key") or "")
        }
        if len(keys) > 1:
            raise ValueError("Replay World cannot mix different comparison_key values")
        episodes = []
        for item in eligible:
            run_id = str(item.get("run_id") or "").strip()
            path = item.get("path")
            metrics = item.get("metrics")
            if not run_id or not isinstance(path, list) or not isinstance(metrics, dict):
                continue
            episodes.append(
                {
                    "run_id": run_id,
                    "path": [entry for entry in path if isinstance(entry, dict)],
                    "metrics": dict(metrics),
                }
            )
        return cls(comparison_key=next(iter(keys), ""), episodes=episodes)

    # covered_runs：当前世界包含的真实历史 Run 数量；不是推演样本数或线上成功率。
    @property
    def covered_runs(self) -> int:
        return self._episode_count

    # 把一个真实 Run 的可观察 Action Path 加入前缀树；相同前缀共享节点，不复制隐藏上下文。
    def _add_episode(self, episode: dict[str, Any]) -> None:
        run_id = str(episode.get("run_id") or "").strip()
        path = episode.get("path")
        metrics = episode.get("metrics")
        if not run_id or not isinstance(path, list) or not isinstance(metrics, dict):
            return
        node = self._nodes["root"]
        node.covered_runs += 1
        prefix: list[str] = []
        for raw_action in path:
            if not isinstance(raw_action, dict):
                continue
            action_key, kind, label, payload = _normalize_action(raw_action)
            prefix.append(action_key)
            child_id = "node:" + sha256("\n".join(prefix).encode("utf-8")).hexdigest()[:20]
            if action_key not in node.children:
                node.children[action_key] = child_id
                node.actions[action_key] = {
                    "kind": kind,
                    "label": label,
                    "payload": payload,
                }
                self._nodes[child_id] = _ReplayNode(child_id, node.depth + 1)
            node = self._nodes[node.children[action_key]]
            node.covered_runs += 1
        node.terminals.append({"run_id": run_id, "metrics": dict(metrics)})
        self._episode_count += 1

    # 读取某个历史前缀；返回的 available_actions 只包含真实已观测下一边。
    def observe(self, node_id: str = "root") -> ReplayObservation:
        node = self._nodes.get(node_id)
        if node is None:
            raise KeyError(node_id)
        actions = []
        for action_key in sorted(node.children):
            child = self._nodes[node.children[action_key]]
            raw = node.actions[action_key]
            actions.append(
                ReplayAction(
                    key=action_key,
                    kind=str(raw["kind"]),
                    label=str(raw["label"]),
                    payload=dict(raw["payload"]),
                    visits=child.covered_runs,
                )
            )
        return ReplayObservation(
            node_id=node.node_id,
            depth=node.depth,
            available_actions=tuple(actions),
            terminal_run_ids=tuple(item["run_id"] for item in node.terminals),
            terminal_metrics=tuple(dict(item["metrics"]) for item in node.terminals),
            covered_runs=node.covered_runs,
        )

    # 沿历史真实存在的边前进；未观测动作抛出显式异常，当前世界不会猜测 counterfactual outcome。
    def step(self, node_id: str, action_key: str) -> ReplayObservation:
        node = self._nodes.get(node_id)
        if node is None:
            raise KeyError(node_id)
        child_id = node.children.get(str(action_key))
        if child_id is None:
            raise UnobservedReplayAction(
                f"action {action_key!r} is outside the realized historical search space"
            )
        return self.observe(child_id)

    # 在单个历史世界中执行候选决策函数；None 表示策略主动停止，不调用真实模型或工具。
    def evaluate(
        self,
        decide: Callable[[ReplayObservation], str | None],
        *,
        max_steps: int = 64,
    ) -> ReplayResult:
        if max_steps < 1:
            raise ValueError("max_steps must be positive")
        node_id = "root"
        action_keys: list[str] = []
        for _ in range(max_steps + 1):
            observation = self.observe(node_id)
            if not observation.available_actions:
                status = (
                    ReplayStatus.TERMINAL
                    if observation.terminal_run_ids
                    else ReplayStatus.STOPPED
                )
                return ReplayResult(
                    status=status,
                    reason=(
                        "reached an observed historical terminal"
                        if status is ReplayStatus.TERMINAL
                        else "historical prefix has no observed continuation"
                    ),
                    steps=len(action_keys),
                    action_keys=tuple(action_keys),
                    terminal_run_ids=observation.terminal_run_ids,
                    terminal_metrics=observation.terminal_metrics,
                    covered_runs=self.covered_runs,
                )
            if len(action_keys) >= max_steps:
                return ReplayResult(
                    status=ReplayStatus.STEP_LIMIT,
                    reason="replay step limit reached before another historical action",
                    steps=len(action_keys),
                    action_keys=tuple(action_keys),
                    terminal_run_ids=observation.terminal_run_ids,
                    terminal_metrics=observation.terminal_metrics,
                    covered_runs=self.covered_runs,
                )
            choice = decide(observation)
            if choice is None:
                status = (
                    ReplayStatus.TERMINAL
                    if observation.terminal_run_ids
                    else ReplayStatus.STOPPED
                )
                return ReplayResult(
                    status=status,
                    reason=(
                        "policy stopped at an observed historical terminal prefix"
                        if status is ReplayStatus.TERMINAL
                        else "policy stopped before any observed terminal"
                    ),
                    steps=len(action_keys),
                    action_keys=tuple(action_keys),
                    terminal_run_ids=observation.terminal_run_ids,
                    terminal_metrics=observation.terminal_metrics,
                    covered_runs=self.covered_runs,
                )
            try:
                next_observation = self.step(node_id, str(choice))
            except UnobservedReplayAction as exc:
                return ReplayResult(
                    status=ReplayStatus.UNOBSERVED,
                    reason=str(exc),
                    steps=len(action_keys),
                    action_keys=tuple(action_keys),
                    terminal_run_ids=(),
                    terminal_metrics=(),
                    covered_runs=self.covered_runs,
                )
            action_keys.append(str(choice))
            node_id = next_observation.node_id
        raise AssertionError("unreachable replay loop")


# ReplayLab：在多个历史世界上批量运行同一候选策略，只汇总证据覆盖，不直接计算发布资格。
class ReplayLab:
    # 固定要比较的历史世界池；空池没有任何可重放证据，因此直接拒绝。
    def __init__(self, worlds: Iterable[ReplayWorld]) -> None:
        # worlds：固定的历史世界池；评估期间不会追加或改写线上 Run。
        self.worlds = tuple(worlds)
        if not self.worlds:
            raise ValueError("Replay Lab requires at least one Replay World")

    # 运行候选策略并汇总 coverage/result；policy_id 只是研究身份，不注册 Active Policy。
    def evaluate(
        self,
        policy_id: str,
        decide: Callable[[ReplayObservation], str | None],
        *,
        max_steps: int = 64,
    ) -> ReplayPolicyReport:
        pid = str(policy_id or "").strip()
        if not pid:
            raise ValueError("policy_id is required")
        results = tuple(
            world.evaluate(decide, max_steps=max_steps) for world in self.worlds
        )
        selected = tuple(
            dict.fromkeys(
                run_id
                for result in results
                for run_id in result.terminal_run_ids
            )
        )
        return ReplayPolicyReport(
            policy_id=pid,
            worlds=len(results),
            terminal_worlds=sum(
                result.status is ReplayStatus.TERMINAL for result in results
            ),
            stopped_worlds=sum(
                result.status is ReplayStatus.STOPPED for result in results
            ),
            unobserved_worlds=sum(
                result.status is ReplayStatus.UNOBSERVED for result in results
            ),
            step_limited_worlds=sum(
                result.status is ReplayStatus.STEP_LIMIT for result in results
            ),
            selected_run_ids=selected,
            results=results,
        )
