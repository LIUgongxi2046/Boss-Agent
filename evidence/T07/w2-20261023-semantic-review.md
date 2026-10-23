# T07 语义核对

核查对象为 W2 提交7f67aa6及当前来源有效性修改，W1 提交3f5b806的数据/API1.0.0，以及独立环境安装的 nanobot0.3.5。当前文件与运行证据摘要由 `check_agent_assets.py`、`check_tool_semantics.py` 保存。该核对属于同一执行者的独立断言与源码审阅，未由另一个审查者签署完整 A07。

## 当前 Tool

四次真实 DeepSeek 记录包含 query_metrics/read_evidence/create_assignment/send_assignment 各4次，以及 read_assignment 共12次。所有输入输出通过 W1 指定的独立 selection-probe.io_schema 根校验；模型可见参数另行校验，envelope、authorization_id、idempotency_key 不在模型参数中。保存、模拟发送和重读关联同一 task_id，message_id 出现在任务 message_ids，任务从 OPEN 到 WAITING_FEEDBACK；该状态没有表示本人已经确认完成。

| Tool | 当前语义 | 核查限制 |
|---|---|---|
| query_metrics | 使用获准明细与固定维度执行 Decimal 计算，并保存 query_id | 当前仅两项产品和两个十日期间，不覆盖全部农业专题；来源有效期与冲突需调用统一政策 |
| read_evidence | 使用已保存 query_id 限制来源与明细，返回当前原始记录 | 来源版本更新为2后，sources.version仍为1，需 W1 修复；完整事实引用验收保持未通过 |
| create_assignment | 服务端注入授权，校验对象内容与幂等，保存 OPEN | 当前固定关联范围，不能推定全部交办类型已覆盖 |
| send_assignment | 核查任务版本、OPEN状态和收件人，保存模拟消息与 WAITING_FEEDBACK | 不提供外部送达证明；当前模型工具与公共命令分别实现，需要统一来源政策 |
| read_assignment | 从 SQLite 查询任务与消息引用 | 读取状态不产生本人完成授权 |

来源版本问题通过真实 Store.invoke 和 SQLite 复现，没有发送模型请求或改变正文。原始结果为 `w2-20261023-tool-semantics.json`：current_document_version=2，reported_source_version=1。W1 的 Store.source、Store.read_evidence 应返回一致的当前版本，或明确拒绝旧查询并要求重新读取。

## 十三项 SOP

| SOP | 已核查的当前处理位置与语义 | 完整实施条件 |
|---|---|---|
| SOP01 今日工作 | W1 TodayAPI._read/reorder按业务日期和对象组织事项；次序写入核查完整事项集合、snapshot_sha256和version | 共同应用接入，完整日历与专题来源，模型实际采用 |
| SOP02 经营提醒 | OwnerPlansAPI及ControlStore调度分别控制本人范围和技术执行；暂停/取消、事件版本与授权撤销参与判断 | 唯一Cron的共同版本执行、周期计划、设备通知及模型说明 |
| SOP03 经营查询 | 五项已注册Tool中的query_metrics/read_evidence提供确定性结果及原文 | 修复来源版本与有效性，补充获准业务覆盖 |
| SOP04 会前准备 | compile_brief读取会议、人员职责、历史承诺、来源、指标和关联影响；prepare保存待审阅状态 | 来源有效期/冲突统一检查，资料变化、模型准备与公共页面验证 |
| SOP05 会议纪要 | minutes_confirm绑定会议、纪要、原文及版本；单项交办另行创建，确认纪要不自动发送 | 统一来源政策，模型分类、逐项本人决定、完整后续流程 |
| SOP06 交办跟进 | 当前五Tool覆盖创建、模拟发送及重读；公共命令另有延期、完成、取消和催办 | 新增命令的模型注册与当前授权绑定；反馈和本人终态完整过程 |
| SOP07 待审材料 | approval_decide核查当前申请、附件、金额和币种；决定仅保存记录，专业放行和资金转移均为false | 模型材料核查、来源有效性、本人决定及共同应用流程 |
| SOP08 沟通 | message_send核查草稿版本、内容摘要、收件人及附件；保存SENT_SIMULATED，delivery_state为NOT_VERIFIED | 模型草稿流程、来源有效性及真实通道条件 |
| SOP09 战略研究 | boss_research按范围查询原文位置并重读版本；W2新增有效期与明确冲突检查，事实确认集合保持空值 | 原文外发授权后的真实引用检查、获准公开资料及完整检索 |
| SOP10 人员会面 | people.attach重新编译联系人、资料、任务及反馈并比较摘要；不会改变参会人员或发出邀请 | 统一来源政策，模型会面准备及共同应用核查 |
| SOP11 出行接待 | travel.confirm重新核查时间、资料及当前冲突影响，比较review_sha256，要求本人确认已知冲突与交通缺口 | 完整会议结束时间、交通来源、模型过程及共同应用 |
| SOP12 私人安排 | calendar.share仅允许busy/starts_at/ends_at/timezone；撤销与删除保存独立结果 | 模型当前授权、完整公共访问与分享恢复检查 |
| SOP13 历史与记忆 | 本人确认及删除分开；Store.context只读取CONFIRMED；获准单条样本已验证删除后的新Runtime/新会话 | 新确认记忆的authorization_id持久关联、有效期、撤销、历史与备份传播 |

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

锁定上游还提供reasoning_delta/reasoning_end及其保存方法。W2/W3当前RoleChannel源码没有对应过滤覆盖。当前非思考模型检查没有观察到这些事件，不能据此宣称实际内容已经泄露；仍需 W3 在公共通道明确禁止内部推理正文进入普通响应、会话保存和业务审计。原生运行模型、会话和goal事件与上述业务事件范围分别管理，不能把此Schema当作全部原生WebSocket协议。

## 接收责任

- W1：修复Tool来源版本；在统一来源检查、会前材料、会面资料和受控检索中采用当前有效期与冲突政策；维护T05/T06对valid_until、validity_state和研究结果新字段的定义。
- W2：维护 `boss_source_policy.source_validity`、研究与Prompt领域采用；完成获准原文的真实模型检查及实际费用；继续各项已具备条件的领域验证。
- W3：公共来源检查调用当前业务时间与执行空间；接入研究source_issues/conflicted_sources展示；保持BOSS正文与维护元信息隔离；过滤内部推理并关联持久run/session/request/配置/Tool结果。

A07仍未验收。公共版本、正式来源修复、原文外发授权、完整模型方法注册及独立审查者签署分别具有明确解除条件。
