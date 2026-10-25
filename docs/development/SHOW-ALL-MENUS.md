# SHOW-ALL-MENUS 全部菜单显示

task_id=SHOW-ALL-MENUS；CURRENT；last_verified=2026-10-25；执行模式S008 SINGLE_TASK。任务来源为用户明确要求“显示全部菜单，然后commit & push代码到main”，通过SHOW-ALL-MENUS-MAIN-20261025交给N3实施。当前记录承载本项状态；N3只在codex/integration提交，主聊天负责合并main及push。当前状态DEVELOPED，输入提交3fc7446801a15b91b2c56e6a3066bc06c823c9fa；提交通过本记录所在Git提交定位。既有N03审查引用更新属于已完成记录，一同保留。

## 依据与完整范围

已检索开发索引、T08、LLD-frontend、UI01/N03记录、原始v6导航、页面配置、hld-72-page-map及page-service-map，并核查delivered-navigation、BossDesktop、BossLogin、BossWorkspaceView、BossOwnerPreferences和MaintainerScheduler的实际消费者。原稿本人六组为今日工作、聊天交办、经营关注、会议与资料、任务与承诺、通知与设置；维护四组为档案与访问、模拟中心、Agent配置、运行与评测。72项设计页面及F19三项独立变体保留；N01/D08继续表达认证入口，D06/D07保留认证后公共状态。

本项采用全部菜单可见的当前决定。导航、页面目录、搜索及合法直接入口使用同一角色目录；页面状态根据现有实现及验收情况明确显示。角色验证及服务端业务权限保持；F27/STT暂停。已有MVP和原生Settings入口继续保留。没有新增业务功能、数据、账号或授权。

## 验收

| ID | Given / When / Then |
|---|---|
| MENU-ALL.C01 | Given原始页面配置和角色映射，When读取本人/维护目录，Then各角色全部合法设计页面均存在，一级导航六组/四组完整，目录分组与页面计数准确 |
| MENU-ALL.C02 | Given任意正式页面ID，When使用直接入口、搜索或共享导航，Then同角色可达、跨角色拒绝；未知ID拒绝，登录状态入口不执行自动认证 |
| MENU-ALL.C03 | Given既有完整/部分实现、N03开发中及语音暂停状态，When显示目录和当前页面，Then状态准确，不把菜单显示登记为完整功能或验收通过；F19变体保持独立 |
| MENU-ALL.C04 | Given现有导航/登录/共享消费者及准备工程，When执行允许的导航/权限检查与严格TypeScript，Then检查通过；N03保持0/26及两项自动认证待批准，既有体验不启动或替换 |

## 实现与检查

delivered-navigation.ts从原始72项页面配置生成角色目录，BossMenuNavigation.tsx承载实际一级导航及分组目录，BossDesktop.tsx采用相同入口与状态，boss-v6.css保留现有目录交互及滚动结构。准备脚本包含新增导航组件。既有BossLogin、BossWorkspaceView、BossOwnerPreferences、MaintainerScheduler继续通过deliveredPage读取相同角色范围。本人目录52项、维护目录26项；包含共同认证/状态页及原有MVP/Settings，因此两个数量不用于相加计算设计页面。

测试文件app/tests/test_all_menus.cjs使用实际页面配置、角色映射、当前导航函数、实际React server渲染及Happy DOM解析，不创建业务资料或认证替代路径。BDD Red阶段四项业务断言失败；Green阶段五项通过，覆盖72页角色权限、六组/四组与唯一目录编号、F19变体、N03及F27状态、全部待用户验收、搜索、未知/对象原型编号拒绝，以及实际React按钮/状态/搜索输出。React输出检查属于静态组件检查，没有执行浏览器认证和点击后的业务流程。

严格TypeScript命令为在.work/product/nanobot/webui执行env TMPDIR="$PWD/../../../tmp" ./node_modules/.bin/tsc -p tsconfig.build.json，退出码0。准备工程BossDesktop.tsx与boss-v6.css通过cmp核对当前源码，导航组件及函数使用当前源码引用。node --test app/tests/test_all_menus.cjs结果为5 passed、0 failed。prepare_boss_webui.py通过AST语法检查，git diff --check通过。现有test_v6_contract.py组合为10 passed、1 failed；未通过项要求BossDesktop包含metrics URL，输入提交同样不包含该URL，该项不属于本项新增变化，没有登记该组合全部通过。

当前磁盘可用空间158MiB，低于既有200MiB制品生成条件；本项没有生成或替换体验制品，不调整该条件。五套既有体验未启动或修改。

## 继续条件

全菜单显示及受影响非视觉检查完成，代码在codex/integration提交，由主聊天接收准确commit后负责main及push。产品认证UI、视觉和原完整菜单验收不属于本项通过范围。MENU-N03保持0/26，两项专用自动认证待授权继续保留。本轮收到的本机读取与表单填充授权仅适用受控Electron主窗口，不扩展到自动登录或初始化认证；本项没有读取凭据。
