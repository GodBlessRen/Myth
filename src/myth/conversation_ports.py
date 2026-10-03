"""对话用例的仓储、执行、控制、记忆和 Goal checkpoint 合同。
只暴露数据与安全点操作；应用不能取得 SQL 游标，具体适配器由 Workspace 装配。"""

from typing import Protocol, Any


# 对话状态端口；步骤、消息与恢复游标原子提交，返回普通数据。
class ConversationRepository(Protocol):
    # 读取 Turn、固定快照与步骤结果；返回值为投影，修改它不会提交持久事实。
    def turn(self, run_id: str) -> dict: ...

    # 读取会话及其消息/轮次投影；持久状态仍由仓储操作修改。
    def session(self, session_id: str) -> dict: ...

    # 原子分配或复用当前未完成步骤；耗尽步数返回空值，恢复不跳过未消费的决定。
    def begin_step(self, run_id: str) -> dict | None: ...

    # 把当前步骤与固定决定关联，并推进 durable cursor；禁止不同决定复用同一步。
    def bind(self, run_id: str, step: int, decision_id: str, decision: Any) -> None: ...

    # 记录确定路径回退原因，供运行观测与评测审计；不改变权限范围。
    def record_route_fallback(
        self, run_id: str, step: int, route: str, reason: str
    ) -> None: ...

    # 原子记入工具结果与步骤完成事实；之后安全点才可派发新动作。
    def finish_tool(self, run_id: str, step: int, result: dict) -> None: ...

    # 记录已知参数/权限拒绝为反馈；拒绝不冒充 Ticket 后的 UNKNOWN。
    def reject(self, run_id: str, step: int, reason: str) -> None: ...

    # 把回答/问题、步骤状态及游标一起提交；普通 COMPLETED 只表示对话回答已结束。
    def finish_reply(
        self, run_id: str, step: int, text: str, question_id: str | None = None
    ) -> None: ...

    # 持久记录阻塞/结束状态及原因；不抹掉已签发凭证和晚到收据。
    def block(self, run_id: str, status: str, reason: str) -> None: ...

    # 按当前持久状态重新进入驱动；恢复核对由执行端口负责，不凭重开动作重发未知效果。
    def reopen(self, run_id: str) -> None: ...


# 对话工具/模型执行与恢复端口；已获凭证的不明效果不能盲重发。
class ConversationExecution(Protocol):
    # 取得一个 Run 的本机执行互斥作用域；竞争不表示效果失败，需按恢复事实判断后续。
    def lock(self, run_id: str) -> Any: ...

    # 用已有请求、Ticket、收据和对象核对执行状态；没有足够事实时保留 UNKNOWN，不盲目重发。
    def recover(self, run_id: str) -> bool: ...

    # 生成下一步决策提案；实现方固定请求身份，返回值仍需本地参数/权限校验。
    def decide(self, turn: dict, step: int, provider: Any) -> tuple: ...

    # 执行已校验/准入的工作并留下结果证据；已存在稳定绑定时复用事实而非重复效果。
    def execute(self, turn: dict, decision_id: str, decision: Any) -> dict: ...


class ConversationControl(Protocol):
    """用例的控制协议；实现方保存命令，用例仅在安全点查询。"""

    # 在安全点应用明确控制意图；停止/暂停未来工作，已发出效果不会被物理撤销。
    def gate(self, run_id: str) -> str | None: ...

    # 生成当前控制事实与命令历史的只读投影；不是新的业务执行决定。
    def view(self, run_id: str) -> dict: ...

    # 只消费生成该决定时使用的 Compact revision；旧决定不能清除更新的压缩请求。
    def consume_compaction(
        self, run_id: str, *, decision_id: str | None = None
    ) -> None: ...


class ConversationMemory(Protocol):
    """完成后经历记录协议；实现方保存来源，文本不升级为验收事实。"""

    # 把一次已结束对话记录为有来源的经历；默认事实等级为 context，不自动成为 verified。
    def record_episode(self, run_id: str, user_text: str, answer: str) -> dict: ...


class GoalCheckpoint(Protocol):
    """Goal 进度协议；实现方校验最新 Run 身份并处理迟到 checkpoint。"""

    # 把 Run 状态映射为 Goal 进度；校验 last_run_id 防止迟到旧轮次覆盖新准入状态。
    def checkpoint_run(
        self,
        goal_id: str,
        run_id: str,
        *,
        status: str,
        summary: str = "",
        next_action: str = "",
        waiting_for: str = "",
    ) -> dict: ...
