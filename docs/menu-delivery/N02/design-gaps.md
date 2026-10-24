# MENU-N02 设计差距

CURRENT；decision_id=D-UI-FIDELITY-20261024；MENU-N02.C01/C02/C25/C26；责任N3。当前差距依据准确原稿和当前独立构建的DOM、计算样式与位置尺寸；没有截图或视觉相似度结论。全部必要差距保持未完成，用户验收未登记。

原设计记录evidence/menu-delivery/N02/reference-dom.json，当前产品记录framework-before.json。两者各18组：三种规定窗口的100%/200%，以及1250、1050、700、690阈值及相邻宽度；每组记录实际innerWidth/innerHeight、devicePixelRatio、scroll位置、clientWidth/offsetWidth和内容状态。产品为当前NATIVE真实新建空会话，没有业务消息；原稿为实际加载的N02空状态。原稿预览工具和预设状态说明不进入产品，不使用它们产生的正文纵向坐标差直接判定业务区域错误。原稿screen的min-height:540px在200%时超过实际视口，必须分别核查容器高度和窗口可操作性。

| 编号 | 原稿依据及数值/结构 | 当前产品数值/结构 | 用户影响与责任文件 | 状态 |
|---|---|---|---|---|
| N02-D01 | screen padding clamp(8px,1.2vw,17px)，1440时17；shell x17/宽1406，1px边框、24px圆角和原阴影 | frame padding0；shell x0/宽1440，边框0、圆角0、阴影none | 正文宽度和外观全部变化；boss-v6.css | FOUND |
| N02-D02 | sidebar原稿padding23px 13px 18px 14px；宽度>1250为204，≤1250为174，≤1050保持60图标导航 | padding18px 12px 12px；1250仍204；≤1050为60，≤690隐藏 | 中等窗口比例和窄窗口导航变化；boss-v6.css | FOUND |
| N02-D03 | HTML六项主导航：今日工作、聊天交办、经营关注、会议与资料、任务与承诺、通知与设置；图标/选中标记使用原稿结构 | 已交付业务入口逐项平铺，聊天为末项大鹏会话 | 导航层级、名称和密度变化；BossDesktop.tsx、delivered-navigation.ts | FOUND |
| N02-D04 | topbar高64，1440 gap18，来源加载后有今日工作/新会话/语音等快捷操作；当前身份来自真实认证 | 高64，gap13，快捷操作缺少；开发标签占用主要区域 | 主要操作位置和信息层级变化；BossDesktop.tsx、boss-v6.css；暂停语音继续说明 | FOUND |
| N02-D05 | N02 hero高146、h1 29px；≤1250为124/25px，≤700标题21px，使用dapeng-side | 当前compact高122/h1 27px；部分200%为高72/标题22px；使用dapeng-front | 标题、品牌位置与正文开始位置变化；BossDesktop.tsx、boss-v6.css；吉祥物边界仍需成对测量 | FOUND |
| N02-D06 | loaded chat主列/右列为minmax(0,1fr)+310px，≤1250为260，≤1050单列；主列当前会话卡片、对话与任务运行卡片，右列持续进展与异常 | 当前仅原生会话容器及工具栏，没有完整N02区域 | 当前事项、执行与异常缺少相应区域；BossConversationWorkspace.tsx、App.tsx、boss-v6.css | FOUND |
| N02-D07 | 当前会话卡片显示关联事项、资料版本、任务对象、返回当前事项和开始新会话 | 当前会话select、两个按钮；正式来源/对象/版本没有显示 | 本人不能核查本次采用范围；BossConversationWorkspace.tsx、公开Conversation读取 | FOUND |
| N02-D08 | 初始HTML及source_summary保留主导航之外的历史会话区域，参考宽度213；loaded chat保留上下文和运行层级 | 当前仅select切换及搜索按钮，没有历史列表区域 | 连续会话入口密度和顺序变化；BossConversationWorkspace.tsx；历史仍采用真实topicSessions及原生保护 | FOUND |
| N02-D09 | 对话内保留交办消息、可观察执行步骤、实际产物、原文/交办/原执行结果入口；右列显示进展与异常 | 当前没有采用ConversationAPI的实际运行/产物投影 | 正式运行和业务产物不能连续核查；BossConversationWorkspace.tsx、public_conversation.py | FOUND |
| N02-D10 | 原稿stage gap11，1440 padding4px 23px 22px 28px；标题及正文父容器按原稿排列 | 当前gap14、底部padding21；原生上下文/工具栏增加独立区域 | 层级和空白分布变化；boss-v6.css、BossDesktop.tsx、App.tsx | FOUND |
| N02-D11 | 原稿Panel h2 17px/26px/760/#163052、正文16/24、辅助14/22，按钮44px/14px、实色#0969E8、焦点offset2px | 当前native内部控件需要按准确区域成对测量；全局焦点offset3px已由源码确认 | 控件密度、层级及焦点位置；boss-v6.css、ThreadComposer/ThreadShell采用处；不能将存在原生组件登记还原通过 | NEEDS_MEASUREMENT |
| N02-D12 | S00—S10、D06/D07/D08、选择/展开/滚动/历史返回及200%均需当前状态证据 | 草稿/附件/排队保护已有实际证据；新N02区域未完成，其他状态没有完整证据 | 必要状态及键盘连续操作仍待运行；当前N02组件及独立行为检查 | NEEDS_MEASUREMENT |

数值来自同一窗口和缩放的实际记录；正文业务卡片尚未实施，不填造尺寸或复核结果。主导航、历史区域与loaded chat结构需要同时保留原稿依据，不能用当前Shell或原生默认布局作为变更批准。动态内容采用正式数据，后续比较同时记录数量、文字长度、选中与展开状态；自然内容高度变化单独说明。当前N02实施所需公共框架修改属于本菜单依赖，不登记F01设计返修完成。
