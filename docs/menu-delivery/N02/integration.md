# MENU-N02 聊天交办

task_id=MENU-N02-N3；CURRENT；2026-10-24；IN_PROGRESS。唯一正式状态为原始目录 specs/feature-delivery.json，主工单为 /Users/liuhaoxian/Downloads/我的/AI项目/Boss-Agent/docs/menu-delivery/N02.md。当前完整稳定检查点 MENU-N02.C01—C26，baseline_id=boss-menu-n02-coverage-20261024-v1，共26项，初始结果 NOT_RUN，候选和开发覆盖分子待核实。视觉及用户验收独立。

当前另有 D-UI-FIDELITY-20261024：执行原始 docs/menu-delivery/高保真还原执行要求.md，所有菜单高度还原原稿，公共框架及正文宽度、比例/层级/间距、组件尺寸/文字/图标和交互逐项核查。当前 Shell 和开源默认布局不能作为接受差距的依据。F01状态为需要设计返修，原业务证据保留；当前仅实施 N02，进入 N03前完成 F01必要返修，用户 F01/UI02/MVP窗口和资料保持。

## 输入、检索与当前依据

使用 S000 DELIVER 整理需求、实际依赖与续接；实施使用 S008，界面/前端设计继承已采用 S003-2/S005-4。已读取当前 PRD 决定、菜单计划、完整 FR-08/24/29、FR-27 暂停范围、共同 E01—E06、N02 原 HTML、页面配置内完整对象、原始提示词、实际 chat builder、design-v6.js、样式及 Token。通用状态 S00—S10 由交互规范继承；N02 的独立 states 数组为空，不据此删除状态要求。

检索开发索引、UI02、F01、FC01/02、T18消息与日历记录、公开 Page/Command 和原生会话。准确前置业务体验候选 d0e6326bcca49a2c8372c476c50808d454076127；F01原业务证据按未变依赖保留，当前设计返修及用户验收待确认。F01 制品、启动入口与10611/10612/20611保持；新 N02 不使用这些业务资料验证。

## 依赖与责任

| 依据 | 当前结论及消费者 |
|---|---|
| 需求/设计 | SATISFIED；当前完整26项工单、原 N02 区域与通用状态，不按原生组件当前功能缩减 |
| 身份/原生框架 | SATISFIED 输入基础；UI02 当前 ClientProvider、历史、新建/选择/搜索、原生输入/上传/流式/停止及 D06；当前完整采用仍需逐项核查 |
| 领域/消息/来源/版本 | 已接收5f21382至e5724eb、附件修复6164aac401712f397072fdfac788d04ffd91488a至eb9a4fe及记录4fcf950；ConversationAPI/附件Schema1.1.0和实际上传元信息采用。一般会话来源/对象投影与完整业务共享路径待继续 |
| Agent/Runtime | 已接收 N2生产者86579a85c278e349d615aa39b57ba26b63729ad5，当前集成77f7647；一般会话可信读取和Runtime模块1.0.0，公开接收/完整规划及业务产物采用 PENDING |
| 公开接收/前端 | N3唯一维护实际注册、RoleChannel、App、Shell、组件/样式、独立制品与连续验证；采用准确已有接口，不编造新业务值 |
| 独立核查 | N4按原 PRD/设计建立26项独立矩阵；准确候选后只核查必要差距和受影响消费者 |
| 新框架/真实外部/新视觉 | NOT_APPLICABLE；沿用当前技术及设计；SIMULATED_FIRST，FR-27保持暂停 |

原 HTML 的会话列表/中部对话/任务与来源，与实际加载 chat 的当前会话/对话执行及持续进展共同映射。历史区域保持克制，当前任务/来源可打开，连续阅读及输入采用原生组件，区域顺序、宽度、间距和重排依据保存到当前设计说明。固定 Token、44px目标及键盘/200%要求继续有效；设计预览标识和静态示例不进入产品。

## 当前验证与续接

当前没有完整 N02产品或业务通过声明。26项必要断言引用完整工单；N1/N2已有正确接口直接接收，存在差距才增量实施。公共层需要核查自然输入、附件、当前事项、同一 Runtime、任务/来源/产物、消息授权、原编号恢复及独立共享路径，不能仅将旧原生会话改名后登记完成。

已实施当前草稿及普通缓存保护增量：ThreadComposer暴露仅在进程内的 ComposerDraftController，涵盖文字、实际附件、引用和排队输入；ThreadShell透传，App以当前会话注册，用于切换、浏览历史地址及离开业务路径。本人明确放弃时清除对应未发送内容，返回继续编辑保留内容；beforeunload覆盖仅附件/排队状态。本人会话明确设置 persistQueuedPrompts=false，继续使用原生内存队列，不读取或写入普通 localStorage队列正文。源码增量保存在 app/webui/nanobot-menu-n02.patch。

独立menu-n02-n3-dist完成TypeScript及Vite构建，当前Vite计时14.98秒，日志.work/menu-n02-build.log。`check-menu-n02-native-privacy.cjs`的实际证据保存于native-privacy.json，使用独立10731/10732/20731及代理10733、SQLite/账号。核查实际运行/产物Dialog、Escape关闭和焦点返回；批准YAML附件单独存在时的离开保护、继续编辑及明确放弃；真实输出延迟时的进程内队列、未发送/不缓存/不恢复。仅覆盖对应当前增量，不登记完整26项或一般会话业务通过。当前构建修改后执行同一必要消费者核查，以报告manifest为准。

BossConversationWorkspace采用真实topicSessions、原生新建/选择/搜索、同一ThreadShell和D06；主列保留当前关联事项、资料版本、任务对象及对话/可观察执行，右列呈现实际进展、异常、来源与可展开附件。实际Runtime产物通过当前会话及原运行引用重读，关闭后返回原按钮；请求/身份/会话变化使迟到结果失效。N02为当前实际入口，原NATIVE本人地址保持兼容，维护Settings保持既有入口。F08仅开放本菜单所需的既有共享消息路径，完整消息授权/回复和一般会话采用继续核查。

N2模块提供 ConversationContext/ConversationScope、五项正式只读适配、ConversationSimulatedProvider/ConversationRuntimeRecorder，记录输入/参数摘要与正式引用，不提供模型本人确认。接收后在当前 PRODUCT 运行 `CONVERSATION_DOMAIN_ROOT=当前PRODUCT validation/.venv/bin/python -m pytest app/tests/conversation_agent/test_runtime.py`，12 passed，9.19秒，证据 evidence/menu-delivery/N02/read-runtime.xml。仅证明模块及实际 SDK的当前读取/终态/隐私；通用自然输入规划、原生接收去重、附件/消息/任务/产物关联和完整公开采用仍待准确接口和实际消费者，不登记完整N02通过。

公共runtime-records.schema.json已接收准确N02字段至1.10.0：feature_id=N02、conversation_context中输入摘要/允许调用摘要/正式引用、工具结果parameters_sha256；不接收正文或原始参数。当前真实SDK两次来源读取记录通过严格CurrentRuntimeRun验证，12 passed、9.21秒，证据read-runtime-schema.xml。一般原生接收与完整任务路径仍待N2准确模块。

N1领域与既有消息消费者在当前PRODUCT共19 passed、10.81秒，原始证据evidence/menu-delivery/N02/received-domain.xml。PublicConversation已接入RoleChannel的四项只读webui_request：boss.conversation.read/artifact/messages/attachments。身份和会话归属由当前认证连接及已订阅chat核查，session_id从原生映射产生，客户端不能提供owner/namespace/session_id。消息历史明确为OWNER_MESSAGE_HISTORY。`check-menu-n02-conversation-read.cjs`通过，结果public-read.json；采用独立10741/10742/20741及实际SDK晨间运行依赖，证明准确运行/产物读取、重复读取不变及维护/未订阅/注入字段/无关产物拒绝。该检查不证明一般会话规划、完整附件处理或完整N02菜单。

实际原生上传成功后，由RoleChannel当前请求内的可信上下文将accepted_media/accepted_paths交给PublicConversation内部record_upload；模型和客户端没有文件路径命令。Schema1.1.0公开区分当前/上传时大小与摘要、可空原生位置及STORED/MISSING/CHANGED/REFERENCE_UNAVAILABLE，不公开内部文件引用。实际WebSocket上传批准morning-coverage.json并完成SDK保存后，public-read.json核对原名/MIME/大小/摘要、无路径输出与原运行；附件领域/SDK保存/既有消息消费者23 passed、8.05秒，证据native-file-receiver.xml。文件保存不授予业务来源资格。当前文件变化状态及一般会话实际采用仍需对应消费者。

N1继续一般N02正式来源/对象上下文投影，marker=MENU-N02-N1-CONTEXT-REFS-20261024；依据已接收conversation_context及tool_results的真实引用，原版本、当前访问版本及有效性分别核查。该增量尚未接收，不根据模型正文推断来源。

N2已接收准确N1接口并继续当前必要原生规划与admit/恢复适配，marker=MENU-N02-N2-NATIVE-20261024，turn=01a16e24-0c1d-72a3-ad17-86f62235402f；发送前复查idle，运行中保持只读。公开注册仍由N3负责，同一请求不得重复生成Runtime。

原设计实际加载检查已运行：18组DOM/计算样式/尺寸见reference-dom.json，含三种窗口100%/200%及阈值相邻样本。当前独立10751/10752/20751及真实新建空会话记录framework-current.json；核查同一实际视口、外框、导航宽度、标题区边界/字号和stage内距/间距共18组。源码及样式按N02-D01—D12必要差距实施，六项主导航与原稿快捷操作保持；尚未交付菜单保持不可用、语音暂停；当前业务入口继续可从目录访问。正文/控件、全部状态及交互仍需完整复核，记录见design-gaps.md，不能把框架尺寸结果作为完整设计通过。当前N02构建未改变F01冻结manifest e3b36c80baac9bbba869d5012b53d38c43b2a05d1869ec9ce10a0c365bafd62c及index 11a935970330ddfa87e50faeb5f266cd27163f11750945e01797be25d3396b1f，已只读复核。

已发送当前四窗口的角色续接，marker=MENU-N02-START-20261024；每次发送前复查 idle。N1 turn=01a16df8-d1c1-79f3-87d2-3b362d5c889e，N2 turn=01a16df8-e6aa-7ac3-8a7b-a0abfc791fc0，N4 turn=01a16df8-f3bc-7ad1-8f73-d95ab5c77283；工具分别返回对应既有 threadId。运行中仅只读，角色准确自然交付后接收必要增量，禁止重复接续。

主记录随准确接口、设计选择、实际修改和原始结果更新；保持全体未完成项、当前范围与必要阻塞。正常完成当前26项后登记开发交付待用户验收，并处理进入 N03前必要的 F01设计返修，始终只实施一个菜单。暂停语音独立保留，不计完成。现有四窗口仅在 idle 复查后一次具体续接，marker=MENU-N02-START-20261024，运行中只读。

## 资料与运行

保护原 UI02/MVP 及当前已交付 F01 的制品、账号、SQLite、会话、端口与用户窗口。新候选使用独立目录、制品和端口，不自动退出、重启、覆盖或热替换已有体验。受控账号注入仅填写当前角色表单，手动登录仍经正常认证。全部外部 SIMULATED_FIRST，无新增真实外部请求；STT/F27/FC28暂停。禁止主动视觉、截图、图像、/tmp、Git恢复和程序化修改源码。
