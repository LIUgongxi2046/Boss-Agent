# SHOW-ALL-MENUS 全部菜单显示

task_id=SHOW-ALL-MENUS；CURRENT；last_verified=2026-10-25；执行模式S008 SINGLE_TASK。任务来源为用户明确要求“显示全部菜单，然后commit & push代码到main”，当前接收SHOW-ALL-MENUS-COMMIT-COMPLETE-20261025的提交收尾要求。当前记录承载本项状态；N3只在codex/integration提交，主聊天负责合并main及push。当前状态CODE_VERIFIED_PRODUCT_UI_PENDING，输入提交346e053356baafeef75f2560813ae52c43613975；提交通过本记录所在Git提交定位。

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
| MENU-ALL.C05 | Given当前角色全部已实现页面，When点击侧栏、目录、搜索及共享入口，Then进入原有相应页面，当前编号、标题、组件与URL一致，未完整功能仍可进入既有实现 |
| MENU-ALL.C06 | Given连续页面和原生会话导航，When刷新、后退、前进及返回，Then目的页面与原返回来源一致，历史记录保留，未保存内容继续等待明确选择 |
| MENU-ALL.C07 | Given独立制品、端口及资料目录，When通过独立启动入口运行，Then使用本项准确制品，保留五套已有体验；账号只在受控Electron填表，登录由本人点击，尚未配置的Runtime准确显示 |

## 实现与检查

delivered-navigation.ts从原始72项页面配置生成角色目录，BossMenuNavigation.tsx在展开侧栏中显示一级分组及全部页面，同时承载分组目录，BossDesktop.tsx采用相同入口与状态，boss-v6.css保留目录及侧栏滚动结构。准备脚本包含新增导航组件、boss-history.ts与boss-route.ts。既有BossLogin、BossWorkspaceView、BossOwnerPreferences、MaintainerScheduler继续通过deliveredPage读取相同角色范围。本人目录52项、维护目录26项；包含共同认证/状态页及原有MVP/Settings，因此两个数量不用于相加计算设计页面。

boss-route.ts统一读取页面、返回页面、任务、来源和方法编号，将本人NATIVE规范为N02；菜单入口清除共享跳转的返回标识。boss-history.ts通过History位置保存原次后退及前进，离开确认期间保持来源，批准后继续原移动。业务组件更新查询参数时保留history.state。nanobot-all-menus-routing.patch记录原生App的相同History函数、确认期间处理及以replace进入原生视图；本次准备工程已经接收该文件的变化。业务页面的现有组件选择条件保留。

测试文件app/tests/test_all_menus.cjs使用实际页面配置、角色映射、当前导航函数、实际React server渲染及Happy DOM解析。侧栏逐页入口检查具有实际Red及Green结果。app/tests/test_menu_routing.cjs及menu-routing-browser.tsx通过独立静态HTTP页面运行真实React组件与Chromium History API；共点击本人及维护侧栏、目录的156个页面按钮，逐项检查URL读取的页面编号及入口标题；同时覆盖直接读取/刷新、角色拒绝、NATIVE/N02、共享任务与来源返回、F19变体、前进后退条目数量及延迟批准后的原历史继续。十项组合检查通过，不创建业务资料或认证替代路径。搜索、一级分组、状态和权限的静态检查继续保留。

严格TypeScript命令为在.work/product/nanobot/webui执行env TMPDIR="$PWD/../../../tmp" ./node_modules/.bin/tsc -p tsconfig.build.json，退出码0。准备工程BossDesktop.tsx与boss-v6.css通过cmp核对当前源码，导航组件及新增模块使用当前源码引用。检查命令为env TMPDIR="$PWD/.work/tmp" node --test app/tests/test_all_menus.cjs app/tests/test_menu_routing.cjs，结果10 passed、0 failed。prepare_boss_webui.py通过AST语法检查，git diff --check通过。原有test_v6_contract.py的10 passed、1 failed仅为此前限定静态检查结果，本次未重跑或登记全部通过。

按用户当前代码提交要求，本次没有生成独立产品制品、初始化脚本或启动器；没有启动业务产品、替换五套体验或读取凭据。浏览器检查只运行独立静态组件页面，并在完成后关闭自身浏览器及HTTP服务。认证后的Shell逐页组件、完整业务流程、视觉及MENU-ALL.C07独立启动尚未验证；这些内容未登记已交付。N03原26项及两项自动认证审批保持原状态。

## 继续条件

当前提交包含全部已实现修改、新增源码、测试入口、原生接收补丁及准备脚本和记录，由主聊天接收准确commit后负责main及push。产品认证UI、独立制品/启动、视觉和原完整菜单验收不属于本次提交通过范围。MENU-N03保持0/26，两项专用自动认证待授权继续保留。本机读取与表单填充授权仅适用受控Electron主窗口，不扩展到自动登录或初始化认证。
