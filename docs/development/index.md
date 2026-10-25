# 开发记录

当前高保真要求：[所有菜单高保真还原执行要求](../menu-delivery/高保真还原执行要求.md)，decision_id=D-UI-FIDELITY-20261024。用户反馈F01仍有较大设计差距，F01设计返修须在进入N03前完成；当前N02及后续工单采用同一完整条件，业务证据与设计/视觉/用户结果分别记录。N4只读设计复查，N3自然阶段结束接收返修，不打断运行窗口，不改写用户体验。

当前按菜单开发入口：[菜单开发总计划](../菜单开发总计划.md)、[当前正式状态](../../specs/feature-delivery.json)、[菜单规划](../../specs/menu-plan.json)。第一项[MENU-F01今日工作工单](../menu-delivery/F01.md)，角色唯一主记录位于各自目录docs/menu-delivery/F01/，由对应角色维护并登记索引；下方旧记录只按原限定范围引用，不代表完整菜单或高保真通过。

**下一位开发者接手入口**：[Boss-Agent 开发交接文档 v2.0](../Boss-Agent开发交接文档-2026-10-23-v2.md)（PRD/UI 约束、实际功能、23 项未验收任务、运行/测试步骤、开发优先级）；下方为逐批开发证据，不替代最新交付台账。
**当前集成与验证入口**：[T11公共入口](T11.md)、[T08前端设计](T08.md)、[T09设计与验收](T09.md)；状态来源为 `delivery-ledger.json`。基础开发说明见[开发交接文档v2.0](../Boss-Agent开发交接文档-2026-10-23-v2.md)，当前源码及证据以各任务主记录为准。

| 任务 | 记录 | 当前状态 |
|---|---|---|
| MENU-N03-N3 | [经营关注完整菜单](../menu-delivery/N03/integration.md) | FR-02/03/14—23、原始v6 N03、MENU-N03.C01—C26；范围/十专题/指标/提醒/关联/来源、实际会话及连续返回；正式状态读取原始feature-delivery.json |
| MENU-N03-N1 | [经营关注领域](../menu-delivery/N03/backend.md) | BusinessOverviewAPI、BusinessOverviewEntry、BusinessOverviewPreparation、经营范围/专题/来源绑定、原编号历史、C17交办源审查、meeting范围限定材料与businessMeetingPreparationRead；正式状态读取N3的feature-delivery.json |
| MENU-N03-N2 | [经营会话消费者](../menu-delivery/N03/agent.md) | 正式经营绑定、结构化指标条件、受限工具、Runtime Schema及晨间共享占用检查；公共接收与完整菜单状态由N3维护 |
| MENU-N02-N1 | [聊天交办领域](../menu-delivery/N02/backend.md) | 当前会话/运行/产物、消息/回复/来源、原生附件元数据及真实权限；正式状态读取N3的feature-delivery.json |
| MENU-N02-N3 | [聊天交办完整菜单](../menu-delivery/N02/integration.md) | FR-08/24/29、原始 v6 N02、MENU-N02.C01—C26；连续会话/附件、任务与来源、实际运行、消息授权及异常；FR-27暂停，正式状态引用原始 feature-delivery.json |
| MENU-F01-N3 | [今日工作完整菜单](../menu-delivery/F01/integration.md) | FR-01、原始 v6 F01、MENU-F01.C01—C18；区域结构、正式来源、排序、会话、共享交办与返回；正式状态引用原始 feature-delivery.json |
| UI02-N3 | [开源界面统一体验](../feature-delivery/UI02/integration.md) | UI02.C01—C08；公共框架、原生会话、Settings、主题与连续操作；正式状态引用原始 feature-delivery.json |
| UI01-N3 | [已完成功能菜单与登录页](../feature-delivery/UI01/integration.md) | 七项工单；已交付导航、受控账号填充和登录布局；后续界面整合见 UI02，用户验收独立登记 |
| MVP01-N3 | [采购成本连续体验](../feature-delivery/MVP01/integration.md) | BOSS-MVP-1、MVP.C01—C12；同一采购报告、实际SDK/原文/本人确认/持久恢复和可启动体验；状态引用原始feature-delivery.json |
| FC07-N3 | [交办与承诺公共集成](../feature-delivery/FC07/integration.md) | FR-06、FC07.C01—C12；F06/N05、发送/催办/反馈/延期/证据/本人结束、SDK、保存恢复；状态引用原始feature-delivery.json |
| FC04-N3 | [经营提醒公共集成](../feature-delivery/FC04/integration.md) | FR-02、FC04.C01—C20；提醒规则、唯一Cron、本人处理与后续调度、桌面通知、原编号恢复；状态引用原始feature-delivery.json |
| FC04-N2 | [提醒投影限定读取与实际Runtime](../feature-delivery/FC04/agent.md) | Fc04Context、notifications_digest、Fc04ReadTool、当前认证、单项工具、实际SDK与认证撤销；公共接收见FC04-N3 |
| FC07-N2 | [交办限定读取与实际Runtime](../feature-delivery/FC07/agent.md) | Fc07Context、两项读取、可信对象及来源版本、实际SDK、认证撤销；当前接收见FC07交付记录 |
| FC01-N3 | [采购成本品质公共集成](../feature-delivery/FC01/integration.md) | 当前功能与独立验收引用原始项目 specs/feature-delivery.json |
| FC02-N3 | [BI连续查询公共集成](../feature-delivery/FC02/integration.md) | 完整FR-03及二十项检查点，当前工单为原始项目docs/FC02经营查询工单.md |
| FC03-N3 | [晨间事项公共集成](../feature-delivery/FC03/integration.md) | FR-01/BR-01/AC-01-S/E；完整22项；MorningAPI、ProductMorning、BossMorningView、日期/清单/来源/排序/原回执及实际SDK；状态引用原始功能来源 |
| FC02-N3-FOLLOWUP-RECOVERY | [默认父查询切换正式场景的公共验证](../feature-delivery/FC02/followup-recovery.md) | C03/C16、父子来源与持久回执、实际公共SDK；状态引用原始功能来源 |
| FC02-N3-BOUNDARY-ADOPTION | [正式经营边界与双方口径的公共采用](../feature-delivery/FC02/boundary-adoption.md) | C05/C08/C11，维护载入、本人场景与来源、双口径及实际Runtime；状态引用原始功能来源 |
| FC02-N4-UI-HISTORY-01 | [来源失效后的历史查询与原请求恢复](../feature-delivery/FC02/history-recovery.md) | C12/C14公共恢复、来源有效性、身份与持久请求；状态引用原始功能来源 |
| FC02-N4-UI-ASYNC-01 | [初始回执与条件编辑的异步顺序](../feature-delivery/FC02/async-recovery.md) | C03/C15实际响应延迟、编辑条件与查询编号；状态引用原始功能来源 |
| FC02-N1 | [BI范围、比较与持久恢复](../feature-delivery/FC02/backend.md) | 已接收正式领域提交，完整功能状态引用原始项目功能记录 |
| FC02-N2 | [BI可信工具与实际Runtime](../feature-delivery/FC02/agent.md) | 已接收正式Agent及领域组合证据，完整判定等待N4 |
| FC01-N4-001 | [实际正文Token](../feature-delivery/FC01/body-tokens.md) | C15共享正文、实际段落、尺寸及键盘；状态引用同一功能来源 |
| FC01-N1 | [采购成本品质领域接收](../feature-delivery/FC01/backend.md) | 领域1.8.0及期间归属筛选，完整功能状态引用同一功能来源 |
| FC01-N2 | [采购成本品质Agent接收](../feature-delivery/FC01/agent.md) | 明确模拟Provider、实际Runtime与工具，独立结果保持限定范围 |
| MENU-F01-N1 | [今日工作领域](../menu-delivery/F01/backend.md) | 完整获准来源、三分类、同事项关联、当前风险、日期/来源截至、排序与原回执；正式状态读取N3的feature-delivery.json |
| FC04-N1 | [经营提醒领域](../feature-delivery/FC04/backend.md) | 规则、来源、连续判断、唯一Cron、本人处理、恢复/抑制历史；正式状态读取N3的feature-delivery.json |
| FC07-N1 | [交办与承诺领域](../feature-delivery/FC07/backend.md) | ControlStore、延期决定、本人承诺来源、CAS与原回执；执行状态读取N3的feature-delivery.json |
| T02 | [选型验证开发记录](T02.md) | ACCEPTED；A02 PASS（选型可行性）；后续产品验证见交接 |
| T03 | [设计资产与交互](T03.md) | C03/A03；72页面、561状态、素材SHA-256；真实状态引用台账 |
| T05 | [数据设计](T05.md) | C05/A05；SQLite、来源、版本与字段；状态引用台账 |
| T06 | [API与正式状态](T06.md) | C06/A06；operationId、角色、CAS与回执；状态引用台账 |
| T07 | [老板Agent设计](T07.md) | C07/A07；SOP、工具、上下文与依赖；状态引用台账 |
| T08 | [前端设计与服务映射](T08.md) | C08/A08；认证、对象状态、Token、72页面映射；真实状态引用台账 |
| T09 | [设计、测试与安全计划](T09.md) | IN_PROGRESS；332项计划检查目录已核查，完整语义和业务验收未完成 |
| T10 | [实施任务与执行接收](T10.md) | IN_PROGRESS；接口1.7.0、28项完整范围及历史回执清查，完整台账校验待完成 |
| T11 | [桌面公共入口与集成开发记录](T11.md) | IN_PROGRESS；1.7.0采购品质公共流程、原请求恢复、当前来源及SOP投影资格；外部API使用SIMULATED_FIRST；工程回归869 passed/13 skipped；完整A11继续验证 |
| T12 | [模拟业务环境](T12.md) | C12/A12；数据集、时钟与重置；状态引用台账 |
| T13 | [指标计算](T13.md) | C13/A13；Decimal、明细与独立复算；状态引用台账 |
| T14 | [老板业务动作](T14.md) | C14/A14；授权、反馈与当前状态；状态引用台账 |
| T15 | [知识与记忆](T15.md) | C15/A15；摄取、引用、撤销与删除；状态引用台账 |
| T18 | [老板端交办闭环首批实现](T18.md) | 部分已开发；A18 整体验收 NOT_RUN |
| T19 | [维护端模拟反馈首批实现](T19.md) | 部分已开发；A19 整体验收 NOT_RUN |
| T16 | [本机 DeepSeek 接入与运行元信息](T16.md) | 指定源码的两次共同任务及真实异常已有证据；当前公共Runtime接收见T11，完整A16保持未验收 |
| T20 | [F27 语音交办开发与真实转写待验收](T20.md) | 部分客户端功能已开发，T20/A20 仍待真实服务和 macOS 联调 |
| T21 | [原料、水产与苗种专题](T21.md) | A21a/b/c；专题来源与输入条件；状态引用台账 |
| T22 | [技服、生猪与禽畜专题](T22.md) | A22a/b/c；四种禽畜用途；状态引用台账 |
| T23 | [养殖、食品、海外与研发专题](T23.md) | A23a/b/c/d；范围、来源与验证；状态引用台账 |
| T27 | [登录与桌面改进](T27.md) | IN_PROGRESS；公共账号、权限、刷新、退出、重启与桌面品牌已接入；完整A27未验收；公共接收见T11 |
| T18/T19 | [F05纪要、F07审批及A03模拟申请](T18-meeting-approval.md) | 真实域事务和React已开发；A18/A19 未通过整体验收 |
| T18/T19 | [F08消息与F12私人日程及忙碌分享](T18-message-calendar.md) | 业务事务及React已编译测试；真实外部投递和Mac视觉验收未完成 |
| T18 | [F04来源版本化会前材料、F08资料请求草稿](T18-meeting-brief.md) | 实际SQLite事务和v6四页签组件已开发；A18/像素/实机未验收 |
| T18 | [F05已确认纪要逐项关联F06任务](T18-minute-task-chain.md) | 分项授权+SQLite版本链路已开发；实际Mac/E2E/视觉仍待验收 |
| T18 | [F09 专题研究与 F04—F09 跨页面功能链路](T18-research.md) | 已有版本化研究、撤销失效检查与 CI 集成测试；模型、Mac 及像素验收仍待执行 |
| T19 | [A05 Prompt版本保存/校验/启停/上下文采纳](T19-prompt-lifecycle.md) | 真实配置及React已接入；DeepSeek质量、Mac实机/高保真验收待执行 |
| T17 | [调度、提醒及F06独立催办](T17.md) | IN_PROGRESS，SQLite和v6组件在建；真实macOS Cron/系统通知与A17仍待验收 |
| T18 | [F10 人员会面与 F11 行程安排 · F04跨页失效复核](T18-people-travel.md) | 老板受权 SQLite 动作与 v6 页面已接入并通过 CI；真实外部服务、Mac 实机/像素验收仍待完成 |
| T18 | [本人设置 N07/N08/F26、授权撤销 N10](T18-owner-preferences.md) | BOSS 草稿/独立确认、真实 Runtime 引用与技术调度更严格抑制、原授权撤销已开发；整体实机/视觉/真实模型验收仍待完成 |
