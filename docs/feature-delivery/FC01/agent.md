# FC01 Agent 执行记录

task_id：FC01-N2；需求：FR-06/14/21/28/29，FC01.C16/C17及C06—C12；状态：IMPLEMENTED，公共候选待接收。功能状态来源为原始项目specs/feature-delivery.json。文档有效性CURRENT，核查日期2026-10-23。

代码基线255101b77d75f966c1e510a5fa158c628b2180ea；保留未提交的SESSION-HANDOVER-W5.md。已读取当前工单、开发计划、适用AGENTS.md、W5交接与S008规范，按功能读取PRD、HLD、LLD、Schema、Desktop v6 Token和对应源码。七项准备工具及135项限定检查复用。

## 实现与接口

版本1.0.0，模块validation/sop_write_tools/fc01；注册函数register_fc01_tools(registry,store,context_provider,allowed_tools=...)接受明确集合，同名工具或本人操作在修改Registry之前拒绝。公共application、RoleChannel、Catalog、ProductRuntime和构建由N3维护。

| 工具 | 输入 | 实际处理与输出 |
|---|---|---|
| bossSupplyQualityRead | interface_id，仅SI09/SI10 | 正式read_projection和Projection Schema；完整计算、当前来源、review_sha256及未知范围；接收1.8.0后采用其成本计算 |
| bossSupplyQualityQuery | 正式Query，interface_id仅SI09/SI10、object_ids、filters | SimulationAPI.query；原料/法人/产品/批次/归属/期间及当前来源保护；字段来自当前领域Schema |
| bossEvidenceRead | source | 当前BossEvidenceReadTool与BossPageAPI的原文、作者与版本 |
| bossSupplyQualityPrepare | CoordinateInput去除client_request_id | 同一读取事务核查当前review_sha256、来源版本和完整采用依据、负责人及期限；返回coordinate_input、source_refs、preparation_sha256、owner_decision_required=true及F14/F21入口；零任务、零授权写入 |
| query_metrics/read_evidence | 既有正式输入，移除服务端字段 | 复用BusinessTool与Store，保持查询及当前依据语义 |
| create_assignment/send_assignment | 既有正式输入，移除envelope/authorization_id/idempotency_key | 仅消费当前服务端绑定的已存在本人授权；实际Store.invoke核查完整内容、来源、CAS、幂等及撤销 |
| read_assignment | task_id | 正式任务重读，保留同一对象与版本 |

contract.py的interface_contract(store,context_provider)返回版本、实际Tool Schema、preparation_output完整JSON Schema和Runtime扩展字段。新增检查验证实际准备输出符合Schema。输入维持原始类型，模型不能提交confirmed、owner、namespace等字段。

## 可信请求与本人交接

Fc01Context字段为role、owner_id、namespace、dataset_id、dataset_version、request_id、session_id、allowed_tools、active、input_bindings、authorization_bindings。认证、账号有效状态、执行空间与允许工具由N3服务端生产者提供。input_bindings是(name,content_digest(params))的frozenset；准备和写入须事先绑定完整内容、对象及来源摘要。不能根据待执行模型参数即时签发绑定，不能把直接构造dataclass作为生产授权。

authorization_bindings为(name,content_digest(params),authorization_id,idempotency_key)的tuple，仅引用本人已签发授权及原幂等编号。实际Runtime调用额外核查RuntimeBinding的数据库、namespace、request_id、session_id及sender_id；执行及返回前重新检查当前认证与资料范围。

准备结果供本人F14/F21表单采用，编辑和放弃由D06维护。boss.supply_quality.coordinate只由N3明确本人确认入口调用，它会创建本人授权，禁止注册为模型工具。本人完成、发送决定、来源确认及专业处置没有新增模型入口。缺少合法授权时，写入工具保持未注册或明确拒绝。

Fc01Tool.receipt(params)只读取原写入的idempotency回执，不注册模型工具；它核查当前范围、原内容摘要和原幂等编号，返回RECORDED或NOT_FOUND_IN_CURRENT_STORE，后者不能证明原动作未执行。公开断开/取消/超时继续保留原request_id与idempotency_key；协调回执继续使用SupplyQualityAPI.receipt。

## Runtime与状态记录

Fc01SimulatedProvider继承安装版本nanobot的LLMProvider，明确模拟事件生产者读取实际messages和tools并返回LLMResponse；没有网络客户端、自动重试或替代结果。实际Nanobot、AgentLoop、ToolRegistry、RuntimeRecorder和SQLite处理工具调用，事件生产者不能返回预设业务成功。

Fc01RuntimeRecorder/Fc01RuntimeHook复用当前准入、配置/Prompt版本、工具定义与源码摘要、查询/任务关联以及失败/取消/超时终态。增加source_type=SIMULATED、external_model_invoked=false、external_delivery_verified=false、feature_id=FC01及simulated_model_events；事件保存event_id、状态、请求摘要和tool_call_ids。工具结果增加来源标识/版本、review_sha256、准备摘要、source_refs、origin及结果摘要。工具错误只保存类别与调用编号。原始参数、模型回答、来源正文及凭据不进入这些记录；模型质量与真实完成观察为false，未知usage/cost_total/price_version保持null。

N3接收时需要在公共Runtime Schema中接收contract.py列出的技术扩展字段，并采用当前记录读取服务。当前独立检查启用maxToolResultChars=200000，完整领域投影进入实际模型消息；公共接入需要核查实际配置与当前输出容量，不能把SDK输出文件引用当成已经读取完整结果。

## 验证与证据

19项限定检查通过，19.08秒；原始XML为check.xml。入口app/tests/sop_write_tools/fc01/test_tools.py，输入为获准data/simulation/supply-quality-v1.yaml，经正式维护导入，使用nanobot-ai 0.3.5及独立SQLite。socket.connect审计拒绝全部外部连接，没有新增外部请求。

```bash
validation/.venv/bin/python -m pytest app/tests/sop_write_tools/fc01/test_tools.py -q -p no:cacheprovider --basetemp=validation/sop_write_tools/.work/fc01-verified --junitxml=docs/feature-delivery/FC01/check.xml
```

全部命令workdir为/Users/liuhaoxian/.codex/worktrees/boss-sop-writes/Boss-Agent。独立数据库位于忽略规则覆盖的validation/sop_write_tools/.work/fc01-verified。检查覆盖准备零授权写入、正式输出Schema、资料换版、维护/失效身份/错误owner与空间、模型内容篡改、本人操作注册拒绝、缺少发送授权、正式筛选、实际Runtime采购/品质/原文/准备调用、本人协调后同一task_id重读及原协调回执、失败/取消/超时、工具拒绝后停止、日志正文排除及Runtime请求绑定。

七项工具135项证据没有重跑。检查仅证明本目录适配限定行为，旧父任务及十八项功能分母保持原语义。

## 接收与必要剩余

N1提供9bd2f9f及daedc63/1.8.0，由N3接收。N2未修改业务状态机或复制N1文件。本目录领域基线为1.7.0，适配从实际领域导入Schema；1.8.0报告成本、期间及cost_owner_id与公共消费者需要在N3候选复验。

N3接收本模块及专有检查，提供真实认证/请求绑定生产者，选择明确SIMULATED Provider、注册所需集合、更新公共目录/准入/Schema/构建，将准备内容接入本人F14/F21及D06，提供准确候选；N4核查同候选C16/C17及C06—C12。当前公开认证生产者、合法未消费授权的公共模型写入、实际页面交接、公开恢复及独立完整候选尚未验收，不能登记完整功能PASS。外部模型质量、费用、投递、设备及视觉均未执行。没有启动服务或后台进程，不启动FC02。
