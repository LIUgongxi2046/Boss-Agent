# MENU-N02-N2 聊天交办Agent开发记录

task_id=MENU-N02-N2；marker=MENU-N02-START-20261024；decision_id=D-MENU-DELIVERY-20261024。当前交接阶段为一般会话可信读取与Runtime，接口版本1.0.0。N02完整26项及正式状态由N3维护，本记录不登记完整菜单或用户验收通过。文档有效性CURRENT，核查日期2026-10-24。

## 依据与当前公共采用

已重新完整读取适用AGENTS、原始N02完整26项工单、PRD最前当前决定、FR-08/24/29及相应BR/AC、共同BR-C01—C07/E01—E06；读取原N02 HTML及其配置、原始提示词线索和实际design-v6-panels.js的chat区域。设计要求包括历史会话、当前事项/版本、连续输入、执行/任务/产物、依据及异常；暂停语音保持独立。LLD的当前请求、来源/版本、配置、同一Runtime和技术日志规则继续采用。

只读核查当前PRODUCT准确d0e6326bcca49a2c8372c476c50808d454076127。F01 NativeMorningAdapter、公共Registry采用、同会话连续讨论及原生停止已经接收；本N2分支缺少N3接收文件不作为未实现依据。公共ProductMorning/FeatureProvider/FeatureRecorder、RoleChannel和application仍由N3唯一维护。当前一般原生请求在没有专有GRANT时进入ProductFc01.events的引导分支；该分支不根据当次输入调用业务工具，不能作为N02完整采用证据。

当前N1正在形成ConversationAPI及会话/运行/业务产物、消息、来源和原生附件元数据投影，准确新增提交尚未接收。当前阶段只复用d0e6326中的正式读取语义，不预填N1新字段，不建立另一份消息状态或第二个模型循环。现有消息草稿/本人明确发送/回复、任务与交办的正式领域和合法共享流程保持。

## 当前模块与明确接口

模块为validation/conversation_agent；检查为app/tests/conversation_agent。当前正式读取集合为bossDashboardRead、bossTasksRead、bossMeetingsRead、bossEvidenceRead、bossWorkspaceRead，均要求同库_BossPageReadTool及read_only=true。未加入消息写入、发送、审批、本人确认或授权签发工具；既有本人合法业务入口不受本阶段读取集合改变。

| 构造器或方法 | 当前明确输入与行为 |
|---|---|
| ConversationContext | frozen dataclass；role/owner_id/namespace/dataset_id/dataset_version/request_id/session_id/chat_id/turn_id/active/input_sha256/allowed_tools/allowed_calls/references |
| ConversationScope(store, context_provider, context_validator) | context_provider(request)从服务端当前身份与原生请求生产ConversationContext；context_validator(context)必须通过实际领域核查并返回True，不能使用客户端字段或固定True代替当前资料检查 |
| scope.current(request=None, *, require_runtime=True) | 核查BOSS、当前active、规范websocket会话、原文摘要、本人资料范围、当前引用和实际RuntimeBinding；来源/身份变化在当前步骤终止 |
| ConversationReadTool(delegate, scope) | delegate必须为同库正式只读工具；保持实际Schema和参数类型，执行前要求(tool_id,checksum(params))属于本次allowed_calls，执行后重新核查当前范围 |
| register_conversation_reads(registry, delegates, scope) | 注册独立读取集合；名称重复或不合法时在任何Registry修改之前拒绝。公共同名工具的兼容分支由N3接收 |
| ConversationSimulatedProvider(event_producer, scope) | event_producer为async(messages,tools)->真实LLMResponse；只接收当前真实Registry集合，消费实际工具结果，调用前后重新核查scope；没有网络客户端 |
| ConversationRuntimeRecorder(scope, registry, runtime_snapshot) | runtime_snapshot()读取当前实际启用配置；context(request)建立真实RuntimeBinding及技术引用，hook_factory(context)返回ConversationRuntimeHook |

allowed_tools为frozenset工具名；allowed_calls为frozenset((tool_id,parameters_sha256))；references为tuple((kind,id,version))，其中version可为None。引用使用现有正式对象标识与版本，不接受正文。input_sha256取自当前request.original_user_text；请求/会话/轮次标识必须来自实际原生消息和当前服务端身份。request_id在实际RuntimeBinding存在时使用其request_id，建立记录前使用当前request.message_id或request.turn_id，与现有Recorder规则一致。上下文不由模型参数反向签发。

当前参考核查器的领域职责为：对本次正式引用重新读取当前对象、来源、版本及采用资格，核查用户当前输入对应的参数。一般自然问法、关联任务选择、消息写入及附件内容产生哪些新引用，需要消费N1准确接口；本模块不将抽取规则或参数摘要本身视为本人授权。

## Runtime、原编号、取消与隐私

Recorder复用当前RuntimeRecorder/Fc01RuntimeRecorder的实际配置版本、Prompt、工具Schema及实现摘要、run_id/request_id/session_id/chat_id/turn_id和真实终态。feature_id=N02，RuntimeContextBlock来源boss-conversation-context，business_authority_granted=false。conversation_context仅保存input_sha256、allowed_call_refs的tool_id/parameters_sha256，以及references的kind/id/version。工具结果记录实际tool_call_id、source_id/version、parameters_sha256和result_sha256。正文、原始问题和来源内容不进入技术记录。

真实Nanobot继续保存本人原生会话历史；同一会话的新问题形成新的实际运行。重复解析同一实际RequestContext复用原RuntimeBinding，独立ControlStore重建后原运行可查。此证据不表示客户端重连去重已经完成：原生消息admit、稳定turn_id到原意图编号、同编号异内容拒绝及只读恢复，需N3在当前公共传输中接收并验证。查询运行或历史不得再次提交业务动作。

Hook在实际工具错误时只记录工具/调用编号与异常类型并终止，模型失败、取消、超时沿用真实状态；未知usage/cost_total/price_version保持null。Provider释放结果前及下一步骤重新核查当前身份与领域引用，撤销后停止采用。原生/stop已有F01准确公共行为，N3接续同一AgentLoop；本阶段SDK取消/超时证据只证明终态与原记录保留，不代签公开停止或写入后取消全部行为。

## N3公共接收与实际依赖

RoleChannel/application中的当前本人连接、attach、token与过期检查继续负责原生请求采用。N3一般会话生产者在输入接收后建立当前可信ConversationContext，保留原始输入及实际媒体消息；通过CONVERSATION_REQUEST=product_conversation_request识别该路径。context_provider需要每次重查当前active及正式引用，不能直接反序列化客户端JSON为可信上下文。F01晨间、采购、经营、交办等已交付专有请求继续使用其当前合法分支，不能同时创建第二份N02运行。

FeatureToolRegistry在Recorder之前按本次allowed_tools设置FEATURE_SCOPE。公共同名读取需要保留既有路径：可以由N3以ConversationReadTool子类接收当前实际只读delegate，并在非N02请求明确转给现有正式工具；新N02范围需要实际执行该读取适配，不能只修改工具名称。Recorder要求实际Registry.get返回ConversationReadTool实例或其子类，且真实集合等于当前allowed_tools。运行时Provider只采用该集合。

FeatureProvider/FeatureRecorder新增当前一般会话的明确选择分支，分别委托ConversationSimulatedProvider和ConversationRuntimeRecorder；继续使用同一个AgentLoop和现有原生传输。event_producer必须读取当前原始输入、有效补充资料及实际工具消息，形成真实参数和结果；当前固定FC01引导不能充当该生产者。信息不足或当前能力未支持时显示具体条件，不能返回预设业务成功。

公共runtime-records.schema.json需要接收feature_id=N02及可选conversation_context。该对象严格字段为input_sha256、allowed_call_refs和references；参数摘要及输入摘要均为SHA256，allowed_call_refs每项为tool_id/parameters_sha256，references每项为kind/id/version。工具结果新增可选parameters_sha256；现有source_id/version/result_sha256继续使用。公共Schema、配置、实际注册和公开运行/产物投影由N3维护。

N1准确接口接收前，当前不登记附件读取/文件名与大小、任务/消息产物关联、消息草稿和模拟发送、送达/reply_to、必要决定以及未知写入恢复通过。一般自然意图的正式规划及新增工具也属于必要接收内容。当前阶段交接读取与Runtime接口，后续依据N1准确提交及公共候选继续必要采用，禁止以此登记完整C06—C23或26项完成。

## 限定检查与证据

隔离候选validation/.work/n02-agent-public为准确d0e6326，N2模块从当前自己目录导入；使用真实ControlStore.initialize的批准selection资料、BossPageAPI、BossEvidenceReadTool、ToolRegistry、Nanobot/AgentLoop和RuntimeRecorder。技术配置仅启用实际bossEvidenceRead。检查事件生产者处理自然文本中明确提供的真实来源ID，并将变化后的ID传给实际source参数，再从实际工具消息产生回答；该限定用例不代表完整自然语言规划能力。

BDD：Given当前本人、有效来源及明确读取对象；When在同一原生会话连续提出读取不同实际资料的问题；Then参数和结果版本随输入变化，真实工具调用及摘要对应当前run，原始输入保留在本人会话，技术日志没有问题或原文。Given维护/伪造范围/不同模型参数/来源或身份撤销；When当前步骤继续；Then模型和工具拒绝采用不符范围，失败/取消/超时原记录可重读且无业务写入。

```bash
env PYTHONDONTWRITEBYTECODE=1 CONVERSATION_DOMAIN_ROOT=/Users/liuhaoxian/.codex/worktrees/boss-sop-writes/Boss-Agent/validation/.work/n02-agent-public validation/.venv/bin/python -m pytest app/tests/conversation_agent/test_runtime.py -q -p no:cacheprovider --basetemp=validation/.work/n02-agent-delivery --junitxml=docs/menu-delivery/N02/read-runtime.xml
```

结果为12 passed、10.69秒，原始证据见read-runtime.xml。没有启动产品服务、读取凭据或用户体验资料，没有外部请求，socket.connect由检查审计拒绝。中间目录已由validation/.work忽略。MVP996x、UI02104xx、F01106xx及其制品/数据保持；FR-27/STT/F27/FC28暂停，视觉及用户验收未执行。
