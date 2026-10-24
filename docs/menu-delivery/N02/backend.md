# MENU-N02-N1 聊天交办领域

task_id=MENU-N02-N1，当前附件工单MENU-N02-N1-NATIVE-FILE-20261024；来源为原始docs/menu-delivery/N02.md完整26项工单及D-MENU-DELIVERY-20261024。正式状态由N3维护specs/feature-delivery.json，本记录只登记领域阶段。当前PRODUCT核查HEAD为484dda57eeed3fe5e545eb91de21419b5a2bef81；PRODUCT仅作只读依赖，未运行其公开检查或预览。

附件实施提交6164aac401712f397072fdfac788d04ffd91488a，分支codex/business，包含8份领域、Schema、对应检查和记录文件；已有领域基础提交5f2138234353c5c224b3d0034d4c1565e6e8939b。N3按本次准确附件增量接收，本记录的模块证据不代表完整26项或用户验收通过。原五项未提交内容继续保持。

## 当前依据与检索

已完整读取适用AGENTS、N02工单、PRD当前决定、完整产品FR-08/24/29及BR/AC、原N02页面与原始提示词、实际chat面板。共同BR-C01—C07/E01—E06及交互规范沿用本轮当前读取内容。S008任务记录、执行规则及接口改动检查继续采用。检索现有消息/联系人/草稿/发送/回复、任务/来源/授权、runtime_run与原生会话/附件代码，读取T18-message-calendar及相关字段规范。记忆索引没有相关命中。

当前PRODUCT的boss_message_calendar.py与本目录相同。正确的版本化草稿、稳定联系人ID、独立模拟发送、原回执和reply_to回复继续复用，不创建第二份消息状态。当前消息正文及附件由本人入口处理，技术维护不能代签。未触及原五项未提交授权消费内容，也不编辑公共Page/Command/RoleChannel/Shell/认证。

## 领域责任与必要接口

ConversationAPI提供当前会话/运行/业务产物及消息来源的只读投影；运行仅从实际runtime_run及已保存工具引用采用，不根据文本推断业务对象。当前会话的原生历史、流式内容、选择和未发送输入仍由原生会话系统维护。公共身份与会话归属核查由N3在调用领域之前完成，不允许浏览器提供owner/namespace或任意文件路径。

原生附件从实际SessionManager读取已保存会话中的可信上传记录及原生user.media，核查获准媒体目录后读取实际文件元信息。当前安装SDK在AgentLoop._restore_turn使用reference_non_image_attachments将普通文档改为正文引用，随后_persist_user_message_early只保存剩余图片media；领域因此采用可信上传记录中的内部文件引用，不解析正文引用。上传、文件选择与用户取消由N3复用原生服务，领域不重新上传或解析文件正文。运行、查询完成及取消不会改变交办完成或消息投递状态。全部外部SIMULATED_FIRST，STT/F27/FC28暂停，视觉未执行。

## 验证与接收

当前领域阶段MODULE_CHECKS_PASSED。必要验证使用已忽略.work下独立SQLite、原生SessionManager与当前PRODUCT正式RuntimeRecorder；未使用用户MVP/UI02/F01目录、端口、制品或数据。完整26项及用户验收保持由N3记录。

## 正式接口及字段

规范为specs/conversation.schema.json 1.1.0。本次只更新boss_conversation_attachments.py、Schema、对应检查及本记录；boss_conversation.py接口保持。公开适配仍采用PRODUCT的PublicConversation，公开Schema、页面字段及正式接收状态由N3维护。没有新增消息写入动作、授权、调度或DDL迁移，没有模型本人确认工具。

| 签名 | 输入及输出 | 当前边界 |
|---|---|---|
| ConversationAPI(store).read(BOSS,query) | Context={session_id,chat_id}；View={projection,source_type,session_id,chat_id,runs,coverage_state,missing_sources,business_authorization_granted,business_mutation_performed} | 只读取实际runtime_run，同一namespace/dataset/session/chat；没有实际运行时UNAVAILABLE，原生历史和未发送内容仍由原生系统维护 |
| ConversationAPI.project_in_transaction(BOSS,db,query) | 相同Context和View | 公共Page已持有只读事务时调用，保持当前快照；不会另开写入事务 |
| ConversationAPI.artifact(BOSS,query) | ArtifactInput=Context+run_id/kind/id；kind=query/task/morning_list/message/message_draft。ArtifactResult返回实际data/evidence及false授权/变更标记 | 先核查实际运行引用，再读取当前正式对象；不从模型正文、标题、任意ID或客户端归属建立关联 |
| ConversationAPI.messages(BOSS) | Messages={projection,source_type,scope=OWNER_MESSAGE_HISTORY,drafts,sent_messages,replies,contacts,false授权/变更标记} | 本人消息历史抽屉，不自动表示与当前会话关联。草稿、发件箱、送达、reply_to、当前任务状态分别读取 |
| ConversationAttachments(native_sessions,approved_media_root).read(BOSS,query) | 原生websocket Context；Attachments={source_type,session_id,chat_id,session_state,attachments,false授权标记} | 读取可信上传引用及实际已保存user.media；目录及符号链接检查后读取实际大小和摘要，不接收客户端路径或解析正文 |
| ConversationAttachments.record_upload(BOSS,query,accepted_media,accepted_paths) | Context及原生上传实际成功的输入/返回路径；UploadMetadataResult={session_id,attachment_ids,metadata_saved=true,business_authorization_granted=false} | 仅可信原生入口内部调用，保存真实原名/MIME/大小/摘要至同一Session.metadata；不注册模型工具或接收客户端路径的公共命令 |

runs逐项包含实际run_id/session_id/request_id/chat_id/turn_id、configuration_id/configuration_version、status/stop_reason/started_at/finished_at；runtime仅保留provider/model_id/api_type/max_tool_rounds/max_output_tokens/timeout/config_sha256。tool_steps仅保留tool_id/tool_call_id/iteration/status/task_status/version/task_version，tool_errors仅保留工具引用及error_type。没有问题正文、原始工具参数、内部推理或预设百分比。运行source_type及external_model_invoked按实际记录提供，未知保持null。

artifacts使用实际tool_results、owner_task_links及已核查的morning_context.selected_item_ref/assignment_context保存的编号，返回kind/id/recorded_version/adoption_state=REQUIRES_CURRENT_READ。kind与存储对应query、task、morning_list、message_outbox或outbox、message_draft；当前内容必须通过artifact重新读取。query复用Store.read_evidence，task复用require_current_assignment_sources，morning_list复用Morning当前快照检查；来源失效在当前位置抛出既有错误，原运行及引用继续可读。origin_references仅返回既有morning_context日期/时区/快照/次序及选中事项编号版本、assignment_context任务版本/核查摘要、reminder_context投影摘要；没有正文，当前采用仍需原领域检查。

消息逐项保留实际草稿/内容版本、稳定收件人、关联任务、当前状态、content_sha256、发送/送达/回复、真实保存时间及授权编号；不存在字段不补造。attachment_refs提供固定source_id/version、当前版本、状态与获准作者/发布时间/观察时间/原文位置。SQL先限制访问范围，再检查版本、有效期与传递来源。失效后body为null并标记NEEDS_REVIEW，已发送历史状态不变；关联回复文本也停止当前采用。contacts来自获准初始资料，保留contact_id/name/organization/responsibility/有效期及按本人业务日期计算的is_current；同名联系人保留独立ID。原本人草稿/发送、模拟回复及operation-status继续由既有公共动作处理。

附件逐项包含attachment_id/stored_name/original_name/mime_type/size_bytes/content_sha256/recorded_size_bytes/recorded_content_sha256/processing_state/user_message_index。编号按当前会话与同一文件保持。仅唯一已保存原生user.media引用能够确认时，user_message_index返回真实数组位置；普通文档的SDK持久化消息没有该引用，或者同一附件对应多个位置时返回null，不添加消息编号或推断turn关联。

原生入口实际上传成功后，record_upload将实际选择的原名、原生识别的MIME、真实大小/摘要及获准媒体目录内部relative_path保存在boss_attachment_metadata。内部relative_path不属于公开请求或输出；客户端只能提供原生上传选择，accepted_paths必须来自可信gateway的成功返回。重复相同元信息保持同一编号，冲突内容拒绝。StoredAttachment规范保留历史四项原名/类型/大小/摘要记录；历史缺少内部引用且原生消息没有media时，只在当前获准媒体目录中按原有完整attachment_id核查文件，编号采用会话与真实文件路径的既有摘要，不按名称、正文或内容猜测，不读取其他文件正文。读取过程不补写历史会话。

STORED说明当前文件存在且已保存摘要与大小一致；仅有原生media且没有上传元信息时，不声称已知上传版本。CHANGED表示当前文件与已保存上传版本不同，size_bytes/content_sha256提供当前值，recorded_size_bytes/recorded_content_sha256保留上传时值。MISSING用于已知引用对应文件缺失，当前大小和摘要为null，原名、类型、编号及上传记录继续可读。REFERENCE_UNAVAILABLE用于历史记录无法确认文件引用，stored_name、当前位置和当前摘要均为null，原名、类型、编号及上传记录保持。读取期间文件变化在当前位置抛出错误。输出不包含本地路径或文件正文，全部状态均不授予业务来源资格。

## 当前证据

2026-10-24，本次附件定向检查8项通过，用时3.82秒，证据native-file-check.xml。四项检查使用实际WebUIMediaGateway上传仓库已有morning-coverage.json、实际Nanobot/AgentLoop及正式查询工具完成运行，通过原生SessionManager保存，再由全新SessionManager重新读取；实际user消息没有media，附件仍能准确读取。另行覆盖当前文件变更、缺失、角色/会话/客户端路径、目录外符号链接、原生media位置及Schema无业务写入。全部会话、媒体和SQLite均位于N1已忽略.work；SessionManager显式指定独立sessions_root。

native-file-snapshot-check.json记录对N1实际SDK已保存历史快照的只读消费。快照具有一项原名/MIME/大小/SHA元信息，原生user消息只有role/content/timestamp/_runtime_context四项字段，media数量为零，元信息没有内部relative_path。检查使用完整既有编号从获准目录确认实际文件；原名morning-coverage.json、MIME application/json、548字节、SHA256 13d6488075fad82313ea8a7a2c89fd611b0f36ccac176282cc918c204243fb7f全部一致，user_message_index为null。另以不存在的获准目录核查REFERENCE_UNAVAILABLE，原始快照及元信息保持不变。正式证据不保存本地路径或正文。

2026-10-24，PRODUCT消费检查6项通过、1项有意不在该组执行，用时5.85秒，原始证据product-domain-check.xml。N1本地和既有消息/日历消费者17项通过、2项Runtime消费不在该组执行，用时1.84秒，证据message-domain-check.xml。两组共享部分边界用例，数量不相加作为菜单完成分子。当前附件原名/类型保存及输出Schema另由2项定向检查通过，用时1.97秒，证据source-attachment-check.xml；运行原型证据保存在已忽略.work，正式结果分别保存。git diff --check通过。

PRODUCT依赖目录为/Users/liuhaoxian/.codex/worktrees/boss-integration/Boss-Agent，只读；本次核查HEAD=484dda57eeed3fe5e545eb91de21419b5a2bef81。没有修改该目录。PYTHONDONTWRITEBYTECODE=1禁止在依赖目录生成缓存。当前Nanobot来自N1 validation/.venv的已安装版本，使用真实AgentLoop/ToolRegistry/Fc02Tool/Fc02RuntimeRecorder及明确SIMULATED生产者，实际调用正式查询工具并消费其结果；socket.connect审计拒绝外部连接，没有读取凭据或调用真实模型。

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

N2继续维护当前原生会话/本次意图与实际Runtime。新工具若实际产生message_id或draft_id，记录器必须从正式返回结果核查正确存储种类后保存对应引用，不能把message_outbox误认为交办outbox；没有实际产物不添加引用。F01选中事项、来源及返回绑定继续用现有正式生产者。当前会话读取仅消费Context匹配的runs，原始正文及未发送输入使用原生会话，不能由本投影推断另一会话目标。当前工具、源截至、原文、对象及版本由相应正式领域验证，不把工具返回引用当作新的本人授权。

N3负责公开注册和实际认证/原生会话归属，在调用前从可信身份与原生路由确定session/chat，不接受模型或payload.role/owner/namespace。消息历史范围独立展示；将同会话运行引用、产物详情、原文入口与原消息返回准确关联。现有本人保存/发送及原编号operation-status继续采用，不重放未知写入。read主投影可在已有只读事务调用project_in_transaction；artifact与messages作为独立只读请求，不能在通用写入事务中触发。原生gateway.store_inbound_attachments实际成功后，将该次真实accepted_media/accepted_paths交给record_upload保存原名、类型、摘要及内部引用；失败/取消不调用，禁止提供模型或客户端任意路径入口。附件read与record_upload签名保持，本次N3接收需要同步Schema 1.1.0、nullable stored_name/user_message_index、两个recorded_*字段及四种processing_state；REFERENCE_UNAVAILABLE不能描述为已确认文件缺失，CHANGED不能继续采用上传时文件内容。构建需包括两份领域模块和conversation.schema.json。本次没有编辑公共适配、OpenAPI或用户体验资料。

当前领域提供C06/C07/C10/C11/C13—C15/C18/C20—C22的必要数据及权限基础；当前原生历史/未发送输入、上传选择/限制及元信息接口实际采用、完整会话/运行/业务共享路径、有效授权消费、公开异步恢复和认证、实际消息工具注册、取消/异常、布局/键盘/启动制品及完整26项由N2/N3继续接收。original_name只采用原生成功上传的实际原名，历史缺少时保持未知。C24仅保留暂停说明及零STT请求，视觉和用户验收未登记。当前不启动下一菜单，不修改正式状态，原五项未提交内容和全部用户体验资料保持。
