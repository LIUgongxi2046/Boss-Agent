# FC04经营提醒公共集成

task_id=FC04-N3。需求来源为原始docs/FC04经营提醒工单.md、当前PRD迭代节及完整PRD第8.2节FR-02/BR-02/AC-02-S/E、提醒独立状态、演示参数、桌面通知及适用BR-C01—C07/E01—E06。唯一状态来源为原始specs/feature-delivery.json；baseline=boss-fc04-coverage-20261024-v1，共20项，verified_checkpoints=null。当前DEVELOPED_PENDING_USER_ACCEPTANCE，完整开发证据由delivery.json关联，用户验收未执行。文档CURRENT，last_verified=2026-10-24。D-UI-PAUSE-20261024要求当前必要验证后暂停后续业务，只自然接续UI01，完成后等待用户，不启动FC06。

## 当前输入与检索

FC07候选56f292f062da0451ae3fce4f58990cb57f452e63，公共实现465bcc6817e5e854dcce70f83e062ac6893b3ce0。FC07开发覆盖十二项且可启动，用户验收与MVP共同验收继续待确认。读取原始工单、完整FR-02与共同异常、状态、12.3演示参数和10.5桌面通知；检索开发索引、LLD相关通知/计划/唯一Cron、BossWorkspaceView的F02 notifications、BossCommandAPI原提醒动作、BossPageAPI及宿主通知能力。

已有提醒、任务期限、本人计划及通知设置继续复用；完整影响/持续/可信/参与条件、恢复、合并、抑制记录及公开连续流程通过正式领域与当前公共证据核查。规划采用S007，实施使用S008及本主记录。

## 职责与依赖

N3负责公共Command/Page/RoleChannel、页面/Shell、CSS、宿主通知、启动/构建、公开规范及唯一正式状态，覆盖C01—C20公共组合。N1负责领域与Schema，N2负责限定工具和运行，N4负责必要定向检查；角色使用既有聊天及各自目录，启动由原监督安排，不追加消息或中断运行角色。

现有FC07/MVP基础SATISFIED。N1领域35f5f3970897140947adf2a09f873584cd391292接收为77daecb，记录9c465de736a69aee4bb30380e9e6f67115d774b2接收为b59f5af；N2正式1636a0771a3cc390f6ae4dccf8a0273725c24d21接收为92d993e。领域模块与Agent模块摘要由准确清单核查，新增来源语义由PublicReminderHook正式接收。公开完整流程和必要组合验证已完成，用户验收独立待确认。不存在第二个调度执行者或平行提醒状态。

## 验证与继续条件

F02/N06开放当前经营提醒与原提醒，桌面系统提示关联当前事件及安全返回。唯一CronService调用正式dispatch_due。C01—C20登记开发覆盖，用户验收未执行。检查使用正式维护导入/时钟、本人决定及同一Cron，在独立忽略目录、SQLite、端口和构建中执行。必要共享消费者包括FC07任务/承诺提醒、MVP、本人通知设置、计划、会议及交办。

当前HEAD与未提交内容、完整HLD/LLD和v6规范均已核查，N1/N2正式字段已完成公共传播与实际业务验证。未知写入只查询原编号；本人与维护权限、来源、版本、幂等、异步失效及隐私全部继承。外部SIMULATED_FIRST，无新真实外部请求，STT暂停，视觉及用户验收未执行。后续仅按原始UI01工单执行，FC06保持暂停。

## 当前公共实现与实际证据

public_notification_target从同一事务核查BOSS、当前事件版本、取消/关闭/暂缓及已保存通知，不读取私人正文或执行写入。桌面notify_event重新调用该入口；只显示通用经营提醒和返回入口。原生状态分别记录REQUESTED/SHOWN/FAILED/CLICKED；系统明确拒绝时显示DENIED_BY_SYSTEM，无法读取的权限保持NOT_REPORTED_BY_SYSTEM。本人可以明确重新请求已失败通知，未知请求不重放；系统点击经当前renderer身份和目标重新核查后导航。当前设备原生返回FAILED及Notifications are not allowed for this application，系统显示/点击成功未验证，应用内处理仍可使用。

F02/N06在当前优先入口开放，知晓/暂缓/关闭采用现有useTransaction的独立reminder范围，URL只保存动作/事件/原编号。原生Client禁止boss.reminder.*连接恢复重发；原回执保留event_id/event_version/until并严格核对原对象。新的BossReminderPreparation采用同一ClientProvider，通过boss.reminder.prepare与原reminder-preparation回执读取实际SDK结果；ProductReminders从服务端当前投影冻结技术摘要，模型只调用bossWorkspaceRead/notifications，不执行本人决定或调度。ProductRuntime仅在明确WORKSPACE_PROJECTIONS配置下采用限定包装器，保留原配置模式及共享消费者。

公开接口及Runtime字段见specs/product-reminders.openapi.yaml与runtime-records.schema.json。当前组合为50项必要检查通过，实际SDK采用正式领域、公开/Runtime Schema与当前配置，并验证共享MVP工具集合。前置全部为获准selection/1、正常维护事件/时钟和正式BOSS动作，未直接修改业务记录。

实际隐藏桌面报告由当前delivery.json关联，覆盖公开助手单项读取、null用量、原生通知拒绝、维护/旧版本拒绝、重复请求复用，以及实际写入成功后响应中断、一次转发、刷新只读恢复与未知Escape保护。本人通知草稿保持未启用，原回执查询后仍需独立启用；本人计划暂停/取消后的Cron抑制可读。当前F06真实任务九项正文16/24，范围限定当前制品。

身份令牌变化继续清除待提交内容与原确认，不自动恢复待执行操作。BossOriginalReceipt仅按当前认证GET查询原动作/编号及安全对象，核对回执身份、对象及只读标记，RECORDED后清除安全引用并重读当前业务状态；该组件没有WebSocket写入、授权恢复或继续执行接口。未确定结果期间阻止新提交及编辑，不使用原内容跨身份续接。普通刷新仍受原未保存保护规则控制。

scripts/run_fc04.command使用原MVP资料及账号，从F02启动；prepare_fc04.py只核查现有资料、端口和制品，不读取账号秘密、不启用工具或规则。需要调整SDK范围时，维护通过现有A08明确保存、校验和启用通知投影；既有配置及草稿保留。evidence/feature-delivery/FC04/launcher.json已通过实际入口、本人登录和既有任务/承诺/本人通知/计划/来源摘要保留检查，独立数据与端口，无自动配置或业务规则/事件创建。

BusinessAlertsAPI、BusinessAlertRulesAPI及BusinessAlertInputAPI已准确接收。Command在通用写入事务之前延迟委派，Workspace在同一只读事务接收business_alerts；同类生成事件从旧提醒集合过滤，旧boss.reminder入口不能跳过review_sha256。公共目录、Load/Read、规则、经营详情、来源、会议关联与交办后续已经实际验证。完整20项登记开发覆盖，用户分子仍为null；FC06暂停。

## 准确公共组合与交付证据

integrated-final.xml为50 passed，10.75秒，覆盖准确领域29项、受限Agent15项及公共/实际SDK6项；原角色、空间、来源、注入、CAS、并发、唯一Cron、原回执、恢复与独立进程检查均保持正式结果。N1正式81项与N2正式14项加认证撤销证据保持限定范围，不换算功能分数。

当前完整桌面报告evidence/feature-delivery/FC04/fc04-journey-363ffb4f-9bd0-4add-bd26-c3ba02fd78af.json覆盖正常维护保存/校验/启用、0/300/600秒连续观察、实际Cron通知、实际SDK领域引用、本人会议关联、经营交办OPEN及F06独立模拟发送、知晓成功响应中断及原编号一次转发、刷新只读核查、暂缓到期重新验证、关闭保持源事件及任务期限、恢复十分钟记录与CLOSED/WAITING_FEEDBACK独立状态。三个窗口1440×900、1280×800、1024×768及100%/200%缩放下208项非空正文16/24，无整页横向溢出，键盘检查通过，视觉未执行。

当前补充报告evidence/feature-delivery/FC04/fc04-public-b4bc799d-3b32-402b-8db0-0600b3fc83ee.json覆盖系统明确拒绝、通用通知正文、维护/旧版本拒绝、原请求复用、旧提醒恢复、本人通知独立生效、本人计划暂停/取消的Cron抑制、维护调度分阶段生效及当前身份只读恢复、F06九项非空正文16/24。故障检查只中断真实成功响应，没有伪造响应或直接改写业务数据库。

PublicReminderHook从正式领域结果记录事件、经营/技术/本人通知版本、来源编号/版本/状态及摘要，不保存facts、documents或本人理由；未启用规则和未知usage/cost保持null。普通Runtime共享MVP仍为原工具集合。公开规范见product-reminders.openapi.yaml及runtime-records.schema.json；界面设计见LLD-frontend的FC04章节。

| 检查点 | 当前开发证据 |
|---|---|
| C01/C02 | 正式详情/规则Schema、公共6项、正常维护与分阶段规则、实际原始截至时间和未知值 |
| C03/C04 | 连续观察0/300/600秒、领域进展/缺少条件与参与判断 |
| C05/C06/C07/C08 | 实际Cron及领域合并/冷却/免打扰，当前本人通知独立生效 |
| C09 | 当前桌面恢复记录与领域复发/冷却，原提醒和任务状态独立 |
| C10/C11 | 当前知晓原回执、三十分钟暂缓到期、非法时间与旧版本拒绝 |
| C12/C13/C14 | 当前会议关联、交办及独立发送，关闭保持任务和期限，来源失效后关闭 |
| C15 | 当前本人计划暂停/取消抑制，领域撤销授权、事件取消、独立重启及SQLite备份 |
| C16/C17 | 实际系统拒绝与应用内处理、目标与本人核查，公共角色/来源/注入/CAS及受限工具 |
| C18 | 实际响应中断、一次转发、刷新/当前身份只读原回执，领域并发同编号及独立重启 |
| C19 | 实际SDK/Registry、领域安全引用、单项工具、投影摘要、共享MVP及失败/撤销 |
| C20 | 当前连续桌面、尺寸/缩放/正文/键盘、TypeScript/Vite、实际入口/登录/资料保持与准确清单 |

当前launcher.json与准确制品一致，通过原脚本、本人登录及既有33项业务记录保持核查，无自动配置/规则/事件创建。体验步骤见experience.md。独立安装、视觉、真实外部送达和系统成功显示/点击未确认，全部外部SIMULATED_FIRST，STT暂停；用户共同验收仍未执行。
