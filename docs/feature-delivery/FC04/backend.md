# FC04-N1 经营提醒领域

task_id=FC04-N1，依据原始FC04完整工单、当前PRD迭代节、完整FR-02/BR-02/AC-02、第5.3/10.5/12.3节与共通规则。唯一状态由N3维护feature-delivery.json，当前仅FC04；20项尚无组合验收结果。接管62822f8，原五项未提交工作保留。当前领域与FC07候选56f292f一致，既有Cron、任务/承诺提醒、OwnerPlans及本人通知设置直接复用。采用S008；已检索T17、本人设置、FC07主记录与当前领域代码。

新增经营提醒采用明确SIMULATED的FC04-ALERT-1正式输入，独立来源/事件/观察记录保存，原selection/1保持。毛利数值由当前获准明细及明确恢复生成规则计算；跨职责不足、可信程度和处理人来自带作者/版本的生成定义，不从职位推断。输入不签发本人授权。规则保存、校验、启用分开，维护只能启用工单批准的固定演示参数；本人自定义关注独立确认。

唯一ControlStore.dispatch_due_in_transaction接收经营提醒判断，不新增Cron或执行者。联合核查影响/持续/可信/处理人与参与条件；汇总、即时、合并、冷却、免打扰、恢复及暂缓到期分别保存记录。源事件、任务、提醒、通知中心与系统投递分别表达。本人知晓/暂缓/会议关联/交办/关闭经当前范围、来源、版本、CAS、明确确认与原回执执行，不注册为模型工具。

新接口和准确Schema在本记录维护；公共Command/Page、本人页面、桌面通知及实际SDK由N2/N3接收。必要验证仅使用正常API、获准输入与独立.work SQLite，不修改用户预览、进程或数据；外部SIMULATED_FIRST，STT暂停，视觉未执行。

## 正式接口与字段

规范为specs/business-alert.schema.json 1.0.0，生成定义为business-alert-input.json / FC04-ALERT-1 / seed20261024。新模块boss_alert_policy.py、boss_alert_rules.py、boss_alert_dispatch.py及boss_business_alerts.py共同接收；既有controls、business、boss_scheduler_config与boss_owner_authorizations采用必要增量。公共入口须延迟导入领域API，在原Command事务之前委派，不从已有写入事务重新开启连接。

| 接口 | 输入、身份与结果 |
|---|---|
| BusinessAlertRulesAPI.read(role) | 本人与维护读取规则目录；维护只见获准定义及自己草稿/有效规则，不能看到本人自定义正文 |
| BusinessAlertRulesAPI.execute(role,action,payload) | action=save/validate/activate/disable。save使用RuleSave；validate/disable使用RuleVersion；activate使用RuleActivate。本人动作前缀boss.alert.rule.；维护前缀boss.simulation.alert.rule.。本人自定义启用与停用分别签发确认，维护仅允许固定演示规则且不能替代本人草稿/有效版本 |
| BusinessAlertInputAPI.load(MAINTAINER,payload) | 动作boss.simulation.alert.load；严格Load输入client_request_id/expected_version/mode/definition_version/seed/frame。frame为MARGIN_DROP/RESOURCE_SHORTAGE/PROGRESS/RECOVERY/LOW_CONFIDENCE/MISSING_HANDLER/CANCELED。事件编号由服务端给出，拒绝客户端主体、数值及授权；LoadResult返回event/source编号版本及明确模拟属性 |
| BusinessAlertsAPI.read(BOSS,event_id=None) | Read={source_type,business_clock,items,coverage_state,missing_sources,execution_owner}；可读取列表或准确事件；只读，不调用调度或产生本人决定 |
| BusinessAlertsAPI.project_in_transaction(BOSS,db,event_id=None) | 同一正式Read投影，供公共Workspace/Page在已有只读事务接收；不建立第二份事件或快照 |
| BusinessAlertsAPI.execute(BOSS,action,payload) | 动作前缀boss.alert.，action=ack/snooze/close/meeting.link/assignment.create；当前本人确认摘要、事件及提醒CAS共同核查，返回ActionResult |
| 三类API的receipt | Rules.receipt(role,action,client_request_id)、Input.receipt(MAINTAINER,client_request_id)、Alerts.receipt(BOSS,action,client_request_id)，只查询原编号。RECORDED或NOT_FOUND_IN_CURRENT_STORE；未知不表示未执行，不自动重放 |

View包含event_id/event_version/episode/state、facts/observed_at/data_as_of、adoption_state、sources/documents、evaluation、business_rule/rule_state、technical_rule_version/owner_notice_version、reminder/reminder_version、notification/summary、existing_measures、meeting_reference、review_sha256、missing_fields、dispatch_history/recovery_history/actions/meeting_links/assignment_references。facts包含实际BASE/CURRENT毛利率、变化百分点、比较期间、单位、影响、可信标记、处理人及本人参与条件/理由；影响金额未知保持null。data_as_of及facts.metric_data_as_of采用获准CURRENT期间原始终点2026-10-10T23:59:59+08:00，observed_at单独保存每次业务观察时间；新版本和读取时间不改变原始资料截至时间。可信标记属于明确演示资料条件，不代表真实模型置信度或真实企业资料质量。既有任务、计划与提醒措施按实际记录读取。

Decision共同输入client_request_id、event_id、event_version、expected_version（当前reminder_version）、review_sha256。snooze增加until，meeting.link增加meeting_id/meeting_version，assignment.create增加purpose/coordinator_id/due_at/timezone/evidence_requirements。身份、来源、关联事件、授权和执行空间由服务端提供；额外confirmed等字段拒绝。ActionResult保留event/version、提醒新version、action、authorization_id、state/until，会议返回准确关联编号版本，交办返回task_id/task_version/task_status及独立创建授权。会议关联不安排会议或发送消息；交办创建OPEN，发送继续现有独立确认。每个提醒episode最多关联一个任务，同一事件后续恢复再发生可以独立确认新任务；会议关联保留事项与会议两侧版本。

## 判断、来源与保存

经营提醒通过原ControlStore.dispatch_due_in_transaction唯一执行，A13手动模拟执行也只调用同一函数。技术规则、经营规则与本人通知设置共同限制通知；只有本人当前有效启用的重要设置与两层允许条件同时满足，才可越过免打扰。有效重要升级可以依明确规则越过冷却，同一持续事件合并并保存引用变化，不重复产生通知中心条目；每次实际内部投递单独保存。原任务/承诺期限提醒继续兼容并保存dispatch_history。

默认规则读取工单1.5个百分点、持续/恢复各600秒、观察间隔300秒、冷却1800秒、Asia/Shanghai免打扰22至7。一般进展保存汇总；缺少可信/完整资料或当前处理人时保留UNKNOWN及缺少条件。持续时间仅由同范围、同依据的连续正式观察证明，缺少中间观察不外推。恢复独立记录，notify_recovery控制是否通知；源事件与任务状态不因恢复、关闭或知晓互相改变。暂缓到期重新检查当前来源、规则、计划、本人设置与授权，撤销后持续停止，原决定保留。

输入原文含生成作者、版本/seed、当前业务观察时间、真实接收/发布时间、来源范围及有效期、原始获准明细和恢复计算说明；恢复按BASE成本率与CURRENT收入计算模拟成本，未知数值不补零。独立document及document_history/FTS与event/business_alert_observation在同一事务保存，初始snapshot校验和保持。当前引用核查访问范围、版本、完整摘要和有效性；失效资料不返回原文及派生facts。本人关闭仍可停止当前提醒。会议来源、双方版本与本人确认摘要同时核查。

生成报告另保存input_source_refs/input_source_fingerprints与initial_snapshot_sha256。共同Store.assignment_sources、external_adoption、检索、晨间和SI13同时检查原始财务依据；原始依据失效不能通过生成报告继续读取缓存明细。SI13沿用既有CHANGED/NEEDS_REVIEW表示依赖需要复核，不新增其公开枚举。正式显式重新载入可以更新已过期但未撤销的旧报告版本，来源撤销不会被载入恢复。

新增business_alert_rule/draft/revision、business_alert_observation/tracking/summary/recovery/delivery/action、dispatch_history、notification_revision、reminder_revision及两类关联记录复用objects，无DDL迁移；没有实际旧记录时不补造历史。输入来源、本人授权、任务和发件箱沿用既有职责。SQLite结构与历史数据保持，备份使用原生backup/integrity_check；代码恢复仅文件编辑。

## 公共接收条件

N3在notifications投影中以business_alerts接收正式Read；现有只读事务使用project_in_transaction。同类原始event、通知、派发和来源正文不能继续从通用objects直接下发：generated_by=BUSINESS_ALERT_INPUT的事件使用本投影，来源撤销/权限变化后facts和失效原文不再采用。维护只接收安全元信息和规则/输入回执，不调用本人读取API。N2从business_alerts采用实际evaluation及规则/来源引用，记录编号/版本/摘要，不能把documents、facts、本人理由写入普通技术记录；不注册调度、规则启用或本人决定工具。

N3登记新动作、规则目录/输入维护、原回执及当前F02/通知详情；新经营提醒不可调用旧boss.reminder入口跳过review_sha256。原生Client对全部新写入保持不自动重发，未知只查原编号。本人来源/内容变化后清除旧确认。系统通知只使用应用名称、事项类别和返回入口，真实宿主权限/回调单独记录；内部DELIVERED仅表示通知中心保存，默认system_notification_state=NOT_REQUESTED，不能据此声明系统或外部送达。桌面权限、点击再认证、公共异步、连续体验与制品由N3接收。

当前为领域阶段，完整20项及用户验收尚未登记通过；N1不切换FC06。准确版本及限定证据在本记录维护，原五项未提交文件保持。

## 领域验证与交付

2026-10-24，限定检查81项全部通过，pytest用时5.51秒；原始结果为本目录domain-check.xml。FC04领域29项、原记忆/通知、调度配置、OwnerPlans、任务期限提醒，以及本人通知和SI13的相关消费者共同检查。处理人有效日期按照规则或本人业务IANA时区计算；UTC跨越上海日期的检查同时覆盖提醒判断与交办负责人采用。

执行命令：

```bash
validation/.venv/bin/python -m pytest -q app/tests/test_fc04_domain.py app/tests/test_boss_memory_notifications.py app/tests/test_boss_scheduler_config.py app/tests/test_boss_owner_plans.py app/tests/test_boss_task_reminders.py app/tests/test_boss_owner_preferences.py::test_confirmed_notice_pause_reaches_real_canonical_dispatcher app/tests/test_boss_owner_preferences.py::test_confirmed_notice_quiet_in_iana_timezone_and_tech_only_stricter app/tests/test_boss_owner_preferences.py::test_technical_pause_always_stronger_than_owner_preference 'app/tests/test_boss_simulation_api.py::test_each_interface_reads_current_approved_data_and_independent_metadata[SI13]' --basetemp=.work/pytest-fc04-domain-final-timezone -p no:cacheprovider --junitxml=docs/feature-delivery/FC04/domain-check.xml --tb=short
```

检查通过正常维护、本人与获准生成接口创建独立SQLite数据，不修改当前用户数据库。实际CronService调用同一调度函数，停用状态保存后由新CronService读取；独立Python进程调用check_fc04_restart.py，对关闭提醒进行SQLite原生backup，逐项比对spaces/objects/idempotency/audit/knowledge并运行integrity_check；备份目标必须尚未存在。新ControlStore读取备份后保持CLOSED，调度返回BOSS_CLOSED，authorization/notification/task/outbox合计零新增。并发、原回执、来源撤销、恢复与复发、本人重要通知设置撤销、OwnerPlans停止及取消分别通过。git diff --check通过。

接收文件包含四个经营提醒模块、两份JSON规范、领域检查与独立进程脚本；公共依赖增量位于controls.py、business.py、boss_owner_authorizations.py、boss_scheduler_config.py、boss_supply_quality.py、boss_morning_projection.py及boss_simulation_api.py。规范同步至openapi.yaml、data-dictionary.json、LLD-data.md及开发索引。N3接收公共文件时应保留其他角色当前内容，采用相关增量。

领域阶段状态为MODULE_CHECKS_PASSED；公共Command/Page/Client、C16系统通知、完整20项组合检查和用户共同验收仍待N3接收与记录。此结果不改变feature-delivery.json，不启动FC06。
