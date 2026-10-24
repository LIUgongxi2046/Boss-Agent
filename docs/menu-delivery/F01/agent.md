# MENU-F01-N2 今日工作Agent开发记录

task_id=MENU-F01-N2；decision_id=D-MENU-DELIVERY-20261024；marker=MENU-F01-START-20261024。当前N2独立工具及Runtime接口版本1.1.0，公共采用等待N3准确组合。菜单正式状态唯一由N3维护，当前记录不登记完整菜单或用户验收通过。文档有效性CURRENT，核查日期2026-10-24。

## 需求、依据与范围

已读取原始PRD最前当前决定、菜单总计划、menu-plan.json、F01完整18项及完整产品PRD的FR-01/BR-01/AC-01-S/E、BR-C02和E01—E06；核查当前LLD适用的Runtime、身份、工具、日志和返回上下文规则，复用FC03实际SDK、正式MorningAPI及既有开发记录。当前工作只修改N2晨间工具、Runtime、专有检查与记录；页面、公开请求、认证、公共Schema及唯一正式状态由N3维护。

当前ProductMorning通过Nanobot和实际Registry执行todayRead、morningListRead、morningDetailRead、morningSourceRead，公开请求支持list_id/item_id。N2的原生适配器消费N3当前准确内容c441a4eec001612238f34941bf02d746af71d7bd及24f5c64领域组合。公共原生会话注册、输入保留与页面返回由N3在最终候选接收并验证。

事项选择适配的十五项限定证据采用e3faa5dcd90831d5e84e42c6ca66b418f85b767c及morning.schema.json 1.0.0。当前原生适配器采用N3准确组合24f5c64及其接收的N1 89d26855，正式Schema为morning.schema.json 1.1.0。全量资料范围、分类、关联合并、时间冲突、排序和来源有效性仍由正式领域确定，公开字段只按准确接口消费。

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

## 原生会话接续适配器

marker=MENU-F01-N2-NATIVE-IMPLEMENT-20261024；N3要求N2实现可信原生绑定与逐轮上下文，公共ProductMorning、RoleChannel、application、App、Client及Schema由N3维护。当前validation/fc03_agent/native.py版本1.0.0，使用现有实际SDK与正式领域，没有另建模型循环或注册本人决定工具。源码核查依据包括N3公共基点b7fdc76、当前24f5c64组合及N3当前ProductMorning；公共传输与页面采用仍等待N3准确候选。

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
| 晨间采用 | ProductMorning._grant读取MORNING_REQUEST；FeatureProvider.chat和FeatureRecorder.context已有该分支；scope_context设置FEATURE_SCOPE，FeatureToolRegistry据此限制真实工具。N2的native_context生产该上下文，公共注册由N3接收 |

### 已实现方法与严格输入

NativeMorningAdapter(service, *, request_attribute="product_morning_request")接收当前真实ProductMorning实例。模块不导入公共ProductMorning类型，N3可以直接组合该适配器；service._request产生的实际MorningRequest通过dataclasses.replace仅采用规范原生session_id，正式数据、选择及认证回调保持真实来源。

| 方法签名 | 输入与返回行为 |
|---|---|
| bind(role, client_request_id, payload, *, attached, active) | client_request_id独立来自原公开请求编号，payload只接受chat_id/date/timezone及成对可选list_id/item_id。attached(chat_id)与active()必须由当前连接生产；规范session_id由webui_session_key生成。返回binding_receipt |
| binding_receipt(role, client_request_id, *, active) | 只读原绑定；返回source_type、client_request_id、outcome、result、adoption_state、write_performed_by_lookup=false、business_authority_granted=false。未知编号为NOT_FOUND_IN_CURRENT_STORE，result=null |
| admit(role, chat_id, turn_id, content, *, attached, active) | 原生message提交前调用。未绑定会话返回None且不限制其既有输入；已绑定会话严格核查当前认证、attach、原生有效turn_id及原文。返回enqueue和turn_receipt；重复原轮次enqueue=false，原文变化拒绝 |
| native_context(request) | 第一个应用context provider；核查可信本轮证明、原文摘要、规范websocket身份/会话、当前本人资料、快照、次序及来源，向attributes写入实际MorningRequest；没有当前证明的已绑定会话拒绝进入模型 |
| turn_receipt(role, chat_id, turn_id, *, active) | 只读当前轮次原请求，返回ProductMorning.receipt的client_request_id/request_state/run_id/receipt/write_performed_by_lookup，并追加chat_id/turn_id/session_id/binding_id |
| hook_factory(context) / finish(client_request_id) | hook_factory为真实NativeMorningHook，on_finally清理本轮进程内证明。finish也用于未进入Runtime的已准备轮次，状态记为FAILED；已有run_id时保留实际Runtime终态 |

绑定在当前SQLite的morning_native_binding保存owner/资料范围、规范会话、日期、快照/次序及选择标识，不保存token、active回调、问题或来源正文。每个chat_id只能存在一个明确绑定；新的事项选择使用新的原生会话与绑定，避免把同一会话历史关联到另一事项。原编号同内容可重读，内容变化拒绝。查询回执标记NOT_REVALIDATED_BY_LOOKUP，不把原元信息当作当前采用证明。

每轮稳定编号由chat_id和原生turn_id摘要形成。admit复用实际service._request建立morning_public_request，保存native_binding_id/native_chat_id/native_turn_id/native_content_sha256；将实际请求和grant的session_id关联到规范原生会话。原始问题只进入SDK原生会话，技术行仅有摘要。当前轮次尚未终止时拒绝并发新输入，重复同一轮仅恢复原回执。绑定last_request_id通过SQLite事务检查；其他服务抢先采用轮次时，本轮拒绝进入Runtime。

首轮没有清单时，由实际todayRead创建正式清单；下一轮从上一实际公共回执取出已保存list_id并核查日期、快照和来源，后续采用morningListRead/detail/source。模型失败后已经保存的清单及原回执保持，下一轮仍按真实当前资格处理。运行期间每次读取grant.active都重新核查连接、当前本人/资料范围、正式快照、次序及来源，资料撤销或范围变化不会继续消费旧依据。active回调及本轮证明只存在进程内，服务重新建立适配器后不会凭session_id恢复执行权限。

### N3公共接入位置

application.py在同一个ProductMorning上建立一个NativeMorningAdapter实例，将native_context注册为第一个应用provider，位于runtime_control.context、Skills/Memory、晨间scope及FeatureRecorder之前；现有FORMAL_TOOLS、FeatureProvider、FeatureRecorder及真实Runtime继续使用。将adapter.hook_factory加入当前AgentLoop的hook_factories，沿用现有Recorder生成独立request_id/run_id，每轮保留同一规范原生session_id。晨间scope在公共注册中继续核查四项正式工具已启用及至少五轮，与独立query的当前配置要求一致。此适配器不调用bot.run，不注册模型授权工具。

RoleChannel新增boss.morning.bind，直接将当前envelope.request_id作为bind的client_request_id，payload不接受另一编号或身份字段。attached必须查询当前连接的webui_connection_chats，active复用现有token/角色/过期/连接检查。新增GET /api/boss/ui/morning/binding?client_request_id读取binding_receipt；新增动作及严格响应字段由N3接收Schema。客户端将绑定动作加入现有中断后原编号恢复范围，禁止默认mutation重放。刚创建但尚无持久历史的原生会话，凭服务端new_chat与当前attach记录核查。

RoleChannel在已认证message交给原生router之前调用admit。返回None时继续既有普通会话处理；enqueue=true时才允许原生处理一次，enqueue=false时只读恢复并重新读取原生历史。turn_id必须原样通过原生normalize_webui_turn_id校验，随后metadata.webui_turn_id保持相同编号。原生router仍负责内容、媒体、workspace校验及保存用户原文，不接受客户端提供的attributes作为证明。

上游处理可能在实际webui_dispatch_message之前拒绝输入，RoleChannel需要在未成功入队时调用finish(client_request_id)，不能把super返回直接当作已入队。已入队后由NativeMorningHook清理；在其他应用provider失败且尚未生成运行hook的路径，同样调用finish以保存准确未执行状态。适配器自己的native_context校验失败已经执行该清理。服务重开后缺少证明的旧轮次仅查询原编号，不自动重新入队。

App先通过现有onCreateChat创建原生会话，等待bind成功后设置pendingAutomationMessage，后续自然输入继续走同一ThreadShell。F01返回记录包括原生chat_id、morningRequest、morningItem、morningDate、morningTimezone及已有筛选/位置/焦点；原始输入保存在原生历史，URL只有获准标识。继续已有讨论时重新选择已绑定chat_id。页面、真实WebSocket交接、返回状态及公开Schema仍由N3验证。

### 原生适配器限定证据

隔离候选validation/.work/menu-f01-native-public来自N3已提交24f5c64，包含N1 89d26855及N2事项选择接口。ProductMorning使用N3本次已读取内容，隔离文件blob=c441a4eec001612238f34941bf02d746af71d7bd；boss_morning.py blob=84b0097e20be7a620c2edbf91dd58e1fb9243180，morning.schema.json blob=3b77ff3a85dd1947a2be2a815a313a5ee32b06db。N3该公共文件尚未提交时以准确blob记录依赖，不将其称为已提交生产者。N2只在自己的隔离候选使用同内容，没有修改N3文件。

app/tests/fc03_agent/test_native.py明确从当前N2的validation/fc03_agent/native.py导入待测模块，并检查实际源码位置；其余接口从上述准确隔离候选导入。真实Nanobot/AgentLoop、FeatureProvider/FeatureRecorder、FormalMorningTool、MorningAPI和SQLite共同执行。检查配置只采用实际四项正式读取工具，未知usage/cost保持null。批准selection资料由ControlStore.initialize生成，模型回复消费实际工具结果；失败事件明确SIMULATED。没有读取凭据、启动服务、建立网络连接、执行视觉功能或触碰用户UI02/MVP。

```bash
env PYTHONDONTWRITEBYTECODE=1 FC03_NATIVE_DOMAIN_ROOT=/Users/liuhaoxian/.codex/worktrees/boss-sop-writes/Boss-Agent/validation/.work/menu-f01-native-public validation/.venv/bin/python -m pytest app/tests/fc03_agent/test_native.py -q -p no:cacheprovider --basetemp=validation/.work/menu-f01-native-current --junitxml=docs/menu-delivery/F01/native-check.xml
```

native-check.xml保存24 passed、20.01秒的当前实际结果。BDD覆盖两轮原始输入及历史、同一原生会话的独立run、第一轮实际清单复用、明确选中事项、严格绑定参数、当前角色/连接、身份与路由伪造、并发与重复、改变原文、来源在调用之前及模型步骤之间撤销、模型失败/取消/超时及原回执、证明清理、普通会话不受晨间限制和重建适配器后只读恢复。实际原生WebSocket与页面返回尚未执行；这些限定SDK证据不登记完整C11/C13/C16/C17或菜单通过。
