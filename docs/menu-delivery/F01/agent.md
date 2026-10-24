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
