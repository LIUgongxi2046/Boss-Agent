# MENU-N02-N1 聊天交办领域

task_id=MENU-N02-N1，当前上下文工单MENU-N02-N1-CONTEXT-REFS-20261024；来源为原始docs/menu-delivery/N02.md完整26项工单及D-MENU-DELIVERY-20261024，当前增量对应C07/C10/C11及C20—C22。正式状态由N3维护specs/feature-delivery.json，本记录只登记领域阶段。当前PRODUCT核查提交为2260000b89414727afcf2720bfa993fc7a601296；PRODUCT仅作只读依赖，未运行其公开检查或预览。

附件实施提交6164aac401712f397072fdfac788d04ffd91488a，主记录提交e8bf27c591e0b1210e5ac952e2023d2b1ef10b75；已有领域基础提交5f2138234353c5c224b3d0034d4c1565e6e8939b。分支codex/business，本记录的模块证据不代表完整26项或用户验收通过。原五项未提交内容继续保持。

上下文实施提交9c47e229e3ee6e67d853076b6b98089e7067e966，包含当前Conversation领域、Schema 1.2.0、实际SDK用例、十八项检查证据及本记录，共6份文件。N3按该准确增量接收，新增boss_conversation_references.py必须进入构建。

## 当前依据与检索

已完整读取适用AGENTS、N02工单、PRD当前决定、完整产品FR-08/24/29及BR/AC、原N02页面与原始提示词、实际chat面板。共同BR-C01—C07/E01—E06及交互规范沿用本轮当前读取内容。S008任务记录、执行规则及接口改动检查继续采用。检索现有消息/联系人/草稿/发送/回复、任务/来源/授权、runtime_run与原生会话/附件代码，读取T18-message-calendar及相关字段规范。记忆索引没有相关命中。

当前上下文增量核查了正式ConversationRuntimeRecorder、ConversationScope、ConversationReadTool、RuntimeRecordHook、PublicConversation和Schema 1.10.0。采用已接收4fcf950的真实三项conversation_context字段及tool_results.source_id/version；当前PRODUCT已提交2260000继续保留该接口，默认无intent_adapter的真实SDK检查使用相同字段。只投影input_sha256/allowed_call_refs/references三项获准元信息，未接收的意图扩展不进入本接口。来源规则直接采用source_validity、external_adoption以及SimulationAPI的当前对象/传递引用保护。当前索引docs/development/index.md已具有本主记录的唯一条目，路径保持。

当前PRODUCT的boss_message_calendar.py与本目录相同。正确的版本化草稿、稳定联系人ID、独立模拟发送、原回执和reply_to回复继续复用，不创建第二份消息状态。当前消息正文及附件由本人入口处理，技术维护不能代签。未触及原五项未提交授权消费内容，也不编辑公共Page/Command/RoleChannel/Shell/认证。

## 领域责任与必要接口

ConversationAPI提供当前会话/运行/业务产物及消息来源的只读投影；运行仅从实际runtime_run及已保存工具引用采用，不根据文本推断业务对象。当前会话的原生历史、流式内容、选择和未发送输入仍由原生会话系统维护。公共身份与会话归属核查由N3在调用领域之前完成，不允许浏览器提供owner/namespace或任意文件路径。

原生附件从实际SessionManager读取已保存会话中的可信上传记录及原生user.media，核查获准媒体目录后读取实际文件元信息。当前安装SDK在AgentLoop._restore_turn使用reference_non_image_attachments将普通文档改为正文引用，随后_persist_user_message_early只保存剩余图片media；领域因此采用可信上传记录中的内部文件引用，不解析正文引用。上传、文件选择与用户取消由N3复用原生服务，领域不重新上传或解析文件正文。运行、查询完成及取消不会改变交办完成或消息投递状态。全部外部SIMULATED_FIRST，STT/F27/FC28暂停，视觉未执行。

## 验证与接收

当前领域阶段MODULE_CHECKS_PASSED。必要验证使用已忽略.work下独立SQLite、原生SessionManager与当前PRODUCT正式RuntimeRecorder；未使用用户MVP/UI02/F01目录、端口、制品或数据。完整26项及用户验收保持由N3记录。

## 正式接口及字段

规范为specs/conversation.schema.json 1.2.0。本次更新boss_conversation.py、新增boss_conversation_references.py，并更新对应Schema、用例、检查证据及本记录。附件1.1.0字段与read/record_upload签名保持。公开适配仍采用PRODUCT的PublicConversation，公开Schema、页面字段及正式接收状态由N3维护。没有新增消息写入动作、授权、调度或DDL迁移，没有模型本人确认工具。

| 签名 | 输入及输出 | 当前边界 |
|---|---|---|
| ConversationAPI(store).read(BOSS,query) | Context={session_id,chat_id}；View={projection,source_type,session_id,chat_id,runs,coverage_state,missing_sources,business_authorization_granted,business_mutation_performed} | 只读取实际runtime_run，同一namespace/dataset/session/chat；没有实际运行时UNAVAILABLE，原生历史和未发送内容仍由原生系统维护 |
| ConversationAPI.project_in_transaction(BOSS,db,query) | 相同Context和View | 公共Page已持有只读事务时调用，保持当前快照；不会另开写入事务 |
| ConversationReferences(store).project_in_transaction(db,trusted_context,run) | 领域内部构造器；返回ContextReference数组 | 仅由已核查会话归属的ConversationAPI调用，输入来自当前正式空间及实际Runtime；没有公开任意对象ID入口 |
| ConversationAPI.artifact(BOSS,query) | ArtifactInput=Context+run_id/kind/id；kind=query/task/morning_list/message/message_draft。ArtifactResult返回实际data/evidence及false授权/变更标记 | 先核查实际运行引用，再读取当前正式对象；不从模型正文、标题、任意ID或客户端归属建立关联 |
| ConversationAPI.messages(BOSS) | Messages={projection,source_type,scope=OWNER_MESSAGE_HISTORY,drafts,sent_messages,replies,contacts,false授权/变更标记} | 本人消息历史抽屉，不自动表示与当前会话关联。草稿、发件箱、送达、reply_to、当前任务状态分别读取 |
| ConversationAttachments(native_sessions,approved_media_root).read(BOSS,query) | 原生websocket Context；Attachments={source_type,session_id,chat_id,session_state,attachments,false授权标记} | 读取可信上传引用及实际已保存user.media；目录及符号链接检查后读取实际大小和摘要，不接收客户端路径或解析正文 |
| ConversationAttachments.record_upload(BOSS,query,accepted_media,accepted_paths) | Context及原生上传实际成功的输入/返回路径；UploadMetadataResult={session_id,attachment_ids,metadata_saved=true,business_authorization_granted=false} | 仅可信原生入口内部调用，保存真实原名/MIME/大小/摘要至同一Session.metadata；不注册模型工具或接收客户端路径的公共命令 |

runs逐项包含实际run_id/session_id/request_id/chat_id/turn_id、configuration_id/configuration_version、status/stop_reason/started_at/finished_at；runtime仅保留provider/model_id/api_type/max_tool_rounds/max_output_tokens/timeout/config_sha256。tool_steps保留tool_id/tool_call_id/iteration/status/task_status/version/task_version及实际存在的source_id，tool_errors仅保留工具引用及error_type。没有问题正文、原始工具参数、文件路径、内部推理或预设百分比。运行source_type及external_model_invoked按实际记录提供，未知保持null。

artifacts使用实际tool_results、owner_task_links及已核查的morning_context.selected_item_ref/assignment_context保存的编号，返回kind/id/recorded_version/adoption_state=REQUIRES_CURRENT_READ。kind与存储对应query、task、morning_list、message_outbox或outbox、message_draft；当前内容必须通过artifact重新读取。query复用Store.read_evidence，task复用require_current_assignment_sources，morning_list复用Morning当前快照检查；来源失效在当前位置抛出既有错误，原运行及引用继续可读。origin_references保留既有morning_context、assignment_context和reminder_context，并提供实际conversation_context的input_sha256、allowed_call_refs及原始kind/id/version引用。allowed_call_refs仅有tool_id和parameters_sha256，不包含参数值。

每项run新增context_references。引用只来自实际conversation_context.references或正式工具结果中的source_id/version；按kind/id/recorded_version合并，相同对象的不同历史版本分别保存。support逐项包含origin=CONVERSATION_CONTEXT或TOOL_RESULT及可空tool_id/tool_call_id；CONVERSATION_CONTEXT表示可信上下文选定关系，TOOL_RESULT关联真正返回该来源的工具调用。上下文选定关系本身不证明模型实际读取过每项来源，也不证明企业结论已经成立。

| ContextReference字段 | 当前含义及采用规则 |
|---|---|
| kind / id / recorded_version | 原Runtime的真实引用；缺少版本保持null，不从当前资料填补历史 |
| current_version / current_object_state | 本人当前可访问记录的版本及实际业务状态；缺少或无权时保持null |
| current_validity | document的当前source_validity结果；普通对象为null，不把业务状态当作来源有效状态 |
| reference_state | CURRENT表示版本相符且通过当前采用检查；VERSION_CHANGED、VERSION_UNRECORDED、NEEDS_REVIEW、INACTIVE、MISSING_OR_FORBIDDEN、UNSUPPORTED_KIND分别保留当前原因 |
| adoption_state | CURRENT / NEEDS_REVIEW / UNAVAILABLE；只说明本次读取资格，业务动作仍需原有有效授权和正式入口核查 |
| source_metadata | 仅当前版本相符、来源有效且传递依据可采用时提供；其他情况为null。严格字段为source_type/version、author_contact_id/author_kind/author_display_name/generator_version、published_at/observed_at/business_as_of/valid_from/valid_until、coverage/business_basis/business_basis_description/allowed_use；未知字段为null，不返回正文、任意定位或本地路径 |
| source_refs | 对象正式采用绑定或派生来源的source_id/version/current_version/status；当前版本再次经过访问范围核查，不填造缺少版本 |
| support | 原上下文或实际工具调用形成的支持关系，tool_call_id保持实际值；不从回答正文建立关系 |

document先在SQL限制namespace、source_id、access_scope及SIMULATED类型，再读取当前获准记录，复用source_validity与external_adoption核查有效期、版本和传递依据。普通对象只采用SimulationAPI已有KINDS对应接口、当前对象选择及_protect检查，不读取任意存储种类；对象和envelope中的现有owner/dataset/execution_namespace字段还需匹配当前范围。无权或缺少对象时保留历史引用，当前版本及元信息保持未知。来源撤销、到期、更新或传递依据失效不删除运行，也不把原运行SUCCEEDED修改为其他状态。

artifact在原有实际产物关系之外，允许读取同一实际Runtime已保存conversation_context.references明确关联的受支持对象，继续限定ArtifactInput的kind和原有对象访问/来源检查。当前任务因此可以使用现有详情入口；artifacts数组仍只表示实际工具/既有流程形成的产物关系，不把预先关联任务描述为新产物。document通过既有本人来源入口按source_id重验，投影没有新增任意来源正文接口。

消息逐项保留实际草稿/内容版本、稳定收件人、关联任务、当前状态、content_sha256、发送/送达/回复、真实保存时间及授权编号；不存在字段不补造。attachment_refs提供固定source_id/version、当前版本、状态与获准作者/发布时间/观察时间/原文位置。SQL先限制访问范围，再检查版本、有效期与传递来源。失效后body为null并标记NEEDS_REVIEW，已发送历史状态不变；关联回复文本也停止当前采用。contacts来自获准初始资料，保留contact_id/name/organization/responsibility/有效期及按本人业务日期计算的is_current；同名联系人保留独立ID。原本人草稿/发送、模拟回复及operation-status继续由既有公共动作处理。

附件逐项包含attachment_id/stored_name/original_name/mime_type/size_bytes/content_sha256/recorded_size_bytes/recorded_content_sha256/processing_state/user_message_index。编号按当前会话与同一文件保持。仅唯一已保存原生user.media引用能够确认时，user_message_index返回真实数组位置；普通文档的SDK持久化消息没有该引用，或者同一附件对应多个位置时返回null，不添加消息编号或推断turn关联。

原生入口实际上传成功后，record_upload将实际选择的原名、原生识别的MIME、真实大小/摘要及获准媒体目录内部relative_path保存在boss_attachment_metadata。内部relative_path不属于公开请求或输出；客户端只能提供原生上传选择，accepted_paths必须来自可信gateway的成功返回。重复相同元信息保持同一编号，冲突内容拒绝。StoredAttachment规范保留历史四项原名/类型/大小/摘要记录；历史缺少内部引用且原生消息没有media时，只在当前获准媒体目录中按原有完整attachment_id核查文件，编号采用会话与真实文件路径的既有摘要，不按名称、正文或内容猜测，不读取其他文件正文。读取过程不补写历史会话。

STORED说明当前文件存在且已保存摘要与大小一致；仅有原生media且没有上传元信息时，不声称已知上传版本。CHANGED表示当前文件与已保存上传版本不同，size_bytes/content_sha256提供当前值，recorded_size_bytes/recorded_content_sha256保留上传时值。MISSING用于已知引用对应文件缺失，当前大小和摘要为null，原名、类型、编号及上传记录继续可读。REFERENCE_UNAVAILABLE用于历史记录无法确认文件引用，stored_name、当前位置和当前摘要均为null，原名、类型、编号及上传记录保持。读取期间文件变化在当前位置抛出错误。输出不包含本地路径或文件正文，全部状态均不授予业务来源资格。

## 当前证据

2026-10-24，上下文增量及受影响检查18项通过，用时9.96秒，正式证据context-reference-check.xml；其中9项为当前上下文引用检查，9项为原有会话、附件和权限回归，不合并为完整菜单完成分子。当前检查全部使用N1已忽略.work/pytest-menu-n02-context-delivery-20261024中的独立SQLite、原生SessionManager及显式独立sessions_root。N1代码基点为e8bf27c591e0b1210e5ac952e2023d2b1ef10b75，PRODUCT依赖为已提交2260000b89414727afcf2720bfa993fc7a601296的正式SDK生产者；未采用运行中N2文件。

Given本人当前正式来源和对象，When通过实际Nanobot/AgentLoop、ConversationScope、ConversationRuntimeRecorder及bossEvidenceRead执行并保存，Then原始conversation_context和tool_results引用由正式生产者产生，ConversationAPI读取同一运行并保留其真实版本、工具调用及当前元信息。随后分别通过正式来源维护、控制和业务服务执行资料换版、撤销、到期、传递来源撤销、任务模拟发送，验证历史运行及引用继续存在，当前版本与原版本分别返回，当前采用停止，任务详情及来源原文继续执行原权限检查。没有手工创建runtime_run、替换业务正文或预设工具答案。

未知版本直接采用正式SimulationAPI返回的contact.version=null，输出VERSION_UNRECORDED；该上下文不包含document引用时，实际bossEvidenceRead结果仍形成独立TOOL_RESULT关系。获准FC02场景通过正式载入器产生来源，实际SDK再读取其作者类型、作者显示名、生成器版本、资料范围、业务口径、允许用途及业务时间；投影逐项与正式记录一致，不输出正文和定位。本人重建Store后结果一致，读取前后的全部业务对象及审计数量一致；匿名、维护、额外输入字段、错误会话/运行/对象均按当前规范拒绝。Schema同时拒绝在source_metadata注入content。

```bash
env PYTHONDONTWRITEBYTECODE=1 MENU_N02_PRODUCT_ROOT=/Users/liuhaoxian/.codex/worktrees/boss-integration/Boss-Agent PYTHONPATH=/Users/liuhaoxian/.codex/worktrees/boss-business/Boss-Agent/validation validation/.venv/bin/python -m pytest -q app/tests/test_menu_n02_context_references.py app/tests/test_menu_n02_native_files.py app/tests/test_menu_n02_domain.py::test_native_attachment_metadata_uses_saved_session_and_actual_file app/tests/test_menu_n02_domain.py::test_native_attachment_symlink_cannot_read_outside_approved_media app/tests/test_menu_n02_domain.py::test_conversation_schema_and_read_operations_grant_no_business_authority app/tests/test_menu_n02_domain.py::test_current_conversation_adopts_only_actual_run_references_and_current_source app/tests/test_menu_n02_domain.py::test_conversation_rejects_other_chat_run_or_injected_identity --basetemp=.work/pytest-menu-n02-context-delivery-20261024 -p no:cacheprovider --junitxml=docs/menu-delivery/N02/context-reference-check.xml --tb=short
```

2026-10-24，本次附件定向检查8项通过，用时3.82秒，证据native-file-check.xml。四项检查使用实际WebUIMediaGateway上传仓库已有morning-coverage.json、实际Nanobot/AgentLoop及正式查询工具完成运行，通过原生SessionManager保存，再由全新SessionManager重新读取；实际user消息没有media，附件仍能准确读取。另行覆盖当前文件变更、缺失、角色/会话/客户端路径、目录外符号链接、原生media位置及Schema无业务写入。全部会话、媒体和SQLite均位于N1已忽略.work；SessionManager显式指定独立sessions_root。

native-file-snapshot-check.json记录对N1实际SDK已保存历史快照的只读消费。快照具有一项原名/MIME/大小/SHA元信息，原生user消息只有role/content/timestamp/_runtime_context四项字段，media数量为零，元信息没有内部relative_path。检查使用完整既有编号从获准目录确认实际文件；原名morning-coverage.json、MIME application/json、548字节、SHA256 13d6488075fad82313ea8a7a2c89fd611b0f36ccac176282cc918c204243fb7f全部一致，user_message_index为null。另以不存在的获准目录核查REFERENCE_UNAVAILABLE，原始快照及元信息保持不变。正式证据不保存本地路径或正文。

2026-10-24，PRODUCT消费检查6项通过、1项有意不在该组执行，用时5.85秒，原始证据product-domain-check.xml。N1本地和既有消息/日历消费者17项通过、2项Runtime消费不在该组执行，用时1.84秒，证据message-domain-check.xml。两组共享部分边界用例，数量不相加作为菜单完成分子。当前附件原名/类型保存及输出Schema另由2项定向检查通过，用时1.97秒，证据source-attachment-check.xml；运行原型证据保存在已忽略.work，正式结果分别保存。git diff --check通过。

PRODUCT依赖目录为/Users/liuhaoxian/.codex/worktrees/boss-integration/Boss-Agent，只读；当前核查提交为2260000b89414727afcf2720bfa993fc7a601296，相关正式生产者、页面读取、对象采用及Runtime Schema文件没有未提交差异。没有修改该目录。PYTHONDONTWRITEBYTECODE=1禁止在依赖目录生成缓存。当前Nanobot来自N1 validation/.venv的已安装版本，使用真实AgentLoop/ToolRegistry、ConversationRuntimeRecorder、Fc02Tool/Fc02RuntimeRecorder及明确SIMULATED生产者，实际调用正式读取或查询工具并消费其结果；socket.connect审计拒绝外部连接，没有读取凭据或调用真实模型。

```bash
env PYTHONDONTWRITEBYTECODE=1 MENU_N02_PRODUCT_ROOT=/Users/liuhaoxian/.codex/worktrees/boss-integration/Boss-Agent PYTHONPATH=/Users/liuhaoxian/.codex/worktrees/boss-business/Boss-Agent/validation validation/.venv/bin/python -m pytest -q app/tests/test_menu_n02_native_files.py app/tests/test_menu_n02_domain.py::test_native_attachment_metadata_uses_saved_session_and_actual_file app/tests/test_menu_n02_domain.py::test_native_attachment_symlink_cannot_read_outside_approved_media app/tests/test_menu_n02_domain.py::test_conversation_schema_and_read_operations_grant_no_business_authority app/tests/test_menu_n02_domain.py::test_current_conversation_adopts_only_actual_run_references_and_current_source --basetemp=.work/pytest-menu-n02-native-file-delivery -p no:cacheprovider --junitxml=docs/menu-delivery/N02/native-file-check.xml --tb=short
```

```bash
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/Users/liuhaoxian/.codex/worktrees/boss-business/Boss-Agent/validation validation/.venv/bin/python validation/check_n02_native_attachment_snapshot.py --snapshot .work/pytest-menu-n02-native-file-red2/test_uploaded_document_survive0 --output docs/menu-delivery/N02/native-file-snapshot-check.json
```

```bash
env PYTHONDONTWRITEBYTECODE=1 MENU_N02_PRODUCT_ROOT=/Users/liuhaoxian/.codex/worktrees/boss-integration/Boss-Agent PYTHONPATH=/Users/liuhaoxian/.codex/worktrees/boss-business/Boss-Agent/validation validation/.venv/bin/python -m pytest -q app/tests/test_menu_n02_domain.py -k 'not contact_expiry' --basetemp=.work/pytest-menu-n02-product-delivery -p no:cacheprovider --junitxml=docs/menu-delivery/N02/product-domain-check.xml --tb=short
```

```bash
env PYTHONDONTWRITEBYTECODE=1 validation/.venv/bin/python -m pytest -q app/tests/test_menu_n02_domain.py -k 'not conversation_adopts and not conversation_rejects' app/tests/test_boss_message_calendar.py --basetemp=.work/pytest-menu-n02-message-delivery -p no:cacheprovider --junitxml=docs/menu-delivery/N02/message-domain-check.xml --tb=short
```

```bash
env PYTHONDONTWRITEBYTECODE=1 validation/.venv/bin/python -m pytest -q app/tests/test_menu_n02_domain.py::test_native_attachment_metadata_uses_saved_session_and_actual_file app/tests/test_menu_n02_domain.py::test_native_attachment_symlink_cannot_read_outside_approved_media --basetemp=.work/pytest-menu-n02-upload-delivery -p no:cacheprovider --junitxml=docs/menu-delivery/N02/source-attachment-check.xml --tb=short
```

命令工作目录均为N1的boss-business/Boss-Agent。正常真实API建立初始资料、草稿、发送及署名模拟回复；当前消息检查同时证明幂等、CAS、同名联系人、撤销附件、独立发送/进展与私人内容权限。实际Runtime生成查询和原文引用，两次不同会话的运行互不混入；伪造主体字段、维护、错误会话/运行/对象拒绝。原生媒体服务实际上传仓库已有获准生成定义文件，SessionManager保存并重新读取，核对字节数/摘要及符号链接拒绝；删除测试文件后保留缺少状态。重复读取及重建Store不产生业务对象、授权或审计写入，来源撤销不能重新读取查询正文。没有替换数据库业务正文，没有新企业事实、mock或预设业务答案。

## N2/N3接收及未完成范围

本次N3需要接收boss_conversation.py、boss_conversation_references.py、conversation.schema.json 1.2.0，构建必须包含新增领域模块。ConversationAPI构造器和公开read/artifact输入签名保持，当前View增加runs[].context_references、origin_references.conversation_context及实际tool_steps.source_id。N3按上述严格字段展示历史版本、当前可访问版本、采用状态和实际支持关系，来源失效时保留历史运行及引用，来源正文继续使用现有本人来源入口。仅上下文明确关联的受支持对象可使用现有artifact详情入口。公开Page/Command/RoleChannel/App、公开Runtime Schema及唯一菜单状态由N3维护，本次没有编辑这些文件。

N2继续维护当前原生会话/本次意图与实际Runtime。新工具若实际产生message_id或draft_id，记录器必须从正式返回结果核查正确存储种类后保存对应引用，不能把message_outbox误认为交办outbox；没有实际产物不添加引用。F01选中事项、来源及返回绑定继续用现有正式生产者。当前会话读取仅消费Context匹配的runs，原始正文及未发送输入使用原生会话，不能由本投影推断另一会话目标。当前工具、源截至、原文、对象及版本由相应正式领域验证，不把工具返回引用当作新的本人授权。

N3负责公开注册和实际认证/原生会话归属，在调用前从可信身份与原生路由确定session/chat，不接受模型或payload.role/owner/namespace。消息历史范围独立展示；将同会话运行引用、产物详情、原文入口与原消息返回准确关联。现有本人保存/发送及原编号operation-status继续采用，不重放未知写入。read主投影可在已有只读事务调用project_in_transaction；artifact与messages作为独立只读请求，不能在通用写入事务中触发。原生gateway.store_inbound_attachments实际成功后，将该次真实accepted_media/accepted_paths交给record_upload保存原名、类型、摘要及内部引用；失败/取消不调用，禁止提供模型或客户端任意路径入口。附件read与record_upload签名保持，当前Schema继续保留nullable stored_name/user_message_index、两个recorded_*字段及四种processing_state；REFERENCE_UNAVAILABLE不能描述为已确认文件缺失，CHANGED不能继续采用上传时文件内容。构建需包括当前全部Conversation领域模块和conversation.schema.json。本次没有编辑公共适配、OpenAPI或用户体验资料。

当前领域提供C06/C07/C10/C11/C13—C15/C18/C20—C22的必要数据及权限基础；当前原生历史/未发送输入、上传选择/限制及元信息接口实际采用、完整会话/运行/业务共享路径、有效授权消费、公开异步恢复和认证、实际消息工具注册、取消/异常、布局/键盘/启动制品及完整26项由N2/N3继续接收。original_name只采用原生成功上传的实际原名，历史缺少时保持未知。C24仅保留暂停说明及零STT请求，视觉和用户验收未登记。当前不启动下一菜单，不修改正式状态，原五项未提交内容和全部用户体验资料保持。
