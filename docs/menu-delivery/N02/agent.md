# MENU-N02-N2 聊天交办Agent开发记录

task_id=MENU-N02-N2；marker=MENU-N02-N2-NATIVE-20261024；decision_id=D-MENU-DELIVERY-20261024。当前一般原生规划、可信读取、原意图与Runtime模块版本1.1.0，限定检查通过。非图像附件的实际SDK保存引用仍有必要领域接收条件。N02完整26项及正式状态由N3维护，本记录不登记完整菜单或用户验收通过。文档有效性CURRENT，核查日期2026-10-24。

## 依据与当前公共采用

已重新完整读取适用AGENTS、原始N02完整26项工单、PRD最前当前决定、FR-08/24/29及相应BR/AC、共同BR-C01—C07/E01—E06；读取原N02 HTML及其配置、原始提示词线索和实际design-v6-panels.js的chat区域。设计要求包括历史会话、当前事项/版本、连续输入、执行/任务/产物、依据及异常；暂停语音保持独立。LLD的当前请求、来源/版本、配置、同一Runtime和技术日志规则继续采用。

当前PRODUCT准确候选为e5724eb。F01 NativeMorningAdapter、公共Registry采用、同会话连续讨论及原生停止已经接收。公共ProductMorning/FeatureProvider/FeatureRecorder、RoleChannel和application由N3唯一维护，一般原生请求需要采用本文明确接口并完成公共候选验证。

当前已采用N1准确5f2138234353c5c224b3d0034d4c1565e6e8939b及PRODUCT接收e5724eb，完整读取backend.md、boss_conversation.py、boss_conversation_attachments.py及conversation.schema.json 1.0.0。会话/运行/产物、本人消息历史及媒体元数据使用这些正式接口；不建立另一份消息状态或第二个模型循环。现有本人草稿/明确发送/回复及任务共享流程保持。D-UI-FIDELITY-20261024由N3恢复当前N02设计，F01设计返修继续作为进入N03前必要工作，原业务证据保留。

## 当前模块与明确接口

模块为validation/conversation_agent；检查为app/tests/conversation_agent。当前正式读取集合为bossDashboardRead、bossTasksRead、bossMeetingsRead、bossEvidenceRead、bossWorkspaceRead和conversationRead，均要求同库_BossPageReadTool及read_only=true。conversationRead的严格projection为runs/messages/attachments/artifact/record；artifact使用N1的run_id/kind/id，record仅按实际本人任务或消息历史中已有的task/message/message_draft编号读取。未加入发送、审批、本人确认或授权签发工具；本人消息写入与任务变更采用现有合法共享入口。

| 构造器或方法 | 当前明确输入与行为 |
|---|---|
| ConversationContext | frozen dataclass；role/owner_id/namespace/dataset_id/dataset_version/request_id/session_id/chat_id/turn_id/active/input_sha256/allowed_tools/allowed_calls/references |
| ConversationScope(store, context_provider, context_validator) | context_provider(request)从服务端当前身份与原生请求生产ConversationContext；context_validator(context)必须通过实际领域核查并返回True，不能使用客户端字段或固定True代替当前资料检查 |
| scope.current(request=None, *, require_runtime=True) | 核查BOSS、当前active、规范websocket会话、原文摘要、本人资料范围、当前引用和实际RuntimeBinding；来源/身份变化在当前步骤终止 |
| ConversationReadTool(delegate, scope) | delegate必须为同库正式只读工具；保持实际Schema和参数类型，执行前要求(tool_id,checksum(params))属于本次allowed_calls，执行后重新核查当前范围 |
| register_conversation_reads(registry, delegates, scope) | 注册独立读取集合；名称重复或不合法时在任何Registry修改之前拒绝。公共同名工具的兼容分支由N3接收 |
| ConversationSimulatedProvider(event_producer, scope) | event_producer为async(messages,tools)->真实LLMResponse；只接收当前真实Registry集合，消费实际工具结果，调用前后重新核查scope；没有网络客户端 |
| ConversationRuntimeRecorder(scope, registry, runtime_snapshot, *, intent_adapter=None) | runtime_snapshot()读取当前实际启用配置；context(request)建立真实RuntimeBinding及技术引用，hook_factory(context)返回ConversationRuntimeHook；NativeConversationAgent自动采用intent_adapter |
| NativeConversationAgent(store, registry, runtime_snapshot, attachments) | attachments为N1的ConversationAttachments，使用同一个实际SessionManager及获准媒体目录；提供scope/provider/recorder/delegates及tools()实际读取适配集合 |
| agent.admit(role, chat_id, turn_id, content, *, media_sha256, attached, active) | media_sha256为实际原生media字段的checksum；attached(chat_id)与active()由当前连接生产；返回enqueue及原编号回执；/stop和已有晨间绑定返回None |
| agent.record_media(role, key, accepted_media, accepted_paths, *, active) | 原生上传成功后的内部调用，复用N1.record_upload保存实际元信息；不作为接收客户端路径的公开动作，不注册模型工具 |
| agent.native_context(request) / scope_context(request) | 规范websocket身份、当次原文/媒体摘要及连接证明通过后规划实际工具；采用当前六项FEATURE_SCOPE；配置轮次不足时就地拒绝 |
| agent.receipt(role, key, *, active) | 原编号只读；RECORDED或NOT_FOUND_IN_CURRENT_STORE；返回request_state/run_id/chat_id/session_id/turn_id，write_performed_by_lookup=false；不重放原意图 |
| agent.guard_context(provider) / finish(key, *, status="FAILED") | 包装公共provider的前置失败清理；未运行的明确取消可以使用CANCELED，已经运行的终态沿用实际Runtime，不伪造原生停止 |

allowed_tools为frozenset工具名；allowed_calls为frozenset((tool_id,parameters_sha256))；references为tuple((kind,id,version))，其中version可为None。引用使用现有正式对象标识与版本，不接受正文。input_sha256取自当前request.original_user_text；请求/会话/轮次标识必须来自实际原生消息和当前服务端身份。request_id在实际RuntimeBinding存在时使用其request_id，建立记录前使用当前request.message_id或request.turn_id，与现有Recorder规则一致。上下文不由模型参数反向签发。

NativeConversationAgent提供当前可信生产者与核查器。ConversationPlanner根据本次实际输入和当前正式资料目录选择来源、概览、任务、会议、消息、运行、附件或已有产物；来源ID/名称及任务/消息/产物编号均从实际资料或正式结果采用。连续来源讨论保留最后一次实际选择，历史来源在后续模型步骤继续核查。支持的读取条件改变实际参数；经营计算条件、消息写入、任务变更或不明确对象返回具体required_inputs并采用现有共享入口，没有预设业务成功。附件元数据保持独立，不能作为业务来源授权。

## Runtime、原编号、取消与隐私

Recorder复用当前RuntimeRecorder/Fc01RuntimeRecorder的实际配置版本、Prompt、工具Schema及实现摘要、run_id/request_id/session_id/chat_id/turn_id和真实终态。feature_id=N02，RuntimeContextBlock来源boss-conversation-context，business_authority_granted=false。conversation_context保存input_sha256、allowed_call_refs、references，以及client_request_id/media_sha256/attachment_refs/required_input_count。attachment_refs仅含attachment_id/content_sha256/processing_state；不包含名称、路径或正文。工具结果记录实际tool_call_id、source_id/version、parameters_sha256和result_sha256；正式产物按真实存储核查后记录query_id/task_id/list_id/message_id/draft_id及适用版本。

真实Nanobot继续保存本人原生会话历史；同一会话的新问题形成新的实际运行。稳定client_request_id由chat_id/原生turn_id摘要生成，conversation_intent保存文字与实际media字段的摘要、正式引用及运行关联。相同轮次同内容enqueue=false，不再进入SDK；文字或媒体变化拒绝。新服务只能读取原回执，不能凭session_id恢复进程内认证证明。重复解析同一实际RequestContext复用原RuntimeBinding；已有完成运行不会重新记为RUNNING。公开重连与Native客户端的实际接收仍由N3验证。

Hook在实际工具错误时只记录工具/调用编号与异常类型并终止，失败、取消、超时保留原运行和已保存对象；未知usage/cost_total/price_version保持null。required_inputs存在时运行记为WAITING_INPUT、stop_reason=required_input并保存finished_at，允许本人提交下一条真实输入。Provider释放结果前及下一步骤核查身份、来源、实际媒体及历史产物当前资格；产物摘要采用实际业务data，依据每次继续由正式API重新核查。原生/stop直接返回既有命令路径，没有额外意图、业务查询或模拟取消运行。

## N3公共接收与实际依赖

RoleChannel/application中的当前本人连接、attach、token与过期检查继续负责原生请求采用。先处理原生/stop，再保留NativeMorningAdapter优先路径；晨间已绑定会话不建立N02意图。一般message在原生router之前调用agent.admit，media_sha256取自实际envelope.media。返回enqueue=false时只读恢复并核查原生历史，禁止再次入队。N2的CONVERSATION_REQUEST仅由native_context生成，不能从客户端JSON或模型参数建立。其他已交付专有SDK请求保持当前合法分支。

原生上传成功后，在webui_dispatch_message将实际媒体入队之前，使用本轮admission、原始已接受media及原生返回paths调用record_media。N3可以在当前原生入口的ContextVar中暂存该帧已接受数据；失败/取消或未实际入队时调用finish。原始数据和路径不进入普通日志、URL或回执。实际SessionManager必须与AgentLoop相同，ConversationAttachments使用当前获准媒体目录；检查中显式指定独立sessions_root。

FeatureToolRegistry在Recorder之前按本次allowed_tools设置FEATURE_SCOPE。公共同名读取需要保留既有路径：可以由N3以ConversationReadTool子类接收当前实际只读delegate，并在非N02请求明确转给现有正式工具；新N02范围需要实际执行该读取适配，不能只修改工具名称。Recorder要求实际Registry.get返回ConversationReadTool实例或其子类，且真实集合等于当前allowed_tools。运行时Provider只采用该集合。

FeatureProvider/FeatureRecorder在agent.handles(request)时分别委托agent.provider和agent.recorder.context，使用同一个AgentLoop和现有原生传输。公共context顺序为晨间native_context、一般agent.native_context、现有配置/Skills/Memory、各专有scope、agent.scope_context及对应Recorder；后续provider由agent.guard_context包装以清理运行前失败。agent.provider读取当前真实规划与本轮实际工具消息后产生回答，不能同时调用ProductMorning.execute或另建第二轮SDK。

公共runtime-records.schema.json需要接收feature_id=N02及可选conversation_context。该对象字段为input_sha256、allowed_call_refs、references，以及可选client_request_id/media_sha256/attachment_refs/required_input_count；参数和媒体摘要均为SHA256，attachment_refs中content_sha256可为null，processing_state为N1正式状态。工具结果采用现有实际产物编号字段并追加parameters_sha256。intent回执严格字段为source_type/client_request_id/outcome/request_state/run_id/chat_id/session_id/turn_id/write_performed_by_lookup/business_authority_granted，admit另有enqueue。公共Schema、配置、实际注册和运行/产物投影由N3维护。

本人发送与任务决定继续采用已有正式共享入口，当前有效授权是否匹配由原领域判断，模型不代签。新模块只从正式返回结果保存产物编号；message_outbox和交办outbox分别核查，消息状态、送达、回复和业务任务独立。当前没有新增消息写入动作。原生交接、阅读位置/焦点、公开原编号端点和实际停止、全部异常、UI及完整26项仍需N3准确候选验证。

### 非图像附件的必要领域接收条件

实际SDK的_restore_turn调用reference_non_image_attachments，将非图像附件转为文本引用并保留image_paths。当前N1 ConversationAttachments.read仅遍历已保存user.media。实际成功上传JSON文件后，N1保存的原名/MIME/大小/摘要存在，原生用户media集合为空；该路径当前在模型步骤之前触发媒体引用冲突，运行保留FAILED及原编号，没有工具采用或业务变更。

N1/N3需要通过可信原生保存流程保留非图像附件的实际引用，使正式附件投影能够同时读取SDK的文件引用和图像media；必须采用真实上传结果、实际Session、获准媒体目录与字节摘要，继续排除任意客户端路径。本模块没有向Session伪造media或跳过当前核查。必要复现为test_non_image_sdk_without_saved_media_reference_fails_without_claiming_processed_source；当前原生检查对已保存图像媒体元数据有效，非图像路径需要接收新的准确领域版本。该项属于当前N02.C06/C22必要依赖，不能据全部模块检查通过登记菜单完成。

## 限定检查与证据

隔离候选validation/.work/n02-agent-public为准确d0e6326，N2模块从当前自己目录导入；使用真实ControlStore.initialize的批准selection资料、BossPageAPI、BossEvidenceReadTool、ToolRegistry、Nanobot/AgentLoop和RuntimeRecorder。技术配置仅启用实际bossEvidenceRead。检查事件生产者处理自然文本中明确提供的真实来源ID，并将变化后的ID传给实际source参数，再从实际工具消息产生回答；该限定用例不代表完整自然语言规划能力。

BDD：Given当前本人、有效来源及明确读取对象；When在同一原生会话连续提出读取不同实际资料的问题；Then参数和结果版本随输入变化，真实工具调用及摘要对应当前run，原始输入保留在本人会话，技术日志没有问题或原文。Given维护/伪造范围/不同模型参数/来源或身份撤销；When当前步骤继续；Then模型和工具拒绝采用不符范围，失败/取消/超时原记录可重读且无业务写入。

```bash
env PYTHONDONTWRITEBYTECODE=1 CONVERSATION_DOMAIN_ROOT=/Users/liuhaoxian/.codex/worktrees/boss-sop-writes/Boss-Agent/validation/.work/n02-agent-public validation/.venv/bin/python -m pytest app/tests/conversation_agent/test_runtime.py -q -p no:cacheprovider --basetemp=validation/.work/n02-agent-delivery --junitxml=docs/menu-delivery/N02/read-runtime.xml
```

原读取阶段为12 passed、10.69秒，证据read-runtime.xml保留其d0e6326范围。当前原生组合validation/.work/n02-native-public为准确e5724eb，boss_conversation.py blob=24fabc547c2cb07ed53a0c864fb383ae7a720039，boss_conversation_attachments.py blob=1ebe75e83a56574a6c65f06748010b438d5ec622，conversation.schema.json blob=44e45d664b359f10c725cc8a8d449a7b78609b14。

当前native-runtime.xml覆盖一般原生及受影响读取检查：连续不同来源与最后选择、正式消息/联系人、真实上传元信息及业务来源等待、原意图重复与异内容、同会话新输入、晨间优先、零额外/stop意图、维护/失效连接拒绝、重建服务原回执、取消/超时、实际SDK查询产物与撤销、本人实际草稿/发送后的正确存储编号、运行前明确取消，以及非图像路径的准确停止。查询由真实Fc02Tool与SDK产生，消息由实际本人BossCommandAPI保存/发送，模型读取没有新增授权或发送记录。产物均可由N1 ConversationAPI重读。

测试使用标准importlib加载当前N2被测package，其余领域、工具和SDK来自准确候选；没有替代依赖。所有SessionManager均使用显式独立sessions_root，不使用用户会话。媒体检查只读取仓库已有资产的字节及元数据，没有执行图像查看或视觉判断。

```bash
env PYTHONDONTWRITEBYTECODE=1 CONVERSATION_DOMAIN_ROOT=/Users/liuhaoxian/.codex/worktrees/boss-sop-writes/Boss-Agent/validation/.work/n02-native-public validation/.venv/bin/python -m pytest app/tests/conversation_agent -q -p no:cacheprovider --basetemp=validation/.work/n02-native-accepted --tb=short --junitxml=docs/menu-delivery/N02/native-runtime.xml
```

当前结果为28 passed、17.94秒，native-runtime.xml记录对应结果。没有启动产品服务、读取凭据或用户体验资料，没有外部请求，socket.connect由检查审计拒绝。中间目录已由validation/.work忽略。MVP996x、UI02104xx、F01106xx及其制品/数据保持；FR-27/STT/F27/FC28暂停，视觉及用户验收未执行。
