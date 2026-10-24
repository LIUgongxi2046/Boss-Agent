# FC04 Agent开发记录

task_id=FC04-N2；当前既有投影的受限SDK读取IMPLEMENTED，完整新语义等待N1正式接口与N3公共接收。需求来源为原始FC04经营提醒工单、当前PRD迭代节及完整FR-02，限定C01/C04/C17/C19。代码基线c6834f9，公共基线56f292f，完整分母20由N3维护，用户验收独立记录。2026-10-24 CURRENT。

已完整读取工单、PRD迭代节/8.2、适用AGENTS.md及SOP02记录，核查BossWorkspaceReadTool、通知投影、ControlStore规则/dispatch、现有唯一调度、本人提醒动作。继续采用S008。N1正式FC04增量尚未提供；既有notifications投影提供事件/规则/抑制/提醒状态，完整持续、影响、可信、参与条件及来源语义等待正式接口。

## 接收清单与实际差距

| 当前接口 | 可复用行为 | 使用方与必要条件 |
|---|---|---|
| BossWorkspaceReadTool(allowed_projections={notifications}) | 当前事件、提醒、通知、规则、delivery/dispatch与本人通知设置的实际投影 | Fc04ReadTool复用，仅允许此投影，不默认开放其他私人工作投影 |
| BossWorkspaceAPI.notifications | 保留当前已有规则版本、对象状态与抑制原因；read_at为实际读取时间 | N1确定完整新增语义，N3公共页面接收同一正式字段；空集合不能代表完整覆盖 |
| ControlStore.dispatch_due及现有Cron | 已有事件/规则/计划/免打扰/任务终态检查及正式记录 | 调度继续由既有唯一Cron承担，不注册给模型，不新增执行者 |
| boss.reminder.ack/snooze/close | 本人知晓、暂缓、关闭分别签发当前授权并保存 | 保留在真实本人页面；不能把这些入口注册为模型决定工具 |
| OwnerPlansAPI及本人通知设置 | 已有本人计划/设置及其撤销条件 | 当前模型不修改；维护技术配置不能扩大本人业务授权 |

完整影响/持续/可信/处理人/本人参与条件、来源采用、恢复/冷却/合并细节，以及会议和交办关联的新正式输入/输出仍PENDING_N1。当前N1可读HEAD为62822f8，FC04主记录及准确新增接口尚未提供。不猜测新字段或接收未验收授权消费模块。C01/C04完整领域语义不能据本次读取适配登记通过。

## 专有适配与可信生产者

版本1.0.0，validation/fc04_agent；register_fc04_tools(registry,store,context_provider)仅注册bossWorkspaceRead，allowed_projections严格为notifications，已有同名工具时在修改Registry之前拒绝。实际parameters复用BossWorkspaceReadTool，memory等其他投影及confirmed/owner/namespace等额外参数被拒绝。没有知晓/暂缓/关闭、会议、交办、发送、审批或规则启用工具。

Fc04Context字段为role、owner_id、namespace、dataset_id、dataset_version、request_id、session_id、active、projection_sha256。N3从真实本人会话与当前正式notifications投影提供这些值，不能依据待执行模型参数即时生成绑定，也不能把直接构造dataclass当作认证或本人授权。notifications_digest(view)对实际投影去除顶层read_at后计算技术摘要；这仅是请求范围摘要，不新增领域快照或业务状态。它覆盖当前投影已经包含的规则、事件、处理状态和本人设置；当前投影没有的来源语义仍等待N1。

每次读取核查当前BOSS、active空间、owner/dataset及版本；实际Runtime另核查同库、namespace、request_id、session_id和sender_id。当前实际投影摘要必须与服务端冻结值一致，规则/事件/提醒状态变化拒绝旧请求；返回前再次检查认证范围。已有Adapter继续核查业务时钟与范围，没有自动重试或替代成功。

## 实际Runtime与安全记录

Fc04SimulatedProvider接口为async(messages,tools)->LLMResponse，明确SIMULATED并只接受单项工具集合。实际Nanobot、AgentLoop、Registry、BossWorkspaceReadTool和BossWorkspaceAPI读取SQLite；模拟事件从实际工具返回的rules/events/dispatches继续，不能按标签生成提醒、升级或成功答案。当前读取不调用调度，也不产生通知、本人决定或授权。

Fc04RuntimeRecorder/Fc04RuntimeHook复用现有真实配置/Prompt/工具Schema及实现摘要、事件和终态；feature_id=FC04、source_type=SIMULATED。reminder_context关联projection和技术摘要；tool_results记录实际rule_versions、event_refs、dispatch_refs与结果摘要。当前返回没有的来源版本不补造；新正式字段由N1/N3交接后补充。问题、原文、私人正文与凭据不进入这些技术记录；未知usage/cost_total/price_version保持null。

失败/取消/超时及认证撤销停止依赖动作，保留已完成读取引用与原request/session/run。模型没有业务写入，因此不增加另一套业务回执；本人决定的未知结果继续由N3现有正式入口按原client_request_id只读恢复，不重放或新建编号。contract.py的interface_contract提供实际Tool Schema、上下文和技术扩展字段。

## 限定证据

准确公共依赖56f292f062da0451ae3fce4f58990cb57f452e63，N2独立检出validation/.work/fc04-fc07base；Agent源码来自本角色当前模块。检查使用获准selection/1，经成熟ControlStore.control规则入口提供工单演示参数：冷却1800秒、Asia/Shanghai免打扰22至7及重要升级设置。参数仅为获准程序行为验证，不声明企业制度，也不制造业务通知或来源。

check.xml：14 passed，7.37秒；实际SDK消费当前规则版本与通知投影，核查角色/身份/空间/数据版本/旧摘要、模型跨私人投影及confirmed注入、规则变化、读取零dispatch/消息/授权、失败/取消/超时保存引用、未知费用null及问题正文排除。revocation.xml只补查读取后认证撤销停止后续调用，1 passed、14 deselected。没有重跑无变化全量或创建调度评测体系。

```bash
env PYTHONDONTWRITEBYTECODE=1 FC04_DOMAIN_ROOT=/Users/liuhaoxian/.codex/worktrees/boss-sop-writes/Boss-Agent/validation/.work/fc04-fc07base validation/.venv/bin/python -m pytest app/tests/fc04_agent -q -p no:cacheprovider --basetemp=validation/.work/fc04-agent-check --junitxml=validation/.work/fc04-agent-check.xml
```

workdir固定为/Users/liuhaoxian/.codex/worktrees/boss-sop-writes/Boss-Agent；数据库/中间结果位于已忽略validation/.work。socket.connect审计禁止全部外部连接；没有启动或修改用户预览/进程，没有执行Cron、系统通知权限、真实设备、视觉或用户验收。

## 公共接收与准确剩余

N3接收本独立模块，提供真实认证与当前冻结投影生产者、请求级单项工具集合及notifications白名单、Fc04SimulatedProvider/Fc04RuntimeRecorder和contract.py技术Schema/构建依赖；原生Client/Provider、F02/通知中心、本人决定和系统通知由N3维护。需要将实际规则/来源新正式投影与本技术摘要绑定到同一版本，不能仅增加工具名称宣布完整采用。

N1新接口到达后，核查其当前字段与来源/规则引用，只修正真实差异并补充受影响消费者。当前独立证据只覆盖既有投影受限读取，不代表C01/C04完整判断、本人处理、唯一Cron全流程或完整20项开发完成。准确公共候选及用户验收由N3维护，本次不启用FC06；MVP/FC07用户验收仍待确认。全部外部SIMULATED_FIRST、STT暂停保持。
