# FC02 Agent开发记录

task_id：FC02-N2；当前独立适配及正式领域组合22项检查通过，等待公共候选验收；唯一功能状态来源为原始项目specs/feature-delivery.json，验收依据为docs/FC02经营查询工单.md二十项检查点。Agent代码提交15aeb1d1c61c50e5958565e2bb5c021c2b35fc79，包含validation/fc02_agent、app/tests/fc02_agent和本目录记录；保留SESSION-HANDOVER-W5.md。文档有效性CURRENT，核查日期2026-10-24。

已完整读取当前工单与功能状态、适用AGENTS.md，核查PRD8.3、正式query_metrics/read_evidence、BusinessTool及RuntimeRecorder和FC01技术适配。S008规范继续适用。N1正式领域提交fe3010563c6986eff6f0c26c1b5b2554d061cff6已在N2隔离组合接收；公共基线2a49d2f7bd6a529a324c43d6155f243acfe401e3。仅在FC02独立模块定义可信执行上下文，不新增领域状态或修改公共入口。

当前工作对应FC02.C03/C10/C12/C13/C16/C17及适用异常。外部模型明确SIMULATED，领域与Registry、Runtime、SQLite实际执行。正式SCOPED查询、幂等及持久追问恢复使用N1接口；真实认证生产者与公共接收由N3提供。完整二十项判定由N4执行。

## 入口与输入输出

版本1.0.0。register_fc02_tools(registry,store,context_provider)仅注册query_metrics/read_evidence；名称冲突在修改Registry之前拒绝，没有交办、发送、审批或本人确认工具。Fc02Tool参数直接使用当前business.SPEC正式输入定义，保留oneOf、SCOPED和全部依赖引用，仅去除服务端注入字段；执行继续调用现有BusinessTool和Store.invoke。业务计算、来源绑定、查询对象和回执没有另建实现。

| 接口 | 输入 | 输出与职责 |
|---|---|---|
| bind_query | 当前完整正式参数、previous_query_id、previous_parameters、overridden_fields | 冻结QueryBinding；只允许明确字段覆盖，其他字段保持继承；该函数没有业务授权能力 |
| bind_scoped_followup | store、当前可信context、parent_query_id、question、overrides | 使用N1 BIQueryAPI.read读取当前正式context_snapshot，按bi_follow_up Schema核查，返回QueryBinding；核查同一会话及当前来源，不调用模型或创建查询 |
| Fc02Tool(query_metrics) | 当前正式查询参数 | 必须匹配服务端事先保存的唯一QueryBinding；正式SCOPED追问额外核查实际父查询的context_snapshot，再调用确定性查询 |
| Fc02Tool(read_evidence) | query_id、source_ids、detail_refs | 仅允许当前Runtime请求实际产生的查询或服务端明确选择的历史query_id，之后由正式领域核查明细/原文/来源版本 |
| Fc02Tool.receipt | 当前可信请求，不接收模型参数 | 使用N1 BIQueryAPI.receipt读取同一session_id/request_id的原回执，不重新执行查询；NOT_FOUND_IN_CURRENT_STORE不能推断原请求未执行 |
| interface_contract | store、context_provider | contract.py返回实际Tool Schema、可见上下文JSON Schema与Runtime扩展字段 |

QueryBinding.visible提供parameters、previous_query_id、overridden_fields、inherited_fields和parameters_sha256。parameters保留当前正式维度，question正文不进入技术记录。query_mode及parent_query_id作为路由信息单独表达，不累计为维度覆盖字段。新问题必须提供完整明确字段；追问只覆盖当前明确输入。

## 可信身份及上下文生产者

Fc02Context字段为role、owner_id、namespace、dataset_id、dataset_version、request_id、session_id、active、query_bindings及readable_query_ids。query_bindings为tuple[QueryBinding,...]，readable_query_ids为frozenset[str]。N3从实际认证会话、当前合法查询与用户明确字段构造这些值；不能根据模型工具参数即时建立绑定，不能把直接构造dataclass作为生产身份依据。模型参数中的owner、namespace、envelope或confirmed被正式Schema拒绝。

Runtime调用同时核查RuntimeBinding的数据库、执行空间、请求、会话及sender_id；每次调用核查当前账号状态、owner与数据集版本，返回前再次核查。read_evidence的已选query_id与实际查询对象共同验证；来源正文和讨论不能扩大权限。正式SCOPED父查询从持久context_snapshot验证，当前旧查询缺少正式快照时不能登记完整持久追问验收。

## 实际模拟Runtime

Fc02SimulatedProvider、Fc02RuntimeRecorder及Fc02RuntimeHook位于runtime.py。它们复用FC01已经检查的技术事件记录和终态实现，实际BI链路单独运行；Registry严格限定两项BI工具。事件生产者接口为async(messages,tools)->LLMResponse，messages包含实际工具结果，usage必须为None；没有网络客户端、自动重试或备用结果。查询、明细和原因缺口均取自实际返回，不能按标签给出预设业务成功或因果解释。

Runtime准入检查当前正式Schema与可信维度，提供boss-bi-query-context上下文。技术记录feature_id=FC02、source_type=SIMULATED，保存当前配置、模型、Prompt、Schema和工具实现摘要；bi_query_context记录可见继承/覆盖条件，bi_readable_query_ids记录服务端选择。工具结果关联实际query_id、父查询、detail_refs、definition_versions、source_refs和结果摘要；实际查询对象在SQLite独立重读。失败/取消/超时保留对应终态和已经保存的查询，未知usage/cost_total/price_version为null；模型质量及真实外部完成观察保持false。没有保存question正文、来源正文、原始模型回答或凭据。

公共认证入口、F03/N03/D01、Client/Provider、RoleChannel、配置目录、公共Schema和构建由N3接收。本模块没有修改公共文件或FC01源码；不能据本地模拟事件宣布公共BI已经接入。

## 验证与证据

当前准确组合22项通过、零跳过。bi-check.xml保存17项通过，4.72秒；scoped-check.xml保存5项通过，5.56秒。组合身份与源码blob见combination.json。17项包括真实查询与明细/原文、SQLite重建读取、明确维度继承和覆盖拒绝、实际两次BI Runtime追问及query_id连接、维护/失效身份/错误空间与资料版本拒绝、模型参数和请求关联拒绝、历史查询选择、来源撤销后停止当前采用、失败/取消/超时保留实际查询、费用null及正文排除。5项正式组合覆盖原请求幂等与回执、正式持久快照追问、超时后原查询恢复、实际SCOPED Runtime追问/依据、撤销后的历史回执。检查使用获准selection资料，socket.connect审计拒绝外部连接。

```bash
env PYTHONDONTWRITEBYTECODE=1 FC02_DOMAIN_ROOT=/Users/liuhaoxian/.codex/worktrees/boss-sop-writes/Boss-Agent/validation/.work/fc02-fe30105-combination validation/.venv/bin/python -m pytest app/tests/fc02_agent/test_scoped.py -q -p no:cacheprovider --basetemp=validation/.work/fc02-scoped-fe30105 --junitxml=validation/.work/fc02-scoped-fe30105.xml
env PYTHONDONTWRITEBYTECODE=1 FC02_DOMAIN_ROOT=/Users/liuhaoxian/.codex/worktrees/boss-sop-writes/Boss-Agent/validation/.work/fc02-fe30105-combination validation/.venv/bin/python -m pytest app/tests/fc02_agent/test_agent.py -q -p no:cacheprovider --basetemp=validation/.work/fc02-bi-fe30105 --junitxml=validation/.work/fc02-bi-fe30105.xml
```

命令workdir为/Users/liuhaoxian/.codex/worktrees/boss-sop-writes/Boss-Agent；数据库及中间数据位于已忽略validation/.work。没有启动服务、占用端口或操作其他进程；没有重跑无变化FC01全量检查。

隔离检出validation/.work/fc02-fe30105-combination的HEAD为公共基线2a49d2f，使用git cherry-pick --no-commit接收准确fe30105；staged修改只包含该提交的七项文件。Agent适配和专有检查来自15aeb1d，其他Runtime/Prompt依赖来自公共基线。原始角色目录只读，未接收未验收授权消费文件。本组合用于N2限定检查，未登记为N3正式公共候选。

N3形成公共候选后，可在N2目录设置FC02_DOMAIN_ROOT为该完整候选绝对路径，使用PYTHONDONTWRITEBYTECODE=1运行受影响专有检查，并将basetemp和XML保存在N2独立目录。该参数只选择实际候选源码；不在其他角色目录写入缓存、数据库或证据。

## 必要剩余与接收条件

已核查N1正式fe30105的specs/bi-query.schema.json、boss_bi_queries.py、business.SPEC组合及实际消费者，五项正式组合检查全部通过。Agent源码无需追加修改；本次只补充当前准确组合证据和接收记录。

N3需要接收N1正式领域和本独立模块，提供真实认证及当前请求生产者，采用明确SIMULATED Provider及两项Registry工具，把可见继承/覆盖条件、当前query_id与原回执接入公开页面，接收技术扩展Schema并发布准确候选。随后由N4核查完整二十项。当前22项限定检查通过不代替公开账号/UI或完整功能PASS；不启动FC03。真实外部模型质量、费用、投递及视觉均未执行。
