    # 兼容旧字符串拒绝入口；新路径通过 failures.py 产生结构化 failure。
    def reject(self, rid, step, reason):
        self.finish_observation(
            rid,
            step,
            {"error": str(reason), "observation_kind": "failure"},
        )
