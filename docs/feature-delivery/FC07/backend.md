# FC07-N1 交办与承诺领域

task_id=FC07-N1。需求来源为原始项目当前PRD迭代节、iteration-plan.json和完整FC07工单，唯一执行状态由N3维护feature-delivery.json。当前状态IN_PROGRESS，用户验收未执行；不启动下一需求。接管HEAD=9fa1600，原五项未提交文件保留。

已读取当前PRD/计划/工单、完整FR-06与BR-C02、HLD信任和状态职责，检索T14、原W1交接、开发索引及任务/反馈/承诺/来源/提醒代码。controls、business、boss_self_commitments、boss_task_reminders及boss_assignment_nudge与MVP931c8dd逐文件一致；公共Command中已有的当前来源采用、结果重新提交与取消历史反馈由N3保留。采用S008，实际前置只使用获准selection/1、正式API和独立SQLite，不修改用户数据或公共入口。

正式范围：C02/C04—C10领域条件。现有任务/来源绑定、结果证据版本摘要、幂等回执、当前授权与任务提醒直接复用。当前需要补充本人承诺创建的非空来源校验、延期申请合法期限、延期批准/拒绝的单次决定及可重读旧/新期限和理由；公共接口与本人确认界面由N3接收，模型不得注册本人决定能力。

取消只终止当前任务及其提醒，不采用失效资料作为完成依据，继续保留现有来源失效后取消能力。历史承诺及历史决定原样保留，新创建必须提供当前有效来源；不补造旧记录的来源、授权或决定历史。新增对象复用objects，无DDL迁移；必要旧库验证使用SQLite backup独立副本，代码恢复只使用文件编辑。

正式输入/输出、准确提交与当前检查结果在本记录维护。全部外部SIMULATED_FIRST，STT暂停，视觉未执行；原授权消费未完成文件属于受保护工作，当前不接收或扩充该模块。

## 正式接口与接收

| 接口 | 输入/输出及当前语义 |
|---|---|
| AssignmentExtensionAPI.execute(role,payload) | BOSS-only；动作boss.assignment.extension.decide。严格DecisionInput包含client_request_id、task_id、task_version、feedback_id、decision、due_at、reason；decision为APPROVE/REJECT，批准提供有时区且更晚的due_at，拒绝显式null。理由必填且不允许空白。返回Result中的task_id/version/status、decision_id/decision/feedback_id、old_due_at/due_at、authorization_id/task_due_event |
| AssignmentExtensionAPI.read(role,task_id) | BOSS-only；返回source_type、task_id、task_version、due_at、decisions。每项决定保留申请编号、原申请理由、本人理由、申请期限、旧/新期限、前后任务版本、授权编号与决定时间 |
| AssignmentExtensionAPI.receipt(role,client_request_id) | BOSS-only；返回原动作、编号、RECORDED或NOT_FOUND_IN_CURRENT_STORE及已保存结果。原未知编号查询不产生授权或重新执行，未知结果不代表未执行 |
| 既有boss.assignment.extend | 输入保持；通过同一ControlStore写入决定和task_revision，原申请理由保留，本人理由未知时为null。已经批准或拒绝的申请不能再次决定；历史旧决定不补造 |
| 既有本人承诺创建/延期/完成/取消 | 原字段保持；新建source_refs至少一项当前有效来源/版本；延期与完成复核已有来源。撤销/过期410、换版409、非法或空来源400。历史对象可读，取消仍可用 |

新模块validation/boss_assignment_extensions.py与specs/assignment-extension.schema.json须共同包含。N3在真实已认证本人确认入口登记动作，在公共execute进入原_transaction之前延迟导入AssignmentExtensionAPI并委派；不能在BossCommandAPI模块顶部导入形成循环引用。读取决定历史和原回执同样由N3严格认证及限定task_id/原请求编号后委派。模型、维护身份和普通读取不调用此决定入口。本人授权沿用真实UI确认后的既有_authorize与_record机制；不消费模型confirmed、authorization_id或外部自签授权。

N3保留公共反馈对RESULT_SUBMITTED重新提交、CANCELED历史反馈、已发送前提及当前来源采用。任务详情采用同一task_id与feedback_id，延期请求本身不改期限；新决定返回后采用实际version刷新。N2只接收领域结果和准备范围，不注册本人的批准、拒绝、完成或取消工具。来源不可采用时允许取消与拒绝延长，不把这些停止动作解释为新内容采用。

当前正式经营事件不要求自身带owner_id，归属从现有namespace继承；显式owner_id必须一致。Store.create_assignment采用相同规则，已通过正常维护事件入口保存的event-1仍可关联创建交办。原事件与任务提醒继续分开保存。

## 实际验证与适用范围

当前领域与必要消费者56 passed，3.39秒；原始XML为本目录domain-check.xml。前置均来自ControlStore.initialize及正式BossCommandAPI/ControlStore控制入口，使用获准selection/1和独立.work SQLite，没有直接替换业务记录或补造授权。覆盖新承诺非空来源、失效后延期/完成拒绝及取消可用；延期申请合法期限、批准/拒绝、旧入口、并发单次决定、同键异内容、角色/注入字段、原回执/同库重建；最新结果才能确认完成，实际经营事件保持OPEN；催办、取消历史反馈、任务提醒、正式OpenAPI承诺消费者与晨间来源关联。

```bash
validation/.venv/bin/python -m pytest -q app/tests/test_fc07_domain.py app/tests/test_boss_self_commitments.py app/tests/test_boss_assignment_nudge.py app/tests/test_boss_late_feedback.py app/tests/test_boss_task_reminders.py app/tests/test_boss_api_spec.py::test_memory_confirm_delete_and_owner_commitments_match_declared_input app/tests/test_fc03_morning.py::test_real_commitment_event_dedup_and_current_rule_priority --basetemp=.work/pytest-fc07-domain-delivery -p no:cacheprovider --junitxml=docs/feature-delivery/FC07/domain-check.xml --tb=short
```

workdir固定为/Users/liuhaoxian/.codex/worktrees/boss-business/Boss-Agent。有效业务Red为.work/fc07-domain-red.xml的2 failed/1 passed及.work/fc07-event-source-red.xml的1 failed；当前完整限定结果使用domain-check.xml。JSON/YAML定义通过标准json/PyYAML读取，正式Schema经Draft202012Validator.check_schema和实际输入/结果验证，git diff --check通过。没有执行无变化全量、外部请求、视觉或用户预览操作；没有新增服务和端口。

改动位置为controls.py、business.py、boss_self_commitments.py及独立boss_assignment_extensions.py，正式Schema/数据字典/OpenAPI领域扩展与LLD-data保持相同字段。受影响的承诺测试前置改为正式当前来源，晨间断言保留实际document引用。开发索引只登记唯一主记录，正式状态继续由N3维护。

当前为领域阶段交付，未登记FC07完整12点通过或用户验收。N3仍需接收公共动作/读取/原回执、F06/N05明确决定与合法来源选择，保持未知写入不重放和旧响应保护；N2已有读取/准备需要按当前task/feedback/source版本采用，不能增加本人决定工具。相同集成候选的真实SDK、公共鉴权、连续页面、重登/服务重启与启动制品由对应角色验证；N1不改写这些公共模块。MVP十二项用户验收状态保持，不启动FC04。
