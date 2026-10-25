# MENU-F01-N1 今日工作领域

task_id=MENU-F01-N1；decision_id=D-MENU-DELIVERY-20261024；执行范围为MENU-F01当前完整18项中的领域责任。正式状态读取原始项目specs/feature-delivery.json，由N3唯一维护。当前核查基点9c465de736a69aee4bb30380e9e6f67115d774b2，原五项未提交内容保持。文档有效性CURRENT，2026-10-24核查；菜单级业务、结构、交互、可启动交付与用户验收分别登记。

## 输入与检索

完整读取原始PRD当前决定、菜单总计划、menu-plan.json、F01完整工单、完整产品PRD第8.1节FR-01/BR-01/AC-01-S/E及共同E01—E06、BR-C02；读取原v6 F01页面、页面配置F01、原始提示词与Token。HLD和LLD采用当前本地SQLite、服务端身份、同一Runtime及唯一调度职责，当前决定覆盖旧MVP限定范围。采用S008，读取任务记录、执行规则与改动检查。检索morning、FC03、FC04、本人目标/通知、任务与承诺、会议、申请、私人日历、出行及当前开发索引；记忆索引没有相关命中。

已有MorningAPI、MorningInputAPI、morning.schema.json、FC03主记录及领域检查提供逐日范围、三分类、目标采用、持久清单、详情、来源、排序/CAS与原回执。当前N3的boss_morning_projection.py与本目录一致。原五项授权消费工作未纳入本任务，不修改公共Shell、Page、Command、Client或其他角色文件。UI02与原MVP运行和资料保持；本任务检查使用已忽略.work下独立SQLite，不启动产品服务，不执行视觉功能，不访问真实外部服务，STT保持暂停。

## 当前领域与接口

MorningAPI.read/query/read_list/detail/source/reorder/receipt与MorningInputAPI保持唯一职责。Day={date,timezone}，Query增加client_request_id/session_id；服务端确定当前owner/dataset/namespace。列表绑定list_id/list_version/snapshot_sha256；详情和来源在同一只读事务核查当前对象、依据、目标、规则与业务时钟。排序只保存本人次序及独立授权，不创建交办或批准业务；未知请求只读原编号。

MENU-F01.C03—C10/C14—C17为当前领域适用范围；C11—C13提供正式清单、事项/来源与关联版本，实际Runtime、共享页面和本人确认由N2/N3接收；C01/C02/C18页面结构、输入交互、构建与运行由N3交付。其余菜单保持排队，完整18项及用户验收不由领域检查代签。

完整获准输入包括当前确认目标、未结束交办/本人承诺/申请、会议与准备期限、事件和已有措施、私人占用及确认出行。日期/IANA时区决定日界，持续待办保留实际期限及适用限制；部分来源和未知覆盖明确，不补造业务值。经营提醒采用当前正式来源与规则判断，关联记录提供同事项合并依据；原文截至与观察时间分别表达。字段、实现和必要证据随本任务当前内容维护。

## 验证与接收

Given当前获准资料和实际领域API；When本人查询、选择同版本事项、重排、重新读取，或来源/规则/权限/关联版本变化；Then完整范围可核查、排序与当前风险一致、同事项合并，未知原编号恢复只读，查询不改变业务状态。当前领域阶段MODULE_CHECKS_PASSED，不登记完整菜单完成。

### 正式字段与采用路径

Schema为morning.schema.json 1.1.0，接口签名、Query/Reorder输入、动作名与原回执保持。新增输出字段允许既有保存清单缺少；当前查询和预览均产生完整新增字段，历史失效内容保持隐藏。

| 字段 | 数据来源与服务端语义 | N2/N3采用要求 |
|---|---|---|
| View.input_coverage | 八类获准输入；kind/state/provided_count/included_count/excluded_count/reported_total/scope。任务包含历史承诺；目标只计当前适用确认内容。state=CONFIRMED/NOT_SET/PARTIAL/NO_RECORDS_IN_PROVIDED_SCOPE/NEEDS_REVIEW，完整reported_total保持null | 显示当前提供数量、当前纳入数量及范围；零条已读取记录不表示完整范围没有事项，不能取消missing_sources |
| View.category_counts | 当前合并后的items按DECIDE/COORDINATE/INFORM计数 | 与同一View的分类和列表一起采用；失效历史为null |
| source_statuses[].data_as_of | finance-note采用获准CURRENT期间终点，FC04来源采用正式metric_data_as_of；其他资料只采用实际提供值。observed_at和published_at保持原始语义 | 不使用read_at或新观察时间补充来源截至。全部已采用来源当前且截至均已知时，View.data_as_of为最早截至；存在未知时为null |
| Item.risk_evaluations | 当前FC04经营规则版本、事件版本、rule_state及原evaluation.phase/reason/duration_seconds/condition_since；UNKNOWN、停用或撤销后不提升排序 | 直接呈现当前判断及版本，不根据impact或技术重要开关自行认定即时风险 |
| Item.source_refs/existing_measures | 通过任务related_event_ids及已有明确关联合并经营事件与任务；去重后保留事件/文档版本，任务、计划和提醒分别保留真实状态 | 同一事项只显示一项；详情继续调用同一清单/事项，不能把当前来源替换为较早版本。已有措施需要复核时只提供元信息，不附失效任务正文 |
| Item.related_meetings | 明确对象关联、原始历史承诺关系或同版本notification_meeting_link；保留meeting编号/版本及其当前资料引用 | 可用关联会议入口采用该数组；没有合法当前关联时明确说明。target_id继续保留原有导航语义，不单凭非空target_id推断当前会议材料有效 |
| Item.timezone/location | 当前对象实际时区与本人获准地点；出行使用已确认current及实际缓冲区间 | 选择日的timezone与对象时区分别表达；私人内容不得进入URL、普通缓存或技术记录 |
| View.order_state / ReadList.current_order.state | NOT_SET/SAVED/REVOKED；新旧Today读取共同核查当前本人授权。撤销停止采用，原记录、回执及CAS版本保留 | read_list.result保留当时清单版本；当前次序采用current_order.item_ids/state，重读后保留真实状态。新保存继续使用当前order_version |

实现位置：boss_morning_projection.py负责来源/分类/风险/合并/关联/覆盖与共同saved_order；boss_morning.py保持持久清单和当前重读，补充历史字段保护与当前次序状态；boss_today.py无参数接口复用同一saved_order核查；boss_owner_authorizations.py将today.reorder纳入持续设置撤销。没有DDL迁移，没有新增执行者或模型工具。字段同步至OpenAPI、data-dictionary及LLD-data；本任务没有编辑原五项内容。

### 必要检查

2026-10-24限定检查40项通过，pytest用时5.89秒；原始XML为本目录domain-check.xml。包括MENU-F01领域11项、既有FC03领域22项、新旧Today消费者3项、FC04来源传播与撤销2项、本人设置撤销2项。检查数量不表示18项菜单验收分子。

```bash
validation/.venv/bin/python -m pytest -q app/tests/test_menu_f01_domain.py app/tests/test_fc03_morning.py app/tests/test_boss_today.py app/tests/test_fc04_domain.py::test_derived_report_search_and_morning_source_stop_when_original_is_withdrawn app/tests/test_fc04_domain.py::test_revoked_snooze_and_rule_authority_stop_future_adoption app/tests/test_boss_owner_preferences.py::test_revoked_confirmation_stops_future_setting_adoption --basetemp=.work/pytest-menu-f01-domain-final -p no:cacheprovider --junitxml=docs/menu-delivery/F01/domain-check.xml --tb=short
```

工作目录固定为N1的boss-business/Boss-Agent。SQLite来自正常initialize、获准事件/申请输入、本人目标、承诺、会议、日历、出行与提醒API；没有直接替换业务对象或生成新企业事实。BDD原始检查保存在已忽略.work/menu-f01-red.xml及menu-f01-settings-red.xml，当前正式结果独立保存。SQLite trigger在回执保存位置产生实际IntegrityError，断言排序、授权和回执均未部分提交，已有清单仍可读取；检查后删除该测试trigger。check_menu_f01_restart.py在独立Python进程读取同库清单、排序和原编号回执，五张物理表摘要在读取前后相同，零业务变更。git diff --check通过。

| 检查范围 | 领域证据与接收边界 |
|---|---|
| C03/C04/C05/C07 | 正式日期/IANA/跨日与夏令时、八类输入覆盖、三分类计数、目标确认/撤销及实际风险判断通过。完整外部范围未知，不登记完整覆盖 |
| C06/C09/C10 | 事件/交办单一事项及同版本依据、实际措施、关联会议版本、私人地点、确认出行及缓冲冲突通过；原业务状态保持 |
| C08/C14 | 排序保存/CAS/撤销/原回执、新服务对象及独立进程重读通过。鼠标/键盘、重登与页面编辑保护由N3验证 |
| C15/C16/C17与E02/E03/E04/E06 | 当前来源变化、历史隐藏、匿名/维护及伪造归属拒绝、并发与幂等、未知原编号只读、实际保存失败事务保持通过。公开认证/Client及页面状态由N3接收 |
| C11/C12/C13与E01/E05 | 提供当前持久清单/详情/原文/关联版本及business_authorization_granted=false；实际Runtime、会话中断/模型失败、准备交办及本人独立确认、返回上下文由N2/N3验证 |
| C01/C02/C18 | 原v6页面和字段/状态已读取；公共页面结构、交互、响应式、构建、可启动交付由N3提供，视觉未执行，用户验收未登记 |

### N2/N3接收清单

N2继续调用正式MorningAPI和同一持久清单/事项/来源接口，工具参数不增加本人排序或业务确认。消费input_coverage、category_counts及risk_evaluations时保持缺少条件、版本和明确SIMULATED属性；技术记录只保存获准编号、版本和摘要，不保存私人地点、目标正文、完整facts或原文。当前次序使用read_list.current_order，原清单result保持查询时版本。

N3接收准确提交中的领域与Schema增量，保留公共Shell/Page/Command/Client当前内容；将1.1.0字段贯穿当前F01类型和布局。原Today无参数接口仍是兼容入口，完整MENU-F01使用显式日期/IANA的Morning接口。本人调整次序仍由实际入口明确保存，未知只查询原编号；来源、对象、规则或关联变化后重新读取当前清单。原有采购事项及其正常业务入口保持，不限制完整获准本人事项范围。

本任务当前没有等待中的领域必要输入。公共组合、实际Runtime、页面/交互/构建与完整18项仍待N2/N3接收；各角色只继续本菜单依赖满足的工作，不启动下一菜单。当前用户UI02及原MVP进程、端口、目录和数据保持。
