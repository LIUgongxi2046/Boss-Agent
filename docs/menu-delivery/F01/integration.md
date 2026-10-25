# MENU-F01 今日工作

### 2026-10-25 F01 第一批真实工程接收结果

- **固定上游与复用**：仍采用 HKUDS/nanobot v0.3.5 固定提交 `1bb712d`、原有 BossMorningView/BossToday、SessionManager、原生 ThreadShell/Composer/Viewport 与全部现存领域组件；没有另建会话平台或降级删减 UI。之前通用 `prepare_boss_webui.py` 仅初始 BossDesktop JSX 包裹，遗漏后续 F01/N02/UI02 原生扩展，致最新主分支干净构建失败。
- **本轮代码**：`855edf4` 新增 `scripts/boss_native_overlay.py` 按已签入的十组历史补丁重建受控上游源码，匹配失败即拒绝覆盖；`df940f7` 接入构建，`dcb696e`/`0d320b5` 修正同名 JSX 属性歧义，保证两种真实 ThreadShell 及 ThreadComposer 分别绑定当前会话/历史阅读与输入保护。原生晨间 `onStartMorningChat`、`boss.morning.bind`、输入丢弃确认、会话恢复和动作中断原编号路径被实际编译，而非空实现。
- **构建与复验**：GitHub Actions `40163435064` 中 `react-webui-build` 成功；固定上游源码+第一方 React+TypeScript+Vite 成功，制品 `.work/product/nanobot/nanobot/web/dist/index.html` 存在，Electron 宿主语法检查成功。新增 `8fd0caf` 的第二次独立准备与 manifest 字节比较，在 `40163625105` 的 `react-webui-build` 全部成功，证明在同一隔离 GitHub Runner 中重复准备不会遗漏补丁/改写其它文件。此证据不是目标 Mac GUI 运行。
- **F01 真实领域**：独立 `.github/workflows/boss-agent-f01.yml` 于 `40163532726` 执行当前 `main` 已签入领域和接口共 **41 passed/0 failed**，包括 `test_boss_today.py`、`test_fc03_morning.py`、`test_menu_f01_domain.py`、`test_public_morning.py`。涉及分类、时间、来源、CAS/幂等、持久化、服务访问和异常；测试在项目 `.work/ci-pytest/f01` 下创建独立模拟 SQLite，没有登录用户程序或读取密钥。该结果仍属于受限模拟领域/公开接口，不能代表模型质量或全部 UI 行为。
- **逐页映射修订**：`specs/page-service-map.json#F01` 只纠正当前源码已存在的 `BossMorningView`/原生绑定、真实只读接口与 `boss.today.reorder`/`boss.morning.bind`，仍保留 `actual_e2e_verified=false`、`visual_pixel_verified=false` 与需复验的三项完整桌面行为；不提前登记 UI 或用户通过。
- **剩余阻碍与责任**：Desktop v7 完整 ZIP/HTML 未在可核查的 GitHub 源码树；现有 v7 2880×2862 长图尺寸记录不能替代正式 DOM/样式及用户视觉验收。已通过的原 v6 开发18项历史保持，当前 v7 新轮完整检查点仍为 **0/18**；须在保留的运行实例之外提供独立验证与准确来源一致的制品、真实受控手动登录、F01 全路径、动态状态、尺寸/长页、焦点/滚动、授权恢复和验收证据。已有 N03 业务/待确认任务不受本轮构建改动推进。
- **CI范围分离**：旧综合流水线的 `python-domain-contract` 仍会因为暂停中的 N03 SDK 检查依赖未提供的本地 `validation/connection.json` 和既有失败而显示总体红色；不伪造密钥、不关闭失败检查，也不据此否认已单独通过的 React 构建和 F01 41项领域测试。

当前结论为 `SOURCE_BUILD_AND_SCOPED_DOMAIN_CHECKS_PASSED__DESKTOP_V7_E2E_PENDING`；正式完成数量及用户验收状态仍以唯一 `specs/feature-delivery.json` 为准，当前不能由某个成功 CI 提升为18/18。

### 2026-10-25 从首菜单重新核验：v7 准入（新一轮，尚未通过）

用户在完成新一轮项目接手和逐菜单讨论后明确要求“建议从头确认下”。本项由当前接手负责人按最新指令重新从 F01 核对，不推倒重做，不删原始证据。原 `MENU-F01.C01—C18` 共18项及 `docs/menu-delivery/F01/delivery-rework.json` 的 `DEVELOPED_PENDING_USER_ACCEPTANCE` 仍是 **Desktop v6、准确旧候选和旧独立环境** 的历史开发覆盖记录，不等于本次 v7 已验证。原 18/18 保留并单列，新一轮 v7 逐项重核从 0/18 起，用户/视觉验收继续 NOT_RUN/PENDING。单活动菜单约束继续有效；N03 已有模块和26项进度冻结保留，不能借此删除。

**本次静态核对来源**：本轮开始时的 GitHub `main` 为 `83e3e303de2e31e61c89ddf8bede517be7d200cc`；已重新完整读取 `docs/开发接手与执行规范.md`、`AGENTS.md`、`specs/feature-delivery.json`、`specs/menu-plan.json`、F01 工单/既有开发与设计记录、`docs/PRD完整产品后续需求.md` 的 FR-01/BR-01/AC-01-S/E 与共同规则、当前 `BossMorningView.tsx`/`BossToday.tsx`、F01 Shell 样式及 `specs/page-service-map.json`。原 F01 源为 `Boss-Agent-Desktop-Complete-v6/pages/F01-今日工作.html` 及加载 CSS/JS、Token。上一聊天的 v7 `Boss-Agent-Desktop-v7-72-Full-Length-UI.zip` 长页审查记录为72个主页面HTML/PNG对应、F01 2880×2862、N02 2880×5256，不能凭图片高度宣告业务内容完整；该 v7 ZIP 未进入当前 GitHub 树，当前无法取得同版本完整HTML/CSS/素材字节进行自动成对比较。旧 v6 测量不继承为 v7 通过证据，既有图像/截图禁令继续有效。

**静态代码实情**：当前 F01 实际保留日期/IANA时区、本人待决定/待协调/需要知晓分类、正式事项详情、同版本来源、排序及 CAS、自然语言交接和明确本人授权流程；应优先复用。现有 `specs/page-service-map.json#F01` 仍标为 `PARTIAL_TODAY_CLASSIFICATION_AND_OWNER_ORDER` 且写有 `conversation.start` 未实现，但这份字段滞后于 `BossMorningView` 当前交接代码和 F01 准确候选记录，不能直接当成当前缺陷或当前通过。该映射需按实际消费者/源码版本重新核定，不删旧历史。最新主线的干净 CI 构建仍失败（见运行 `40161702949`）：原生 `App.tsx` 尚未完成 `BossDesktop` render-prop 整合以及 `ThreadViewport` 的真实阅读控制器补丁接收；本项为 F01/N02 公共可重建阻碍，不能靠仅复制文件、静态页面或类型空实现宣布解除。旧 F01 私有独立候选有构建与行为证据，但它不是最新 `main` 或 v7 的可启动交付。

**本轮 F01 确认门槛**：保留18个稳定检查点，从头对照最新正式 FR-01 和 v7 当前HTML/长页中的真实区域与状态；逐项补当前源码功能、前后端真实消费及同库保存/重读/权限/撤销/幂等/失败与返回证据；复用 v6 已验证的同版本正确域能力。高保真核查覆盖公共Shell、左列分类/事项/自然语言、右侧选中详情/来源/会议承诺、尺寸/时区/滚动/键盘及所有适用异常；先形成有原值和实测值的差异表再修复。独立干净构建需包含纳入的原生 nanobot 必要补丁，编译、启动器、认证后真实完整使用与制品/源码版本一致；用户原体验和资料不切换。不获得授权时不执行截图/图像查看或自动认证，未完成的外部模拟状态、语音暂停和私人资料保护全部保留。

**当前结论**：`F01_V7_REVALIDATION_IN_PROGRESS`，当前新一轮逐项有效验证 0/18（尚未执行 v7 逐项完整证据），旧 18/18 保留为有边界的历史开发结果，不能计作最新版本已通过。核验并修好 F01 后，依次重新确认 N02（历史26项保留）和 N03（已有业务继续复用），再继续其他菜单。不得重做已经满足且依赖未变的业务实现，也不得绕过用户验收门槛。


task_id=MENU-F01-N3；CURRENT；2026-10-25；DEVELOPED_PENDING_USER_ACCEPTANCE。唯一正式状态来源为原始目录specs/feature-delivery.json。完整范围为MENU-F01.C01—C18，开发覆盖18/18；用户验收分子null，视觉NOT_RUN。必要设计事项F01-D01—D12均已在指定范围关闭。

## 需求与设计依据

需求采用D-MENU-DELIVERY-20261024、D-UI-FIDELITY-20261024、docs/menu-delivery/F01.md、完整FR-01/BR-01/WF-FR-01/AC-01-S/E、BR-C01—C07及E01—E06。设计采用原始v6 F01 HTML、design-v6-panels.js实际加载的home、公共CSS、页面配置及Token。S008实施记录、S003-2设计规范和S005-4状态规则适用于当前实现。

主列采用日期范围、三类Tabs与紧凑事项、自然语言输入；右列采用选中对象、保存与返回。完整来源、会议、冲突、风险、目标及查询记录均有明确展开入口。公共框架保留原六类导航、侧栏尺寸、留白、问候、顶部控件和响应阈值；未交付菜单保持禁用，其他已交付页面由目录访问。原设计预览身份与示例业务值不进入产品。

BossToday的compact呈现保留完整事项集合、统一上移/下移/保存/继续讨论，以及Alt+方向键。分类数量、选择、排序理由、负责人、期限、状态和风险均来自同一正式View。本人确认保存采用既有完整集合CAS接口。来源和会议通过同版本引用读取，Dialog关闭恢复触发焦点。

自然语言采用可见“本次需求”标签；没有问题文字时继续讨论聚焦输入。实际问题由本人明确提交，引用由正式服务绑定。D06支持保留编辑和明确放弃；放弃后清除未提交问题并建立独立会话。晨间返回保存安全技术坐标、分类和控件标识；刷新后重新核查当前事项版本，并恢复分类、滚动和继续讨论焦点，不持久保存问题正文。

## 当前候选与适用证据

基准为N02候选8e135b8c8b09e0aa3b95ceddb9146868565fa8d7。当前实施为c72cb2e0d12662f25bdfbfdf0ff8885a9a6ebed4，必要Dialog检查候选为9fd9c6e2128a313e1820a4e7bedd16b4a10da7bf。独立制品menu-f01-rework-n3-dist的manifest为ee1b543a5258a12ad01676eed39e2923e6c55ed6aba4f857d78890016e32296a，index为fe9842f392bf853f217294d83dcad3918d2046afb62dfdbdac33ccee21ccff22。严格TypeScript和Vite构建通过。最终候选指针和完整文件摘要以正式状态及rework-candidate-inventory.json为准。

| 记录 | 适用来源与结果 |
|---|---|
| rework-dialogs.json | 当前ee1制品PASS；六种窗口/缩放、来源和会议共12组；x、width、实际定位容器、字体、边界、焦点与三种关闭均有实际记录 |
| rework-launcher.json | 当前ee1制品PASS；两个角色受控填充与手动登录、14工具配置、实际普通会话、D06保留/放弃和独立新会话；既有业务与凭据保持 |
| rework-design.json | 沿用准确8cab候选原字节；18组默认布局、字段样式、同分类状态、位置尺寸与焦点记录PASS |
| rework-header.json | 沿用准确8cab候选原字节；18组环境、15组顶部角色及36项导航状态记录PASS |
| rework-behavior.json | 沿用准确8cab候选原字节；当前正式资料、来源/会议、实际延迟响应、排序、CAS、原编号恢复、独立重开和本人确认交办PASS |
| rework-native.json | 沿用准确8cab候选原字节；实际连续会话、固定事项引用、刷新返回分类/滚动/讨论焦点及独立会话范围PASS |
| combination.xml、native-adapter.xml | 保留准确原F01领域与适配器记录，分别21项和24项通过；仅用于当前未变依赖对应的日期、来源、事务、权限、Runtime生命周期等行为 |

四份沿用报告来自8cabf2ca2a7d3ae99500b1a137bc1dc14ea55827，保持原manifest6094fd56d16e1d50a10094a9d7c8c477972b8cf0c772ae5de4989bea2860ebfe及原摘要。Git核查确认app/webui除boss-morning.css外源码未变；该CSS差异仅包含F01遮罩、实际Radix定位容器与Dialog内容三条布局规则。沿用报告不登记为当前制品重新运行。

当前Dialog采用原Modal的min(580px,94vw)、24px内距、16px圆角及原字体/阴影；实际定位层采用grid、place-items、20px内距，无背景模糊。1024×768／200%下两种Dialog的x均为20px，与参考相同。全部12组验证Escape、关闭按钮、外部点击及返回焦点。有限动画和焦点过渡按实际状态完成后测量，不修改页面样式。其他逐项依据及测量见design-rework.md。

## 领域、Agent与检查点

N1领域依赖采用已接收的89d26855ba7d1fdb8bbe9ff0795a00562c9f53ab及其集成24f5c64，八类输入、分类、来源截至、风险、会议和排序采用正式字段；N02后续领域依赖按其准确接收版本继续保留。N2当前Runtime1.3.0与Schema1.13及已接收原生连接、会话、工具范围、来源和生命周期继续采用。完整业务与实际安装SDK摘要由候选清单核查；没有新增领域或Agent替代实现。

C01/C02/C18采用原设计区域、层级、列结构、间距、文案、窗口/缩放和键盘证据；C03—C10采用正式日期、完整来源、分类、合并、排序、关联和当前版本；C11—C14采用实际Runtime、会话交接、独立交办及保存重读；C15—C17采用适用异常状态、权限、CAS、撤销与同编号恢复。具体18项映射保存在delivery-rework.json。N4对准确候选9fd9c6e完成D12限定关闭，D01—D11既有关闭结论保留；qa.md摘要为3bae06f42605a57c2662db56df0150a6fe7a6b237eb1db3c9ac0b0c4cb29c3e9。N4没有独立运行产品；必要审查不增加独立全菜单PASS门槛。

当前UI检查覆盖实际响应交付中断后的原编号只读恢复、并发CAS保留编辑、较早详情/来源响应不覆盖新选择、维护角色不能读取本人绑定、实际取消/超时与来源撤销。独立交办保存为OPEN，发送需要本人操作；未知写入只读查询，没有重放。来源缺少和没有记录分别呈现。

## 运行与保护

入口scripts/run_menu_f01_rework.command采用10621/10622/20621与validation/.work/menu-f01-rework-release-experience。正式用户目录已经初始化READY，配置version2、14项工具及WORKSPACE_PROJECTIONS与当前制品一致；该目录没有用于业务测试。体验步骤见experience-rework.md。

账号填充仅沿用用户明确授权：受控Electron主窗口读取当前应用accounts/credentials.json对应角色的既有账号密码并填入表单；登录由本人操作。凭据不进入日志、URL、静态制品或浏览器持久存储。

原F01入口及10611/10612/20611、N02及10711/10712/20711、UI02及10411/10412/20411、MVP及9961/9962/19961均受保护。相关前端、用户资料及桌面不用于测试、退出、重启或热替换。全部外部SIMULATED_FIRST；STT/F27/FC28保持暂停。DOM、计算样式和位置尺寸使用隐藏Electron核查，没有使用截图或图像工具。视觉和用户验收继续待确认。
