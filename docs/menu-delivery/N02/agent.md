# MENU-N02-N2 聊天交办Agent开发记录

task_id=MENU-N02-N2；marker=MENU-N02-N2-OBSERVABLE-FAILURE-20261025；decision_id=D-MENU-DELIVERY-20261024。当前模块版本1.2.0，包含原请求只读列表、本轮必要引用及实际配置截止；本次只增加可观察字段与失败行为的限定用例及记录。N02完整26项及正式状态由N3维护specs/feature-delivery.json，本记录只登记Agent模块及准确消费证据，不登记完整菜单或用户验收通过。文档有效性CURRENT，核查日期2026-10-25。主记录路径及既有索引引用保持。

## 当前依据与准确依赖

本次可观察字段及失败行为的准确候选为PRODUCT e31370e9c9cac27187016ebb736b9c9cf889ed1b，包含4836527的公共接收及当前实际N1与Fc02接口。独立依赖目录validation/.work/n02-observable-public从该准确提交检出正式validation、specs与仓库资产；使用既有conftest加载当前N2被测模块，生产依赖保持原值。公共ProductMorning/FeatureProvider/FeatureRecorder、RoleChannel、application、Schema和App由N3唯一维护；本目录没有修改这些文件，也没有启动产品或预览。D-UI-FIDELITY-20261024及F01设计返修继续由N3处理，进入N03前的必要条件保持。

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

ConversationPlanner根据当次输入和实际目录选择来源、概览、任务、会议、消息、运行、附件、已有产物或经营查询。来源ID/名称及任务/消息/产物编号均从正式资料采用。本轮references只包含实际工具需要的来源，独立任务或明确新资料不要求无关历史资料继续有效。来源、对象不明确时返回具体required_inputs；消息写入和任务变更使用现有合法共享入口。附件元信息不授予业务来源资格。

### C07/C20本轮必要依据与明确沿用

native_context读取历史意图的技术引用供选择，旧意图及原运行保持原值；当前规划从空references和artifact_checks建立本轮范围。明确读取来源按完整编号或实际名称选择当前正式版本；“继续核查这份资料”等指向此前资料的输入采用最后明确选择的来源及其固定版本，失效时停止。独立输入不会更改该明确来源选择；本人明确读取新资料后，后续指向该资料的输入采用新选择。

conversation_intent内部last_source_ref仅保存kind/id/version，用于保持明确选择的版本，公开回执字段保持。旧格式没有该字段时，从真实runtime_run中bossEvidenceRead的已保存source_id/version核查此前选择，不采用消息或其他无关对象的来源版本替换该选择；不补写旧记录。当前引用仍通过正式来源政策及固定版本核查，没有新增权限或来源恢复。

产物按本轮实际选择的kind/id保留原摘要检查，再由正式API核查当前资格；同一产物在多个运行中的引用按kind/id归为同一对象，采用其实际运行引用。独立输入不采用无关旧产物，明确继续原产物仍要求已记录摘要一致。经营追问的正式父查询、参数继承及当前产物摘要核查继续适用。单对象消息只采用该正式草稿或发送消息的有效来源；完整消息历史投影采用实际返回内容需要的有效来源。附件当前采用、身份和配置核查保持。

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

### C09/C19可观察步骤与真实失败

当前NativeConversationAgent.events只产生实际正文与正式工具调用，LLMResponse没有reasoning_content载荷。实际SDK虽然提供推理事件接口，本次核查只检查当前生产者是否具有该字段载荷及事件类型，不索取、构造、注入或保存内部推理内容。实际RunStream事件集合为run.started/run.completed、tool.started/tool.completed、text.delta/text.completed；原生on_progress的实际工具开始/结束字段没有reasoning或reasoning_end标记。已保存Session消息和实际工具结果按SDK定义字段核查，没有reasoning_content载荷。该结论限于当前N02生产者和本次实际SDK会话，不代表所有SDK Provider。

工具保存后的后续输出失败由真实关闭的OS管道触发：同一Nanobot/AgentLoop通过正式AgentLoop.process_direct(on_stream=...)产生真实回答，接收端已关闭，实际os.write产生BrokenPipeError。回调进入前，正式query_metrics结果及query_id已经保存。SDK沿实际异常路径结束为FAILED、stop_reason=error；tool_results保留已完成一步，没有业务工具失败记录，原查询和原请求可在同库重建服务后读取。没有替换LLMResponse、工具结果、业务数据或成功文案。这份证据属于SDK输出回调路径，公开WebSocket与界面接收由N3维护。

正式工具失败使用获准资料中实际期间的反向起止作为明确无效输入。Fc02Tool采用当前合法绑定并调用正式query_metrics，领域产生HTTPBadRequest；记录器保存实际tool_id/tool_call_id/error_type/source_type后终止，运行FAILED、stop_reason=error，当前tool_results为空，没有新查询或替代结果。前一轮已经完成的查询、运行和正式产物保持原值并可重读。

轮次限制使用RuntimeValues正式校验的隔离配置max_tool_rounds=1，测试Config、实际AgentLoop与当前配置快照保持一致，并保存原配置版本。需要一次工具及最终回答时，scope_context在Runtime建立前正式拒绝，guard_context将原意图记为FAILED、run_id=null；前一轮已保存查询与运行保持可读。没有把准备阶段拒绝登记为SDK max_iterations运行中耗尽。合法Native规划为有限的plan.calls加最终回答，入口要求实际配置至少为len(plan.calls)+1；当前没有构造额外模型响应来强行进入轮次耗尽路径。该SDK路径本次未执行。

本次没有修改生产模块、字段、签名或公共注册。实际采用接口为Nanobot.run_streamed/RunStream.stream_events、AgentLoop.process_direct(on_progress/on_stream)、既有NativeConversationAgent和RuntimeRecorder。失败仍使用既有status/stop_reason/tool_results/tool_errors，以及原请求request_state/run_id/client_request_id；没有新增状态或恢复执行入口。

### C17/C19正式SDK取消与实际配置截止

当前ProductRuntime._apply和公开配置将timeout固定为120秒，RuntimeRecorder在采用时核查启用配置与snapshot一致，并将timeout保存在本轮runtime记录。ConversationRuntimeHook.before_run在实际状态进入RUNNING后，从该记录取得有限正数timeout，以事件循环单调时钟固定本轮截止点。ConversationSimulatedProvider使用asyncio.timeout_at约束真实事件等待，各模型步骤共用该截止点；后续步骤不重新获得120秒。截止只保存在Recorder内部按run_id区分，终态后清理对应记录，不增加公开参数、模型工具或Schema字段。

到达截止时，由asyncio实际定时触发TimeoutError，SDK Runner沿正式异常路径记录TIMED_OUT、stop_reason=error并执行原意图清理。没有在事件生产者手工抛出TimeoutError或写入预设终态。本模块的截止检查发生在模型阶段；已经完成的同步工具及其正式结果保留，后续SDK保存和传输采用原路径。当前事件生产者、模型、工具与业务数据保持实际来源。

SDK控制采用Nanobot.run_streamed返回的正式RunStream.cancel()。外部取消保持实际CancelledError，Runner记录CANCELED、stop_reason=cancelled；只清理目标run_id的截止及原意图proof。两个会话共用同一Nanobot/AgentLoop时，另一会话可以继续完成。原生/stop继续使用已有公共路径，本次实际控制证据明确限定为SDK取消入口。

## N3公共接收要求

1. RoleChannel/application保持当前本人连接、attach、token与过期检查。原生/stop及SDK非Agent命令保留原路径；NativeMorningAdapter优先。一般message在router之前调用admit，摘要取自实际envelope.media。enqueue=false时只读取原编号及实际历史，禁止重复入队。
2. 原生上传实际成功后，在webui_dispatch_message发布本轮消息之前，传递实际已接受media和gateway返回paths调用record_media。可使用当前请求的ContextVar传递可信帧数据；失败、取消或没有入队时finish。媒体原始数据及路径不进入普通日志、URL或回执。
3. Context顺序采用晨间native_context、一般agent.native_context、现有配置/Skills/Memory与专有scope、agent.scope_context及对应Recorder。后续provider使用agent.guard_context处理准备失败。CONVERSATION_REQUEST只能由native_context建立。
4. FeatureProvider/FeatureRecorder在agent.handles(request)时分别委托agent.provider和agent.recorder.context，采用同一AgentLoop、SessionManager、实际Registry和原生传输；不另行调用bot.run。
5. 当前一般范围为CONVERSATION_TOOLS七项。六项只读的公共同名工具保留既有正式分支；query_metrics使用agent.tools()返回的ConversationQueryTool及其实际Fc02上下文。公共同名适配必须保持ConversationReadTool子类，且提供当前实际delegate，不能仅修改名称。其他业务请求继续进入原有合法工具分支。
6. 配置实际启用全部七项，max_tool_rounds至少为本次plan.calls数量加一。Recorder核查Registry实际集合与当前allowed_tools完全一致，模型只能看到该集合。query_metrics已存在于公共配置名称集合；本模块没有新增本人写入工具。
7. 公共runtime-records.schema.json接收feature_id=N02、conversation_context以及实际tool_results的parameters_sha256和已有Fc02的bi_query_context/source_refs/definition_versions/detail_refs。附件投影采用Schema1.1.0的四状态、nullable字段与recorded_*字段。公共Schema、配置、注册及实际候选检查由N3完成。
8. 当前会话原请求读取调用agent.requests(role, chat_id, attached=当前连接采用核查, active=当前本人有效认证核查)。返回数组逐项保持上述receipt字段；公共Schema、路由和前端读取由N3接收。本接口不注册为模型工具，不恢复或执行列表中的原请求。
9. 当前实际配置截止由同一ConversationRuntimeRecorder/Hook/Provider执行，N3现有注册接口继续接收本模块；每个实际运行采用其已保存timeout。截止内部状态没有公开字段，也不恢复为可执行原请求。公开停止入口与完整菜单证据由N3维护。

公开原编号端点、实际WebSocket接收/重连/停止、阅读位置与焦点、UI完整设计及全部26项由N3对准确候选验证。本人草稿/发送/回复及任务共享流程需要完整产品消费证据，本模块检查不代替这些验收。复杂或不明确自然条件明确保持待补充；未支持的其他业务动作仍需相应正式输入及领域能力。F01设计返修、STT暂停及用户验收状态继续保持独立。

## 当前限定验证

consumer-runtime.xml对应依赖validation/.work/n02-consumer-public，准确2260000b89414727afcf2720bfa993fc7a601296。附件模块blob=045e78b53a1c1eb8dce78edcec07c26ff37692ea；conversation.schema.json blob=6595d986b7bf47a540899c973be9086b0c010f10；Fc02Tool blob=4b3ce9f0ab422bbca5e3c2e28b5eb8de932b62fa；boss_bi_queries.py blob=70a667719797634bfcb0989c07a90da33cfeb85b。

conftest.py使用标准importlib加载当前N2被测package，其余领域、工具与SDK来自准确候选，没有替代依赖。检查使用实际ControlStore.initialize批准selection资料、WebUIMediaGateway、Nanobot/AgentLoop、SessionManager、Fc02Tool和RuntimeRecorder。SessionManager均显式指定独立sessions_root；SQLite、媒体和会话位于本目录已忽略validation/.work。测试文件采用仓库已有真实文件字节，没有虚构企业事实或业务值。

BDD：Given当前本人、正式来源与明确范围；When连续输入不同来源、补充缺失条件或改变查询期间/产品/指标；Then实际工具参数、正式快照、父查询与结果随输入变化，实际query_id可从当前会话产物重读。Given仅附件输入及实际成功上传；When SDK保存普通文档且user.media为空；Then正式元信息保持可读，等待用途，后续输入继续；文件变化或缺失停止采用。Given SDK非Agent命令、晨间绑定、参数越界、失效连接或来源撤销；When进入相应路径；Then无额外一般意图、无越权查询或结果释放，原编号与真实终态可读。

consumer-runtime.xml记录41 passed、15.28秒的限定范围，模块状态MODULE_CHECKS_PASSED；覆盖可信读取、Runtime、原意图幂等、同键异内容、维护拒绝、重建服务回执、取消/超时终态映射、本人实际草稿和明确模拟发送后的正确消息编号。既有read-runtime.xml及native-runtime.xml分别保留原限定范围，不将数量相加登记菜单完成。

```bash
env PYTHONDONTWRITEBYTECODE=1 CONVERSATION_DOMAIN_ROOT=/Users/liuhaoxian/.codex/worktrees/boss-sop-writes/Boss-Agent/validation/.work/n02-consumer-public validation/.venv/bin/python -m pytest app/tests/conversation_agent -q -p no:cacheprovider --basetemp=validation/.work/n02-consumer-receive --tb=short --junitxml=docs/menu-delivery/N02/consumer-runtime.xml
```

本次request-history.xml为54 passed、17.80秒，包含13项原请求定向用例和受影响的原41项。依赖validation/.work/n02-requests-public准确1b7a7fa0c72e176df746ca3d3e0e90993604e6e0；boss_conversation.py blob=334de8f8f188dc342188447606380283e6fbe34d，boss_conversation_references.py blob=2164498b428c1e59595358c8b09e16764c1bbec3，conversation.schema.json blob=22aa46f993b76f3db618fc063ea81fc3d88a46af，role_channel.py blob=456f1cd1748425dfb3e7b64d219cdf11b83d8d86。N1领域及公共文件仅作为只读依赖，当前扩展没有修改这些文件。

Given真实SDK已运行、实际admit后准备失败、明确运行前取消及尚未运行原请求；When当前本人读取同一chat列表并重建同库服务再次读取；Then原client_request_id/turn_id及真实状态相同，尚无运行保持null，其他chat不混入，进程内proof没有恢复。Given匿名/维护、未attach、过期或技术归属被篡改；When请求列表；Then正式拒绝。所有对象按namespace/kind计数、spaces、idempotency及audit数量在成功、空集合、拒绝及重建读取前后保持相同；技术归属拒绝使用实际admit产生的记录，没有虚构Runtime或替代生产依赖。

```bash
env PYTHONDONTWRITEBYTECODE=1 CONVERSATION_DOMAIN_ROOT=/Users/liuhaoxian/.codex/worktrees/boss-sop-writes/Boss-Agent/validation/.work/n02-requests-public validation/.venv/bin/python -m pytest app/tests/conversation_agent -q -p no:cacheprovider --basetemp=validation/.work/n02-requests-delivery --tb=short --junitxml=docs/menu-delivery/N02/request-history.xml
```

本次current-references.xml为59 passed、22.29秒，记录准确9c3caf80651fc74e1c0286fa5f946b96fc6d360e依赖下的当前引用组合，包含5项必要引用用例及受影响的54项。boss_conversation.py blob=334de8f8f188dc342188447606380283e6fbe34d，Fc02Tool blob=4b3ce9f0ab422bbca5e3c2e28b5eb8de932b62fa，附件模块blob=045e78b53a1c1eb8dce78edcec07c26ff37692ea。实际SDK、SQLite及正式control撤销证明finance-note撤销后独立任务与meeting-minutes读取成功，明确沿用finance-note停止；已有查询产物的独立输入成功，原产物及父查询追问停止；本人正式更新草稿后，独立任务成功，原产物摘要变化停止。原运行、原意图及历史引用逐项保持相同，旧格式来源版本由实际已保存运行取得。现有附件、身份、配置、取消、原编号和经营连续条件用例包含在同一受影响检查中。

```bash
env PYTHONDONTWRITEBYTECODE=1 CONVERSATION_DOMAIN_ROOT=/Users/liuhaoxian/.codex/worktrees/boss-sop-writes/Boss-Agent/validation/.work/n02-references-public validation/.venv/bin/python -m pytest app/tests/conversation_agent -q -p no:cacheprovider --basetemp=validation/.work/n02-references-final --tb=short --junitxml=docs/menu-delivery/N02/current-references.xml
```

本次sdk-cancel-deadline.xml为61 passed、143.86秒，包含2项实际SDK控制/计时及受影响的59项。准确依赖为validation/.work/n02-cancel-public的490ba0b041d91229bdf37a8e3c285d94c05b2069；product_runtime.py blob=de258204d4334c1b641de37dfdc7fc957d7a0eec，boss_runtime_records.py blob=302bfed77595c4fa00764641c305823f073216f3，runtime-records.schema.json blob=1f26bfc860afcd596895944d47354738a0b48ba4。实际已安装SDK的sdk/streaming.py SHA256=264004c9381e90ec2b79040b37cec3ac90366c8266a610329a180e39f953799a，agent/runner.py SHA256=72ecdd211827762f098da376b85f79f5722d6b506bf7935ce6b418c814864662。

Given同一实际Nanobot/AgentLoop中两个当前ConversationGrant和已完成的正式工具；When调用目标RunStream.cancel；Then目标为CANCELED，另一会话仍为RUNNING且能够完成，目标已保存tool_results保持，只有该轮原意图proof及截止被清理。当前实测cancel调用耗时0.008秒。Given本轮实际配置timeout=120且query_metrics已产生正式查询；When仅延迟后续真实事件释放；Then实际计时在120秒触发，SDK请求前至异常返回测得120.239秒，包含准备及收尾，运行终态TIMED_OUT。计时没有调整配置、替换LLMResponse、工具结果或业务数据。

两个场景中已执行步骤均为query_metrics，计划中的后续bossEvidenceRead(meeting-minutes)未执行；目标tool_results仅保留原一步，query只有实际一项，没有新增授权或任务。相同Store重建服务后，原client_request_id、run_id、query_id及真实终态可以重读，正式产物仍可由ConversationAPI.artifact读取，没有恢复proof或重新执行。另一会话的实际来源读取独立完成。轮次规划、轮次配置检查及SDK后续保存/表达路径没有本次行为修改，受影响的原59项随同验证。

```bash
env PYTHONDONTWRITEBYTECODE=1 CONVERSATION_DOMAIN_ROOT=/Users/liuhaoxian/.codex/worktrees/boss-sop-writes/Boss-Agent/validation/.work/n02-cancel-public validation/.venv/bin/python -m pytest app/tests/conversation_agent -q -p no:cacheprovider -o junit_family=xunit1 --basetemp=validation/.work/n02-cancel-delivery --tb=short --junitxml=docs/menu-delivery/N02/sdk-cancel-deadline.xml
```

本次observable-failure.xml为64 passed、1 deselected、26.72秒；包含4项可观察字段/失败场景及受影响检查。既有实际120秒截止用例没有本次代码影响，沿用sdk-cancel-deadline.xml及已接收的4836527范围，本组明确不重复该计时。当前没有修改conversation_agent生产代码。准确e31370e依赖中，conversation_agent/runtime.py blob=7745e5646cf3a029d427e13a07c5e3c1d63c81e5，boss_conversation_references.py blob=f6865ddeb97fd6106e17204884fc8b1aa7f1b890，boss_bi_queries.py blob=70a667719797634bfcb0989c07a90da33cfeb85b，product_runtime.py blob=de258204d4334c1b641de37dfdc7fc957d7a0eec。

Given实际当前Native生产者与正式工具；When通过RunStream及原生进度/正文回调执行；Then仅观察当前事件类型、字段和实际工具结果，历史无推理载荷，检查仅保存字段存在性的布尔值及可观察事件名称。Given正式查询已保存；When实际输出管道关闭；ThenFAILED并保留原query_id与工具结果。Given正式领域输入期间无效；When实际Fc02工具执行；Then保存真实HTTPBadRequest类型并停止，没有新增查询，原查询可读。Given隔离的正式轮次配置不足；When进入原生准备；Then原意图FAILED且run_id=null，旧运行及查询保持。四项均使用真实SQLite、SessionManager、Nanobot/AgentLoop、Registry与正式业务API；没有mock、人工抛出测试异常、伪造Runtime或替代依赖。

```bash
env PYTHONDONTWRITEBYTECODE=1 CONVERSATION_DOMAIN_ROOT=/Users/liuhaoxian/.codex/worktrees/boss-sop-writes/Boss-Agent/validation/.work/n02-observable-public validation/.venv/bin/python -m pytest app/tests/conversation_agent -q -p no:cacheprovider -o junit_family=xunit1 -k 'not actual_configured_deadline' --basetemp=validation/.work/n02-observable-delivery --tb=short --junitxml=docs/menu-delivery/N02/observable-failure.xml
```

所有检查socket.connect由审计拒绝，没有外部请求、凭据读取或产品服务启动。MVP的9961/9962/19961、UI02的10411/10412/20411、F01的10611/10612/20611及其源码、资料、制品和进程保持。FR-27/STT/F27/FC28暂停，没有视觉或用户验收。当前提交范围仅包含本模块、用例、主记录及其限定证据。
