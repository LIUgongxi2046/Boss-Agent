# MENU-N02 设计差距

CURRENT；decision_id=D-UI-FIDELITY-20261024；MENU-N02.C01/C02/C25/C26；责任N3。当前状态依据准确原稿和独立构建的DOM、计算样式、位置尺寸及行为；完整设计通过、视觉及用户验收尚未登记。

原设计记录evidence/menu-delivery/N02/reference-dom.json，当前产品记录framework-current.json，manifest=7fd1a426910b2f4efed10143e91f3fc76d9afe1502ce2234ef91107a31c016c5。18组默认区域、18组历史展开、18组提交按钮五种状态：三种规定窗口100%/200%，以及1250、1050、700、690阈值及相邻宽度；记录实际视口、scroll位置、client/offset尺寸及内容状态。真实启用操作、禁用/悬停/键盘焦点/按压、字体、SVG节点/属性、图像、输入祖先及滚动祖先均记录。伪元素仅记录计算样式，不声称具有独立测量边界。历史来自本实例12个实际请求，记录原run_id和实际终态。原稿预览工具和预设状态说明不进入产品，不据不同内容下的正文纵向坐标差判错；screen的min-height:540px与200%动作可达分别核查。

| 编号 | 原稿依据及数值/结构 | 当前产品数值/结构 | 用户影响与责任文件 | 状态 |
|---|---|---|---|---|
| N02-D01 | screen padding clamp(8px,1.2vw,17px)，1440时17；shell x17/宽1406，1px边框、24px圆角及原阴影 | 18组同一视口；外框位置、内距及圆角采用原稿；1440为x17/宽1406 | 外框复核已记录；boss-n02.css；完整样式仍需独立核查 | FRAMEWORK_CHECKED |
| N02-D02 | sidebar padding23px 13px 18px 14px；宽度>1250为204、≤1250为174、≤1050保持60图标导航 | 18组导航宽度相同，≤690仍保留60；采用原内距和阈值 | 响应框架复核已记录；boss-n02.css；图标与全部状态继续核查 | FRAMEWORK_CHECKED |
| N02-D03 | 六项主导航及原稿选中标记 | 六项名称、顺序和对应图标已采用；当前N02选中；未交付菜单不可用，现有业务从目录可访问 | BossDesktop.tsx、delivered-navigation.ts、boss-n02.css；完整状态与键盘待复核 | REVIEW_PENDING |
| N02-D04 | topbar高64、1440 gap18；今日/开始对话/语音/通知快捷操作；真实身份 | 采用64/gap18和原阈值，四项快捷操作已提供；语音暂停，身份来自当前认证 | BossDesktop.tsx、boss-n02.css；操作、窄窗口与密度待完整复核 | REVIEW_PENDING |
| N02-D05 | hero高146/h1 29px；≤1250为124/25px，≤700标题21px，dapeng-side | 18组hero边界及标题字号与原稿相同；使用dapeng-side | BossDesktop.tsx、boss-n02.css；品牌图像边界及状态仍需测量 | FRAMEWORK_CHECKED |
| N02-D06 | loaded chat主列+310px右列，≤1250右列260，≤1050单列；上下文、对话执行与进展 | 1440主列825/右列310，间距14；当前上下文、对话执行、右侧进展与可打开来源/附件已采用 | BossConversationWorkspace.tsx、App.tsx、boss-n02.css；全部区域/状态待独立复核 | REVIEW_PENDING |
| N02-D07 | 关联事项、资料版本、任务对象及返回/新建 | 当前三项采用正式上下文、实际任务工具引用及来源元信息；原/当前版本和支持关系分别呈现 | BossConversationWorkspace.tsx、Conversation Schema1.2；实际task_id/version及TOOL_RESULT公开检查通过 | REVIEW_PENDING |
| N02-D08 | HTML/source_summary的历史区域参考213；loaded chat的上下文和对话宽度 | 历史默认收起；18组实际展开记录12项真实会话，>1250宽度213px、≤1250单列；每组真实滚动成功；真实搜索、键盘选择及历史恢复通过 | BossConversationWorkspace.tsx、framework-current.json；完整状态继续复核 | TARGETED_CLOSED |
| N02-D09 | 可观察步骤、实际产物、来源/交办/原执行结果入口和右侧进展 | 当前真实Runtime步骤/产物及重读采用；实际Dialog关闭及查询来源原文/交办详情返回后，同一会话、运行选择、滚动和触发按钮焦点保持 | BossConversationWorkspace.tsx、public_conversation.py、native.json；完整C07—C23待继续 | RETURN_CHECKED_REVIEW_PENDING |
| N02-D10 | stage gap11、1440 padding4px 23px 22px 28px | 18组stage间距/内距匹配；正文起点1440为y243，不包含设计预览工具 | boss-n02.css、BossDesktop.tsx、App.tsx；正文内部完整密度待复核 | FRAMEWORK_CHECKED |
| N02-D11 | Panel h2 17/26/760/#163052、正文16/24、辅助14/22、主操作84×44/14、背景#0969E8、焦点offset2；输入最小88/字重600 | 18组输入横向位置/宽度/88px高度与原稿相同；主操作五种状态84×44、字体14/690/24、键盘焦点offset2；真实label本次消息、主操作提交需求、附件入口添加附件；交办消息/步骤采用h2及完整Panel边框/圆角/内距/阴影 | boss-n02.css及原生Composer采用处；运行停止、长内容和全部状态仍需完整复核 | CONTROLS_CHECKED_REVIEW_PENDING |
| N02-D12 | S00—S10、D06/D07/D08、选择/展开/滚动/历史返回及200% | 实际产物Dialog/Escape/焦点、草稿/附件/排队保护通过；完整状态、权限、异常和历史阅读仍待运行 | 当前N02组件及独立行为检查；完整26项尚未通过 | INTERACTION_PENDING |

动态内容采用正式数据，比较继续记录数量、文字长度、选中与展开状态；自然高度变化单独说明。框架尺寸检查不代表正文和全部控件已完成设计复核。当前样式按N02作用范围采用，F01必要设计返修保持独立未完成。

N4对b3de8ea3788629f977f02f182e74a18ea430dc85和7fd1制品的指定SVG、子Panel、标签/输入/附件/提交操作、五状态、历史展开及详情返回增量已给出APPROVED/TARGETED_CLOSED；记录SHA256为30db6b3981e5df7bdf84046b391da4f1b09636d4f2e9594f482ebe6f83babeca。该范围没有未处理必要缺陷。随后实际IME、输入限制、文件选择、长文件名及D06、语音暂停/快捷键、搜索和历史阅读位置证据见input.json、framework-current.json、native-privacy.json。完整26项、关闭与迟到文件等其他必要路径、任务进入会话的版本绑定及用户验收继续保留。
