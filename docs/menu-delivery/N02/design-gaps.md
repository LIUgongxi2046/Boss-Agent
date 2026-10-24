# MENU-N02 设计核查

CURRENT；2026-10-25；decision_id=D-UI-FIDELITY-20261024；MENU-N02.C01/C02/C25/C26；责任N3。当前必要结构、样式及交互采用DOM、计算样式、实际位置尺寸及业务操作核查；视觉及用户验收独立待确认。

当前制品manifest=b2b0d845349e0a87d5263a501f2821c4e6a64223bcca37e2d7443c7e5166d6b4。原设计为reference-dom.json；framework-current.json包含18组默认区域、18组真实历史展开和18组提交按钮五状态，header.json包含18组标题导航及36组导航状态。三种桌面窗口分别为1440×1024、1280×800、1024×768的100%/200%；另含1250、1050、700、690阈值及相邻宽度。共享页面另按1440×1000、1280×800、1024×768及200%检查，两个尺寸集合分别保留。

| 编号 | 原稿依据及当前采用 | 实际证据及范围 | 状态 |
|---|---|---|---|
| N02-D01 | screen内距clamp(8px,1.2vw,17px)，1440时17；外框x17/宽1406、1px边框、24px圆角与原阴影 | framework-current的18组同一视口、框架边界及内距；没有像素结论 | RECORDED_SCOPE_CHECKED |
| N02-D02 | 侧栏内距23/13/18/14px；>1250宽204，≤1250宽174，≤1050保留60px图标导航 | 18组宽度及阈值；200%仍保留导航，实际操作目标至少44px | RECORDED_SCOPE_CHECKED |
| N02-D03 | 原六项主导航的名称、顺序、SVG节点/属性/线宽与当前选中标记；未交付菜单保持不可用 | framework-current记录六项真实导航；header逐项默认样式，并检查选中/未选中导航的悬停、按压和实际键盘焦点 | RECORDED_SCOPE_CHECKED |
| N02-D04 | topbar高64px、宽屏间距18px及原阈值；四项快捷操作、搜索与真实身份 | 搜索左右内距14px，≤700快捷内距6px；身份文字11/15.4px，≤1250隐藏；header的18组属性比较及实际目标≥44×44 | RECORDED_SCOPE_CHECKED |
| N02-D05 | hero高146/h1为29px，≤1250为124/25px，≤700标题21px；原品牌与dapeng-side素材 | framework-current保留原图像自然尺寸及实际矩形；品牌文字单独使用Range，17/26.35px、820字重及#172B4D，与原稿对应 | RECORDED_SCOPE_CHECKED |
| N02-D06 | loaded chat主列加310px右列，≤1250右列260px，≤1050单列；间距14px，列内13px | 当前会话/关联事项→连续对话/可观察执行；右侧进展、来源、附件与异常。18组布局及真实任务/F08共享状态分别核查 | RECORDED_SCOPE_CHECKED |
| N02-D07 | 关联事项、资料版本、任务对象及返回/新建入口 | Conversation Schema1.3.0、Runtime Schema1.13.0；正式任务prepare/bind/read/receipt、来源摘要和实际SDK消费；morning-entry及task-entry-ui | RECORDED_SCOPE_CHECKED |
| N02-D08 | 原HTML/source_summary的克制历史区域参考213px，同时保持loaded chat的对话宽度 | 默认收起；18组展开12项本实例真实会话，>1250宽213px，其余单列；实际滚动、搜索、键盘选择及新空会话 | RECORDED_SCOPE_CHECKED |
| N02-D09 | 可观察执行、当前产物、来源/交办/消息共享路径、原执行核查与最新进展 | native、task-entry-ui、return-position及native-privacy；同会话/原消息/运行、内外滚动和触发按钮焦点恢复，真实分页及迟到响应隔离 | RECORDED_SCOPE_CHECKED |
| N02-D10 | stage间距11px，1440内距4/23/22/28px，正文起点y243 | framework-current的18组实际边界；设计预览工具、静态身份和预设答案不进入产品，动态正文按实际对象表达 | RECORDED_SCOPE_CHECKED |
| N02-D11 | h2为17/26px、760、#163052；正文16/24px、辅助14/22px；输入88px/600；提交84×44px、14/690/24px及#0969E8 | 18组默认/启用/悬停/聚焦/按压、实际输入label与附件入口；主操作焦点2px/外距2px，导航采用原规则2px/外距3px | RECORDED_SCOPE_CHECKED |
| N02-D12 | 适用S00—S10、D06/D07/D08、历史阅读、取消、未知结果及返回 | input、close、native、unknown、task-entry-ui、native-privacy及shared-layout；实际IME、准确边界、文件读取失败、重登、真实关闭、实际业务D06焦点及原编号恢复 | RECORDED_SCOPE_CHECKED |

header比较字体、字号、字重、行高、颜色、背景、圆角、字距及显示规则；其他实际元素同时比较padding/gap，头像比较宽高。品牌文字与父容器分别处理，有限CSS过渡完成后采样。36组导航状态使用真实悬停、按压及Tab/Shift+Tab，没有修改被测样式。小窗口快捷操作最小宽度44px依据当前Token及工单目标要求，字体和内距继续采用原稿。

N4指定内距及导航状态审查APPROVED，准确实现3ebb31cdcac6f90e39b3b2c0808e5e9f21116c98，qa.md摘要404c7dadd9a778334933a211440c5cc43fafefe9879bbf33d8b8b4753c5ec2e5；G04/G05已关闭，该指定范围没有确定剩余必要缺陷。其他消费者报告与12份当前界面/启动记录由N3核对，没有独立完整26项PASS要求。

framework报告的外框自动比较、原始测量与本记录的组合判断分别保留；MEASURED不转换为视觉评分。全部12份报告采用同一当前制品，完整26项开发证据见delivery.json。未测量的像素和视觉细节不作通过声明。F01必要设计返修保持独立，须在N03之前完成；F01/UI02/MVP原体验保持。
