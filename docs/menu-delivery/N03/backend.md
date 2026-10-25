# MENU-N03-N1 经营关注领域

task_id=MENU-N03-N1；marker=MENU-N03-START-20261025；依据原始docs/menu-delivery/N03.md的C01—C26及完整产品FR-02/03/14—23。当前唯一菜单N03，正式状态由N3维护specs/feature-delivery.json，本记录不登记完整菜单或用户验收通过。last_verified=2026-10-25，领域状态MODULE_CHECKS_PASSED。原五项未提交内容保持。

总览实施提交a38bf9b41f5b1f88d08ebbac10b62a2610962515，记录提交4b48ccb2fa8e586de26aa5a16e7c0ea1c742e47e，分支codex/business。N3已经通过67be86d/a8cc244接收总览领域与Schema；本次独立原生入口增量继续由N3/N2接收。

原生入口补充marker=MENU-N03-N1-NATIVE-ENTRY-20261025，范围为C16/C18/C20/C24必要领域绑定。依据N2准确设计6d9eacf2725f82a103daabc778453ee5aea07b52的docs/menu-delivery/N03/agent.md，读取PRODUCT a8cc2446be0f4a94022c15d841814514012492d8及N1基准4b48ccb2fa8e586de26aa5a16e7c0ea1c742e47e。入口领域状态MODULE_CHECKS_PASSED；采用独立经营准备与绑定，task_entry保持固定任务语义。真实Session、来源与范围变化、同库重开、原编号历史、互斥及零业务变更检查维护于app/tests/test_menu_n03_entry.py。公共Page/Command/RoleChannel/application/认证/Shell/Agent仍由原角色维护。

## 当前依据与边界

完整读取当前工单和适用AGENTS，沿用S008任务记录、实施与接口检查规范。核查准确PRODUCT基准3d04f28d6d3b7d53b58a1a69b085a54ca1cc6f57的BossSectorAPI、正式BI计算、SimulationAPI、供应品质、经营提醒、任务和来源规则；验证时PRODUCT HEAD为ba59c33bc3cc6b914bdd0b0792aeedc49b3f2220，相关领域文件与基准相同。PRODUCT目录为/Users/liuhaoxian/.codex/worktrees/boss-integration/Boss-Agent，仅作只读依赖。记忆索引没有本任务相关证据。

总览由validation/boss_business_overview.py提供，规范specs/business-overview.schema.json当前1.1.0，新增Entry系列定义。总览只读采用真实Store；入口仅保存技术准备、资料实例标识及绑定，不新增查询、任务、授权、通知动作、DDL或另一AgentLoop。没有修改公共BossPageAPI/Command/RoleChannel/application/Shell/认证，没有启动产品、预览、桌面或使用用户实例。SIMULATED_FIRST，STT及视觉继续暂停。

## 正式接口与范围

构造器BusinessOverviewAPI(store)。调用方传入的role必须来自可信认证，payload没有owner/namespace/dataset。匿名401、维护403；额外、无效或未支持范围400；旧快照409；上游错误在当前位置抛出，不返回替代成功。

| 函数签名 | 输入 | 输出及事务 |
|---|---|---|
| dimensions(BOSS) | 无payload | 当前正式记录提供的法人ID、区域ID、期间、已验证IANA时区及attention枚举；独立只读事务 |
| read(BOSS,scope) | Scope严格字段见下表 | View；同一BEGIN事务核查范围、权限、来源、指标、专题、提醒及关联 |
| project_in_transaction(BOSS,db,scope) | 相同Scope，db为调用方现有只读事务 | 相同View；不另开写入事务 |
| detail(BOSS,{scope,page_id,snapshot_sha256}) | page_id限定F14—F23，摘要来自同一scope的View | 当前topic、来源、范围及时间；重新读取并核查快照，变化409 |

公共路由建议：本人读取GET /api/boss/ui/business-overview/dimensions；范围和详情采用POST /api/boss/ui/business-overview/read、POST /api/boss/ui/business-overview/detail，JSON分别为上述Scope和Detail。路由尚未注册，N3负责公共适配，讨论工具由N2按准确接口采用。POST读取用于传递严格结构，操作仍为只读。

| Scope字段 | 精确语义 |
|---|---|
| legal_entity_id | dimensions.legal_entity_ids中的正式ID；不按名称猜测 |
| region_id | 正式区域ID或null；null明确表示没有区域限制，有区域限制时缺少区域证明的对象不进入专题当前结果 |
| period_start / period_end | dimensions.periods提供的完整起止日期；包括获准selection期间和正式记录明确报告期间，不分摊未知日期区间 |
| timezone | 当前已验证本人IANA时区；不支持的时区明确拒绝 |
| attention | ALL、OWNER_INVOLVEMENT、SOURCE_REVIEW；不接受自由文字并暗中忽略 |

草稿由客户端维护，read只采用明确提交的scope，View.applied_scope原样返回。dimensions的法人/区域来自当前获准明细和正式对象元信息，期间来自明确报告字段；维度可读不表示相应数值已通过当前来源检查。当前数据资格在read内重新核查。

## JSON字段与业务采用

View严格根字段：source_type=SIMULATED、projection=business-overview、applied_scope、dimensions、scope_application、metrics、metric_missing_fields、metric_scope、metric_coverage、query_handoff、query_handoff_unavailable_reason、topics、alerts、alert_scope_exclusions、associations、sources、excluded_records、unclassified_records、business_at、read_at、coverage_state=PARTIAL、snapshot_sha256，以及恒false的business_authorization_granted/business_mutation_performed。

metrics复用正式BI的_period_rows及_aggregate，只采用当前有效finance-note和明确法人/区域/期间的原始明细。逐项metric_id/value/unit/formula/definition_version/precision/business_as_of/source_refs；数值为Decimal字符串，缺少或零分母保持null。metric_scope=WATER_FEED_EXTERNAL_SALES_ONLY，metric_coverage保存实际record_id/version、缺少区域和SCOPED_AVAILABLE/PARTIAL/UNAVAILABLE。这些金额和比率不作为原料价格、领用成本或农业专业结果。query_handoff仅在有效当前/比较期间及完整区域条件下提供正式F03范围参数，包含原source_ids、业务口径、单位及比较期间；否则null，公共入口须说明当前需要的有效查询条件。

topics按F14—F23固定十项顺序，title/purpose来自现有获准SECTORS定义。每项包含page_id/title/purpose、availability、data_as_of、latest_source_published_at、records、missing_fields、scope_application、related_sales_source_refs及uses。可读状态PARTIAL、NEEDS_REVIEW、SOURCE_NOT_AVAILABLE、FILTER_EMPTY分别表示部分正式对象、需要复核、没有本专题当前资料和关注条件筛除结果。data_as_of采用实际observed_at；发布时间单独保存，不代替业务观察时间。F19 uses为BROILER/EGG/MILK/BEEF；当前共享页面对应F19、V19-EGG、V19-MILK、V19-BEEF，完整专业菜单仍由后续工单管理。

供应对象和质量对象复用SimulationAPI的正式选择及_protect来源/传递采用规则。法人只通过对象明确legal_entity_id或显式批次/库存ID关系核查；跨法人或无法确认关系时排除。区域限制不从相近名称推断。F14采用材料行情/合同/库存/领用/成本报告/配方的合法明确对象，F21提供生产批次、追溯、专业记录、反馈及事件的有限质量关系，均保留完整专题缺口。记录逐项kind/id/version/state/adoption_state/source_refs/facts，facts仅提供当前通过检查的归属、单位、币种、报告期间及专业/检验状态；来源失效时facts=null。没有将生产批次推断为苗种批次，也没有将未确认用途的农业观察推断为禽畜或完整养殖专题。unclassified_records明确保存已获准但专题适用关系不足的对象；excluded_records说明法人或区域无法确认的类型与原因。

scope_application明确：指标采用完整所选期间；专题是business_at时点的当前状态，报告期间随facts明确返回，不作为所选期间流量合计；提醒采用实际比较期间及selection财政资料范围；关联采用正式来源关系，不作为任务创建期间。attention过滤专题、提醒和关联，指标保留为已应用法人/区域/期间的上下文。需要本人参与的专题没有自动专业分类时不编造提醒。

alerts复用BusinessAlertsAPI.project_in_transaction，保留原事件、通知、规则版本、参与原因、已有措施、处理人、缺少字段及状态。范围只从实际生成器保存的比较期间和正式selection来源范围确定，无法证明范围时不采用；alert_scope_exclusions分别给出范围和关注条件排除数量。来源变化后保留正式历史事件元信息及NEEDS_REVIEW，facts/当前通知等正文采用资格继续由原领域决定。读取不调度、知晓、暂缓、关闭或发送。

associations仅从正式任务的source_refs与当前范围的明确来源关系采用，逐项kind/id/version/state/adoption_state/source_refs/relation=EXPLICIT_SOURCE_REFERENCE。OWNER_INVOLVEMENT进一步限定实际提醒已有措施中的任务；SOURCE_REVIEW限定正式NEEDS_REVIEW。来源撤销后历史引用和状态仍可辨，当前业务采用需要原领域重新核查。

sources逐项source_id/version/status/sha256/metadata，SQL先限制当前namespace、本人access_scope、source_id和SIMULATED类型，再核查source_validity及external_adoption。当前metadata包含实际作者、类型、发布时间、观察时间、有效期、范围和原文定位；失效或无权时不返回metadata。sha256覆盖当前完整正式来源对象，供版本变化核查。snapshot_sha256覆盖当前范围、资料、对象及正式结果，read_at不参与摘要；detail重新计算并拒绝已变化的引用。未提供任意客户端来源或对象ID入口。

## 当前验证

2026-10-25，11项限定检查通过，用时3.22秒，原始结果domain-check.xml。数据均为N1独立.work/pytest-menu-n03-delivery下的真实SQLite，来自正式初始化、本人Command服务、获准supply-quality-v1.yaml导入及经营提醒定义。没有mock、替换业务正文、外部网络或用户实例。

实际拒绝6类非法/未支持法人、区域、期间、时区、关注条件和额外身份字段请求，均为400；匿名401、维护403；来源撤销后指标null、查询入口null，旧快照409。成功检查覆盖原始毛利率8.00%、十专题顺序和四用途、真实供应/质量资料、未分类农业范围、精确区域限制、正式报告期间、来源复核、经营提醒与通知/规则独立状态、真实任务关联及稳定版本。同库重开结果摘要一致，所有读取前后的objects/audit/idempotency完全相同；旧范围提醒被明确排除，来源失效后的历史提醒保持NEEDS_REVIEW且facts=null。

```bash
env PYTHONDONTWRITEBYTECODE=1 MENU_N02_PRODUCT_ROOT=/Users/liuhaoxian/.codex/worktrees/boss-integration/Boss-Agent PYTHONPATH=/Users/liuhaoxian/.codex/worktrees/boss-business/Boss-Agent/validation validation/.venv/bin/python -m pytest -q app/tests/test_menu_n03_overview.py --basetemp=.work/pytest-menu-n03-delivery -p no:cacheprovider --junitxml=docs/menu-delivery/N03/domain-check.xml --tb=short
```

验证工作目录为/Users/liuhaoxian/.codex/worktrees/boss-business/Boss-Agent。PYTHONDONTWRITEBYTECODE=1阻止依赖目录生成缓存，现有检查审计禁止socket.connect。生成前磁盘249MiB；没有创建全仓副本。git diff --check通过。

## 接收与未完成范围

N3需要公共注册、完整设计与交互、范围草稿/应用和返回状态、实际页面、共享入口及独立交付；N2需要实际工具与同一SDK对准确scope/topic/snapshot/source版本的消费。N1本次交付提供这些消费者的数据接口，不表示上述公共与Agent行为已经完成。未来完整专题、真实外部接入、STT、视觉和用户验收均未登记通过。唯一26项状态继续读取N3正式记录。

query_handoff_unavailable_reason在不可进入当前比较查询时明确说明FINANCE_SOURCE状态、NO_EXTERNAL_SALES_ROWS_FOR_SCOPE、REGION_COVERAGE_INCOMPLETE或NO_PRIOR_COMPARISON_PERIOD；可进入时为null。公共入口不能把query_handoff=null显示为已完成查询，也不应提交缺少条件的动作。

## 独立原生入口与恢复签名

入口文件validation/boss_business_overview_entry.py，构造器BusinessOverviewEntry(conversation,native_sessions)，正式getter为ConversationAPI(store).business_entry(native_sessions)。native_sessions必须为公共原生执行使用的实际SessionManager。Schema在specs/business-overview.schema.json 1.1.0，EntryPrepare/EntryBind/EntryNativeContext/EntryPreparation/EntryContext/EntryReceiptInput/EntryReceipt均为严格字段定义。原有Scope/View/Detail字段语义保持。

| 精确调用 | JSON输入 | 当前输出与持久行为 |
|---|---|---|
| prepare(BOSS,payload) | client_request_id、applied_scope、snapshot_sha256、topic_reference，四项全部必需 | EntryPreparation；同一BEGIN IMMEDIATE事务重新调用BusinessOverviewAPI.project_in_transaction，核查摘要、专题及用途，保存固定引用 |
| bind(BOSS,payload) | client_request_id、preparation_id、preparation_sha256、chat_id，四项全部必需 | EntryPreparation，状态BOUND；根据真实chat导出session_id，核查实际已保存Session和created_at，原子保存绑定 |
| read(BOSS,query) | session_id、chat_id，二项全部必需 | EntryContext；同一BEGIN事务重新核查服务端身份、资料实例、固定范围、专题、来源及实际Session，返回当前overview和references |
| receipt(BOSS,payload) | 仅client_request_id | EntryReceipt；按原编号读取同库历史，RECORDED或NOT_FOUND_IN_CURRENT_STORE；没有当前资格检查或自动重新提交 |
| require_available_in_transaction(db,query) | 可信调用方的现有写入事务，以及相同EntryNativeContext | 没有返回数据；已有晨间、任务、经营绑定、runtime_run或conversation_intent均409；供其他入口在同一绑定事务内调用 |

client_request_id为8—128字符的[A-Za-z0-9_.-]+。applied_scope为现有六字段Scope，必须来自当前已应用选择。snapshot_sha256来自对应View，服务端重新计算并比较；客户端摘要不签发任何授权。topic_reference可为null，或严格{page_id,use}，page_id限定F14—F23；use为null或BROILER/EGG/MILK/BEEF，非null用途仅在F19合法。缺少专题资料仍返回正式可读状态与缺口；绑定成立只证明固定范围可重新检查，不证明专业资料存在或后续动作得到授权。

EntryPreparation固定字段为source_type=RUNTIME_RECORD、store_reference、preparation_id、client_request_id、preparation_sha256、prepared_at、bound_at、binding_state、context、applied_scope、scope_sha256、topic_reference、topic_sha256、snapshot_sha256、source_references、business_at、return_reference、current_use_verified和两个恒false业务标记。PREPARED时context/bound_at为null；BOUND时context严格包含session_id/chat_id/native_session_created_at。created_at按实际SDK值原样保存，兼容SDK当前没有时区后缀的日期时间。

source_references逐项保存kind=document、id、version、content_sha256、status，来自总览实际读取的完整来源集合；不接收客户端来源清单。version/content_sha256在正式来源缺少时保持null，失效来源状态保留。EntryContext.references只提供当前VALID且具有版本的kind/id/version，作为后续消费者当前引用输入。全部来源属于所选范围上下文，是否支持当前专题必须继续根据overview.topics对应项、related_sales_source_refs和真实对象关系判断；没有专题来源时不得借用其他经营资料回答。

scope_sha256为规范Scope摘要；topic_sha256为对应正式Topic摘要，没有专题时null；snapshot_sha256继续覆盖完整范围、资料、当前对象和来源，read_at不参与。preparation_sha256覆盖服务端namespace/owner/dataset身份、资料实例UUID、原请求摘要、准备编号/时间、完整Scope、专题、三个摘要、来源引用及business_at。该校验值用于发现引用变化，不具有本人授权语义。store_reference为服务端首次准备时在同库当前空间生成并持久保存的UUID；独立初始化资料库得到不同实例引用。输出不公开owner/namespace，也不保存数据库路径、私人关注文字、问题、凭据或来源正文。

技术持久对象仅为conversation_business_store、conversation_business_preparation、conversation_business_binding，沿用objects表。原准备编号由client_request_id确定，同编号同内容复用，异内容409；已绑定准备只能使用原chat，原chat只能承接一个明确入口。bind要求实际Session已经保存、当前messages为空、没有已有运行/意图/晨间/任务/经营绑定，SQL同时检查所有namespace。准备与绑定写入在BEGIN IMMEDIATE内串行执行；失败不保存部分绑定。没有解除或修改既有经营绑定的接口；重新应用其他范围或专题需要明确新准备和新的未使用原生会话，原记录保留为历史。

read未绑定时返回UNBOUND、entry/overview=null、references=[]、current_use_verified=false。绑定后返回BOUND、当前EntryPreparation、同事务正式overview和当前来源三字段引用。prepare/bind/read每次重新验证固定选择；来源撤销、换版、有效期或传递采用变化、业务时钟与对象关系改变导致快照不同，当前采用409。实际Session删除404，同名重建的created_at不同409。历史receipt继续返回原选择和原来源，entry.current_use_verified恒false；NOT_FOUND_IN_CURRENT_STORE只能说明当前库没有原编号，不推断先前是否执行，不创建准备、问题或业务对象。同库重新构造Store及SessionManager可以read原绑定，资格仍需当前检查。

return_reference严格为{page_id:N03,applied_scope,topic_reference,snapshot_sha256}。该引用只描述返回选择，刷新/返回时仍需重读当前正式范围；来源已变化时可显示原选择历史并要求明确重新采用，不能恢复原执行证明。滚动与焦点由N3按安全界面字段保存；私人文字不进入URL或普通持久缓存。每轮实际Agent执行前后，N2/N3需要调用read并比较本轮固定preparation_id/preparation_sha256和当前页面选择；不能凭receipt或历史Runtime恢复进程内证明。

任务入口的_unused_session已经增加conversation_business_binding检查，领域限定用例核查双向任务互斥。经营read也检查其他晨间/任务绑定，后续出现冲突即停止当前采用。现有PRODUCT晨间Agent和一般会话admit属于N3/N2维护范围：晨间在保存新绑定前，需要在自身BEGIN IMMEDIATE内调用require_available_in_transaction；一般会话每轮采用经营绑定时，需要从read取得当前证明并沿用原SDK检查节点。上述调用方接收PENDING_N3_N2，本领域没有修改Agent。共享检查函数已经验证会拒绝占用原生会话，当前范围不登记完整晨间公共互斥或N03 Agent消费通过。

## 原生入口限定证据

2026-10-25，36项通过，用时6.95秒；22项N03入口和14项受影响N02任务绑定回归，原始结果native-entry-check.xml。使用N1独立.work/pytest-menu-n03-entry-delivery的实际SQLite与SessionManager，以及已批准SIMULATED_FIRST的真实Nanobot/AgentLoop/Registry/来源工具流程。入口源码路径断言为当前N1文件；实际总览依赖来自PRODUCT a8cc244，boss_business_overview.py与已交付a38bf9b逐文件相同，入口直接读取自身1.1.0 Schema。没有mock、替代来源正文或外部连接。

Given获准Scope和当前View，When准备、绑定、重复、并发及同库重开，Then固定Scope/专题/四用途/快照/来源/实际Session.created_at和安全返回引用准确，同内容重用、异内容拒绝，业务对象、audit及idempotency保持。独立库的store_reference不同，不能使用其他库的准备校验值绑定。

Given已经保存的绑定，When真实SDK根据返回引用读取来源并保存消息与结果，Then原Session身份和领域绑定继续有效，保存的运行引用与返回引用相同。来源撤销后当前read拒绝，ConversationAPI仍保留原运行编号，receipt没有当前证明。正式供应品质导入后的来源换版、有效期届满和传递来源撤销分别检查停止采用；原来源引用不被替换。

匿名401、维护403；注入owner/namespace/dataset/store/source/confirmed字段400；自算摘要、旧快照、同键异内容、跨会话接管和已有入口409；不存在Session404。同名Session重建、真实已有SDK消息、已有晨间和任务绑定均不能接管；task_entry无法接管新经营绑定。共享事务检查函数拒绝占用会话；后续出现其他晨间绑定时经营read停止，原历史可读。现有14项任务绑定回归全部通过。

Red行为检查在实施前确认ConversationAPI缺少独立business_entry入口。最终限定命令如下，未执行公共页面、产品启动、GUI、视觉或全量菜单验收。

```bash
env PYTHONDONTWRITEBYTECODE=1 MENU_N02_PRODUCT_ROOT=/Users/liuhaoxian/.codex/worktrees/boss-integration/Boss-Agent PYTHONPATH=/Users/liuhaoxian/.codex/worktrees/boss-business/Boss-Agent/validation validation/.venv/bin/python -m pytest -q app/tests/test_menu_n03_entry.py app/tests/test_menu_n02_task_entry.py --basetemp=.work/pytest-menu-n03-entry-delivery -p no:cacheprovider --junitxml=docs/menu-delivery/N03/native-entry-check.xml --tb=short
```

本次接收范围包含新领域文件、ConversationAPI最少getter、task_entry互斥类型、business-overview Schema、限定测试与同一主记录/索引/证据。N3接收实际公共prepare/bind/read/receipt路由及原生Session前置，N2接收每轮当前核查、受限工具与结构化Fc02采用；晨间共享检查接入由N3/N2完成。完整C01—C26及用户/视觉状态继续由N3唯一正式记录管理，领域通过不增加完整验收数量。
