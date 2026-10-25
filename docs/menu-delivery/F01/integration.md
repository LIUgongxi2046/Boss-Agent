# MENU-F01 今日工作

### 2026-10-25 F01 第四批：当前晨间事项到交办的来源闭环

本次重新完整读取 `docs/开发接手与执行规范.md`、`AGENTS.md`、正式 `specs/feature-delivery.json`、`specs/menu-plan.json`、F01 原18项工单、对应 FR-01/BR-01/AC 与旧实现；只推进 F01，N02 原26项、N03 现有源码与正式暂停状态及全部用户目录保持。开始时 `main` 为 `20feea6e0e0e7acaf13ca5ba17194539d0467513`。

**确认的具体功能缺陷**：在 `BossMorningView` 的已固定列表选择会议、事项后点击“准备交办”进入 F06，`BossMorningPreparation.tsx` 仅识别 `finance-note`、`si09-si10-business-v1`、`FC04-ALERT-1` 预设来源。实际上 `MorningAPI.detail` 已从同一 CURRENT 清单返回该选中事项下带版本的其他有效模拟来源；服务端 `BossCommandAPI._create` 对正式 `morning_reference` 已执行当前清单、当前事项、snapshot、source_refs、会议和事件范围验证，但 `Store.create_assignment` 继承旧 MVP 全局白名单，导致例如 `meeting-minutes` 在实际请求中 HTTP 400。这是跨前端、领域数据的真缺口，旧 v6 F01 已有测试并不覆盖该路径。

**本轮复用/修复（不新增第二套交办或放宽普通业务权限）**：

- `7e44072`：新增 `app/webui/morning-assignment-context.ts`，按返回的真实选中事项 `source_refs` 与当前 `documents` 的 ID、版本、来源属性、清单 ID、事项 ID、snapshot 精确绑定，保留其已有会议和事件引用；不再根据演示资料名称静默漏选，版本不一致、跨事项、重复、不完整、非 SIMULATED 文档均报错。缺少文档时不拼造来源、不允许创建；只计算本人待确认的交办准备上下文。
- `418a255`：`BossMorningPreparation` 接受上述现有领域读取并接入 `BossAssignmentFlow`；保留原页面信息、本人确认弹窗、当前负责人及任务创建/发送/完成分离，不改变现有权限或模拟模式。
- `bd5d2e4`、`a7010f5`：在已有 `BossCommandAPI._create` 的 **当前 `morning_reference` 完整验证之后**，仅通过内部 `verified_morning_selection` 参数让 `Store.create_assignment` 接受当前选中事项的有效来源；普通未绑定晨间清单的交办仍保留其既定来源白名单和完整授权/时钟/负责人/CAS/幂等规则。无需数据迁移或新的模拟数据集。
- `f285606`、`d33c0b6`、`4e811fb`、`0875b79`：新增纯前端引用范围、版本及误用拒绝测试和正式 SQLite 业务 API 正反向测试，覆盖会议纪要等旧白名单以外来源创建 `OPEN` 任务、普通入口继续拒绝、另一个有效来源不能冒用当前事项、失败无任务/授权/outbox 写入。已在定向检查中真实触发旧 HTTP 400，修复后方通过；没有删用例或修改预期以绕过功能缺陷。

**准确测试版本与范围**：`40183732776` （`main` 的 `0875b79` 候选）定向 F01 CI：Node 前端 **19/19**、nanobot 原生晨间 Agent **39/39**、实际 SQLite 领域与公共 API **44/44**，分别通过，共102项不同层面的限定断言；`40183732779` 的 `react-webui-build` 为 PASS（TypeScript/Vite、固定原生补丁、重复准备一致性、Electron 宿主语法）。综合 workflow 的 `python-domain-contract` 仍包含暂停 N03 旧失败，记录为 FAILURE，不得写成全套 CI 通过。无真实外部发件、没有实际用户 Mac 的 GUI 自动认证或个人资料访问。

**用户结果与继续验收**：F01 当前可以在源码及领域测试范围内把非财务但获准的晨间文档纳入真实待本人确认交办，同时阻止错误来源和越权动作。新 F01 v7 稳定18项在唯一状态中继续 **0/18完整验收**；独立启动器、当前准确 Mac 认证 UI、长页结构/滚动/键盘、全部状态和用户视觉仍需核验，且最新 v7 HTML/CSS 原始 ZIP 尚不能获得获准字节副本。不可用旧 v6 制品或旧 CI 报告替代最终验收。N02/N03 不切换，不申请账号自动登录或外部真实调用授权。

### 2026-10-25 F01 第三批：预览、历史清单及来源读取恢复

按用户“继续推进，需要另外开一个新窗口吗？”的指令在**原对话中继续**，没有新建开发聊天、自动任务或第二活动菜单。已重新完整阅读 `docs/开发接手与执行规范.md` 和原 F01 工单，核对 `main`、正式活动状态及 v7 设计资料可访问边界。仅修改本菜单的 `app/webui` 与定向测试；已完成的 v6 F01/N02 证据和 N03 代码、独立制品、原运行资料全部保留。

**本批明确问题与实际修复：**

- `56b7e57`、`e2021d9`：F01 首屏只有日期预览、尚无已固定的晨间清单时，用户可点选事项，但旧 `chooseItem` 误将详情设为 `loading`，实际详情效验路径要求 `CURRENT` 清单而永不调用，界面永久“正在核查”。现采用 `currentMorningDetailScope` 共用判断：当前 `adoption_state`、正式稳定清单 ID 与页面投影 ID 必须全部对应，才进入详情加载；未满足时明确提示只是日期预览、当前不能绑定交办或采用正式来源。新清单或旧清单失效时清理旧详情/加载标志，避免将历史事实当现行证据。
- `00431ec`：来源原文读取同样采用上述当前清单与页面 ID 校验；清单被替换或失效时不再发起旧范围读取，原文弹窗不继续展示旧正文，明确报告需要重新查询正式清单。
- `559ab1a`：来源 HTTP/版本校验失败从全局提示细分为弹窗内明确错误，并提供“重新核查当前来源”按钮；只重读现有有权只读 API，重新核对当前版本，不发业务写动作，不盲目重复原请求。
- `2bb3e90`：对范围检查增加 TypeScript 类型守卫，只有被严格验证的 `view.list_id:string` 才能传给 `URLSearchParams`；修复初次源码编译中的可空 ID 错误，未通过 `any` 或跳过类型校验绕过。
- `d4ab7d8`、`6533c7e`：增加并接入专项回归，覆盖预览无正式清单、有效且 ID 一致、当前 ID 不一致、历史/撤销/复核状态以及空 ID 等权限边界。

**当前真实 CI 证据：** `40165910636` 中 F01 专项独立通过 **12/12** Node 前端逻辑、**39/39** nanobot 晨间 Agent/正式工具/来源权限、**41/41** SQLite 业务与 HTTP 适配。`40165910623` 中 `react-webui-build` job `121086785406` 全部阶段 PASS，包含固定上游 TypeScript/Vite、正式 dist 文件、第二次复编 manifest 一致性及 Electron 宿主语法。这些都是 GitHub 独立隔离环境的限定结果，不宣称已在用户 Mac 上登录或实现 v7 像素级还原。综合流水线的 `python-domain-contract` 仍因暂停中的 N03 及原有环境问题失败，不能把整条 workflow 标为绿色，相关失败未删去或屏蔽。

**剩余门槛**：完整 v7 ZIP 在 Library 有名称与长页审查报告，但仍没有获准的原始 HTML/CSS/资产字节访问；v7 成对 DOM、完整长页 UI 测量和用户视觉验收继续 NOT_RUN。当前用户 Mac 上使用既有正式认证的持续操作、F01 交办/会话闭环、错乱网络恢复、焦点/滚动及同库启动器版本验收仍需准确的独立产品证据。**新一轮 F01 18 项完整检查点继续 0/18，用户验收保持 PENDING**；测试通过只能归入已验证的局部范围，不能累计为完整菜单分子。

### 2026-10-25 F01 第二批功能与安全恢复修复（新轮未结项）

采用本轮继续执行指令，仅限活动菜单 MENU-F01，不切换其他菜单；开发时重新完整读取开发接手与执行规范和本菜单工单，并在 `main` 上基于实际现存源码修改。以下是增量工作证据，原 v6 18/18 及 N02/N03 当前源码和状态均保持。

1. **分类排序的真实操作语义**（`fc14376`、`ab24197`、`bf5799d`）：新增 `app/webui/today-order.ts`，在“待决定/待协调/需要知晓”筛选下，向上/向下只交换该分类内相邻的实际事项，隐藏分类原位置不变；全部模式继续采用完整全局次序，最终仍以本人 CAS、完整 item_ids 和正式 SQLite 服务保存。compact/table 控件按当前分类的真实边界启停，不再点击后只移动不可见的项目。
2. **排序原编号的严格回执与恢复**：从成功回调中抛出的校验异常现在由 `recover` 的 `try/catch/finally` 统一接收，错误不再使操作持续显示加载；回执要求 `boss.today.reorder`、同一 client_request_id、非写入只读标记及正式 outcome。未知结果仍只读取原编号，不盲目重发。
3. **返回坐标和实际事项键**（`3b2f86c`、`ffa247e`、`402ee78`、`e7f466d`）：新增 `morning-return.ts`，接受已有 `task:xxx`、`event:xxx` 这类带冒号的技术对象 ID，严格限制 `morning-` 前缀、允许字符、长度、滚动坐标，保留焦点和滚动重读能力；私人正文及任意用户字符串不进入 URL。`e7f466d` 还修复了返回时被选事项详情读取失败会永久阻止恢复原按钮焦点的问题；页面就地显示失败，焦点仍可回到同一个技术事项控件。
4. **详情失败与重试**：`BossMorningView` 针对当前被选中的事项，区分 loading、版本校验失败、服务错误、当前清单历史失效与真正的未选中状态；详情失败不再永久显示“正在核查”，在同一侧栏就地展示准确错误与重新核查按钮，重试使用相同既有读接口，无新业务写入。
5. **原生 Agent 权限测试的真实前置资料**（`7603d44`、`8409d46`）：新增运行 `fc03_agent/test_formal.py`、`test_menu.py`、`test_native.py`；发现旧测试暗中假设默认资料一定有非当前事项但有效的文档而失败。修改为在隔离测试 SQLite 中通过既有正式 `boss.knowledge.source.create` 维护动作生成真正有效、BOSS 可读但与已选中事项不相关的文档，再断言选中事项的原生受限工具仍返回 HTTP 403；没有跳过或删除源权限拒绝断言。

**实际测试结论（不同范围不转换为本菜单检查点数量）**：`40164777236` 的 F01 workflow 中，前端独立 Node 逻辑 **8/8**、原生晨间 Agent/来源受限 **39/39**、正式 SQLite 领域/公开接口 **41/41** 通过，分别真实运行而非沿用旧报告；`40164765972` 的桌面集成 workflow `react-webui-build` 成功（TypeScript/Vite/构建清单/复编/宿主语法）。该综合流程的 `python-domain-contract` 仍有 N03及旧断言失败，单独记录，不删检查换取全绿。以上未进行目标 Mac 上的自动认证、私人业务测试、真实模型联网或 GUI 实例切换。

**设计阻碍**：在 Library 中能查到 Desktop v7 的72页长图 ZIP 记录和配套核查报告，但原 ZIP 不提供获准的原字节 materialize 路径，当前无法读取逐页面 HTML、加载 CSS/JS 与完整素材；后续 F01 的 v7 成对 DOM/计算样式/长页面尺寸核查保持 NOT_RUN，不构造截图、不宣称像素相似度。当前只复用旧 v6 正确业务逻辑、对现有 F01 交互做定向修复。

**正式状态**仍为 F01 v7 重核 **0/18完整检查点**，视觉 NOT_RUN，用户验收 PENDING；此记录是当前局部质量提升证据，不代表新版 F01 可以交付给用户完整验收。

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
