# MENU-N02-N2 聊天交办Agent开发记录

task_id=MENU-N02-N2；marker=MENU-N02-N2-REQUEST-HISTORY-20261024；decision_id=D-MENU-DELIVERY-20261024。当前模块版本1.2.0，包含原请求只读列表扩展。N02完整26项及正式状态由N3维护specs/feature-delivery.json，本记录只登记Agent模块及准确消费证据，不登记完整菜单或用户验收通过。文档有效性CURRENT，核查日期2026-10-24。主记录路径及既有索引引用保持。

## 当前依据与准确依赖

本次原请求扩展的PRODUCT准确候选为1b7a7fa0c72e176df746ca3d3e0e90993604e6e0，包含N2消费模块cd1a5b0的公共接收、N1上下文引用66fc44d/c9dada0及附件Schema1.1读取。公共ProductMorning/FeatureProvider/FeatureRecorder、RoleChannel、application、Schema和App由N3唯一维护；本目录没有修改这些文件。D-UI-FIDELITY-20261024及F01设计返修继续由N3处理，进入N03前的必要条件保持。

已完整读取适用AGENTS、原始N02完整26项、PRD当前决定、FR-08/24/29及BR/AC、共同BR-C01—C07/E01—E06、原N02 HTML、原始提示词及实际chat区域。当前续接读取N02主记录、backend.md、boss_conversation.py、boss_conversation_attachments.py和conversation.schema.json 1.1.0，核查实际SDK命令生命周期、Session保存、Fc02Tool、bind_query、bind_scoped_followup、BIQueryAPI和范围Schema。S008任务记录、执行规则及连续验证要求继续采用；记忆索引没有相关命中。

会话、运行、业务产物、本人消息历史与附件采用正式领域接口，实际原生历史、未发送输入和传输继续使用同一Nanobot。没有另一份消息状态或第二个模型循环。本人草稿、明确发送、回复及任务共享入口继续使用既有业务服务。

## 模块及正式接口

代码为validation/conversation_agent，检查为app/tests/conversation_agent。READ_TOOLS保持bossDashboardRead、bossTasksRead、bossMeetingsRead、bossEvidenceRead、bossWorkspaceRead和conversationRead六项同库正式只读工具，_BossPageReadTool及read_only=true要求继续适用。CONVERSATION_TOOLS=READ_TOOLS加query_metrics，共七项。query_metrics使用同库实际Fc02Tool，产生正式查询记录；没有发送、审批、本人确认或授权签发工具。

conversationRead严格projection为runs/messages/attachments/artifact/record；artifact使用N1正式run_id/kind/id，record按当前本人任务或消息历史中已有的task/message/message_draft编号读取。消息记录分别核查message_outbox与交办outbox。

| 构造器或方法 | 当前明确输入及行为 |
|---|---|
| ConversationContext | frozen dataclass；role/owner_id/namespace/dataset_id/dataset_version/request_id/session_id/chat_id/turn_id/active/input_sha256/allowed_tools/allowed_calls/references |
| ConversationScope(store, context_provider, context_validator) | 从服务端实际请求生产上下文，核查BOSS、active、规范websocket身份、原文摘要、当前资料范围和正式来源；核查器必须实际采用当前领域，不能固定返回True |
| scope.current(request=None, *, require_runtime=True) | require_runtime时要求同库、同namespace/request/session的实际RuntimeBinding；模型和工具每次继续采用之前重新核查 |
| ConversationReadTool(delegate, scope) | 同库正式只读delegate；保留实际Schema及参数类型，执行前核查(tool_id,checksum(params))属于本次allowed_calls，执行后重新检查当前范围 |
| register_conversation_reads(registry, delegates, scope) | 名称重复或工具不合法时，在Registry修改之前拒绝；用于独立正式读取注册 |
| ConversationSimulatedProvider(event_producer, scope) | 实际LLMResponse事件生产者，核查真实Registry范围，消费实际工具消息，调用前后核查当前范围；没有网络客户端 |
| ConversationRuntimeRecorder(scope, registry, runtime_snapshot, *, intent_adapter=None) | 使用实际配置、RuntimeBinding和Hook；NativeConversationAgent自动采用intent_adapter；重复同一RequestContext复用原运行 |
| NativeConversationAgent(store, registry, runtime_snapshot, attachments) | attachments为N1 ConversationAttachments，与AgentLoop共享实际SessionManager及获准媒体目录；提供scope/provider/recorder/delegates及tools() |
| agent.admit(role, chat_id, turn_id, content, *, media_sha256, attached, active) | 实际原生media字段checksum、当前连接attach和active证明；返回enqueue及原回执。SDK判断不进入Agent轮次的命令及已有晨间绑定返回None |
| agent.record_media(role, key, accepted_media, accepted_paths, *, active) | 仅原生实际上传成功后内部调用；重新核查接收证明和当前连接、成功上传数据与本轮摘要一致，再调用N1.record_upload |
| agent.native_context(request) / scope_context(request) | 当前身份、输入、媒体和连接证明通过后生成ConversationGrant及正式规划，核查七项工具配置和实际轮次要求；设置本次FEATURE_SCOPE |
| agent.query_context() | 从当前实际RequestContext及RuntimeBinding生成Fc02Context，query_bindings仅来自当前可信规划 |
| ConversationQueries(store, conversation).plan(text, query, pending_scope=None) | 采用正式维度与同会话查询产物，完整条件生成QueryBinding；条件不足返回required_inputs及已识别的安全条件 |
| ConversationQueryTool(Fc02Tool(..., agent.query_context, "query_metrics"), scope) | ConversationReadTool子类；核查同库、正式Schema、当前参数摘要与Fc02绑定，执行后重新检查范围 |
| agent.receipt(role, key, *, active) | 原编号只读；RECORDED或NOT_FOUND_IN_CURRENT_STORE，返回实际request_state/run_id/chat_id/session_id/turn_id；不重放原意图 |
| agent.requests(role, chat_id, *, attached, active) | 当前本人及连接采用的规范chat；返回实际conversation_intent的安全回执数组，包含尚无Runtime、准备失败、已取消及已运行请求；无记录返回空数组 |
| agent.guard_context(provider) / finish(key, *, status="FAILED") | 后续provider前置失败清理；明确运行前取消可以使用CANCELED，已有运行终态采用实际Runtime，不伪造停止 |

allowed_tools为frozenset工具名，allowed_calls为frozenset((tool_id,parameters_sha256))，references为tuple((kind,id,version))，version可为None。input_sha256来自request.original_user_text；request_id使用实际RuntimeBinding.request_id，建立记录前使用request.message_id或request.turn_id。session/chat/turn来自实际原生请求和服务端身份，不能由模型参数或客户端归属字段签发。

## 当前输入、正式条件与连续追问

ConversationPlanner根据当次输入和实际目录选择来源、概览、任务、会议、消息、运行、附件、已有产物或经营查询。来源ID/名称及任务/消息/产物编号均从正式资料采用。连续来源讨论保留最后实际选择，后续步骤核查当前版本。来源、对象不明确时返回具体required_inputs；消息写入和任务变更使用现有合法共享入口。附件元信息不授予业务来源资格。

queries.py通过BIQueryAPI.dimensions和dimension_options取得获准维度、已保存期间、指标定义和来源。支持六项现有指标的中文名称及英文identifier、实际维度编号、明确日期范围、全部当前产品/全部区域、币种、单位、交易范围、结算状态及明确的正式口径字段。只有本人明确选择“使用当前获准口径”时，才采用相应单一正式维度值；区域、产品、指标和两组期间仍需要明确输入。相对期间要求实际起止日期。

完整条件使用bind_query与实际Fc02Tool.parameters校验后调用query_metrics。缺少条件逐项返回中文required_inputs，只将已识别的正式字段保存在conversation_intent.pending_query_scope，没有原始问题；后续补充可继承这些已明确条件。当前不支持的明确指标/产品保持等待，不调用旧范围替代当前要求。

追问按照本人明确query_id或同会话最后实际查询选择正式父产物，通过ConversationAPI.artifact重新核查，再调用bind_scoped_followup继承正式context_snapshot，仅覆盖本次明确字段。实际参数包含parent_query_id，参数摘要与绑定一致。查询期间、比较期间、产品和指标变化均由实际SDK检查。已有正式查询产物使用相同语义；来源、定义、明细及产物变化后停止当前采用。没有开发N03完整菜单。

presentation.py根据实际工具消息产生中文说明，包含查询期间/范围/指标值、来源及版本、对象编号、当前状态、资料缺口和待补充条件。数值直接采用正式Decimal字符串，null保持无法确定，比较限制与未解释原因采用实际结果。助手消息不序列化整份工具JSON，完整内容继续通过正式会话、来源或产物投影读取。该能力明确SIMULATED，没有真实外部模型调用或预设业务答案。

## 原生媒体与SDK命令

文字为空时，admit要求media_sha256区别于checksum([])；native_context必须具有本轮实际成功上传及record_media证明。无文字且无媒体拒绝。成功上传数据必须与接收摘要一致，实际路径仅来自原生gateway成功结果。仅附件输入读取真实元信息并返回待补充用途，运行结束为WAITING_INPUT；后续本人说明目的可以继续采用原附件。元信息保存不宣称已经分析正文、完成经营计算或建立业务来源。

ConversationAttachments Schema 1.1.0保存可信上传的内部引用。实际SDK将普通文档转换为文本文件引用且user.media为空时，附件仍可从同一真实Session的上传记录读取；本模块不解析该文本或添加media。当前及recorded大小/摘要、nullable stored_name/user_message_index、STORED/MISSING/CHANGED/REFERENCE_UNAVAILABLE均采用N1正式字段。所有已采用附件必须保持STORED和本轮摘要；变化、删除或无法确认引用时在当前位置停止，原编号及已有运行保持可读。该普通文档引用已经通过当前限定检查。

当前准确RoleChannel与SDK _dispatch_message已核查：仅附件原生帧仍应提供content=""、实际turn_id及非空media，当前本人连接需已attach目标chat。SDK保持该空文字，仅在content.strip()与成功上传的media_paths同时为空时拒绝。RoleChannel使用原始media计算接收摘要，将gateway实际路径及同一原始media传给record_media，之后发布原生消息；这些已有模块要求保持。本次没有新增上传或输入处理代码，没有启动公开产品；实际仅附件普通文档与后续用途的SDK用例在当前组合继续通过。

admit和native_context调用正式SDK builtin_command_starts_agent_turn。/help、/new、无参数/goal、/model及/stop等非Agent轮次没有conversation_intent或额外Runtime。原生认证、命令接收与/stop取消仍由原路径处理。NativeMorningAdapter保持优先，已有晨间绑定不建立一般会话意图。

## Runtime、回执与隐私

Recorder复用当前RuntimeRecorder/Fc01RuntimeRecorder的实际配置、Prompt、工具Schema及实现摘要、run_id/request_id/session_id/chat_id/turn_id和真实终态。feature_id=N02，RuntimeContextBlock来源boss-conversation-context，business_authority_granted=false。conversation_context包含input_sha256/allowed_call_refs/references，以及client_request_id/media_sha256/attachment_refs/required_input_count；attachment_refs仅含attachment_id/content_sha256/processing_state，没有名称、路径或正文。

工具结果记录实际tool_call_id、parameters_sha256/result_sha256及来源标识。正式存储核查后记录query_id/task_id/list_id/message_id/draft_id与适用版本。query_metrics追加QueryBinding.visible的bi_query_context、source_refs、definition_versions和detail_refs，排除原始问题。当前实际查询产物在后续模型步骤及结果释放前通过正式API重新核查并比较实际结果摘要。本人消息状态、任务状态和运行终态保持独立。

稳定client_request_id由chat_id及原生turn_id摘要生成。conversation_intent保存文字/媒体摘要、正式引用和运行关联；相同轮次相同内容enqueue=false，文字或媒体不同拒绝。新服务只能读取原回执，不能恢复进程内连接证明。receipt字段为source_type/client_request_id/outcome/request_state/run_id/chat_id/session_id/turn_id/write_performed_by_lookup/business_authority_granted，admit另有enqueue；write_performed_by_lookup=false。未知结果只读取原编号，不重新执行。

### C18/C19/C22原请求只读列表

requests在同一SQLite BEGIN快照中按ui-check和实际chat_id选择conversation_intent，连接启用query_only；逐项复用receipt的_receipt及_owner检查。输出与receipt具有相同安全字段，按实际created_at及id排序，client_request_id和turn_id保留原值。每项要求当前owner/dataset/version、规范session/chat和稳定轮次编号相符；返回前重新核查active、attach及当前资料身份。没有读取原生会话正文、来源正文或问题内容，没有创建Runtime、业务对象、审计或进程内proof。

合法但尚无记录的已attach会话返回[]，不创建Session或原请求。非法chat_id返回400，匿名/维护/过期认证拒绝，未attach或记录归属/资料版本不符拒绝；当前namespace无效沿用正式范围错误。列表包含实际ADMITTED、FAILED、CANCELED及Runtime状态；run_id尚不存在时保持null，不能据此推断已经入队或未执行。服务重建后沿用原编号读取，不恢复连接证明，不重新提交未知结果。公共调用必须使用当前服务端role、attached、active，不能采用客户端声明的身份或资料字段。

Hook在实际工具错误时保存工具/调用编号和异常类型并终止。失败、取消、超时保留原运行与已保存对象，未知usage/cost_total/price_version保持null。存在required_inputs时，成功结束的运行记为WAITING_INPUT、stop_reason=required_input并保留finished_at，允许下一条本人输入。模型不能签发本人授权；本人写入/发送的匹配资格由正式共享领域判断。

## N3公共接收要求

1. RoleChannel/application保持当前本人连接、attach、token与过期检查。原生/stop及SDK非Agent命令保留原路径；NativeMorningAdapter优先。一般message在router之前调用admit，摘要取自实际envelope.media。enqueue=false时只读取原编号及实际历史，禁止重复入队。
2. 原生上传实际成功后，在webui_dispatch_message发布本轮消息之前，传递实际已接受media和gateway返回paths调用record_media。可使用当前请求的ContextVar传递可信帧数据；失败、取消或没有入队时finish。媒体原始数据及路径不进入普通日志、URL或回执。
3. Context顺序采用晨间native_context、一般agent.native_context、现有配置/Skills/Memory与专有scope、agent.scope_context及对应Recorder。后续provider使用agent.guard_context处理准备失败。CONVERSATION_REQUEST只能由native_context建立。
4. FeatureProvider/FeatureRecorder在agent.handles(request)时分别委托agent.provider和agent.recorder.context，采用同一AgentLoop、SessionManager、实际Registry和原生传输；不另行调用bot.run。
5. 当前一般范围为CONVERSATION_TOOLS七项。六项只读的公共同名工具保留既有正式分支；query_metrics使用agent.tools()返回的ConversationQueryTool及其实际Fc02上下文。公共同名适配必须保持ConversationReadTool子类，且提供当前实际delegate，不能仅修改名称。其他业务请求继续进入原有合法工具分支。
6. 配置实际启用全部七项，max_tool_rounds至少为本次plan.calls数量加一。Recorder核查Registry实际集合与当前allowed_tools完全一致，模型只能看到该集合。query_metrics已存在于公共配置名称集合；本模块没有新增本人写入工具。
7. 公共runtime-records.schema.json接收feature_id=N02、conversation_context以及实际tool_results的parameters_sha256和已有Fc02的bi_query_context/source_refs/definition_versions/detail_refs。附件投影采用Schema1.1.0的四状态、nullable字段与recorded_*字段。公共Schema、配置、注册及实际候选检查由N3完成。
8. 当前会话原请求读取调用agent.requests(role, chat_id, attached=当前连接采用核查, active=当前本人有效认证核查)。返回数组逐项保持上述receipt字段；公共Schema、路由和前端读取由N3接收。本接口不注册为模型工具，不恢复或执行列表中的原请求。

公开原编号端点、实际WebSocket接收/重连/停止、阅读位置与焦点、UI完整设计及全部26项由N3对准确候选验证。本人草稿/发送/回复及任务共享流程需要完整产品消费证据，本模块检查不代替这些验收。复杂或不明确自然条件明确保持待补充；未支持的其他业务动作仍需相应正式输入及领域能力。F01设计返修、STT暂停及用户验收状态继续保持独立。

## 当前限定验证

consumer-runtime.xml对应依赖validation/.work/n02-consumer-public，准确2260000b89414727afcf2720bfa993fc7a601296。附件模块blob=045e78b53a1c1eb8dce78edcec07c26ff37692ea；conversation.schema.json blob=6595d986b7bf47a540899c973be9086b0c010f10；Fc02Tool blob=4b3ce9f0ab422bbca5e3c2e28b5eb8de932b62fa；boss_bi_queries.py blob=70a667719797634bfcb0989c07a90da33cfeb85b。

conftest.py使用标准importlib加载当前N2被测package，其余领域、工具与SDK来自准确候选，没有替代依赖。检查使用实际ControlStore.initialize批准selection资料、WebUIMediaGateway、Nanobot/AgentLoop、SessionManager、Fc02Tool和RuntimeRecorder。SessionManager均显式指定独立sessions_root；SQLite、媒体和会话位于本目录已忽略validation/.work。测试文件采用仓库已有真实文件字节，没有虚构企业事实或业务值。

BDD：Given当前本人、正式来源与明确范围；When连续输入不同来源、补充缺失条件或改变查询期间/产品/指标；Then实际工具参数、正式快照、父查询与结果随输入变化，实际query_id可从当前会话产物重读。Given仅附件输入及实际成功上传；When SDK保存普通文档且user.media为空；Then正式元信息保持可读，等待用途，后续输入继续；文件变化或缺失停止采用。Given SDK非Agent命令、晨间绑定、参数越界、失效连接或来源撤销；When进入相应路径；Then无额外一般意图、无越权查询或结果释放，原编号与真实终态可读。

当前consumer-runtime.xml为41 passed、15.28秒，模块状态MODULE_CHECKS_PASSED；覆盖上述行为及受影响的可信读取、Runtime、原意图幂等、同键异内容、维护拒绝、重建服务回执、取消/超时、本人实际草稿和明确模拟发送后的正确消息编号。既有read-runtime.xml及native-runtime.xml分别保留原限定范围，不将数量相加登记菜单完成。

```bash
env PYTHONDONTWRITEBYTECODE=1 CONVERSATION_DOMAIN_ROOT=/Users/liuhaoxian/.codex/worktrees/boss-sop-writes/Boss-Agent/validation/.work/n02-consumer-public validation/.venv/bin/python -m pytest app/tests/conversation_agent -q -p no:cacheprovider --basetemp=validation/.work/n02-consumer-receive --tb=short --junitxml=docs/menu-delivery/N02/consumer-runtime.xml
```

本次request-history.xml为54 passed、17.80秒，包含13项原请求定向用例和受影响的原41项。依赖validation/.work/n02-requests-public准确1b7a7fa0c72e176df746ca3d3e0e90993604e6e0；boss_conversation.py blob=334de8f8f188dc342188447606380283e6fbe34d，boss_conversation_references.py blob=2164498b428c1e59595358c8b09e16764c1bbec3，conversation.schema.json blob=22aa46f993b76f3db618fc063ea81fc3d88a46af，role_channel.py blob=456f1cd1748425dfb3e7b64d219cdf11b83d8d86。N1领域及公共文件仅作为只读依赖，当前扩展没有修改这些文件。

Given真实SDK已运行、实际admit后准备失败、明确运行前取消及尚未运行原请求；When当前本人读取同一chat列表并重建同库服务再次读取；Then原client_request_id/turn_id及真实状态相同，尚无运行保持null，其他chat不混入，进程内proof没有恢复。Given匿名/维护、未attach、过期或技术归属被篡改；When请求列表；Then正式拒绝。所有对象按namespace/kind计数、spaces、idempotency及audit数量在成功、空集合、拒绝及重建读取前后保持相同；技术归属拒绝使用实际admit产生的记录，没有虚构Runtime或替代生产依赖。

```bash
env PYTHONDONTWRITEBYTECODE=1 CONVERSATION_DOMAIN_ROOT=/Users/liuhaoxian/.codex/worktrees/boss-sop-writes/Boss-Agent/validation/.work/n02-requests-public validation/.venv/bin/python -m pytest app/tests/conversation_agent -q -p no:cacheprovider --basetemp=validation/.work/n02-requests-delivery --tb=short --junitxml=docs/menu-delivery/N02/request-history.xml
```

所有检查socket.connect由审计拒绝，没有外部请求、凭据读取或产品服务启动。MVP的9961/9962/19961、UI02的10411/10412/20411、F01的10611/10612/20611及其源码、资料、制品和进程保持。FR-27/STT/F27/FC28暂停，没有视觉或用户验收。当前提交范围仅包含本模块、用例、主记录及其限定证据。
