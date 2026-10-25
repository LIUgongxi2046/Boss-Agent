# MENU-N03-N2 正式经营绑定消费者

task_id=MENU-N03-N2；marker=MENU-N03-N2-BOUND-CONSUMER-20261025；decision_id=D-MENU-DELIVERY-20261024；CURRENT；last_verified=2026-10-25。模块VERSION=1.4.0，Runtime Schema=1.14.0；模块状态MODULE_CHECKS_PASSED，公共接收PENDING_N3。本记录登记N2消费者和限定证据；公共RoleChannel/application/配置/绑定与界面接收由N3维护。完整C01—C26、用户及视觉验收状态唯一来源为原始项目specs/feature-delivery.json。

## 准确输入与责任

完整工单为原始项目docs/menu-delivery/N03.md，baseline_id=boss-menu-n03-coverage-20261025-v1。本次接续6d9eacf2725f82a103daabc778453ee5aea07b52的同一记录。已读取适用AGENTS、S008技能与此前完整任务记录/执行规则、当前N03工单、N1 backend.md、完整boss_business_overview.py、boss_business_overview_entry.py、business-overview.schema.json 1.1.0和ConversationAPI.business_entry。既有conversation_agent、Fc02、任务、晨间、公共Registry及原生接收路径继续按实际代码核查。记忆索引没有相关命中。

准确只读依赖PRODUCT 72f0a7f5af190eadded4f93e385abfa4d067be2a，目录/Users/liuhaoxian/.codex/worktrees/boss-integration/Boss-Agent。N1总览提交a38bf9b及记录4b48ccb通过67be86d/a8cc244接收；入口d57de121854c656ba2a068392298c121ab05af29及记录97e3b3c通过804c064/72f0a7f接收。公共总览读取接入836df71沿用N3分工。

| 依赖 | 准确blob或版本 |
|---|---|
| boss_business_overview.py | 1d9e7bc05070d99754b6a6c7e55cd48f6ebe97a0 |
| boss_business_overview_entry.py | e03b99c4bfa2454a8a6bc60b80c5bceffab63c8d |
| business-overview.schema.json | 1.1.0；7b276e0da5c79c1710fdacfc4f96617f452975b6 |
| 原Runtime Schema | 1.13.0；7d9ed6d282dc1c7853bc2e2e2690fc99f1697b66 |
| 当前Runtime Schema | 1.14.0；3cdcec23d54beeee8fdf2983b2b2d77274160598 |

本次仅修改自己的conversation_agent、必要限定测试、Runtime Schema及本记录/报告。N1领域、PRODUCT、公共ProductConversation/RoleChannel/application/Registry实现均未修改。测试读取PRODUCT正式领域，使用PYTHONDONTWRITEBYTECODE=1；实际ProductConversation继承当前被测Native实现，测试使用其真实registry_tool适配。

## 六层治理与执行配置

| 层级 | 实际采用 |
|---|---|
| Context | 当前本人/连接、原生chat/turn、已应用选择证明、正式Entry.read与不可变Grant；旧receipt不能恢复执行证明 |
| Action | 普通N02保持原七项；N03模型仅见businessOverviewRead/query_metrics/bossEvidenceRead三项，参数与本轮摘要匹配 |
| Skill | 既有skills.context和固定Prompt/配置继续采用，不从来源正文或专题内容生成权限 |
| Control | admission、native_context、context_provider、模型前后、工具前后及Runtime Hook均检查当前资格 |
| Isolation | 同一Nanobot/AgentLoop、实际SessionManager、Provider和Registry；按chat/turn/request固定证明与截止；没有第二个执行循环 |
| Verification | 正式Scope、实际工具参数、保存结果、来源/实例变化和真实SDK控制；公共传输/UI接收另由N3验证 |

ProductRuntime的当前配置检查保持：deepseek/deepseek-flash、实际provider/model/generation、原生配置摘要、启用工具与工作投影政策。timeout继续120秒，max_tool_rounds/max_output_tokens来自已启用快照；至少需要len(plan.calls)+1轮，规划最多10项工具调用。没有新增外部模型调用、自动重试或费用估算；未知usage/cost保持null。

## 正式接口与实际注册

| 方法或字段 | 准确行为 |
|---|---|
| NativeConversationAgent(store,registry,runtime_snapshot,attachments) | 继续原构造器；通过ConversationAPI(store).business_entry(attachments.sessions)取得正式服务，与原生Loop共享SessionManager |
| tools() | 保持N02原七项；bossDashboardRead/bossTasksRead/bossMeetingsRead/bossEvidenceRead/bossWorkspaceRead/conversationRead/query_metrics |
| business_tools() | 返回一个ConversationReadTool，其实际delegate为BusinessOverviewReadTool，名称businessOverviewRead；供N3加入available工具目录 |
| business_claimed(chat_id) | 所有namespace查找该chat的经营绑定占用，仅作路由判断；不授予当前资格 |
| business_admission(role,chat_id,*,attached,active) | 正式认证/attach、Entry.read及当前绑定核查；返回是否属于当前有效经营入口，冲突立即拒绝 |
| admit_business(role,chat_id,turn_id,content,*,media_sha256,attached,active,selection_current=None) | 非经营chat或SDK非Agent命令返回None；经营chat必须具有可调用selection_current；复用原admit产生稳定原意图及enqueue回执 |
| admit(...,selection_current=None) | 普通调用保持原语义；经营chat缺少当前选择证明时拒绝。selection_current应由可信服务端提供，返回当前(preparation_id,preparation_sha256)二元组 |
| ConversationGrant.business_entry_json | 冻结正式Entry的十二项安全字段；每轮及历史本会话已经保存的选择必须相同，不能改写到新版本 |
| ConversationQueries.plan(...,applied_parameters=None) | 普通查询保持原入口；N03传入正式query_handoff，以source_ids取得正式维度并采用结构化完整范围 |

businessOverviewRead Schema严格为object、additionalProperties=false、required=[projection]，projection仅overview/topic。模型没有scope、来源列表、身份或授权字段。overview只允许未选具体专题的绑定；topic只允许原绑定专题。工具每次从正式Entry.read取得当前View，专题详情再调用BusinessOverviewAPI.detail(BOSS,{scope,page_id,snapshot_sha256})；额外topic_reference直接来自正式Entry，用于准确表达F19用途。

N3把business_tools()返回的真实工具加入available目录和启用配置。现有ProductConversation.registry_tool对该名称可以通过self.delegates找到真实delegate，再以当前Scope包裹；query_metrics沿用当前Fc02分支。FeatureToolRegistry按本轮FEATURE_SCOPE只向N03暴露三项工具，N02仍暴露七项。Recorder使用同一个PREPARING_REQUEST在准备阶段取得实际本轮工具定义；外层公共Recorder原有设置保持兼容。

## N3必须接收的公共顺序

1. 本人明确应用范围，调用BusinessOverviewAPI.read(BOSS,scope)。Scope严格为legal_entity_id/region_id/period_start/period_end/timezone/attention；attention为ALL/OWNER_INVOLVEMENT/SOURCE_REVIEW，region_id=null明确表示不限制区域。topic_reference为null或{page_id,use}，用途仅在F19采用。
2. 通过正式business_entry.prepare(BOSS,{client_request_id,applied_scope,snapshot_sha256,topic_reference})保存原选择。使用实际原生new_chat创建并保存空白Session，沿用同一个SessionManager。
3. business_entry.bind(BOSS,{client_request_id,preparation_id,preparation_sha256,chat_id})。服务端再次read(BOSS,{session_id,chat_id})，核查当前证明；session_id为websocket加真实chat_id。receipt(BOSS,{client_request_id})仅查原编号历史，不能代替read或恢复进程内proof。
4. 当前连接保存服务端已验证的所选preparation_id/preparation_sha256；selection_current读取这份当前选择。来源仍由Entry.read复核。重新应用范围需要新的准备及未使用原生会话；新选择到达时，旧轮次的selection_current立即不再匹配，旧chat即使仍attach也不能继续执行。
5. RoleChannel在晨间候选及morning.native.admit之前调用admit_business，传入实际content、turn_id、media摘要、当前role/active/attach与selection_current。返回非None时采用同一普通原生发布路径，enqueue=false只查原编号；禁止继续进入晨间候选或第二次一般admit。非Agent命令保留SDK路径。
6. Context provider顺序继续晨间native_context、一般native_context、当前配置/Skills/Memory、各受限scope和对应Recorder；N03当前没有晨间绑定，晨间provider返回None。后续provider使用guard_context，实际运行采用同一Provider/Recorder。

晨间新增绑定事务必须在保存前调用business_entry.require_available_in_transaction(db,{session_id,chat_id})，检查与保存位于同一BEGIN IMMEDIATE；N1已经让任务入口检查经营占用。N2的morning_claimed对已占用经营chat不选择晨间分支，随后正式Entry.read拒绝任何真实冲突绑定。该模块保护不能替代公共晨间保存事务检查。公共前置方法、选择证明和共享事务接收均由N3完成；当前记录不宣称RoleChannel整条生产链路已经验收。

## 参数、专题和当前引用

N03新轮次首先读取原正式overview/topic，返回的applied_scope、业务截至、读取时间、状态和缺口来自实际领域。法人、区域、期间与关注条件进入原Entry摘要。查询以query_handoff生成QueryBinding，scope.source_ids保持正式来源。明确指标补充生成metric_ids，产品与区域可在原允许集合内缩小；单区域补充同步更新region_id/region_ids。法人、当前期间、来源、口径等超出原范围时WAITING_INPUT，要求明确重新应用；比较期间沿用正式BI校验。父查询仍核查同会话、正式产物及原摘要，后续补充保存parent_query_id和实际继承/覆盖字段。

当前六项指标为sales_quantity/revenue/cost/gross_profit/gross_margin/gross_profit_per_tonne，含单位、定义及比较期间。自由关注条件、未支持指标、不能解释的筛选文字及专业事项不会被静默忽略。普通总览查询仅代表WATER_FEED_EXTERNAL_SALES_ONLY；库存、农业、海外等专业问题不会用外销成本或收入替代。

选定专题的指标请求只有F14明确“关联外销”且正式related_sales_source_refs存在时允许使用该参考；其余专题或资料不足返回实际专题和具体缺口，保持WAITING_INPUT，不创建finance-note查询。专题原文只能采用该专题正式records.source_refs中的有效来源。总览来源列表明确标记为已应用范围来源，不把它表示为每个专题均具有依据。

十项专题按F14原料与饲料、F15水产季节、F16苗种批次、F17动保与技服、F18生猪合作、F19禽类与反刍、F20公司水产养殖、F21食品与品质、F22海外业务、F23研发应用保留。F19的BROILER/EGG/MILK/BEEF原用途固定，变更用途要求新的明确应用。时间、归属、数量、单位、专业作者及确认/执行状态继续采用工单和正式领域语义，零采购成交、用药、设备控制、质量放行、资金交易或专业发布。

Entry.read每轮重新核查store_reference、服务端身份/资料、Scope、topic、完整快照、来源及实际Session.created_at；消费者固定原preparation_sha256和全部安全引用。模型前后、工具前后经Scope重复read并比较；来源过期/撤销/换版、范围、关联关系、时钟、Session或身份变化即停止，不更新版本或重绑。当前页面选择变化通过selection_current继续限制原轮次。

## Runtime、取消与恢复

Runtime仍使用feature_id=N02记录共享会话引擎，1.14.0在conversation_context增加可选business_entry。严格十二项字段为store_reference/preparation_id/client_request_id/preparation_sha256/applied_scope/scope_sha256/topic_reference/topic_sha256/snapshot_sha256/source_references/business_at/return_reference。字段均来自正式Entry；source_references保留kind=document/id/version/content_sha256/status，缺少值保留null；return_reference严格page_id=N03及原范围/专题/快照。嵌套对象additionalProperties=false，拒绝正文、路径、身份或授权注入。没有把PRIVATE关注文字存入Runtime或pending_query_scope。

工具结果沿用parameters_sha256/result_sha256及已有正式query_id/来源引用，不新增伪造结果类型。Bound上下文、原意图、实际会话、业务查询和原回执保持相互关联。SDK取消只清理本轮proof、pending_media和deadline，绑定、原生历史及已经保存的结果保留；错误FAILED、取消CANCELED、超时TIMED_OUT、缺少条件WAITING_INPUT沿用既有真实映射。

未知结果使用同一个client_request_id/run_id及requests/receipt读取，不重放。相同轮次相同内容enqueue=false；异内容拒绝。重建同库ProductConversation能够读原请求及真实终态，不恢复进程内proof。模型没有本人确认、创建、发送或授权工具；会议/交办需要正式共享流程再次核查当前对象及本人决定，保存、发送与完成独立。

## 验证、证据与完整范围

测试使用真实ControlStore初始化、正式经营Entry、实际SessionManager、真实ProductConversation/FeatureToolRegistry和Nanobot/AgentLoop。所有Session显式指定独立sessions_root；数据在本目录已忽略validation/.work，不使用产品实例。测试原生transport调用正式admit_business并提供从真实Entry取得的当前选择证明，没有手工构造可信Grant或Runtime。输出全部来自实际工具，没有mock、替代业务正文或模型结果。

自动审批审查对SDK测试曾要求排除外部模型风险；读取实际Provider、注入点和conftest后，相同本地测试获得复核批准。ConversationSimulatedProvider/Fc01SimulatedProvider没有网络客户端，sys.addaudithook对socket.connect强制抛出PermissionError；测试没有GUI、自动登录、凭据读取或外部模型调用。当前认证UI自动化限制保持，由N3独立处理，没有通过代理规避。

| 验收范围 | 当前限定证据及剩余接收 |
|---|---|
| C01—C07 | 固定正式应用Scope/专题及原生读取，缺少资料时等待；公共布局和十专题界面由N3验证 |
| C08—C09 | 实际查询采用原法人/日期/source_ids，指标补充生成父查询，区域补充缩小实际参数；未知条件不生成查询 |
| C10—C12 | 直接消费正式View提醒和关系，无写入；完整对象详情及F02公共交接由N3维护 |
| C13—C15 | 实际正式导入换版、过期、撤销及专题缺口停止当前采用；F19/EGG没有外销查询替代，专业权限保持禁止 |
| C16—C17 | 实际ProductConversation、Registry三工具与原生admission消费正式绑定；会议/交办等待正式共享本人入口；公共传输接收未由本组登记通过 |
| C18—C19 | 原返回引用和Scope/专题固定，新正式应用选择使旧实际SDK轮次停止；滚动/焦点与UI迟到响应由N3验证 |
| C20—C22 | 实际SDK取消后继续、模型和工具前后来源变化、Session重建、重复原编号只读；120秒截止沿用未修改的既有Hook/Provider控制证据 |
| C23—C24 | 匿名/维护/过期或未attach拒绝、namespace变化拒绝、额外Schema字段拒绝、同库重建读取原请求，零模型授权和任务 |
| C25—C26 | N3维护独立制品、端口、响应/焦点/滚动及保护；本组没有产品启动、GUI或视觉验收 |

agent-check.xml记录受影响组合77 passed、57.55秒；包含23项N03定向及54项N02 Native/来源/任务/Runtime Schema回归。当前N03消费者的business-check.xml为25 passed、19.58秒，包含专业事项及未支持经营资料编号的条件判定。两组证据分别表示受影响回归和当前定向范围，数量不相加；没有运行无关仓库全量。原请求列表、既有可观察事件和120秒实际计时的未变部分引用../N02/agent.md及既有准确报告，不登记新增N03覆盖。

```bash
env PYTHONDONTWRITEBYTECODE=1 CONVERSATION_DOMAIN_ROOT=/Users/liuhaoxian/.codex/worktrees/boss-integration/Boss-Agent validation/.venv/bin/python -m pytest app/tests/conversation_agent/test_business_consumer.py app/tests/conversation_agent/test_native.py app/tests/conversation_agent/test_current_references.py app/tests/conversation_agent/test_task_entry_consumer.py app/tests/conversation_agent/test_task_entry_schema.py -q -p no:cacheprovider -o junit_family=xunit1 --basetemp=validation/.work/n03-business-final --tb=short --junitxml=docs/menu-delivery/N03/agent-check.xml

env PYTHONDONTWRITEBYTECODE=1 CONVERSATION_DOMAIN_ROOT=/Users/liuhaoxian/.codex/worktrees/boss-integration/Boss-Agent validation/.venv/bin/python -m pytest app/tests/conversation_agent/test_business_consumer.py -q -p no:cacheprovider -o junit_family=xunit1 --basetemp=validation/.work/n03-business-delivered --tb=short --junitxml=docs/menu-delivery/N03/business-check.xml
```

## N3接收与环境保护

N3下一动作是接收准确工具及1.14.0 Schema，将admit_business及可信selection_current放在晨间候选之前，配置工具目录与当前受限包装，完成共享晨间绑定事务检查；然后验证真实公共prepare/new_chat/bind/read、原生发布、范围切换、取消、未知恢复及返回UI。全26项和当前唯一菜单不变，N2模块证据不表示完整菜单、未来专题或用户验收通过。

当前PRODUCT尚未包含本主记录路径；本次提交以6d9eacf记录为前置。接收时可按顺序接收6d9eacf与本次消费者提交，代码依赖采用上述准确72f0a7f领域。本次git diff --check通过，N1正式源码和相关Schema在验证结束时与准确输入一致。

磁盘生成前检查232MiB及后续197MiB；没有创建仓库副本。原F01的10611/10612/20611、新F01的10621/10622/20621、N02的10711/10712/20711、UI02的10411/10412/20411、MVP的9961/9962/19961及其制品、桌面和用户资料均未用于验证。N03端口10811/10812/20811及独立制品由N3管理，本次未启动。STT/F27/FC28与视觉保持暂停；没有新聊天、子代理或向其他聊天发送消息。公共索引由N3接收本主记录的稳定路径。
