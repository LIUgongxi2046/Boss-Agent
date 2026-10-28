# Boss-Agent 后端设计

版本1.6.0；T06/A06；2026-10-23；引用LLD-data1.6.0、PRD V1.2.0和HLD1.0.0。字段、operationId、角色、输入/结果、错误与事件作为W2/W3确定接收版本；A06保持NOT_RUN，完整边界、独立语义与公开集成仍需验证。

2026-10-28核查：doc_id=DOC-LLD-BACKEND，维护责任为当前主执行者。当前公共入口、账号、经营查询、会话绑定和错误处理采用[集成指南](开发者集成指南.md)及[经营接口扩展](../specs/product-business-overview.openapi.yaml)，来源为`9cd9888490521242def326f475c93823a68ec95b`及未提交修改。十四项模拟接口已有当前仿真资料，实际覆盖见[仿真任务](development/SIMULATION-20261028.md)。本文保留完整后端设计，2026-10-23接收说明只适用于其版本；全部动作Schema及完整业务集成仍为NEEDS_REVIEW，不通过文档同步改变A06。

## 服务、身份与事务

FC07公共扩展采用specs/product-assignment.openapi.yaml。BossCommandAPI对boss.assignment.extension.decide完成角色检查后延迟导入AssignmentExtensionAPI，在同一正式领域事务完成独立本人授权、CAS、决定和原回执。BossPageAPI严格读取assignment-extensions，operation-status委派原动作和编号，读取不执行决定。任务投影增加source_versions、结果证据重新提交标记、反馈证据版本/状态与historical_only、本人承诺的当前来源及期限/修订历史；模拟消息正文和授权编号仅提供给BOSS。

RoleChannel在当前认证和有效连接内执行boss.assignment.prepare；HTTP assignment-preparation仅读取原请求。ProductAssignment从实际会话、当前task/version及来源摘要建立可信读取范围，assignment_public_request仅记录查询准备及运行关联；正式任务状态继续由ControlStore维护。来源或任务变化返回HISTORICAL_REQUIRES_REQUERY并隐藏旧准备内容。所有公开参数拒绝额外字段，客户端不能传入owner、namespace或授权。

RoleChannel 从服务端认证确定 BOSS/MAINTAINER；HTTP 查询和 WebSocket 写入复用同一身份。联系人、正文、模型、payload.role/owner_id 不提供身份。前端只能提交动作参数；owner、namespace、数据集和有效资料版本由服务端验证。MAINTAINER 可以配置技术参数和提供获准模拟反馈，不能完成、批准、发送或读取私人正文。

`BossCommandAPI.execute` 是已有写入入口；`BossPageAPI.serve` 是已有读取入口。所有动作按当前 `ACTION_ROLES` 验证角色。当前业务空间 `ui-check` 的来源为获准 selection 数据集；不能冒充生产企业资料。SQLite 保存正式状态，聊天和工具文本只引用对象 ID。

写入事务顺序为 BEGIN IMMEDIATE → active space → 原请求查重 → 当前对象/版本/来源/授权检查 → 业务对象和授权写入 → 幂等回执 → 最小审计 → COMMIT。异常使事务不提交；模型后续失败不删除已经提交的结果。

`client_request_id` 为8—128位 ASCII 字母数字及 `-_.`；namespace+action+key 唯一。digest 绑定动作与全部业务参数。同键同内容返回原结果，同键不同内容409。CAS 使用当前 version 字符串。读取回执不重放动作；没有回执表示当前存储尚未发现，不能推断原动作未发生。

## 传输协议

现有读取使用 `/api/boss/ui/*` HTTP Bearer。现有写入使用已认证 nanobot WebSocket：`type=webui_request, request_id, action, payload`；响应 `event=webui_response, request_id, ok, result|error`。业务幂等 ID 在 payload 内，与传输 request_id 分开。重新连接产生新传输请求时仍保留原 client_request_id。此协议没有 Last-Event-ID 或 SSE 心跳承诺。

OpenAPI定义全部当前HTTP读取、58项基线WebSocket命令、10项W1领域动作及5个工具；每项命令绑定角色、输入Schema、处理位置和必需回执字段。workspace路径参数及BOSS/MAINTAINER投影白名单分别定义，原请求回执采用原动作相同角色。十四类模拟接口逐项给出输入、结果、实体、读取位置、可用状态和缺少来源；SimulationAPI已实现当前获准资料的统一读取及独立技术检查，公共路由、AD02和Agent采用保持PENDING_W3_W2。

Runtime提交使用`type=message,chat_id,content`，当前会话取消使用同一入口和`content=/stop`，停止该会话活动及队列中的后续步骤。线程读取使用既有Runtime入口。独立T02验证服务的健康、空间、工具与配置路径在`x-validation-service.routes`分别定义角色；这些路径用于验证，不增加产品业务入口。

## W1 新增接口接收规范

| operationId | 身份与参数 | 调用和结果 | 使用方 |
|---|---|---|---|
| ownerPlansRead | BOSS，无查询参数 | `OwnerPlansAPI(store).read(role)`：plans/events/results/dispatches/technical_schedule | N09、W3 |
| ownerPlanSave | BOSS，client_request_id、plan_id（新建为空字符串）、expected_version、purpose、event_ids、timezone、not_before | `execute(role,"save",payload)`；保存 ACTIVE 或保留 PAUSED；事件范围唯一绑定 | N09、W3 |
| ownerPlanPause | BOSS，client_request_id、plan_id、expected_version | ACTIVE→PAUSED，返回新 version | N09、W3 |
| ownerPlanResume | 同上 | PAUSED→ACTIVE，重新保存本人确认授权 | N09、W3 |
| ownerPlanCancel | 同上 | ACTIVE/PAUSED→CANCELED；终态不恢复；历史保持 | N09、W3 |
| todayRead | BOSS，无查询参数 | `TodayAPI(store).read(role)`：items/category/reason/source_refs/snapshot_sha256/order_version | F01、W3 |
| todayReorder | BOSS，client_request_id、expected_version、snapshot_sha256、item_ids | `TodayAPI(store).reorder(role,payload)`；核对完整当前集合，返回新 version 和 authorization_id | F01、W3 |
| meetingArrangementRead | BOSS，无查询参数 | `MeetingAPI(store).read(role)`；当前会议、独立草稿、引用范围、核查状态与历史版本 | F04、W3 |
| meetingDraftSave | BOSS，meeting_id、meeting_version、expected_version（草稿）、purpose、完整时间/时区、preparation_due_at、participant_ids、source_refs及client_request_id | `execute(role,"draft.save",payload)`；保存草稿和影响摘要，当前安排保持 | F04、W3 |
| meetingConfirm | BOSS，meeting_id、meeting_version、draft_version、review_sha256、acknowledge_conflict及client_request_id | `execute(role,"confirm",payload)`；核查完整上下文与来源后产生当前SCHEDULED版本 | F04、W3 |
| meetingCancel / meetingHeld | BOSS，meeting_id、expected_version（会议）、reason及client_request_id | `execute(role,"cancel"或"held",payload)`；独立本人确认；终态不恢复，举行需开始时间已经到达 | F04、W3 |
| assignmentSourcesRead | BOSS，task_id | `AssignmentSourcesAPI.read(role,task_id)`；当前交办、许可来源、已知绑定历史及结果证据复核状态 | F06、W3 |
| assignmentSourcesConfirm | BOSS，client_request_id、task_id、task_version、review_sha256、reason | `AssignmentSourcesAPI.execute(role,payload)`；独立确认当前来源与递增任务版本，业务状态和发送结果保持 | F06、W3 |

四项会议动作与读取路径在`specs/openapi.yaml`标记PENDING_W3。F01/N09此前版本已由W3接入，记录见W3的T11；本目录当前1.2.0增量仍需相同集成版本复验。不得把领域检查当作公共入口或设备验收。

会议完整时间通过IANA时区和UTC时差校验，结束须晚于开始，持续时间上限31天；准备期限可空，提供时须位于当前业务时间与会议开始之间。参会对象使用唯一有效联系人标识，材料引用校验当前许可、撤销和版本。私人占用及行程缓冲产生冲突条件，确认时重算摘要并要求本人明确知晓。保存草稿不签发安排授权；确认、取消与举行分别保存本人授权。meeting_materials被会前材料、纪要、人员会面、行程、私人日历、今日投影和恢复读取采用；公共查询与W2上下文接入要求见T14。

计划只控制已有获准事件的时间和范围，不创建第二个 Cron。时间条件限 Asia/Shanghai，not_before 在当前业务时间之后366天以内；执行时还检查事件期限、保存时 event_versions、本人计划状态、当前撤销状态、技术启停、规则、免打扰、暂缓和去重。`authorization_id` 是已保存计划的本人确认依据；其撤销即时停止继续采用。15分钟授权窗口用于当次确认提交，已经保存的持续计划由当前 ACTIVE 状态、绑定对象版本及未撤销确认共同控制。

`authorization_can_revoke`统一判断撤销资格。memory.confirm、owner_goals.confirm、owner_notice.confirm、owner_plan.save/resume及calendar.share的原确认窗口到期后，BOSS仍能撤销后续持续采用；状态、业务期限、归属和当前撤销记录继续检查。一次性授权到期后不能产生新动作；历史业务结果不反向改变。W3的授权列表can_revoke须采用同一函数，并使界面说明与当前规则一致。Store.context在当前读事务内调用confirmed_memory，按对象、前置版本与本人范围识别对应确认；已撤销确认不进入新上下文。

`query_metrics`和`read_evidence`采用W2来源有效性规则与W1的访问检查。当前来源和引用记录都返回实际document版本。query_source_binding与query同一事务保存，在read_evidence读取当前原文前检查owner/dataset、来源ID/版本/完整摘要及实际明细摘要。来源版本或同版本元信息变化、旧查询没有绑定时返回409要求重新查询；WITHDRAWN/EXPIRED返回410，其他非当前状态409，访问范围或类型不符403。没有向旧查询自动补充来源绑定；已经保存的交办、消息和原请求回执继续保留。

会前材料、纪要/审批、附件消息、人员会面、交通资料、会议草稿和本人承诺已在相应领域采用当前来源检查。W3还需在公共_require_current_source及直接原文、反馈、任务完成等读取位置采用相同规则，并核查全部公开投影的当前状态与历史展示。Source VALID仅表明当前获准资料可以读取，专业结论、对方接收与业务完成分别确认。

五项真实Tool在自身事务执行相同规则。新create_assignment绑定当前来源版本与完整摘要，检查负责人有效期及交办期限；send_assignment和control_decide的完成决定重新读取assignment_source_binding。纪要交办同时重验原始纪要来源。源资料变化、到期、访问范围改变或旧交办缺少绑定时禁止新动作。公共后续采用点可调用Store.require_current_assignment_sources(db,namespace,data,task)，必须保留本次事务和原请求查重顺序。

Store.invoke的新写入检查授权的owner、namespace、BOSS身份及签发者、action、target_id、content_version、完整参数、revoked及valid_from/valid_until。一次创建授权只产生一个task，一次发送授权只产生一个outbox；不同请求编号并发执行时在BEGIN IMMEDIATE内检查既有结果。相同编号及内容始终读取原回执，授权撤销后继续可读。独立完成/延期控制复用相同身份与时间检查，决定的content_version对应task_version。read_assignment按原始read_output字段投影，服务端来源和纪要扩展字段继续保存。

control_feedback在同一事务保存每项结果证据的实际版本、完整摘要及当前有效状态。普通反馈拒绝非当前资料；CANCELED的历史反馈允许失效资料但继续检查来源类型、标识和本人范围，历史标记不变。control_decide的完成动作逐项核对提交时证据，包含不属于原始交办来源的额外证据；变化或旧记录缺少绑定时409，不提交新授权和完成状态。重新提交结果保存独立反馈与当前绑定，原反馈保持。W3公共反馈入口需允许已发送且RESULT_SUBMITTED任务按当前CAS提交新的结果，原请求幂等、取消历史和COMPLETED_CONFIRMED拒绝继续有效。

来源复核仅允许BOSS，当前产品空间为ui-check，当前采用状态由AssignmentSourcesAPI统一读取。read自行开启只读事务，project_in_transaction(role,db,task_id)用于公共页面已持有的同一事务。绑定缺少或资料变化时，界面提供当前获准片段及原文入口；未获准、撤销、过期等资料不返回片段。执行来源确认前重新检查角色、当前任务版本、全部资料权限/状态与完整核查摘要，摘要包含任务、当前绑定、当前原文、业务时钟及数据集。BEGIN IMMEDIATE内归档已知绑定、保存独立assignment.sources.confirm授权、更新当前绑定和任务版本、保存回执及最小审计。来源或并发数据变化409，未认证401、越权403、未知对象404，撤销/到期资料410，输入400。终态不重新确认，原请求在后续来源撤销后继续可读；同键不同内容拒绝。

公共boss.assignment.sources.confirm须在通用事务之前委派，当前Tool范围保持。公共任务的当前来源校验使用Store.require_current_assignment_sources；任务表保留原始纪要版本，当前采用版本由binding.origin_source提供。F06来源状态可使用project_in_transaction避免重复定义。来源复核不改变旧反馈的提交时证据；result_evidence_requires_resubmission为true时仍需要负责人独立提交。发送继续独立本人授权，发送后的任务版本从当前版本递增。

当前计划未包含晨间模型生成和周期重复定义；需要 W2 提供真实 Runtime 任务能力和 W3 接入后继续完成，不登记 A17 完成。已有事件更新时保留 owner_plan_id 并检查 event_versions，不自动扩大本人范围。

今日投影按待决定、待协调、需要知晓组织当前未结束任务、本人承诺、申请、会议、事件及私人占用。相同任务事件合并；来源 ID 与版本可查。重要事项持续优先，其余采用本人次序；新事项追加当前默认顺序。当前完整日历结束时间和农业区域覆盖不足，必须显示 PARTIAL/INSUFFICIENT_EVIDENCE。

## 状态和拒绝条件

本人目标及通知设置读取由`effective_owner_goals(db,data,namespace)`和`effective_owner_notice(db,data,namespace)`在当前事务检查有效空间和完整确认绑定；namespace由服务端提供，默认值保留既有ui-check使用方。`record_runtime_goal_context_load(store,namespace)`拒绝失效空间，读取与记录采用次数均使用同一空间。唯一调度通过`owner_notification_suppression(...,namespace=ns)`读取对应本人通知规则。失效空间返回409，确认归属、签发者、动作、对象、前置版本或内容摘要不符返回403，不新增采用记录。新空间尚无确认设置时保持未确认，历史设置继续保留原空间。

交办、消息、审批、会议、资料、提醒、运行与记忆状态完整继承 PRD 第5节。现有领域方法必须区分草稿、模拟发送、外部送达、反馈提交和本人完成；没有外部通道回执时 delivery_state 不得宣称已验证。

本人计划暂停和取消不删除已经保存的任务、通知或消息。取消后迟到反馈保存为historical_only，保持任务CANCELED和已取消事件；当前领域接收已验证，公共反馈入口的状态检查与回执仍需W3接入。资料撤销、更新和申请变更使对应旧确认失效。已确定结果需查询原回执和正式对象，无自动新编号重发。

| 错误 | 状态 | 自动重试 | 恢复 |
|---|---|---|---|
| UNAUTHENTICATED |401|禁止|重新认证后读取当前状态|
| FORBIDDEN |403|禁止|核对当前身份和获准范围|
| NOT_FOUND |404|禁止|核对当前对象和空间，不泄露受限正文|
| INVALID_INPUT |400|禁止|修正输入后由本人提交|
| VERSION_OR_IDEMPOTENCY_CONFLICT |409|禁止|读取当前对象/原请求，重新确认变化|
| SOURCE_WITHDRAWN / SHARE_INACTIVE |410|禁止|停止采用已撤销资料或分享|
| BOSS_SERVICE_NOT_READY |503|禁止自动写入|核查服务后读取原请求|

领域函数在出错位置抛出 HTTPException 或输入错误；公共边界仅转换为安全响应。日志只记录身份、动作、状态、对象/授权 ID 与版本；不记录私人正文、录音、凭据或内部推理。

## 十四类模拟接口责任

### SI09/SI10 当前实施接口

当前1.8.0使用现有三个动作维护material_cost_report，记录引用当前库存及其传递来源，成本归属与明确批次一致。SI09的cost_reports按报告范围、成本口径及成本归属提供入库/实际领用的报告与基期数量、金额、计算单价和变化；期间时长不同、缺少数值、分母为零或成本归属未知时，不产生相应变化。calculate_cost_reports由同一事务的有效投影提供输入，不能凭该计算函数授予读取或执行权限。完整原料actual_cost_change继续要求完整来源；当前消费者同步接收1.8.0字段。

当前确定接收版本1.8.0，依据原始项目计划13.18；领域行为与结果Schema已验证，当前公共接入由W3接收。SupplyQualityAPI接收显式SIMULATED资料，不连接外部服务。MAINTAINER动作boss.simulation.supply_quality.import接收client_request_id、mode=SIMULATED、simulation_definition、outcome、records和error_code；SUCCESS执行完整Schema、时间、关系、CAS及来源检查后原子保存。EMPTY不删除已有事实；FAILED/TIMED_OUT保存明确的失败尝试及原回执，分别返回502/504。相同编号继续读取原结果，不自动生成新编号重试。普通审计只包含动作、类别、对象ID、版本、来源与结果元信息。

boss.simulation.supply_quality.withdraw核查当前实体版本，保存撤销状态和原文历史，并移除FTS当前条目。BOSS动作boss.supply_quality.coordinate核查当前来源与完整复核摘要，使用已有任务状态、本人授权和SQLite存储创建协调任务；不执行采购或专业业务。当前business.SPEC组合原定义和business-tools.schema.json，兼容无关联会议、空关联事件和明确注册的模拟外部来源，T02原文件保留。当前ToolRegistry继续读取同一business.SPEC。协调授权、交办、关联、原请求回执及审计在同一事务保存，授权有效期为实际时间15分钟；同一核查摘要的并发请求仅产生一个协调任务。

GET /api/boss/ui/supply-quality调用SupplyQualityAPI.read_http(role,query_string)，仅接受单项interface_id=SI09或SI10。GET /api/boss/ui/supply-quality-receipt调用receipt_http，仅接受action与client_request_id，身份必须符合原动作。维护回执读取须在通用BOSS-only限制之前分派，并保持方法内部身份检查。公共写入沿用已认证webui_request通道，命中ACTION_INPUTS时调用execute。新的公开路由、构建、依赖打包和完整页面验收由W3接收，当前领域检查不登记公共入口完成。

读取复用SI09/SI10及SI13当前来源入口，提供来源、版本、业务观察时间、失败状态、可用量/覆盖计算及批次追溯范围。维护只获得独立技术元信息。服务沿用10秒SQLite连接期限；当前模拟模式不产生网络等待，TIMED_OUT为显式模拟的外部结果，自动重试次数为零。真实外部超时、额度、调用质量和第三方投递另行验证。未知输入400、未认证401、越权403、对象不存在404、版本/摘要冲突409、失效来源410，拒绝时不产生部分业务写入。

当前业务消费者使用require_current_business_source(store,db,namespace,owner_id,source_id)，核查原文身份与有效性，以及明确外部记录的完整采用依据；状态读取使用external_adoption。会议准备、会面、行程、纪要、消息和私人日历附件已接入；催办同时检查任务完整来源绑定。Store创建的所有新交办均保存source_versions，既有交办缺少该字段时通过本人来源复核建立当前采用版本。公共原文、研究及其模型消费者需要W2/W3在相同集成版本接入，不能仅检查原文VALID。

`GET /api/boss/ui/simulation-query`为BOSS-only，调用`SimulationAPI(store).query_http(role,query_string)`；`GET /api/boss/ui/simulation-inspect`为MAINTAINER-only，调用`inspect_http`。使用当前nanobot GET读取通道，不新增业务写入动作。interface_id必需；object_ids、product_ids以重复参数组成数组，其余参数仅允许一个值。直接领域读取为query(role,payload)、inspect(role,payload)，payload为interface_id/object_ids/filters；已有事务可使用project_in_transaction。身份由RoleChannel注入，owner/namespace/dataset参数拒绝。URI查询部分最多4096字节，超过414；候选或结果超过1000项返回413，要求缩小对象范围，不截断候选后返回不完整结果。对象选择支持业务ID、存储ID或entity_type:ID；object_id保存真实业务ID，storage_id保留资源键，record_id为entity_type:业务ID。初始嵌套记录的资源键采用获准原资料ID。

当前SI07/SI08接受period_start/period_end、region_id、product_ids、legal_entity_id、customer_id、currency=CNY及source_version；期间必须完整等于已提供的BASE或CURRENT之一。SI09/SI10接受material_id、asset_owner_id、ownership_type、product_ids、legal_entity_id、customer_id、batch_id、currency及记录自身source_version，不进行单位或币种换算；技术投影在SQL内独立筛选。SI13另外接受source_version，其余接口只接受对象选择，不支持的筛选400。来源类型、访问范围、有效状态、版本、已有完整摘要逐次核查；缺少真实绑定的旧查询和交办需要复核。会议材料、会面、行程和会议草稿使用现有领域规则核查缓存上下文，当前领域核查只支持ui-check；其他空间的既有缓存正文保持不可采用并要求复核。所有Record的business_authorization_granted=false，资料正文属于不可信来源内容，不能作为系统指令或新增授权。

结果保留真实存储版本、状态、原来源时间和顶层实际read_at。data=null时继续提供当前元信息和明确缺少项；技术检查始终data=null、sources/source_refs为空。维护读取独立使用SQLite JSON投影，只选择对象标识、类别、版本与状态，原文/私人正文/缓存快照不进入维护结果。查询不创建对象、授权、审计、回执或Runtime记录，不触发模型、外部检索、消息和Cron；原有写入继续使用正式领域动作。空结果配合PARTIAL/UNAVAILABLE及缺少范围，不能推断完整业务范围没有记录。

独立控制入口的private_calendar读取同一namespace内的当前对象；尚未保存当前对象时采用获准initial安排。当前对象的calendar_id与owner_id必须符合本人范围，DELETED返回410。该读取不创建对象或恢复正文。SQLite原生备份恢复保持当前状态、来源绑定、本人复核历史、原请求回执和删除标记；重置创建新执行空间，既有空间继续保留历史并拒绝新动作。当前领域验证范围见T12，完整旧版本迁移与产品设备恢复继续验收。

| PRD 接口 | 当前数据/能力与完整性 |
|---|---|
| SI01 档案组织 | owner_profile 与本人设置；完整组织字段待补充 |
| SI02 联系关系 | contacts、people 会面；真实职责与资料限定获准样本 |
| SI03 日历出行 | private_calendar、calendar_share、travel、meeting/draft；会议状态与关联采用领域已验证，公共接入待完成 |
| SI04 消息邮件 | draft/send/reply 与 outbox；外部送达未验证 |
| SI05 会议资料 | brief/minutes/逐项交办；来源变化复核 |
| SI06 任务承诺 | assignment/commitment/feedback/延期/完成/取消；历史反馈领域已验证，公共接入待完成 |
| SI07 销售 BI | query_metrics/read_evidence；当前仅获准的两个十日期间明细 |
| SI08 财务应收 | 成本收入明细；现金、账龄和结算数据不足 |
| SI09 采购库存 | 显式模拟报价/合同/库存/耗用/比例/订单导入、覆盖和计划假设计算；真实服务与完整业务范围待验收 |
| SI10 生产品质 | 显式模拟批次/追溯/专业记录/客诉/事件/产能；原事件、专业状态和协调任务分别保存；真实服务与完整业务范围待验收 |
| SI11 审批 | application/decision，按材料与版本校验 |
| SI12 外部信息 | 获准原文知识；未配置真实实时检索 |
| SI13 知识资料 | document/FTS5/撤销；摄取与实际模型采用由 W2 验证 |
| SI14 通知中心 | event/reminder/dispatch/delivery；Cron 唯一来源，系统通知由 W3 验证 |

## Runtime、外部依赖和观察

Runtime保持单一nanobot AgentLoop。取消停止尚未执行步骤，已提交写入继续可查。超时、工具错误、轮数上限分别记录stop_reason。runtime-events定义回执、普通消息与工具活动、文字增量、流片段结束、turn结束、恢复、重试状态和上下文压缩事件，字段来自锁定nanobot0.3.5源码。chat_id/turn_id/stream_id与业务run_id通过服务端记录关联，没有全域sequence或SSE恢复承诺。内部reasoning事件不得进入普通业务投影，实际通道过滤由W2/W3验证。

DeepSeek 适配当前使用120秒超时、max_retries=0；没有备用模型。语音和检索的真实服务/权限、限制与费用由 W2 核查，缺少条件保持 BLOCKED。当前本机领域调用使用10秒 SQLite 锁等待；没有已测吞吐和限流阈值。发生故障保留准确错误、已执行结果及未知费用；业务服务不返回替代成功内容。

配置草稿、校验、启用、下一任务实际采用分别留证。模型/Prompt/知识由 W2 维护；本人目标和通知只能 BOSS 确认。运行关联 run_id/session_id/request_id/tool_id、namespace、数据/配置/来源/授权版本、真实时间、usage 与价格来源；缺少计费覆盖时总额 null。

运行读取接口为GET /api/boss/ui/runtime-records，operationId=runtimeRecordsRead；W2维护RuntimeRecorder和runtime_records_query，W3维护公共认证路由及A15挂载。BOSS与MAINTAINER读取相同技术元信息，正文不在该接口中。参数限provider/run_id/dataset_id/status/stop_reason、started_from/started_until、limit及成对cursor_started_at/cursor_run_id；单独run_id读取单项，组合参数执行列表。拒绝重复、未知、空参数及不合法时间范围，limit为1—100的十进制字符串，缺少时50。客户端不能指定namespace/owner或正文范围。完整输入和输出分别引用runtime-records.schema.json的RuntimeRecordsQuery和RuntimeRecordsProjection。

查询在当前空间同一只读事务中按全部记录筛选后分页，按started_at/run_id倒序；matched_count为过滤总数，next_cursor沿用相同筛选条件。单项不存在404，失效空间409，未认证401、无权限身份403，输入400。没有新业务幂等键和外部超时，因为读取不执行模型或工具；SQLite仍采用已有10秒连接期限。重读只查询已保存状态，不重发业务动作。W3当前已接入公共路由，版本化Schema与实际页面读取仍需相同集成版本复验；记录存在或配置版本相同不能替代模型行为质量验收。

## 验证与剩余交付

领域检查与全部当前 app/tests 已实际执行，见 T17/T18 主记录。完整公开路径接入、所有现有 action 的独立请求/响应 Schema、全部14类接口、Runtime 流事件、取消/超时模型验证、并发撤销、旧库恢复、设备通知与完整持续计划尚未验收。OpenAPI/事件结构检查仅证明格式；T06/A06 继续保留未验收状态。
