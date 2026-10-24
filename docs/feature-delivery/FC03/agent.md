# FC03 Agent开发记录

task_id：FC03-N2；当前现有读取及受限Runtime基础IMPLEMENTED，正式清单接口待接收。唯一功能状态为原始项目specs/feature-delivery.json，需求及完整22项为docs/FC03晨间事项工单.md。代码基线92a6e01；当前独立模块validation/fc03_agent、专有检查app/tests/fc03_agent；保留SESSION-HANDOVER-W5.md。核查日期2026-10-24，文档有效性CURRENT。

已完整读取工单、适用AGENTS.md，核查现有TodayAPI、BossTodayReadTool、Registry及Recorder。继续使用S008开发记录与BDD规范。当前N1正式日期/清单/详情/回执Schema尚未提供，现有读取参数为空对象。本模块只接收当前实际读取结果的date/timezone/snapshot_sha256/order_version，不建立另一个领域清单或本人排序入口。完整公共鉴权、F01和Client/Provider由N3接收。

## 当前入口与可信上下文

版本1.0.0；register_fc03_tools(registry,store,context_provider)只注册todayRead，名称重复时在修改Registry之前拒绝。Fc03TodayTool直接复用现有BossTodayReadTool的parameters及execute，当前参数为严格空对象，不接收模型提交日期、owner、namespace或confirmed。身份、日期、来源或对象由模型正文推断时不会自动建立可信绑定。没有排序、交办、发送、审批、日历修改或其他本人决定工具。

Fc03Context字段：role、owner_id、namespace、dataset_id、dataset_version、request_id、session_id、active、read_parameters_json、date、timezone、snapshot_sha256、order_version。日期、时区、快照及次序版本均取自当前正式TodayAPI返回；read_parameters_json保存服务端事先批准的准确读取参数。N3需要从真实认证会话及当前正式读取对象生产这些值，不能依据待执行模型参数即时签发范围，不能把直接构造dataclass作为生产认证。当前独立检查中的身份与Runtime编号绑定只证明Adapter范围判断。

每次调用校验实际active空间、owner及dataset版本；存在Runtime时核查同一SQLite、namespace、request_id、session_id及sender_id。正式读取结果必须与可信date/timezone/snapshot_sha256/order_version一致；返回前再次核查认证范围。本人保存次序后需要新的当前绑定；模型无法通过旧快照采用新的次序。源对象与来源的完整采用政策继续由N1正式领域确定，本模块不补造来源有效性。

## Runtime、模拟事件和技术记录

Fc03SimulatedProvider继承当前已验证的无网络模拟Provider，模型事件生产者接口为async(messages,tools)->LLMResponse，只接受todayRead集合且usage必须为None。事件生产者从实际工具消息形成返回内容，不按问题标签生成预设清单或成功文本；实际执行Nanobot、AgentLoop、ToolRegistry、TodayAPI和SQLite。当前上下文source为boss-morning-context，明确business_authority_granted=false。

Fc03RuntimeRecorder/Fc03RuntimeHook复用真实配置、工具Schema及实现源码摘要、Prompt版本、事件与终态机制，技术记录feature_id=FC03、source_type=SIMULATED。morning_context保存date/timezone/snapshot_sha256/order_version及参数摘要；tool_results关联实际tool_call_id、business_clock和item_refs（item_id/object_id/version/source_refs）。标题、问题、来源正文、私人正文及模型回答不进入这些技术记录。模型真实质量与外部调用观察保持false，未知usage/cost_total/price_version保持null。

技术引用可以通过原run_id/request_id重读；失败/取消/超时及认证撤销保留实际终态和已完成读取的引用。当前TodayAPI读取不创建正式清单对象，N2没有把技术引用冒充持久清单或原业务回执。list_id/list_version、详情及原请求恢复在N1正式接口接收后补充关联，不自动重放排序或其他写入。

contract.py的interface_contract返回实际Tool Schema和技术扩展字段，供N3公共Schema、工具配置和构建接收。当前只能处理领域已经支持的默认业务日期；F01可选日期的实际传递等待正式Adapter参数，不能据当前空参数工具声明日期选择完成。

## 限定验证

19 passed，4.49秒；原始XML为check.xml。使用获准selection数据，经实际ControlStore.initialize创建隔离空间；没有伪造来源、替换业务记录或外部请求。网络socket.connect审计拒绝所有外部连接。技术配置只为实际Registry启用todayRead，未签发本人业务授权。

Given 当前正式晨间投影及可信范围；When 通过实际Registry读取并由Nanobot消费结果；Then 模型返回的items与领域实际items相同，缺少资料保留，运行引用在独立ControlStore重建后可查。覆盖维护/失效身份/错误owner/空间/dataset/日期/快照拒绝、模型额外参数与Runtime请求伪造拒绝、重复注册、正式本人排序后旧绑定拒绝、模型失败/取消/超时、认证撤销后停止后续步骤、费用null和私人正文排除。排序前置仅通过明确BOSS的TodayAPI.reorder形成，模型没有该入口。

```bash
validation/.venv/bin/python -m pytest app/tests/fc03_agent -q -p no:cacheprovider --basetemp=validation/.work/fc03-agent-current --junitxml=docs/feature-delivery/FC03/check.xml
```

workdir固定为/Users/liuhaoxian/.codex/worktrees/boss-sop-writes/Boss-Agent；数据库与中间结果位于已忽略validation/.work/fc03-agent-current。有效业务Red为同目录fc03-agent-order-red.xml的旧排序绑定断言失败，Green见当前check.xml。没有运行FC02全量、当前新领域组合、公共账号/页面或视觉检查；没有启动服务、端口或操作用户预览。

## 正式接收条件与下一动作

N1当前记录基线31b6313，已说明date/timezone、list_id/list_version/snapshot_sha256及排序兼容方向；FC03正式Schema、准确方法签名和实现提交尚未提供。接收时需要：逐日读取及IANA规则、可查询清单/详情/来源和采用资格、同意图幂等与原回执读取、当前/历史及排序版本语义。N2将依据该唯一正式定义修改必要只读Adapter、可信绑定与技术引用，不另外定义业务日期或清单状态。

N3接收本独立模块和准确提交，提供真实认证及请求生产者、仅todayRead的请求级Registry范围、明确SIMULATED Provider/Recorder选择、公共技术Schema/构建及F01真实入口。正式领域到达后，只执行受影响的FC03组合检查。现有19项只是当前读取基础，完整C03/C18/C19/C20及二十二项仍待N3候选和N4独立验收；不登记完整功能PASS，不启用FC04。STT暂停；真实模型质量、投递、设备及视觉均NOT_RUN。
