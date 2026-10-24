# MENU-N02 设计差距

CURRENT；decision_id=D-UI-FIDELITY-20261024；MENU-N02.C01/C02/C25/C26；责任N3。当前状态依据准确原稿和独立构建的DOM、计算样式、位置尺寸及行为；完整设计通过、视觉及用户验收尚未登记。

原设计记录evidence/menu-delivery/N02/reference-dom.json，当前产品记录framework-current.json，manifest=9abccea0d664926083f9e568e3d3bcf088a30fa1ddc3651386ced43835961c8e。各18组：三种规定窗口100%/200%，以及1250、1050、700、690阈值及相邻宽度；记录实际视口、scroll位置、client/offset尺寸及内容状态。默认空会话测量后，逐组输入未发送文字并采用Tab/Shift+Tab核查真实启用操作、伪元素、字体、焦点、图标/图像及滚动祖先，结束前清除测试输入。原稿预览工具和预设状态说明不进入产品，不据其正文纵向坐标差判错；screen的min-height:540px与200%动作可达分别核查。

| 编号 | 原稿依据及数值/结构 | 当前产品数值/结构 | 用户影响与责任文件 | 状态 |
|---|---|---|---|---|
| N02-D01 | screen padding clamp(8px,1.2vw,17px)，1440时17；shell x17/宽1406，1px边框、24px圆角及原阴影 | 18组同一视口；外框位置、内距及圆角采用原稿；1440为x17/宽1406 | 外框复核已记录；boss-n02.css；完整样式仍需独立核查 | FRAMEWORK_CHECKED |
| N02-D02 | sidebar padding23px 13px 18px 14px；宽度>1250为204、≤1250为174、≤1050保持60图标导航 | 18组导航宽度相同，≤690仍保留60；采用原内距和阈值 | 响应框架复核已记录；boss-n02.css；图标与全部状态继续核查 | FRAMEWORK_CHECKED |
| N02-D03 | 六项主导航及原稿选中标记 | 六项名称、顺序和对应图标已采用；当前N02选中；未交付菜单不可用，现有业务从目录可访问 | BossDesktop.tsx、delivered-navigation.ts、boss-n02.css；完整状态与键盘待复核 | REVIEW_PENDING |
| N02-D04 | topbar高64、1440 gap18；今日/开始对话/语音/通知快捷操作；真实身份 | 采用64/gap18和原阈值，四项快捷操作已提供；语音暂停，身份来自当前认证 | BossDesktop.tsx、boss-n02.css；操作、窄窗口与密度待完整复核 | REVIEW_PENDING |
| N02-D05 | hero高146/h1 29px；≤1250为124/25px，≤700标题21px，dapeng-side | 18组hero边界及标题字号与原稿相同；使用dapeng-side | BossDesktop.tsx、boss-n02.css；品牌图像边界及状态仍需测量 | FRAMEWORK_CHECKED |
| N02-D06 | loaded chat主列+310px右列，≤1250右列260，≤1050单列；上下文、对话执行与进展 | 1440主列825/右列310，间距14；当前上下文、对话执行、右侧进展与可打开来源/附件已采用 | BossConversationWorkspace.tsx、App.tsx、boss-n02.css；全部区域/状态待独立复核 | REVIEW_PENDING |
| N02-D07 | 关联事项、资料版本、任务对象及返回/新建 | 当前三项采用正式上下文、实际任务产物及来源元信息；原/当前版本和支持关系分别呈现 | BossConversationWorkspace.tsx、Conversation Schema1.2；任务工具引用的必要来源投影继续核查 | DOMAIN_ADOPTION_PENDING |
| N02-D08 | HTML/source_summary的历史区域参考213；loaded chat的上下文和对话宽度 | 历史默认收起，明确展开后213px；原生选择/搜索/新建及保护保持，≤1250单列；测量登记实际数量/标题长度/展开状态 | BossConversationWorkspace.tsx；保留两个正式设计输入，完整历史阅读与状态继续复核 | REVIEW_PENDING |
| N02-D09 | 可观察步骤、实际产物、来源/交办/原执行结果入口和右侧进展 | 当前真实Runtime步骤/产物及重读采用；实际Dialog关闭及焦点返回通过；一般来源与完整业务路径待接收 | BossConversationWorkspace.tsx、public_conversation.py；完整C07—C23待继续 | DOMAIN_ADOPTION_PENDING |
| N02-D10 | stage gap11、1440 padding4px 23px 22px 28px | 18组stage间距/内距匹配；正文起点1440为y243，不包含设计预览工具 | boss-n02.css、BossDesktop.tsx、App.tsx；正文内部完整密度待复核 | FRAMEWORK_CHECKED |
| N02-D11 | Panel h2 17/26/760/#163052、正文16/24、辅助14/22、主操作84×44/14、实色#0969E8、焦点offset2；输入最小88/字重600 | 18组主操作84×44、字体14/690、输入字重600、键盘焦点及offset2通过；交办消息/步骤标题采用h2，顶部/正文背景透明 | boss-n02.css及原生Composer采用处；禁用/运行停止、长内容和全部状态仍需完整复核 | CONTROLS_CHECKED_REVIEW_PENDING |
| N02-D12 | S00—S10、D06/D07/D08、选择/展开/滚动/历史返回及200% | 实际产物Dialog/Escape/焦点、草稿/附件/排队保护通过；完整状态、权限、异常和历史阅读仍待运行 | 当前N02组件及独立行为检查；完整26项尚未通过 | INTERACTION_PENDING |

动态内容采用正式数据，比较继续记录数量、文字长度、选中与展开状态；自然高度变化单独说明。框架尺寸检查不代表正文和全部控件已完成设计复核。当前样式按N02作用范围采用，F01必要设计返修保持独立未完成。
