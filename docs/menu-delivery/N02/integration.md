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
| 领域/消息/来源/版本 | 现有 boss_message_calendar、消息命令、任务和来源为可复用输入；完整 N02 的会话/任务/产物关联及必要增量 PENDING，由 N1准确交接 |
| Agent/Runtime | 已接收 N2生产者86579a85c278e349d615aa39b57ba26b63729ad5，当前集成77f7647；一般会话可信读取和Runtime模块1.0.0，公开接收/完整规划及业务产物采用 PENDING |
| 公开接收/前端 | N3唯一维护实际注册、RoleChannel、App、Shell、组件/样式、独立制品与连续验证；采用准确已有接口，不编造新业务值 |
| 独立核查 | N4按原 PRD/设计建立26项独立矩阵；准确候选后只核查必要差距和受影响消费者 |
| 新框架/真实外部/新视觉 | NOT_APPLICABLE；沿用当前技术及设计；SIMULATED_FIRST，FR-27保持暂停 |

原 HTML 的会话列表/中部对话/任务与来源，与实际加载 chat 的当前会话/对话执行及持续进展共同映射。历史区域保持克制，当前任务/来源可打开，连续阅读及输入采用原生组件，区域顺序、宽度、间距和重排依据保存到当前设计说明。固定 Token、44px目标及键盘/200%要求继续有效；设计预览标识和静态示例不进入产品。

## 当前验证与续接

当前没有完整 N02产品或业务通过声明。26项必要断言引用完整工单；N1/N2已有正确接口直接接收，存在差距才增量实施。公共层需要核查自然输入、附件、当前事项、同一 Runtime、任务/来源/产物、消息授权、原编号恢复及独立共享路径，不能仅将旧原生会话改名后登记完成。

已实施当前草稿及普通缓存保护增量：ThreadComposer暴露仅在进程内的 ComposerDraftController，涵盖文字、实际附件、引用和排队输入；ThreadShell透传，App以当前会话注册，用于切换、浏览历史地址及离开业务路径。本人明确放弃时清除对应未发送内容，返回继续编辑保留内容；beforeunload覆盖仅附件/排队状态。本人会话明确设置 persistQueuedPrompts=false，继续使用原生内存队列，不读取或写入普通 localStorage队列正文。源码增量保存在 app/webui/nanobot-menu-n02.patch。

独立 menu-n02-n3-dist 构建通过，Vite计时30.53秒，日志 .work/menu-n02-build.log。`node validation/desktop/check-menu-n02-native-privacy.cjs` 通过，原始结果 evidence/menu-delivery/N02/native-privacy.json；使用新10731/10732/20731及代理10733、独立SQLite/账号。实际批准 YAML文件的附件单独存在时触发离开保护，继续编辑保留、明确放弃清除；代理仅延迟真实当前会话输出，排队输入没有进入URL/普通浏览器缓存、没有发送，明确放弃后不恢复。该证据仅覆盖相应 C04/C06/C21的当前增量，不登记完整26项或一般会话业务通过。F01制品未更改。

N2模块提供 ConversationContext/ConversationScope、五项正式只读适配、ConversationSimulatedProvider/ConversationRuntimeRecorder，记录输入/参数摘要与正式引用，不提供模型本人确认。接收后在当前 PRODUCT 运行 `CONVERSATION_DOMAIN_ROOT=当前PRODUCT validation/.venv/bin/python -m pytest app/tests/conversation_agent/test_runtime.py`，12 passed，9.19秒，证据 evidence/menu-delivery/N02/read-runtime.xml。仅证明模块及实际 SDK的当前读取/终态/隐私；通用自然输入规划、原生接收去重、附件/消息/任务/产物关联、公开注册与Schema仍待准确接口和实际消费者，不登记完整N02通过。N1当前正在完成准确领域交付，运行中仅只读，不采用未完成文件作为正式接口。

原设计实际加载检查已运行：`env TMPDIR=validation/.work/tmp node validation/desktop/check-menu-n02-design.cjs`，结果 PASS，六组 DOM/位置尺寸保存在 evidence/menu-delivery/N02/reference-dom.json。采用独立 menu-n02-reference-profile，未启动产品或读取现有用户资料。该结果仅证明设计来源及六组布局读取，不登记 N02 产品检查点通过。区域/Token/真实原生组件与正式接口依赖记录于 design.md。

已发送当前四窗口的角色续接，marker=MENU-N02-START-20261024；每次发送前复查 idle。N1 turn=01a16df8-d1c1-79f3-87d2-3b362d5c889e，N2 turn=01a16df8-e6aa-7ac3-8a7b-a0abfc791fc0，N4 turn=01a16df8-f3bc-7ad1-8f73-d95ab5c77283；工具分别返回对应既有 threadId。运行中仅只读，角色准确自然交付后接收必要增量，禁止重复接续。

主记录随准确接口、设计选择、实际修改和原始结果更新；保持全体未完成项、当前范围与必要阻塞。正常完成当前26项后登记开发交付待用户验收，并处理进入 N03前必要的 F01设计返修，始终只实施一个菜单。暂停语音独立保留，不计完成。现有四窗口仅在 idle 复查后一次具体续接，marker=MENU-N02-START-20261024，运行中只读。

## 资料与运行

保护原 UI02/MVP 及当前已交付 F01 的制品、账号、SQLite、会话、端口与用户窗口。新候选使用独立目录、制品和端口，不自动退出、重启、覆盖或热替换已有体验。受控账号注入仅填写当前角色表单，手动登录仍经正常认证。全部外部 SIMULATED_FIRST，无新增真实外部请求；STT/F27/FC28暂停。禁止主动视觉、截图、图像、/tmp、Git恢复和程序化修改源码。
