# FC03 Agent开发记录

task_id：FC03-N2；当前正式清单/详情/来源及受限Runtime适配IMPLEMENTED，等待公共候选验收。唯一功能状态为原始项目specs/feature-delivery.json，需求及完整22项为docs/FC03晨间事项工单.md。基础读取提交5aca0f3；当前独立模块validation/fc03_agent、专有检查app/tests/fc03_agent；保留SESSION-HANDOVER-W5.md。核查日期2026-10-24，文档有效性CURRENT。

已完整读取工单、适用AGENTS.md，核查TodayAPI、BossTodayReadTool、Registry及Recorder，继续使用S008开发记录与BDD规范。正式领域已接收准确e3faa5dcd90831d5e84e42c6ca66b418f85b767c及morning.schema.json 1.0.0。只复用正式MorningAPI创建和读取清单，不建立另一套领域状态或本人排序入口。完整公共鉴权、F01和Client/Provider由N3接收。

## 当前入口与可信上下文

版本1.0.0；register_fc03_tools(registry,store,context_provider)默认只注册兼容的空参数todayRead；formal=True明确选择正式模式，注册todayRead、morningListRead、morningDetailRead、morningSourceRead。名称重复时在修改Registry之前拒绝。正式todayRead仅接收Day，其他三项只接收list_id及对应item_id/source_id。参数沿用当前正式Day/Id定义，额外owner、namespace、confirmed和client_request_id被拒绝。没有排序、交办、发送、审批、日历修改或维护载入工具。

Fc03Context字段：role、owner_id、namespace、dataset_id、dataset_version、request_id、session_id、active、read_parameters_json、date、timezone、snapshot_sha256、order_version；正式模式追加client_request_id及allowed_list_ids，保留旧构造兼容。日期、时区、快照及次序版本取自当前正式MorningAPI.read预览，read_parameters_json保存批准的Day。client_request_id来自原公共晨间意图，重连/超时后保持；allowed_list_ids为服务端明确选择的已有清单集合。N3需要从真实认证会话及当前正式对象生产这些值，不能根据待执行模型参数即时签发范围，不能把直接构造dataclass作为生产认证。

每次调用校验实际active空间、owner及dataset版本；存在Runtime时核查同一SQLite、namespace、request_id、session_id及sender_id。正式读取结果必须与可信date/timezone/snapshot_sha256/order_version一致；返回前再次核查认证范围。本人保存次序后需要新的当前绑定；模型无法通过旧快照采用新的次序。源对象与来源的完整采用政策继续由N1正式领域确定，本模块不补造来源有效性。

## Runtime、模拟事件和技术记录

Fc03SimulatedProvider继承当前已验证的无网络模拟Provider，模型事件生产者接口为async(messages,tools)->LLMResponse，只接受todayRead集合且usage必须为None。事件生产者从实际工具消息形成返回内容，不按问题标签生成预设清单或成功文本；实际执行Nanobot、AgentLoop、ToolRegistry、TodayAPI和SQLite。当前上下文source为boss-morning-context，明确business_authority_granted=false。

Fc03RuntimeRecorder/Fc03RuntimeHook复用真实配置、工具Schema及实现源码摘要、Prompt版本、事件与终态机制，技术记录feature_id=FC03、source_type=SIMULATED。morning_context保存date/timezone/snapshot_sha256/order_version及参数摘要；tool_results关联实际tool_call_id、business_clock和item_refs（item_id/object_id/version/source_refs）。标题、问题、来源正文、私人正文及模型回答不进入这些技术记录。模型真实质量与外部调用观察保持false，未知usage/cost_total/price_version保持null。

正式todayRead校验冻结的Day/快照/次序，再调用MorningAPI.query(role,{client_request_id,session_id,date,timezone})保存同意图清单。同编号同内容只产生一份清单，查询没有问题正文或业务授权。读取、详情、来源先核查morning_list的实际请求/会话或allowed_list_ids及日期快照，再调用正式read_list/detail/source；对象/来源变化由正式领域拒绝，当前本人次序变化同样要求新绑定。模型没有historical选择权。

FormalMorningTool.receipt()不注册模型工具，按可信client_request_id调用MorningAPI.receipt(role,boss.morning.query,id)，只返回原元信息，不重放query；NOT_FOUND_IN_CURRENT_STORE保持未知。失败/取消/超时后独立ControlStore重建读取同一list_id/list_version，已保存清单和原回执保留。历史采用资格继续由正式MorningAPI.read_list(historical=True)及私人内容清理规则处理，公共恢复入口由N3接收。

contract.py的interface_contract(...,formal=True)返回四项实际Tool Schema和技术扩展字段，供N3公共Schema/工具配置/构建接收。Fc03SimulatedProvider(...,allowed_tools=FORMAL_TOOLS)严格采用当前四项集合；Fc03RuntimeRecorder使用实际已注册todayRead进行可信输入校验。morning_context追加client_request_id；tool_results追加list_id/list_version、事项source_refs与document_ref（source_id/version），不保存原文或私人详情。

## 限定验证

19 passed，4.49秒；原始XML为check.xml。使用获准selection数据，经实际ControlStore.initialize创建隔离空间；没有伪造来源、替换业务记录或外部请求。网络socket.connect审计拒绝所有外部连接。技术配置只为实际Registry启用todayRead，未签发本人业务授权。

Given 当前正式晨间投影及可信范围；When 通过实际Registry读取并由Nanobot消费结果；Then 模型返回的items与领域实际items相同，缺少资料保留，运行引用在独立ControlStore重建后可查。覆盖维护/失效身份/错误owner/空间/dataset/日期/快照拒绝、模型额外参数与Runtime请求伪造拒绝、重复注册、正式本人排序后旧绑定拒绝、模型失败/取消/超时、认证撤销后停止后续步骤、费用null和私人正文排除。排序前置仅通过明确BOSS的TodayAPI.reorder形成，模型没有该入口。

```bash
validation/.venv/bin/python -m pytest app/tests/fc03_agent -q -p no:cacheprovider --basetemp=validation/.work/fc03-agent-current --junitxml=docs/feature-delivery/FC03/check.xml
```

workdir固定为/Users/liuhaoxian/.codex/worktrees/boss-sop-writes/Boss-Agent；数据库与中间结果位于已忽略validation/.work/fc03-agent-current。有效业务Red为同目录fc03-agent-order-red.xml的旧排序绑定断言失败，Green见当前check.xml。没有运行FC02全量、当前新领域组合、公共账号/页面或视觉检查；没有启动服务、端口或操作用户预览。

## 正式领域组合与验证

准确组合为公共8769fbe0b9e62dd131f6aef4c6ede390af5d2fbe加N1正式e3faa5dcd90831d5e84e42c6ca66b418f85b767c；N2隔离检出validation/.work/fc03-formal-e3faa5d使用git cherry-pick --no-commit接收该正式提交，其他角色目录只读。当前组合boss_morning.py blob为f6d009defc85ce152407aca1cda9d8709a291753，morning.schema.json为e0a54c9d7424d5a1b7351fea0bc3ac4dbecf66ce。Agent源码来自当前N2专有修改，没有接收未验收授权消费文件。

正式组合8 passed，6.35秒，formal-check.xml：实际SDK/Registry消费Query→ReadList→Detail→Source，当前日期/模型请求字段拒绝，未选择清单拒绝，来源撤销后当前采用拒绝且原回执保留，本人排序后冻结绑定拒绝，以及失败/取消/超时后只有一份清单和同编号回执。模型返回内容采用实际工具结果，技术引用的list_id/list_version和来源版本逐项核查，标题与问题未进入技术记录。预览/维护/业务前置均使用正式API，未改写检查数据库。

本次工具注册/Recorder变化影响的原消费者6 passed、13 deselected，4.67秒，consumer-check.xml；没有重跑原19项全量、FC02或其他功能全量。原check.xml保留其独立基础范围，不与正式组合混充同候选完整22项。

```bash
env PYTHONDONTWRITEBYTECODE=1 FC03_DOMAIN_ROOT=/Users/liuhaoxian/.codex/worktrees/boss-sop-writes/Boss-Agent/validation/.work/fc03-formal-e3faa5d validation/.venv/bin/python -m pytest app/tests/fc03_agent/test_formal.py -q -p no:cacheprovider --basetemp=validation/.work/fc03-formal-final --junitxml=docs/feature-delivery/FC03/formal-check.xml
validation/.venv/bin/python -m pytest app/tests/fc03_agent/test_agent.py -q -k 'actual_runtime or terminal or revocation or only_current' -p no:cacheprovider --basetemp=validation/.work/fc03-legacy-consumers --junitxml=docs/feature-delivery/FC03/consumer-check.xml
```

## 公共接收条件与下一动作

N3接收N1正式领域及本独立提交，提供真实认证/请求生产者、明确formal=True与FORMAL_TOOLS、原client_request_id/session_id及已选清单绑定、SIMULATED Provider/Recorder、公共技术Schema/构建和F01真实入口。原编号恢复调用只读receipt，按正式当前/历史资格呈现，不根据模型决定重放或本人排序。完整C03/C18/C19/C20及二十二项仍待N3准确候选和N4独立验收；不登记完整功能PASS，不启用FC04。STT暂停；真实模型质量、投递、设备及视觉均NOT_RUN。
