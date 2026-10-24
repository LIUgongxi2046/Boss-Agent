# MENU-F01-N2 今日工作Agent开发记录

task_id=MENU-F01-N2；decision_id=D-MENU-DELIVERY-20261024；marker=MENU-F01-START-20261024。当前N2独立工具及Runtime接口版本1.1.0，公共采用等待N3准确组合。菜单正式状态唯一由N3维护，当前记录不登记完整菜单或用户验收通过。文档有效性CURRENT，核查日期2026-10-24。

## 需求、依据与范围

已读取原始PRD最前当前决定、菜单总计划、menu-plan.json、F01完整18项及完整产品PRD的FR-01/BR-01/AC-01-S/E、BR-C02和E01—E06；核查当前LLD适用的Runtime、身份、工具、日志和返回上下文规则，复用FC03实际SDK、正式MorningAPI及既有开发记录。当前工作只修改N2晨间工具、Runtime、专有检查与记录；页面、公开请求、认证、公共Schema及唯一正式状态由N3维护。

只读核查的公共基点为b7fdc76c81ef693da75511d736db60d92550784c。ProductMorning已通过Nanobot和实际Registry执行todayRead、morningListRead、morningDetailRead、morningSourceRead；当前公共请求的选择字段为list_id。公共文件validation/product_morning.py所属提交9bc99903988baafc1f61bedd1be88133fcde5cc6，读取时blob为efe5b62713e42ff0ed659513ec3ef6bee7bcd276。完整当前事项选择、输入保留、原生会话续接和页面返回须由N3在最终候选补齐并验证。

正式领域采用既有准确提交e3faa5dcd90831d5e84e42c6ca66b418f85b767c；MorningAPI及morning.schema.json 1.0.0继续作为正式接口。N1本菜单记录当前提供完整范围核查，尚无本菜单新增准确提交供接收；未来公开字段和语义变化只消费N1准确提交，不推测字段。全量资料范围、分类、关联合并、时间冲突、排序和来源有效性仍由正式领域确定。

## 当前可信事项与实际工具

Fc03Context追加可选selected_list_id与selected_item_id，两者同时提供。现有构造保持兼容。服务端从真实认证及明确选择生产字段；模型参数没有签发本人选择或授权的入口。选中清单仍须属于当前请求或服务端allowed_list_ids，并匹配日期、时区、snapshot_sha256及当前order_version。工具从MorningAPI.read_list/detail重新读取正式事项，拒绝失效或已变化资料。

RuntimeContextBlock的morning_context可选selected_item_ref，包含list_id、list_version、item_id、object_id、version和source_refs。source_refs完全采用正式Ref的kind/id/version；document引用才可用于morningSourceRead。引用来自实际正式详情，不接受客户端提供正文或版本。实际Runtime运行保存同一引用，实际工具结果保留tool_call_id、list_id/list_version、事项与来源版本、业务时间和运行关联。原始问题继续作为SDK用户输入，问题、标题、资料正文及私人正文不写入技术记录。

没有选择事项时，四项正式工具行为及原Schema保持兼容；整个清单、分类、排序原因、来源及覆盖字段由实际工具输出完整传递。选中事项继续讨论时，morningListRead读取同一清单，morningDetailRead只接受当前事项，morningSourceRead只接受该事项绑定的document；todayRead拒绝新建清单。工具没有排序、准备确认、交办创建、发送、审批、本人确认或来源确认操作。准备交办只向本人已有合法入口交接当前引用，不由模型生成业务授权。

## BDD与限定证据

Given当前已认证本人、真实领域清单和明确选中事项；When通过实际SDK提交继续讨论问题并调用当前详情与原文；Then输入和可信事项引用同时进入模型消息，输出消费同一正式事项，对象、版本、来源及run关联可查，费用及usage保持null。当前验证使用selection批准数据和ControlStore.initialize，资料来自真实领域读取，没有替换领域记录或外部请求。

Given其他事项、无关来源、不完整选择、来源撤销、本人次序变化或模型失败；When工具读取或运行继续；Then拒绝不符选择或失效依据，不创建新清单或业务授权，已提交清单及原编号回执可重读，失败/取消/超时保持实际终态。未知原编号恢复继续调用只读receipt，不重放query。

当前限定检查为app/tests/fc03_agent/test_menu.py及受影响test_formal.py，结果15 passed，9.08秒；其中新增当前事项检查7项，受影响正式读取检查8项。准确领域组合为公共8769fbe0b9e62dd131f6aef4c6ede390af5d2fbe加N1 e3faa5d；boss_morning.py blob=f6d009defc85ce152407aca1cda9d8709a291753，morning.schema.json blob=e0a54c9d7424d5a1b7351fea0bc3ac4dbecf66ce。领域从已忽略validation/.work/fc03-formal-e3faa5d读取，该目录没有fc03_agent模块，Agent使用当前N2源码。完整输出见agent-check.xml。

```bash
env PYTHONDONTWRITEBYTECODE=1 FC03_DOMAIN_ROOT=/Users/liuhaoxian/.codex/worktrees/boss-sop-writes/Boss-Agent/validation/.work/fc03-formal-e3faa5d validation/.venv/bin/python -m pytest app/tests/fc03_agent/test_menu.py app/tests/fc03_agent/test_formal.py -q -p no:cacheprovider --basetemp=validation/.work/menu-f01-agent-delivery --junitxml=docs/menu-delivery/F01/agent-check.xml
```

workdir固定为N2的boss-sop-writes/Boss-Agent。检查隔离SQLite和中间资料均在已忽略validation/.work；没有启动服务、使用用户资料或操作UI02/MVP进程。网络审计拒绝socket.connect，外部明确SIMULATED_FIRST。未重复旧全量检查，未执行视觉功能或真实模型质量检查。

## 检查点责任与当前限制

| 检查点 | N2当前证据与公共依赖 |
|---|---|
| C03—C07/C10 | 工具原样采用正式日期、范围、分类、合并、排序、冲突与覆盖字段；完整业务范围以N1本菜单准确结果为依据，最终候选仍需核查 |
| C09/C11 | 实际SDK采用可信当前事项及同版本来源；当前独立限定证据有效，公开入口及原生会话连续采用等待N3 |
| C12/C13 | 四项只读工具不能创建、发送或批准；准备交接、关联页面及返回位置由N3完成当前必要路径 |
| C14—C17 | 正式幂等清单、只读原回执、失效来源拒绝、当前次序变化及实际失败终态已有受影响检查；公共认证、重连和独立服务证据由最终候选提供 |
| C01/C02/C08/C18 | 页面结构、排序交互、窗口、缩放、键盘、构建和可启动交付由N3/N4验证；N2不登记通过 |

## N3准确接收要求

接收本N2提交并继续使用formal=True及FORMAL_TOOLS；公共请求增加受验证的item_id，与list_id成对，并在建立MorningRequest前调用正式详情确认属于当前清单。服务端将选择写入可信Fc03Context的selected_list_id/selected_item_id，维护、模型参数及导航不得签发本人授权。新字段必须进入原意图内容摘要，重复原编号遇到选择变化应当拒绝。

ProductMorning.events从当前可信选择读取详情及该事项实际document引用；从实际工具结果形成模拟回答，保留正式范围和缺口。自然语言问题原样进入实际原生会话，继续讨论保留当前事项、原始输入及会话/run关联；公共技术存储继续排除正文。没有document时说明当前依据范围，不补造原文。继续讨论使用已选清单读取，不建立新的领域清单。

公共runtime-records.schema.json的MorningContext需要接收可选selected_item_ref。该对象字段严格为list_id/list_version及MorningItemReference的item_id/object_id/version/source_refs，字段均必填；source_refs沿用正式kind/id/version。当前公开Schema使用additionalProperties=false，接收该扩展后再验证公开运行记录接口与构建。没有选中事项时该字段不存在。

本人独立确认、准备内容持久化、选中事项与日期/筛选/位置/焦点返回、原生会话保留、公开请求鉴权及当前菜单完整18项仍依赖N3准确集成。模拟必须消费实际工具结果；失败终止当前依赖步骤，未知请求查询原编号。N2独立Registry与SDK证据不代替公共采用，不增加完整菜单或用户验收数量。

## 原生会话接续核查

marker=MENU-F01-N2-NATIVE-READ-20261024；来源为N3指定的只读核查。当前只读取公共基点b7fdc76、N3现有原生源码及已安装nanobot，不修改公共实现、不执行产品或旧检查。下列接口方案需要N3实施与验证，当前没有新增运行通过证据。既有15项检查仍限定于前述独立SDK组合。

原生源码位于N3的.work/product/nanobot，读取时HEAD=1bb712d3488915ca4ed9ccc1a93067ff722f5ab9；App.tsx读取时blob=64becd36c55afdb80d9a7a23367e6bf918552537，nanobot-client.ts blob=a2f133d1c6c415b9fe894baaa5d787b1b2ba2675。已安装nanobot/webui/inbound_commands.py blob=4e17136a8f04664f4f824edf8671636b2c249f0a，nanobot/channels/websocket/runtime.py blob=1105e4a7c023887063f067fd927d5b6446e9c57d。这些摘要描述本次实际读取内容，后续公共候选应当使用其自身准确版本。

| 当前实际接口 | 源码位置与行为 |
|---|---|
| onCreateChat / onStartAutomationChat | webui/src/App.tsx:1631/1663；前者调用createChat并打开websocket:chat_id，后者随后设置pendingAutomationMessage；普通onStartChat没有晨间可信字段 |
| createChat / newChat | webui/src/hooks/useSessions.ts:282；调用client.newChat。服务端inbound_commands.py:296的new_chat生成UUID，设置workspace并attach；此时会话可以尚未写入SessionManager，首条原生消息才保存历史 |
| requestMutation | webui/src/lib/nanobot-client.ts:881；通过现有已认证WebSocket发送webui_request，返回webui_response；当前晨间独立query由RoleChannel单独调用ProductMorning.execute |
| pendingFirstMessage / sendMessage | ThreadShell.tsx:1362调用现有send；nanobot-client.ts:972发送message/chat_id/content/turn_id/webui，不发送任意RequestContext.attributes |
| 原生消息处理 | nanobot/webui/inbound_commands.py:476/607/655/681；校验输入，构建受控metadata，保存用户原文，调用webui_dispatch_message，再广播user_message/message_accepted；envelope的任意metadata或attributes没有直接传递入口 |
| 原生会话与身份 | session_identity.py提供webui_session_key(chat_id)=websocket:chat_id；RoleChannel._dispatch_active_envelope将已认证本人连接的sender_id设置为boss-1；WebSocketChannel.webui_connection_chats(connection)提供当前连接已经attach的会话 |
| 实际Runtime上下文 | AgentLoop._request_context_for_turn在loop.py:731形成channel/chat_id/session_key/original_user_text/metadata/attributes；resolve_runtime_context按注册顺序逐项调用provider，attributes随后进入实际工具请求 |
| 晨间采用 | ProductMorning._grant读取MORNING_REQUEST；FeatureProvider.chat和FeatureRecorder.context已有该分支；scope_context设置FEATURE_SCOPE，FeatureToolRegistry据此限制真实工具。当前普通原生消息没有建立MORNING_REQUEST的生产者 |

### N3实施的连续路径

使用现有原生new_chat、ThreadShell及message传输。F01调用专有晨间入口，将原始question、正式date/timezone及适用list_id/item_id交给App；App等待现有onCreateChat返回服务端chat_id，再通过client.requestMutation完成晨间范围绑定，成功后才设置pendingAutomationMessage。后续输入继续由同一ThreadShell发送到同一chat_id，已有原生转发、流事件、历史保存和读取路径继续负责显示与保存。晨间路径不另行调用一次ProductMorning.execute；每条原生用户消息只进入一次现有AgentLoop。

需要N3新增的公开动作可以命名boss.morning.bind，payload严格限定client_request_id、chat_id、date、timezone及适用list_id/item_id；响应提供绑定编号、chat_id、规范session_id和当前正式引用，不返回凭据或正文。该名称及字段是本次建议新增接口，当前源码尚未提供。RoleChannel在本人有效连接内校验角色、token、过期、当前连接attach状态及当前owner/namespace/dataset，拒绝客户端指定owner、namespace、session_id、active、confirmed或授权字段。chat_id只用于关联已认证请求。绑定通过当前MorningAPI读取核查清单、事项、日期、快照和次序；新建原生会话尚无持久历史不能直接判定为不存在，需核查其服务端创建与当前连接attach记录。首条输入之前失败时不发送pendingFirstMessage，不执行模型。

绑定在SQLite保存当前本人/资料范围、规范原生session_id、日期/时区、当前清单/事项及正式快照/次序版本；不保存active回调、token、问题或正文。同编号同内容返回原结果，内容变化拒绝。绑定不授予业务写入权限。新的事项选择建立明确的新绑定；进行中轮次使用其接收时固定的绑定版本，旧响应不能改变后续选择。新增动作同样使用原编号只读恢复，需要接入nanobot-client.ts:1074的已有中断处理，结果未知时不依赖默认mutation重放。配套建议新增GET /api/boss/ui/morning/binding?client_request_id，由当前本人认证读取该编号的绑定元信息或NOT_FOUND_IN_CURRENT_STORE，write_performed_by_lookup=false；此读取接口同样需要N3登记严格Schema，当前尚不存在。

### 每轮可信采用与请求关联

RoleChannel在已认证message进入上游router之前，按chat_id及规范有效turn_id保存本轮服务端记录，包含绑定版本、原始内容摘要、当前连接身份和可重新检查的active回调。需要使用原生normalize_webui_turn_id保证原始turn_id与metadata.webui_turn_id一致，不能允许缺少编号后在两个位置生成不同编号。记录只在服务端创建；任意session_id、模型文本或客户端metadata不能创建该记录。上游仍构建原生metadata并保存原文。

新增ProductMorning.native_context(request)作为第一个应用context provider，位于runtime_control.context、Skills/Memory、晨间scope及FeatureRecorder之前。该provider从服务端保存的本轮记录找到绑定，逐项核查request.channel=websocket、sender_id=boss-1、chat_id、session_key、metadata.webui_turn_id、原始输入摘要、绑定版本及当前active；随后重新读取当前资料范围、正式清单/事项/来源和order_version，生成本轮MorningRequest并写入request.attributes[MORNING_REQUEST]。这些步骤失败必须终止本轮。已经绑定晨间的会话如果缺少当前连接证明、授权失效或服务重开后尚未建立本轮记录，同样拒绝进入模型，不能进入其他FeatureProvider分支。

每轮独立创建morning_public_request和Runtime运行，保留同一原生session_id，以及当前客户端turn_id、runtime_request_id和run_id。不能重复使用已经RUNNING/SUCCEEDED的首轮公共请求记录，因为现有bind_runtime只允许PREPARED进入RUNNING。原意图编号需要稳定关联chat_id/turn_id，内容摘要包括原始输入、绑定编号/版本和当前选择；重复同一轮只读取已有结果或原生历史，不再次入队。已有正式清单的domain_client_request_id继续指向创建该清单的原编号，后续讨论复用morningListRead/detail/source，不重新执行todayRead。轮次终止后清理进程内连接证明；持久请求及历史只保留获准标识和结果状态，不恢复active回调。

第一条自然问题没有已有清单时，可以通过本轮todayRead产生正式清单；清单关联只从本轮实际工具结果及运行记录取得并保存，下一轮读取该正式清单。原生RuntimeContextBlock和技术记录继续由已有Fc03RuntimeRecorder形成。FeatureProvider/FeatureRecorder现有MORNING_REQUEST分支和FORMAL_TOOLS继续使用，当前没有建立第二个模型循环的必要。ProductMorning.events只消费最近用户输入之后的本轮工具结果，并根据可信当前选择读取实际详情及对应document。持久历史中的旧依据不能替代当前来源检查；来源失效时在模型调用之前拒绝本轮，历史保留只读标识。

### 返回、重连与必要验证

App与BossDesktop继续使用同一原生会话和现有NATIVE页面；F01返回记录需要包含原生chat_id及原始morningRequest、morningItem、morningDate、morningTimezone和页面已有筛选/位置/焦点。URL仅存放获准标识，原始问题留在原生历史。返回F01重新读取当前正式对象，重新打开讨论时选择已绑定chat_id；通用onStartAutomationChat每次创建新会话的行为不能直接作为继续讨论。退出/身份失效沿用clearPrivateNativeState，并撤销本轮active证明；重新认证及服务重开后需要当前已认证连接重新建立本轮证明，单独读取会话历史不构成继续执行授权。

N3最终候选需要定向验证：F01原问题只提交一次且在原生历史可见；第二条自然问题进入同一websocket会话、新run和同一正式事项；工具结果与来源当前版本一致；返回并重新进入恢复事项和会话；伪造chat_id/turn_id/metadata、维护身份、撤销、来源变化及无当前证明的服务恢复均在模型调用前拒绝；中断后原编号核查不重复查询或业务变更。当前只读核查没有执行这些公共路径，不登记C11/C13/C16/C17通过。
