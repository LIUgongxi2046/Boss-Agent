# MENU-N03 经营关注

task_id=MENU-N03-N3；CURRENT；last_verified=2026-10-25。完整工单为原始项目docs/menu-delivery/N03.md；正式状态唯一来源为原始项目specs/feature-delivery.json。MENU-N03.C01—C26开发覆盖0/26，用户分子null，视觉NOT_RUN。前置F01必要设计事项已经关闭，准确基准3d04f28d6d3b7d53b58a1a69b085a54ca1cc6f57。当前任务保持完整菜单范围，完成后接续F02。

## 需求、原稿与职责

采用完整PRD FR-02/03/14—23、BR-C01—C07、E01—E06及交互规范。原稿依据为N03 HTML、页面配置与提示词、实际加载的design-v6-panels.js topics/TOPIC、design-v6.js、CSS和Token。独立界面保留主列“经营关注范围”“十个经营专题”、右列“经营提醒与来源”，以及完整指标、提醒、关联、来源和合法共享操作。十专题按F14—F23固定顺序；F19四用途独立，未知专业资料保持具体缺口。

N3负责原稿设计、公共身份/注册/读取、范围草稿与应用、对象选择、当前来源、真实会话/准备接收、D06、连续返回、独立构建及唯一正式状态。N1负责领域/Schema，N2负责原生Agent/受限工具/Runtime，N4负责必要的只读差距核查。没有新聊天或子代理；仅在现有角色自然完成且idle复查后发送准确依赖任务。

## 当前实现

| 范围 | 当前行为 |
|---|---|
| 独立入口 | BossDesktop和delivered-navigation以经营关注MENU-N03提供独立容器、六类导航与原稿Hero；独立草稿状态、D06和关闭保护 |
| 范围 | 正式法人、区域、期间、IANA时区及三项关注条件；明确应用后读取，同步核查范围/来源摘要；身份失效清理当前受保护内容 |
| 专题 | 十项完整目录、真实状态/截至/缺口/对象/来源；F19用途保留；详情与原文均以当前固定版本复核 |
| 指标及共享查询 | 正式query_handoff传入F03表单，重新核查原总览摘要；不自动采用其他历史查询，补充条件影响本次查询 |
| 提醒与任务 | 明确事件/任务稳定ID及版本；F02重新核查已应用范围中的准确事件版本和来源审查摘要，只呈现该事项；保留原经营范围和返回入口 |
| 原生会话 | PublicConversation接收prepare/bind/read/receipt；实际new_chat/attach/bind/read之后打开同一SDK会话，没有自动提交问题 |
| 选择证明 | 当前连接只采用服务端已经重新核查的preparation_id/preparation_sha256；明确应用范围清理旧选择；历史回执不恢复执行证明 |
| 受限Agent | admit_business位于晨间候选之前；经营轮次仅三项正式工具，N02原七项保持；Runtime Schema 1.14.0固定安全范围引用 |
| 共享入口 | 应用创建实际SessionManager后注入morning.native.bind_sessions；新增晨间绑定在同一写入事务内拒绝已有经营/任务/意图占用 |
| 交办准备 | 正式Scope/专题/对象/来源审查生成准确准备输入；实际SDK执行前后复核context_sha256，结果匹配任务版本和review_sha256；同编号不重复运行 |
| 原请求 | 未知准备保留原编号及安全技术引用；回执只读，取消只停止界面等待；保存、邀请、发送和完成分别处理 |
| 返回 | 安全URL保存应用范围、专题/用途、位置与控件引用；返回重新读取当前服务，迟到响应不能覆盖当前选择 |

BusinessOverviewPreparation已经提供并接收范围限定会议准备：正式关系、材料版本、参会职责、会议状态和范围指标通过后，严格公共只读动作返回当前准备结果，Dialog呈现实际材料及指标。缺少关系或必要来源时保持具体等待条件。当前制品的完整公共交互仍待认证UI检查，不能登记完整C17通过。新交办需要明确本人输入和合法来源关系，当前界面没有默认生成负责人、期限或授权。

## 准确依赖

| 输入 | 当前接收 |
|---|---|
| N1总览 | a38bf9b/4b48ccb → 67be86d/a8cc244；BusinessOverviewAPI与正式Scope/View/Detail |
| N1原生入口 | d57de121/97e3b3cf → 804c064/72f0a7f；business-overview Schema 1.1.0 |
| N2经营消费者 | 6d9eacf、68d9b269 → a71c8dd/a7a3992；businessOverviewRead、结构化指标、Runtime Schema 1.14.0 |
| N2共享晨间 | e3c28e01 → 5b334fd；bind_sessions与原子互斥 |
| N1准备接口 | 463704e2/d95532b1及504d0b0e/4056c823 → 03af5a8/5a899ef、c7054eb/38ae898；BusinessOverviewPreparation与preparation Schema 1.1.0 |
| N4期望与审查 | qa.md，当前摘要22d3c51df92c71a5d2768708e7c3bccf1e3faffbe6a44ab118441b54c81e99da；完整26项、D01—D12、G01—G07；本次3fc7446限定审查C17/G05及受影响消费者 |

公共总览读取使用当前已认证WebUI结构化动作与GET范围选项；没有第二套认证或新增HTTP POST服务。公共准备提供严格read/verify及实际交办prepare与原编号读取。RoleChannel仅记录动作和状态。nanobot-menu-n03.patch记录当前SDK客户端对经营准备/绑定/选择接收的中断处理，连接重建不自动重发这些动作。

## 限定检查与剩余验证

| 当前证据 | 结果与适用范围 |
|---|---|
| reference-dom.json | REFERENCE_MEASURED；原加载页面18组窗口/缩放/阈值，三个区域、四字段、十专题顺序及27项DOM/计算样式/位置尺寸；产品未测量 |
| domain-receiver.xml | 11通过，7.34秒；正式总览、范围/来源/关系和只读状态 |
| public-receiver.xml | 14通过，5.25秒；公共总览及领域组合，含严格输入、角色和旧快照拒绝 |
| native-entry-receiver.xml | 36通过，9.92秒；原生Session、准备/绑定/回执、并发与任务互斥 |
| agent-receiver.xml | 29通过，21.80秒；实际SDK经营消费者与Runtime Schema准确基准；禁止socket.connect |
| public-entry-receiver.xml | 6通过，2.36秒；实际PublicConversation/SQLite/SessionManager，角色/附着/额外字段/来源变化拒绝 |
| morning-receiver.xml | 10通过，4.89秒；共享原子互斥、实际生命周期及晨间优先 |
| scoped-preparation-receiver.xml | 15通过，8.27秒；范围固定的公共适配、实际交办SDK、相同编号零重复、异内容拒绝及领域准备回归 |
| meeting-receiver.xml | 32通过，11.28秒；范围限定会议准备、实际SDK受控工具、严格公共动作、实际材料/指标、角色与在途变化，以及受影响交办准备 |
| protected-frontends.json | PASS；既有五套体验制品摘要保持；没有读取业务资料 |
| TypeScript/Vite | 当前独立N03容器、查询、固定事项、会话与会议/交办准备Dialog严格编译通过；独立menu-n03-n3-dist构建通过，Vite用时15.46秒；没有产品UI或完整交付声明 |

以上组合存在范围交集，数量不相加。各领域/SDK结果不能替代认证UI、当前产品的成对DOM、连续业务行为、启动器、制品清单及完整26项映射。N2自有25项当前定向和77项受影响组合、N1自有24项准备组合分别见各自准确主记录，不登记为N3完整菜单通过。

N4已完成3fc7446801a15b91b2c56e6a3066bc06c823c9fa的C17/G05新增范围限定会议准备、受影响公共DTO/Dialog及准确提醒版本消费者源码审查，限定结论为SOURCE_REVIEW_COMPLETE_NO_NEW_CONFIRMED_DEFECTS；qa.md摘要22d3c51df92c71a5d2768708e7c3bccf1e3faffbe6a44ab118441b54c81e99da。G01/G03/G04及既有交办准备继续按7db7dbacdaa02445e4ff0fcc1c677835b150426f的原有限定范围采用；32项meeting-receiver.xml保持原次接收证据及覆盖范围，N4没有重新执行。C17保持SOURCE_AND_RECEIVER_EVIDENCE_PRESENT/NEEDS_AUTHENTICATED_UI，完整检查点未关闭。D01—D12保持SOURCE_PRESENT/NEEDS_MEASUREMENT；认证UI、连续返回、焦点/滚动及当前制品成对测量仍需验证，没有完整菜单或独立产品通过结论。

会议准备Dialog通过boss.business.meeting.prepare读取同一正式领域结果，展示真实材料、参会职责、范围指标和各自版本；不注册新的模型权限。N1独立businessMeetingPreparationRead的实际SDK检查表示该受控工具的能力，当前N03原生讨论继续采用三项既有经营工具。刷新只保存严格范围、对象和选择引用，不保存会议材料正文。

check-menu-n03-entry.cjs在执行前被自动审批审查拒绝，理由是自动完成认证被认为与“产品不自动登录”约束冲突。没有启动该检查、没有创建其测试数据、没有有效UI Red或产品通过结果。专用测试认证授权已提出并等待明确回复；不重试、委派或通过间接登录执行被拒绝动作。产品受控凭据填充仍仅按用户明确授权，保持本人点击登录。

N03初始化与启动脚本的创建也被自动审批审查拒绝：拟采用新建专用目录中生成的维护账号，通过本机正式HTTP/WebSocket维护入口配置Runtime，审查认为包含自动认证且超出仅填表授权。脚本没有创建或执行，目录没有因此初始化。该专用初始化认证已独立请求明确授权；当前不重试或通过其他代码路径执行。

## 制品、资料与环境

N03目标为独立menu-n03-n3-dist及menu-n03-*专用资料，正式端口10811/10812/20811；当前没有最终候选、完整制品清单或已认证产品验收。原F01、新F01、N02、UI02和MVP的制品、桌面、用户资料及端口全部保护。外部SIMULATED_FIRST，STT/F27/FC28和视觉暂停。没有截图或图像评分。

磁盘生成门槛保持200MiB。清理仅针对确认结束且通过活动进程、路径及objects表检查的专用测试SQLite或缓存，保留账号、报告、源码和用户体验。N02先前32轮检查曾因空间不足被自动审批审查拒绝；限定清理与生成门槛检查后已完成必要检查。N03当前认证检查的批准状态独立保留，不由该历史处理推断授权。
