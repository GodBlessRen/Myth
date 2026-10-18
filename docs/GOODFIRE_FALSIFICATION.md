# Goodfire 启发：可证伪的 Context 因子评测

## 已实现范围

沿用 `task_benchmark.py` 的四臂 Context 实验；没有新增 Runtime 状态所有者、
模型神经元访问器、数据库表、自动 Promote 逻辑或第二套 Evals。

四臂分别为 baseline、causal only、relevance only、full。针对同一
`(case_id, repeat)`，在四臂均有明确布尔型独立 Oracle、机制配置报告一致且无重复记录时，
额外计算：

- **四个方向的质量对照**：Causal 在有/无 Relevance 时的 PASS 差，
  Relevance 在有/无 Causal 时的 PASS 差；负值构成“启用机制不退化”假设的反例。
- **交互项**：`full - causal - relevance + baseline`，是二值 Oracle 的描述性差分，
  不是平均因果处理效应。
- **成本交互项**：只对四臂都实际报告且非负的同名成本 meter 计算；
  缺测仍为 `null`。
- **Case 去重**：重复试次可增加反例次数，但不能增加独立 Case 数。
- **未知与不可识别性**：缺少 Oracle/开关校验或出现重复单元时输出
  `UNVERIFIED`。`material_intervention_verified=null` 与
  `causal_attribution=false` 明示尚未验证实际模型可见信息变化或因果归因。

此报告属于诊断信息；Context 原有的完整分母、供应商实测、统计验证、
held-out 复核、人工 Promote 仍是唯一准入通道。

## 为什么不直接引入所谓 Neural Microscope？

Goodfire 研究的是权重、激活与神经元机制；Myth 核心是 Agent 外部
Runtime 的权限、状态与任务执行。对没有权重/激活访问权的远程模型，
不能借用术语冒充模型内部因果证据。

## 下一步验证边界

将每次模型请求的**实际可见内容规范化摘要**与同条件试次关联，
检查开关是否产生了真实的材料差异；只记录哈希与选择来源身份，避免复制用户私密内容。
之后才能将 `material_intervention_verified` 从未知升级为具备明确比较条件的报告。
仍需预注册假设、随机化或平衡试次顺序、独立题集和真实 Provider 复验。

运行新增局部用例：
`python -m unittest discover -s tests -p 'test_context_falsification.py' -v`

本文描述代码合同，不声明远程模型收益已被实测。
