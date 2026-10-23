# Boss-Agent 前端设计

版本：0.4.3；日期：2026-10-23；T08/A08；状态：IN_REVIEW。已接收T05/T06 1.5.0和T07 0.6.0-draft，公共Runtime扩展0.2.0等待正式接收，源码版本`ccfca967`及W3公共接入。本文件记录已核查工程与设计要求；完整字段、全部页面及状态审查和T03视觉仍未完成，A08保持NOT_RUN。

## 1. 资产与工程映射

PRD V1.2.0维护FR-01—32、AD01—16及AC。HLD 1.0.0维护唯一身份、Runtime、数据库与Cron责任。`specs/hld-72-page-map.json`维护完整72页面架构；`specs/page-service-map.json`维护当前真实源码、读取路径和写入动作。本文件引用该全量集合，不另设页面数量或缩减功能范围。

固定前端为nanobot commit `1bb712d3488915ca4ed9ccc1a93067ff722f5ab9`的React 18、TypeScript、Vite工程。`scripts/prepare_boss_webui.py`把`app/webui/`加入同一认证Shell。构建目录为本worktree的`.work/product/nanobot`，正式dist位于其`nanobot/web/dist`。构建manifest记录上游和页面元数据摘要。静态HTML承担设计预览，产品使用React业务组件。

实际导航使用`?bossPage=<page_id>`与浏览器history；`NATIVE`用于上游会话。N01/D08 通过版本化认证修改接入 `BossLogin`。页面ID与角色必须同时通过`allowed`及服务端身份检查；客户端路径不授予权限。技术页面由MAINTAINER访问，业务页面由BOSS访问，D06/D07使用认证后的公共状态。

## 2. 身份、数据与副作用

`RoleChannel`从bootstrap秘密建立API与WebSocket token对应角色；`/api/boss/identity`返回当前服务端角色。渲染入口只能使用该结果。联系人identifier、payload.role、owner_id及URL不能替代认证。维护请求业务正文和本人确认动作必须被服务端拒绝。

领域状态只由SQLite事务维护。读取采用当前认证token、`cache:no-store`和AbortController；组件显示服务器返回的source_type、对象ID、版本与日期。写入通过上游`client.requestMutation`、稳定`client_request_id`及服务端CAS。保存、校验、启用和下一任务采用分别显示。未知结果先查询原回执，不自动生成新动作。

私人正文、录音及Prompt不进入通用遥测、URL或前端持久缓存。浏览器仅保留完成当前交互所需本地状态。登出及身份改变后清除业务投影、草稿和选择；异步回调需确认当前身份、对象与请求版本。服务错误显示当前失败位置和已执行结果；模型输出不更新正式状态。

## 3. Token与可访问性

权威值为`Boss-Agent-Desktop-Complete-v6/design-tokens.json`，公共映射为`app/webui/boss-v6.css`。全部领域组件继承相同字体、颜色、间距与焦点规则。

| Token | 值 | 使用位置 |
|---|---|---|
| brandBlue/deepBlue | #005BAC / #073B70 | 品牌与导航 |
| brandGreen/actionBlue | #5CA63B / #0968EA | 正常状态与操作 |
| background/surface | #F5F7FA / #FFFFFF | 页面与卡片 |
| text/secondaryText | #172B4D / #52647A | 正文与说明 |
| error/focus | #B42318 / #0A64E8 | 错误与键盘焦点 |
| typography | 16px/24px、14px/22px | 正文与辅助内容 |
| spacing | 8px单位、18—24px卡片内边距 | 共享布局 |
| radii | 14px卡片、9px输入框 | 卡片与表单 |
| accessibility | 44px操作目标、2px焦点 | 键盘和指针 |

字体使用Noto Sans CJK SC / PingFang SC。遵循prefers-reduced-motion。需要在1024×768、1280×800、1440×1024和200%缩放验证内容、长文本、表单错误、弹窗与滚动区域。没有批准的独立深色设计，完整界面遵循v6设计参数。视觉结果NOT_RUN。

## 4. 类型与状态所有权

已有类型以`BossDesktop.tsx`及对应领域组件为当前源码来源；T06 Schema确定后逐项核对序列化。本阶段不新增未经定义的API字段。

```typescript
type Role = "BOSS" | "MAINTAINER";
type Identity = { role: Role | null; owner_id: string | null };
type SourceAnchor = { source_id: string; version: string; start: number; end: number };
```

| 状态 | 维护者与来源 | 恢复与失效 |
|---|---|---|
| role | 服务端identity，Shell读取 | 失效token需要重新认证 |
| page | URL与BossDesktop | 刷新按当前角色检查page_id |
| selectedTaskId、sourceAnchor | BossDesktop | 跨页面保留稳定ID和来源版本 |
| assignmentDraft、settingsDirty | 表单及Shell | 离开前确认；未经确认不发送 |
| dashboard、tasks、meetings | 服务端投影 | 刷新重新读取，旧请求不得覆盖新对象 |
| query产品、期间及日期 | 查询组件 | 请求绑定筛选快照，条件变化使旧结果失效 |
| chat_id、turn_id、events | nanobot客户端 | 使用原生事件关联、恢复和取消 |
| mutation结果 | 服务器回执 | 重连查询同一client_request_id |

S00—S10适用性继承561条状态关联及N/D公共状态要求。加载、空内容、运行、等待输入、结果、失败、权限、来源变化、恢复核查和取消各自有明确反馈。页面状态不能推导交办完成、外部送达或专业结果。

## 5. 组件与接口职责

```mermaid
graph TD
  Auth[上游认证] --> Shell[BossDesktop]
  Shell --> Read[jsonRequest 认证读取]
  Shell --> Domain[老板领域组件]
  Shell --> Admin[维护领域组件]
  Shell --> Native[nanobot ThreadShell与Settings]
  Domain --> Mutation[client.requestMutation]
  Admin --> Mutation
  Read --> Role[RoleChannel]
  Mutation --> Role
  Role --> API[BossPageAPI与BossCommandAPI]
  API --> Store[唯一SQLite业务状态]
```

| 组件 | 输入/输出与责任 | 副作用及检查 |
|---|---|---|
| BossDesktop | getToken、onLogout、onStartChat、children；导航与对象选择 | 身份查询、页面读取、未保存提示 |
| BossLogin | mode、failed、expired、message、onSecret | 真实 bootstrap 与 identity、提交限制、过期认证与退出 |
| BossToday | TodayProjection、onCommand、onNavigate、onDirtyChange | 当前事项与本人次序、快照 CAS、保存后重读 |
| BossOwnerPlans | OwnerPlanProjection、onCommand、onDirtyChange | 本人范围与时间、暂停恢复取消、原请求回执查询 |
| BossMeetingArrangement | MeetingArrangementProjection、onCommand、onReload、onDirtyChange | 草稿与当前会议分别保存，四项本人动作、当前影响摘要与独立授权 |
| BossMeetingBrief.refreshVersion | 公共Shell请求版本 | 重新读取当前会议及来源，保留当前页签与本地输入 |
| MaintainerRuntimeRecords | 稳定getToken、onOpenTask(taskId,runId) | 真实记录查询、分页、详情重读、取消读取和费用未知状态 |
| RuntimeTaskTechnicalView | taskId、runId、getToken | 重新核查运行中task引用与维护身份获准task_refs，仅展示当前技术元信息 |
| ProductRuntimeConfiguration | getToken、onCommand、onDirtyChange、onReload | A08当前配置与独立草稿，保存、静态校验、启用和停止新任务；原请求回执、CAS与D06 |
| BossAssignmentSourceReview | 当前task_id、Projection、onCommand、onReceipt、onOpenSource、onDirty | F06本人独立确认当前来源，业务状态保持；来源与交办切换受D06保护 |
| MaintainerMemoryStatus | getToken、onNavigate(page,run_id) | A12当前确认、删除传播及实际上下文选择，只读取技术元信息；关联记录进入A15筛选 |
| BossAssignmentFlow等老板组件 | 当前任务、版本、来源及导航回调 | 本人授权、回执、CAS、刷新重读 |
| BossWorkspaceView | page_id、角色和读取函数 | 通用只读投影；完整映射见page-service-map |
| MaintainerPromptVersion、Scheduler等 | 服务端维护配置和当前版本 | 保存/校验/启用/采用分别核查 |
| BossVoiceAssignment | 麦克风权限、实际转写、核查文本 | 本人确认文本后提交共同流程 |
| Panel、Tag、Value、StatusLine | 展示数据与语义状态 | 无业务写入 |

每个页面的`component_file`、`role_gate`、`verified_http_read_routes`、`code_wired_write_actions`、未完成动作及验证状态以page-service-map逐项交接。新组件进入构建白名单后才能被当前dist采用。领域props和接口更新必须同时核对调用方与拒绝路径。

## 6. 事件、恢复与性能

实际传输为WebSocket。无需新增SSE传输；事件使用nanobot原生解码与消息存储，成熟Markdown组件呈现模型文本，不渲染未经处理的HTML。事件关联chat_id、turn_id、request_id；工具结果与模型完成分别呈现。取消只停止尚未执行的步骤，已写入回执保留。

| 条件 | 保留内容 | 页面动作与核查 |
|---|---|---|
| 401/登录失效 | 当前page_id和安全对象标识 | 重新认证并查询正式状态 |
| 403 | 无正文的拒绝信息 | 返回当前身份可访问入口 |
| 409 | 本人输入和旧版本 | 读取当前版本，核查后提交 |
| 断流/响应未知 | client_request_id、对象ID | 查询原回执，禁止重复发送 |
| 来源撤销/版本变化 | 历史引用及失效标记 | 停止当前采用，显示NEEDS_REVIEW |
| 页面/对象切换 | 目标对象上下文 | 取消旧读取，拒绝过期结果 |
| 未保存离开 | 当前草稿和焦点 | 留在原页面或明确放弃 |
| 服务重启 | 服务端正式状态 | 新bootstrap，重新读取对象 |

流式文本复用上游增量呈现与批量更新；目录搜索及可产生网络请求的筛选需要防抖。操作反馈和取消不延迟。性能数值阈值引用D05，当前未知；记录实际构建、请求耗时及渲染表现，不宣称达到未知阈值。中文IME组合期间Enter不得提交；必须验证composition与原生会话行为。

D06使用项目固定Radix Dialog提供焦点约束、Tab循环和Escape关闭，Portal保留v6主题上下文。关闭后恢复导航触发元素焦点；返回继续编辑保留输入，明确放弃后才进入目标页面。真实隐藏Electron已验证三个尺寸和100%/200%缩放的内容边界；检查仅输入现有获准原文，没有保存会议或调用模型。浏览器history、完整对象选择、筛选与滚动恢复继续单独核查。

A08采用维护专用运行配置投影与四项boss.runtime动作，字段与序列化见`specs/product-runtime.openapi.yaml`。保存或静态校验不表示模型质量通过；明确启用后读取实际admission_ready、当前版本、工具范围与进行中数量。已有运行继续原配置，变更启用等待运行结束，停用只停止新任务。实际本人首页任务与A15查询、明细、关联交办、退出和重启已通过，证据见T11；页面整体及全部管理状态仍保持partial。

F06通过`GET /api/boss/ui/assignment-source-review?task_id=...`读取唯一来源绑定。本人核查后通过`boss.assignment.sources.confirm`、task_version和review_sha256独立确认，任务业务状态保持，发送继续使用独立授权。`bossTask`保存当前选择，查看原文后返回和刷新恢复同一交办；未保存的核查依据在切换来源或交办时进入D06。当前绑定与结果证据分别核查，当前结果证据需要重新提交时明确显示。

A12手动读取维护专用`admin/memory-status`，展示当前版本、本人确认、未来采用资格、最近实际运行的memory_reference及删除各项范围。读取失败清除旧投影，取消终止当前读取，退出卸载组件。页面不提供正文或本人修改能力。本人F13删除后，A12保留历史选择的原版本，新的真实任务记录当前DELETED版本和eligible=false；模型完成观察与模型遵从验证分别展示。历史会话、备份及物理擦除保持NOT_VERIFIED。

## 7. 验收与接收条件

T08正式接收必须包含：72页面各自组件、真实读写与事件、角色、对象/版本、全部状态、返回上下文、焦点恢复及源码位置；完整561状态与公共状态责任保留。T03提供视觉和素材结果，T05/T06提供字段及operationId，T07提供工具/事件和上下文采用；完整设计验收仍未完成。

已接收的局部接口与字段如下；正式设计验收继续独立执行。

| 接口/字段 | 序列化与消费 | 实际检查 |
|---|---|---|
| todayRead：items、item_id、order_version、snapshot_sha256 | TodayAPI → BossPageAPI → TodayProjection → BossToday | 原始顺序、本人调整、保存及重读 |
| todayReorder：expected_version、snapshot_sha256、item_ids | scopedCommand → BossCommandAPI → TodayAPI.reorder | 当前完整集合与 CAS，原请求编号保持 |
| ownerPlansRead：plans、events、results、dispatches、technical_schedule | OwnerPlansAPI → BossPageAPI → OwnerPlanProjection | 事件范围、计划状态及唯一执行责任 |
| ownerPlanSave/Pause/Resume/Cancel：plan_id、expected_version、client_request_id | BossOwnerPlans → scopedCommand → OwnerPlansAPI | 创建 ACTIVE、PAUSED、ACTIVE、CANCELED，版本与重启连续性 |
| identity.role 与 bootstrap.api_token | BossLogin 核验服务端身份 → 原生 App 保存当前认证 | 入口范围错误拒绝、401/403、过期及退出 |
| memory technical status | MAINTAINER-only 读取 → BossDesktop A12 | 无正文、无外部范围参数，身份拒绝与技术重读 |
| prompt-versions.runtime_eligibility | MAINTAINER-only 读取 → BossDesktop A05 | 当前来源版本、排除原因与采用条件；读取不记录上下文采用 |

本机工程构建、413项回归与30项相关公共入口检查已通过；完整回归11项条件检查跳过。当前真实Electron59项技术记录覆盖N01/D08、角色、三个尺寸及200%缩放、F01次序、N09计划、A05/A12、刷新及重启。70个认证后页面完成72次角色/页面组合DOM检查，没有renderer异常、失败读取或整页横向滚动。结果见T11主记录。全部动作及561状态、IME、跨页焦点和滚动、完整来源撤销、系统权限与视觉验收仍待执行。T09据完整FR/AC建立独立断言；T24在相同集成版本验证持久化及后续采用。构建通过不修改A08状态。
