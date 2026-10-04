"""显式成本权重合同及 SQLite 版本目录。
token、时延、调用量默认多维；只有用户登记的权重版本可生成标量成本，登记身份不可被不同内容复用。"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Mapping

from ..domain import canonical_json


# SCHEMA：本仓储拥有的当前表、索引与约束；由 Store 原子初始化，不叠加旧格式迁移。
SCHEMA = """
CREATE TABLE IF NOT EXISTS cost_models(
    cost_model_id TEXT PRIMARY KEY,
    version INTEGER NOT NULL CHECK(version > 0),
    weights_json TEXT NOT NULL,
    description TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


# 显式权重版本合同；只把已声明成本维度转为标量，负成本变化不计额外支出。
@dataclass(frozen=True)
class CostModel:
    # cost_model_id：显式成本权重合同身份；不能被不同内容复用。
    cost_model_id: str
    # version：固定合同/配置版本；历史比较必须保留版本身份。
    version: int
    # weights：各 meter 到标量成本的显式权重；默认不发明归一化。
    weights: dict[str, float]
    # description：显式说明文本；不作为能力授权。
    description: str = ""

    # 在合同构造时校验输入边界；非法值提前拒绝，避免进入后续执行或比较。
    def __post_init__(self):
        if not self.cost_model_id.strip() or self.version < 1:
            raise ValueError("cost model id/version are required")
        for meter, weight in self.weights.items():
            if (
                not str(meter).strip()
                or not isinstance(weight, (int, float))
                or weight < 0
            ):
                raise ValueError(
                    "cost weights require non-empty meters and non-negative numbers"
                )

    # 按显式权重汇总正向成本差；不存在维度当前按零项处理，不表示该维度已真实测量。
    def weighted_cost(self, delta: Mapping[str, float]) -> float:
        return sum(
            float(weight) * max(0.0, float(delta.get(meter, 0.0)))
            for meter, weight in self.weights.items()
        )


# 成本模型的不可变身份目录；同 ID 不允许不同版本/权重悄悄覆盖。
class SqliteCostModelRegistry:
    # 复用 Runtime 连接建立不可变成本权重目录；同身份重试只能复用完全相同内容。
    def __init__(self, runtime):
        # store：持久事实仓储；短事务维护本地一致性；外部效果不能并入数据库事务。
        self.store = runtime.store
        self.store.ensure_schema(SCHEMA)

    # 以 cost_model_id 固定版本/权重内容，重复相同复用、不同内容拒绝覆盖。
    def put(self, model: CostModel) -> dict:
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            existing = db.execute(
                "SELECT version,weights_json,description FROM cost_models WHERE cost_model_id=?",
                (model.cost_model_id,),
            ).fetchone()
            payload = canonical_json(model.weights)
            if existing:
                if (
                    int(existing["version"]) != model.version
                    or existing["weights_json"] != payload
                    or existing["description"] != model.description
                ):
                    raise ValueError(
                        "cost_model_id is immutable; create a new version/id"
                    )
            else:
                db.execute(
                    "INSERT INTO cost_models(cost_model_id,version,weights_json,description) VALUES (?,?,?,?)",
                    (model.cost_model_id, model.version, payload, model.description),
                )
        return self.get(model.cost_model_id)

    # 按身份取得已登记数据；缺失身份显式失败，调用方不能据此捏造已存在对象。
    def get(self, cost_model_id: str) -> dict:
        row = self.store.db.execute(
            "SELECT * FROM cost_models WHERE cost_model_id=?", (cost_model_id,)
        ).fetchone()
        if row is None:
            raise KeyError(cost_model_id)
        value = dict(row)
        value["weights"] = json.loads(value.pop("weights_json"))
        return value

    # 按保存记录还原 CostModel，供明确指定成本语义的评测使用。
    def model(self, cost_model_id: str) -> CostModel:
        value = self.get(cost_model_id)
        return CostModel(
            value["cost_model_id"],
            int(value["version"]),
            {k: float(v) for k, v in value["weights"].items()},
            value["description"],
        )

    # 返回当前目录/仓储的可见条目；排序和过滤只生成投影，不授予执行权。
    def list(self) -> list[dict]:
        return [
            {**dict(row), "weights": json.loads(row["weights_json"])}
            for row in self.store.db.execute("SELECT * FROM cost_models ORDER BY rowid")
        ]
