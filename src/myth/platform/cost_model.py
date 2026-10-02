"""Versioned, explicit cost semantics for evaluation and Information Gain."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Mapping

from ..domain import canonical_json


SCHEMA = """
CREATE TABLE IF NOT EXISTS cost_models(
    cost_model_id TEXT PRIMARY KEY,
    version INTEGER NOT NULL CHECK(version > 0),
    weights_json TEXT NOT NULL,
    description TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


@dataclass(frozen=True)
class CostModel:
    cost_model_id: str
    version: int
    weights: dict[str, float]
    description: str = ""

    def __post_init__(self):
        if not self.cost_model_id.strip() or self.version < 1:
            raise ValueError("cost model id/version are required")
        for meter,weight in self.weights.items():
            if not str(meter).strip() or not isinstance(weight,(int,float)) or weight < 0:
                raise ValueError("cost weights require non-empty meters and non-negative numbers")

    def weighted_cost(self, delta: Mapping[str,float]) -> float:
        return sum(
            float(weight)*max(0.0,float(delta.get(meter,0.0)))
            for meter,weight in self.weights.items()
        )


class SqliteCostModelRegistry:
    def __init__(self,runtime):
        self.store=runtime.store
        self.store.db.executescript(SCHEMA)

    def put(self, model: CostModel) -> dict:
        with self.store.tx() as db:
            existing=db.execute(
                "SELECT version,weights_json,description FROM cost_models WHERE cost_model_id=?",
                (model.cost_model_id,),
            ).fetchone()
            payload=canonical_json(model.weights)
            if existing:
                if (
                    int(existing["version"])!=model.version
                    or existing["weights_json"]!=payload
                    or existing["description"]!=model.description
                ):
                    raise ValueError("cost_model_id is immutable; create a new version/id")
            else:
                db.execute(
                    "INSERT INTO cost_models(cost_model_id,version,weights_json,description) VALUES (?,?,?,?)",
                    (model.cost_model_id,model.version,payload,model.description),
                )
        return self.get(model.cost_model_id)

    def get(self,cost_model_id: str) -> dict:
        row=self.store.db.execute(
            "SELECT * FROM cost_models WHERE cost_model_id=?",(cost_model_id,)
        ).fetchone()
        if row is None:raise KeyError(cost_model_id)
        value=dict(row);value["weights"]=json.loads(value.pop("weights_json"))
        return value

    def model(self,cost_model_id: str) -> CostModel:
        value=self.get(cost_model_id)
        return CostModel(
            value["cost_model_id"],int(value["version"]),
            {k:float(v) for k,v in value["weights"].items()},
            value["description"],
        )

    def list(self) -> list[dict]:
        return [
            {**dict(row),"weights":json.loads(row["weights_json"])}
            for row in self.store.db.execute("SELECT * FROM cost_models ORDER BY rowid")
        ]
