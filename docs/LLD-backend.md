# Boss-Agent 后端设计

版本1.2.0；T06/A06；2026-10-23；引用LLD-data1.2.0、PRD V1.2.0和HLD1.0.0。字段、operationId、角色、输入/结果、错误与事件作为W2/W3确定接收版本；OpenAPI3.1标准检查通过。A06保持NOT_RUN，完整合法输入匹配、独立语义与公开集成仍需验证。

## 服务、身份与事务

RoleChannel 从服务端认证确定 BOSS/MAINTAINER；HTTP 查询和 WebSocket 写入复用同一身份。联系人、正文、模型、payload.role/owner_id 不提供身份。前端只能提交动作参数；owner、namespace、数据集和有效资料版本由服务端验证。MAINTAINER 可以配置技术参数和提供获准模拟反馈，不能完成、批准、发送或读取私人正文。

`BossCommandAPI.execute` 是已有写入入口；`BossPageAPI.serve` 是已有读取入口。所有动作按当前 `ACTION_ROLES` 验证角色。当前业务空间 `ui-check` 的来源为获准 selection 数据集；不能冒充生产企业资料。SQLite 保存正式状态，聊天和工具文本只引用对象 ID。

写入事务顺序为 BEGIN IMMEDIATE → active space → 原请求查重 → 当前对象/版本/来源/授权检查 → 业务对象和授权写入 → 幂等回执 → 最小审计 → COMMIT。异常使事务不提交；模型后续失败不删除已经提交的结果。

`client_request_id` 为8—128位 ASCII 字母数字及 `-_.`；namespace+action+key 唯一。digest 绑定动作与全部业务参数。同键同内容返回原结果，同键不同内容409。CAS 使用当前 version 字符串。读取回执不重放动作；没有回执表示当前存储尚未发现，不能推断原动作未发生。

## 传输协议

现有读取使用 `/api/boss/ui/*` HTTP Bearer。现有写入使用已认证 nanobot WebSocket：`type=webui_request, request_id, action, payload`；响应 `event=webui_response, request_id, ok, result|error`。业务幂等 ID 在 payload 内，与传输 request_id 分开。重新连接产生新传输请求时仍保留原 client_request_id。此协议没有 Last-Event-ID 或 SSE 心跳承诺。

OpenAPI定义全部当前HTTP读取、58项基线WebSocket命令、9项W1领域动作及5个工具；每项命令绑定角色、输入Schema、处理位置和必需回执字段。workspace路径参数及BOSS/MAINTAINER投影白名单分别定义，原请求回执采用原动作相同角色。十四类模拟接口逐项给出输入、结果、实体、现有读取位置、可用状态和缺少来源；通用模拟查询协议仍属于设计，需要T12接入真实服务。

Runtime提交使用`type=message,chat_id,content`，当前会话取消使用同一入口和`content=/stop`，停止该会话活动及队列中的后续步骤。线程读取使用既有Runtime入口。独立T02验证服务的健康、空间、工具与配置路径在`x-validation-service.routes`分别定义角色；这些路径用于验证，不增加产品业务入口。

## W1 新增接口接收规范

| operationId | 身份与参数 | 调用和结果 | 使用方 |
|---|---|---|---|
| ownerPlansRead | BOSS，无查询参数 | `OwnerPlansAPI(store).read(role)`：plans/events/results/dispatches/technical_schedule | N09、W3 |
| ownerPlanSave | BOSS，client_request_id、plan_id（新建为空字符串）、expected_version、purpose、event_ids、timezone、not_before | `execute(role,"save",payload)`；保存 ACTIVE 或保留 PAUSED；事件范围唯一绑定 | N09、W3 |
| ownerPlanPause | BOSS，client_request_id、plan_id、expected_version | ACTIVE→PAUSED，返回新 version | N09、W3 |
| ownerPlanResume | 同上 | PAUSED→ACTIVE，重新保存本人确认授权 | N09、W3 |
| ownerPlanCancel | 同上 | ACTIVE/PAUSED→CANCELED；终态不恢复；历史保持 | N09、W3 |
| todayRead | BOSS，无查询参数 | `TodayAPI(store).read(role)`：items/category/reason/source_refs/snapshot_sha256/order_version | F01、W3 |
| todayReorder | BOSS，client_request_id、expected_version、snapshot_sha256、item_ids | `TodayAPI(store).reorder(role,payload)`；核对完整当前集合，返回新 version 和 authorization_id | F01、W3 |
| meetingArrangementRead | BOSS，无查询参数 | `MeetingAPI(store).read(role)`；当前会议、独立草稿、引用范围、核查状态与历史版本 | F04、W3 |
| meetingDraftSave | BOSS，meeting_id、meeting_version、expected_version（草稿）、purpose、完整时间/时区、preparation_due_at、participant_ids、source_refs及client_request_id | `execute(role,"draft.save",payload)`；保存草稿和影响摘要，当前安排保持 | F04、W3 |
| meetingConfirm | BOSS，meeting_id、meeting_version、draft_version、review_sha256、acknowledge_conflict及client_request_id | `execute(role,"confirm",payload)`；核查完整上下文与来源后产生当前SCHEDULED版本 | F04、W3 |
| meetingCancel / meetingHeld | BOSS，meeting_id、expected_version（会议）、reason及client_request_id | `execute(role,"cancel"或"held",payload)`；独立本人确认；终态不恢复，举行需开始时间已经到达 | F04、W3 |

四项会议动作与读取路径在`specs/openapi.yaml`标记PENDING_W3。F01/N09此前版本已由W3接入，记录见W3的T11；本目录当前1.2.0增量仍需相同集成版本复验。不得把领域检查当作公共入口或设备验收。

会议完整时间通过IANA时区和UTC时差校验，结束须晚于开始，持续时间上限31天；准备期限可空，提供时须位于当前业务时间与会议开始之间。参会对象使用唯一有效联系人标识，材料引用校验当前许可、撤销和版本。私人占用及行程缓冲产生冲突条件，确认时重算摘要并要求本人明确知晓。保存草稿不签发安排授权；确认、取消与举行分别保存本人授权。meeting_materials被会前材料、纪要、人员会面、行程、私人日历、今日投影和恢复读取采用；公共查询与W2上下文接入要求见T14。

计划只控制已有获准事件的时间和范围，不创建第二个 Cron。时间条件限 Asia/Shanghai，not_before 在当前业务时间之后366天以内；执行时还检查事件期限、保存时 event_versions、本人计划状态、当前撤销状态、技术启停、规则、免打扰、暂缓和去重。`authorization_id` 是已保存计划的本人确认依据；其撤销即时停止继续采用。15分钟授权窗口用于当次确认提交，已经保存的持续计划由当前 ACTIVE 状态、绑定对象版本及未撤销确认共同控制。

当前计划未包含晨间模型生成和周期重复定义；需要 W2 提供真实 Runtime 任务能力和 W3 接入后继续完成，不登记 A17 完成。已有事件更新时保留 owner_plan_id 并检查 event_versions，不自动扩大本人范围。

今日投影按待决定、待协调、需要知晓组织当前未结束任务、本人承诺、申请、会议、事件及私人占用。相同任务事件合并；来源 ID 与版本可查。重要事项持续优先，其余采用本人次序；新事项追加当前默认顺序。当前完整日历结束时间和农业区域覆盖不足，必须显示 PARTIAL/INSUFFICIENT_EVIDENCE。

## 状态和拒绝条件

交办、消息、审批、会议、资料、提醒、运行与记忆状态完整继承 PRD 第5节。现有领域方法必须区分草稿、模拟发送、外部送达、反馈提交和本人完成；没有外部通道回执时 delivery_state 不得宣称已验证。

本人计划暂停和取消不删除已经保存的任务、通知或消息。取消后迟到反馈保存为historical_only，保持任务CANCELED和已取消事件；当前领域接收已验证，公共反馈入口的状态检查与回执仍需W3接入。资料撤销、更新和申请变更使对应旧确认失效。已确定结果需查询原回执和正式对象，无自动新编号重发。

| 错误 | 状态 | 自动重试 | 恢复 |
|---|---|---|---|
| UNAUTHENTICATED |401|禁止|重新认证后读取当前状态|
| FORBIDDEN |403|禁止|核对当前身份和获准范围|
| NOT_FOUND |404|禁止|核对当前对象和空间，不泄露受限正文|
| INVALID_INPUT |400|禁止|修正输入后由本人提交|
| VERSION_OR_IDEMPOTENCY_CONFLICT |409|禁止|读取当前对象/原请求，重新确认变化|
| SOURCE_WITHDRAWN / SHARE_INACTIVE |410|禁止|停止采用已撤销资料或分享|
| BOSS_SERVICE_NOT_READY |503|禁止自动写入|核查服务后读取原请求|

领域函数在出错位置抛出 HTTPException 或输入错误；公共边界仅转换为安全响应。日志只记录身份、动作、状态、对象/授权 ID 与版本；不记录私人正文、录音、凭据或内部推理。

## 十四类模拟接口责任

| PRD 接口 | 当前数据/能力与完整性 |
|---|---|
| SI01 档案组织 | owner_profile 与本人设置；完整组织字段待补充 |
| SI02 联系关系 | contacts、people 会面；真实职责与资料限定获准样本 |
| SI03 日历出行 | private_calendar、calendar_share、travel、meeting/draft；会议状态与关联采用领域已验证，公共接入待完成 |
| SI04 消息邮件 | draft/send/reply 与 outbox；外部送达未验证 |
| SI05 会议资料 | brief/minutes/逐项交办；来源变化复核 |
| SI06 任务承诺 | assignment/commitment/feedback/延期/完成/取消；历史反馈领域已验证，公共接入待完成 |
| SI07 销售 BI | query_metrics/read_evidence；当前仅获准的两个十日期间明细 |
| SI08 财务应收 | 成本收入明细；现金、账龄和结算数据不足 |
| SI09 采购库存 | 原料合同/库存质量等获准数据不足 |
| SI10 生产品质 | 专业批次/追溯/措施数据不足 |
| SI11 审批 | application/decision，按材料与版本校验 |
| SI12 外部信息 | 获准原文知识；未配置真实实时检索 |
| SI13 知识资料 | document/FTS5/撤销；摄取与实际模型采用由 W2 验证 |
| SI14 通知中心 | event/reminder/dispatch/delivery；Cron 唯一来源，系统通知由 W3 验证 |

## Runtime、外部依赖和观察

Runtime保持单一nanobot AgentLoop。取消停止尚未执行步骤，已提交写入继续可查。超时、工具错误、轮数上限分别记录stop_reason。runtime-events定义回执、普通消息与工具活动、文字增量、流片段结束、turn结束、恢复、重试状态和上下文压缩事件，字段来自锁定nanobot0.3.5源码。chat_id/turn_id/stream_id与业务run_id通过服务端记录关联，没有全域sequence或SSE恢复承诺。内部reasoning事件不得进入普通业务投影，实际通道过滤由W2/W3验证。

DeepSeek 适配当前使用120秒超时、max_retries=0；没有备用模型。语音和检索的真实服务/权限、限制与费用由 W2 核查，缺少条件保持 BLOCKED。当前本机领域调用使用10秒 SQLite 锁等待；没有已测吞吐和限流阈值。发生故障保留准确错误、已执行结果及未知费用；业务服务不返回替代成功内容。

配置草稿、校验、启用、下一任务实际采用分别留证。模型/Prompt/知识由 W2 维护；本人目标和通知只能 BOSS 确认。运行关联 run_id/session_id/request_id/tool_id、namespace、数据/配置/来源/授权版本、真实时间、usage 与价格来源；缺少计费覆盖时总额 null。

## 验证与剩余交付

领域检查与全部当前 app/tests 已实际执行，见 T17/T18 主记录。完整公开路径接入、所有现有 action 的独立请求/响应 Schema、全部14类接口、Runtime 流事件、取消/超时模型验证、并发撤销、旧库恢复、设备通知与完整持续计划尚未验收。OpenAPI/事件结构检查仅证明格式；T06/A06 继续保留未验收状态。
