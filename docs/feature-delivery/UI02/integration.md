# UI02 开源界面统一体验

task_id=UI02-N3；CURRENT；last_verified=2026-10-24；DEVELOPED_PENDING_USER_ACCEPTANCE。需求来源为原始目录 docs/UI02开源界面统一体验工单.md、D-UI-INTEGRATION-20261024；八项检查点 UI02.C01—C08，八项开发覆盖，唯一正式状态来源为原始 specs/feature-delivery.json。用户验收保持 PENDING_USER_ACCEPTANCE，用户通过分子为 null；独立验收 NOT_RUN。

## 输入与依据

采用 S008，已读取任务记录规则、执行规则、实施流程、续接要求和改动检查。检索 docs/development/index.md、UI01 与 FC04 主记录、当前前端设计、Desktop v6 Tokens，以及上游 AGENTS.md、设计、安全、常见问题和贡献要求。基准为 386c577b67b2b53fc1989f258095547035750ad3；保留当前未追踪证据。

BossDesktop 与原生 App 共用 ClientProvider。RoleChannel 拒绝 MAINTAINER 读取 /api/sessions，维护 Settings 采用原生获准接口。本人会话和维护 Settings 使用同一产品框架，原生会话、Markdown、工具结果及 Settings 控制器继续采用成熟实现。未知动作继续采用原编号只读恢复；领域、认证、客户端传输及宿主权限保持既有实现。源码与构建输入通过 inventory 核查，准确实现 commit 见 delivery.json，候选 commit 见正式状态。

## 当前实现

| 文件及 identifier | 当前职责与关联流程 |
|---|---|
| app/webui/BossDesktop.tsx、delivered-navigation.ts | 本人十项业务与会话、维护五项业务与 Settings；公共标题、返回、目录、history、安全对象选择及 D06 |
| app/webui/boss-v6.css | v6 语义 Token、字体、44px 控件、原生内容及短窗口滚动；品牌资源保持 |
| app/webui/nanobot-ui02-shell.patch / App、ThreadShell、ThreadComposer | UI01 预备源码的原生增量；保持同一原生客户端，按身份呈现、保留输入、清理退出状态并暂停 STT |
| 同一补丁 / SettingsPage、useSettingsController | 先核查编辑及保存状态，再改变分类；明确保留编辑离开和返回，原生保存行为保持 |
| scripts/run_ui02.command、prepare_fc04.py | 独立默认入口，只核查既有初始化资料；不调整当前用户窗口或资料 |
| validation/desktop/check-ui02*.cjs、ui02_delivery_inventory.py | 实际桌面、连续业务、完整导航、默认入口及源码/制品/依赖核查 |

children(role, visible) 与 ThreadVisibilityContext 保持原生组件和会话上下文。Meta/Control+K 打开唯一目录，Radix 约束焦点并恢复触发位置。普通业务切换保留会话输入；其他会话和 Settings 编辑使用明确离开保护。退出及认证失效清除私人界面、WebuiThreadCache 和原生待发送队列的浏览器记录。原客户端继续处理流式结果、取消与重连，未增加模型工具或自动业务确认。

## 实施与验证

| 检查点 | 场景与断言 | 当前证据 |
|---|---|---|
| C01 | 已交付业务与原生入口、一组主导航和标题、旧链接不可用 | COVERED；navigation.json 实际本人 11 项、维护 6 项，目录一致；current.json 核查旧链接及原生标题 |
| C02 | 同一窗口和认证、返回/前进/刷新/深链接与权限拒绝 | COVERED；current.json 会话重读、前进/返回与角色；business.json 拒绝本人维护路径 |
| C03 | 共用 Token、DOM 样式及原生内容；视觉独立登记 | COVERED；六组实际输入 16px/24px、字体及颜色一致，已保存会话呈现正常，品牌及减少动效规则保持；视觉 NOT_RUN |
| C04 | 控件与状态、焦点和键盘操作 | COVERED；成熟加载、空内容、失败和离线呈现继续复用；实际核查保存、权限、未知结果、断流恢复、对话框焦点和唯一目录 |
| C05 | 对象与结果保持、未保存保护、身份与异步边界 | COVERED；真实 task_id 返回、输入保留、Settings 编辑离开/返回、退出清理与维护 403；读取保留 AbortController 和请求代次检查 |
| C06 | 实际原生传输、会话与 Settings 操作 | COVERED；真实消息发送、SIMULATED 响应和刷新重读，Settings 语言及代码换行保存重读；STT 按钮和快捷键暂停；同一客户端与权限摘要保持 |
| C07 | 本人确认、未知原编号恢复及无重复写入 | COVERED；business.json 实际成功响应中断，原编号只读恢复；保存仅发送一次，启用保持本人独立确认，导航没有启用配置 |
| C08 | 六组尺寸/缩放、准确构建与入口、原资料保持 | COVERED；输入可聚焦、目录焦点恢复、原生与 Settings 均无整页横向溢出；launcher.json 实际默认入口与双方认证，27 项独立业务记录和账号文件保持 |

验证命令：node validation/desktop/check-ui02.cjs、check-ui02-navigation.cjs、check-ui02-business.cjs，前三项使用已有独立 FC04 检查资料报告作为参数；node validation/desktop/check-ui02-launcher.cjs 使用独立默认资料。四份当前报告均为 PASS，manifest_sha256 均为 2b95fb287e88aef5bf3aadbca0ae416262ed077ca3555ac4346616ffbc885523。TypeScript 严格检查与 Vite 构建通过，Vite 19.60 秒，原始日志 build.log。Red 证据 red.json 记录实际 UI01 制品缺少原生入口，结果源于业务行为。当前检查使用原生 Electron、真实本地认证、SQLite、实际 WebSocket 和真实成功响应中断，没有替代业务响应。

## 环境与约束

验证采用独立资料、端口和 ui02-n3-dist；用户当前桌面及 9961/9962/19961、mvp01-experience 保持原状态。默认入口采用 ui02-experience 与 10411/10412/20411。全部外部 SIMULATED_FIRST，不新增真实外部请求。STT 暂停；视觉 NOT_RUN。本机账号填充沿用用户明确授权和既有安全边界，填入后仍需明确登录。未改变的 160 项业务依赖及 6 项认证/客户端/宿主源码由 inventory 核查，不重复执行无变化的领域全量检查。

当前八项开发覆盖与用户验收分别登记。准确入口与操作步骤见 experience.md，当前制品清单见 candidate-inventory.json。用户外观判断、真实外部模型质量、外部投递、独立安装及用户共同验收未执行。当前等待用户，其他业务保持暂停，不接续 FC06。
