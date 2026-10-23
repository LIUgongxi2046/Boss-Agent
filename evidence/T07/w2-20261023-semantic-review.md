# T07 语义核对

核查对象为W2提交1d13d77及本轮接收修改、W1提交5b34dcf77963351f249686375a76f07ac4486d03的数据/API1.3.1，以及独立环境安装的nanobot0.3.5。正式规范使用确定Git对象，实际W1源码在检查前后验证字节一致。当前摘要由check_agent_assets.py、check_tool_semantics.py和check_received_v13.py保存。本核对为同一执行者的独立断言和源码审阅，另一审查者尚未签署完整A07。

正式规范当前引用fc4b2b5/1.4.1；本记录Tool和会议动作的实际领域结果仍适用于上述1.3.1确定源码。1.4.1复验受到W1未提交business.py修改影响，在版本断言处终止。1.4.1结构检查已实际核验15条真实运行、8条当前生产者记录及4个故障查询投影；两条历史记录缺少正式Schema要求的model_attempts_coverage和工具implementation_sha256，差异见design-check报告。历史数据保持原样，公共兼容验收继续待完成。四项TypedDict事件字段已通过1.4.1核查。

## 当前 Tool

四次真实 DeepSeek 记录包含 query_metrics/read_evidence/create_assignment/send_assignment 各4次，以及 read_assignment 共12次。所有输入输出通过 W1 指定的独立 selection-probe.io_schema 根校验；模型可见参数另行校验，envelope、authorization_id、idempotency_key 不在模型参数中。保存、模拟发送和重读关联同一 task_id，message_id 出现在任务 message_ids，任务从 OPEN 到 WAITING_FEEDBACK；该状态没有表示本人已经确认完成。

| Tool | 当前语义 | 核查限制 |
|---|---|---|
| query_metrics | 当前owner/类型/有效性通过后计算Decimal指标，同事务保存query和query_source_binding | 当前获准产品和两个十日期间；没有新增农业明细 |
| read_evidence | 重查查询范围、当前来源版本/完整元信息与明细摘要，返回一致版本 | 旧查询、同版本元信息变化或缺少绑定409；重新query_metrics取得新query_id；非当前来源409/410，访问错误403 |
| create_assignment | 当前完整授权、来源、负责人及期限校验，保存OPEN和assignment_source_binding | 一份授权不能通过不同请求编号新增多项交办；固定关联范围继续保留 |
| send_assignment | 当前授权、对象版本、负责人和创建时来源绑定校验，保存模拟消息与WAITING_FEEDBACK | 创建后来源变化或缺少绑定409；模拟发送不证明外部送达；原回执不执行新发送 |
| read_assignment | 按原始Schema投影已保存任务及消息引用，保留服务端扩展字段 | 读取状态不产生本人完成授权或新的来源许可 |

实际W2 BusinessTool调用W1 1.3.1领域服务通过来源版本检查：旧query_id返回409，新查询与原文均报告版本2，正文保持相同。缺少绑定、同版本元信息变化及RECEIVED/INCOMPLETE/CONFLICTED/SUPERSEDED分别409，WITHDRAWN/EXPIRED分别410；失败结果未作为成功Tool结果释放。另实际创建、模拟发送、重读、同编号回执、重复授权拒绝、撤销后原回执与创建后来源变化拒绝发送通过。检查保存2项任务和1项模拟发件箱，没有新增模型请求或真实收件人。证据为w2-20261023-tool-semantics.json。

模型参数继续排除envelope、authorization_id和idempotency_key，实际授权由当前服务端绑定。现有Audit在工具错误发生后终止当前尝试；409引导后续新请求重新查询，当前检查没有声明模型在同一次失败运行内自动恢复。正式error_output与公共HTTP/事件错误响应映射仍需W3同一集成版本验证。历史28项结果校验不能替代当前1.3.1完整五工具模型过程。

## 十三项 SOP

| SOP | 已核查的当前处理位置与语义 | 完整实施条件 |
|---|---|---|
| SOP01 今日工作 | TodayAPI._read/reorder按业务日期和对象组织事项；W2 BossTodayReadTool实际读取现有3项事项、当前次序和资料缺口；写入继续核查完整事项集合、snapshot_sha256和version | 共同应用接入，完整日历与专题来源，模型实际采用 |
| SOP02 经营提醒 | OwnerPlansAPI及ControlStore分别控制本人范围和技术执行；W2 BossOwnerPlansReadTool实际返回现有空计划与CronService责任，暂停/取消、事件版本与授权撤销继续由业务服务判断 | 有计划记录的完整生命周期、唯一Cron共同版本执行、周期计划、设备通知及模型说明 |
| SOP03 经营查询 | W2 Tool与W1 1.3.1实际组合提供确定性指标、来源绑定和版本一致原文 | 当前集成版本的模型过程及获准业务覆盖 |
| SOP04 会前准备 | compile_brief读取会议、人员职责、历史承诺、来源、指标和关联影响；prepare保存待审阅状态 | 来源有效期/冲突统一检查，资料变化、模型准备与公共页面验证 |
| SOP05 会议纪要 | minutes_confirm绑定会议、纪要、原文及版本；单项交办另行创建，确认纪要不自动发送 | 统一来源政策，模型分类、逐项本人决定、完整后续流程 |
| SOP06 交办跟进 | 当前五Tool覆盖创建、模拟发送及重读；公共命令另有延期、完成、取消和催办 | 新增命令的模型注册与当前授权绑定；反馈和本人终态完整过程 |
| SOP07 待审材料 | approval_decide核查当前申请、附件、金额和币种；决定仅保存记录，专业放行和资金转移均为false | 模型材料核查、来源有效性、本人决定及共同应用流程 |
| SOP08 沟通 | message_send核查草稿版本、内容摘要、收件人及附件；保存SENT_SIMULATED，delivery_state为NOT_VERIFIED | 模型草稿流程、来源有效性及真实通道条件 |
| SOP09 战略研究 | boss_research按范围读取原文版本；W2采用有效期与明确冲突政策，事实确认集合保持空值；获准finance-note四阶段真实引用已通过 | 公共注册、获准公开资料及完整检索 |
| SOP10 人员会面 | people.attach重新编译联系人、资料、任务及反馈并比较摘要；不会改变参会人员或发出邀请 | 统一来源政策，模型会面准备及共同应用核查 |
| SOP11 出行接待 | travel.confirm重新核查时间、资料及当前冲突影响，比较review_sha256，要求本人确认已知冲突与交通缺口；当前会议可提供已确认结束时间 | 获准交通来源、模型过程及共同应用 |
| SOP12 私人安排 | calendar.share仅允许busy/starts_at/ends_at/timezone；撤销与删除保存独立结果 | 模型当前授权、完整公共访问与分享恢复检查 |
| SOP13 历史与记忆 | confirmed_memory同事务核查当前对象与确认授权；撤销后停止新任务采用，新确认采用新版；获准样本的新Runtime及新会话已验证 | 公共入口、已有会话/缓存、历史及备份传播与物理擦除；未知期限保持未知 |

其余 SOP 的 WebSocket 操作定义存在，当前只注册五项模型 Tool。未把接口定义、页面按钮或本地领域测试登记为全部方法已经被模型采用。

## 事件与状态

| 事件 | 当前源码含义 | 验收边界 |
|---|---|---|
| webui_response | RoleChannel按request_id返回ok与result/error | 与业务client_request_id分开，不表示模型任务完成 |
| message/tool_events | send_projected_message区分普通回答、tool_hint和progress | Tool事件动态结构与私人内容权限仍需公共边界验证 |
| delta | send_delta发送回答增量，可带stream_id | 不能根据增量文字更新正式业务终态 |
| stream_end | 结束当前片段，支持resuming/merge_next | 不等于完整turn结束，不能假定全域sequence |
| turn_end | encode_turn_end投影用量、错误和状态；completed时可省略outcome | 与本人业务完成分别表达，缺少用量不能填写零 |
| recovery_state/retry_status | 记录恢复与重试的实际状态 | 不提供业务写入重放授权；当前Provider没有自动重试 |
| context_compaction | 表达压缩开始和终止阶段 | 项目配置关闭自动压缩，未登记其业务采用通过 |

锁定上游提供reasoning_delta/reasoning_end及其保存方法。当前非思考模型检查没有观察到这些事件；公共通道和SessionManager的过滤需要W3在同一集成SHA独立验证，本次字段核对不提供已经泄露或已经完成过滤的结论。原生运行模型、会话和goal事件与上述业务事件范围分别管理，本Schema没有覆盖全部原生WebSocket协议。

## 接收责任

- W1：提供确定的当前业务模块、规范和来源访问规则；继续独立语义、迁移与完整字段验收，接收W2 Runtime扩展。
- W2：维护 `boss_source_policy.source_validity`、研究与Prompt领域采用；完成获准原文的真实模型检查及实际费用；继续各项已具备条件的领域验证。
- W3：公共来源检查调用当前业务时间与执行空间；接入研究source_issues/conflicted_sources展示；保持BOSS正文与维护元信息隔离；过滤内部推理并关联持久run/session/request/配置/Tool结果。

A07继续未验收。W3须共同接收W1确定业务源码与W2适配，完成公共版本、来源/授权采用、完整模型方法注册及同一集成SHA复验；独立审查者签署继续待完成。
