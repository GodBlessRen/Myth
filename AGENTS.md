# Myth 开发规范

目标：把可持续推进真实工作的本地 Agent Runtime 做扎实。最高约束是关注点分离、解耦、原子性、六边形架构、安全和简体中文指导性注释；具体规则见[架构宪法](docs/ARCHITECTURE_CONSTITUTION.md)。

## 修改前先定位

1. 阅读[源码地图](docs/CODE_GUIDE.md)，确定状态所有者、调用方和提交边界。
2. 用源码引用和实际失败说明改动价值。文件很长不等于需要重写，文件很短不等于职责单一。
3. 先固定输入、故障窗口和期望，再修改关键状态路径；恢复功能不能随兼容代码一起误删。
4. 新增 Port、Strategy 或依赖必须解决当前使用场景。组件登记只列真实接入的实现。

## 实现约束

- 内圈依赖领域合同与 Port，供应商、数据库、网络、文件和 UI 留在适配器或装配根。
- 状态聚合由所属仓储写入；跨聚合准入由明确协调入口使用同连接短事务提交。
- 身份核对、序号分配、读改写和结果消费在提交事务内完成。业务事务不得装配仓储或执行外部 I/O。
- Ticket 是开始授权，Receipt 是效果事实，Verification 是独立验收，三者不能相互代替。
- 已派发而效果不明进入 UNKNOWN，先核对。Stop 停止未来调度，晚到真实结果仍记录。
- State 是真相，Context、摘要、索引、观测是投影。压缩不制造进度，向量命中回权威源核对。
- 凭据只进系统安全凭据库；不得进入 SQLite、事件、Artifact、日志或 Web JSON。
- 第三栏 Runtime Observatory 是产品合同；心跳、持久进度、完成证据各自显示。
- Evaluation 使用固定完整分母，partial 不具发布资格；Evolution 必须显式 Promote。
- 文件、类、函数、字段和关键步骤写准确中文说明，解释协作、单位、事务、幂等与恢复；同步删除失效注释。

## 淘汰与格式

当前为无人使用的开发阶段：不保留无调用者的旧别名、旧库迁移、占位实现和版本降级路径。

每次更新检查淘汰物：迁移当前调用者 → 放入 `.trash/<日期>/<原路径>` → 记录理由 → 核对生产引用和发布包。垃圾站只作开发留档，不能作为 import、运行输入或发布内容。历史测试若仍证明当前不变量则继续保留。

数据库只接受 `store.SCHEMA_VERSION` 指定的当前格式。格式改变时更新身份及回归，旧实验库保留原件，使用新 `--root`，不自动清空或迁移。

## 验证与交付

```bash
python -m compileall -q src tests scripts
python scripts/check_annotations.py
python scripts/audit_secret_patterns.py
python -m unittest discover -s tests -v
node --check src/myth/webui/app.js
node --check src/myth/webui/inspector.js
node --check src/myth/webui/goals.js
node --check src/myth/webui/reconnect.js
node --check src/myth/webui/statistics.js
node --check src/myth/webui/theme.js
node --test tests/test_observatory_ui.cjs tests/test_reconnect_ui.cjs tests/test_statistics_ui.cjs tests/test_workspace_interactions_ui.cjs
python -m build
python scripts/validate_release.py dist
```

关键路径补对应故障回归：准入/恢复检查 UNKNOWN、崩溃、租约和同 Run 接续；Goal 检查跨 Session/restart；调度检查争抢与提交后退出；认证检查协议、凭据轮换与泄漏；Context 检查来源、窗口和用量；验收检查对象摘要与完整评测。

安装 wheel 后运行 `scripts/validate_package.py --package-dir <安装目录>`，核对真实导入、HTTP 资源和基本 API。

README 做导航，CHANGELOG 记历史，架构描述当前事实，ROADMAP 保留下一步。测试结论写清输入、版本和测量范围，不把替身通过称为真实模型可靠。宪法也可按证据修订，但不能削弱上述事实与权限边界。
