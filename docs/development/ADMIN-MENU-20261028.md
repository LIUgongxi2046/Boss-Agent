# 管理员菜单用途核查

任务ID：`ADMIN-MENU-20261028`。唯一状态来源：`specs/feature-delivery.json`。文档有效性：CURRENT。源码基线：`9cd9888490521242def326f475c93823a68ec95b`，当前包含未提交修改。

## 用户结果与依据

2026-10-28用户要求在管理员资料处理完成后检查页面的实际用途，允许隐藏没有用途的入口，明确举例访问权限限制。管理员资料的只读展示及两端对应检查已经完成，见 `SIMULATION-20261028.md`；本任务核对页面入口、实际消费者、可执行操作和重复入口。Boss端当前配置、数据、运行和菜单保持现有行为。

已完整读取开发接手与执行规范、当前状态、仿真主记录、S008及其任务记录与验证参考。允许修改管理员菜单配置、必要导航接收、相关测试和文档；保留Boss端来源、全部设计要求、权限校验及无关修改。无视觉检查授权，使用DOM和真实接口验证。

## 验收

| ID | 行为 |
|---|---|
| ADM-M01 | 当前管理员页面均有明确用途、实际读取及操作证据；隐藏范围采用当前产品需求与用户要求。 |
| ADM-M02 | 隐藏的入口不出现在管理员菜单与目录检索中；仍有用途的入口与关联操作可连续使用。 |
| ADM-M03 | Boss端菜单、权限、资料及运行配置保持一致；管理员只读展示仍然正常。 |
| ADM-M04 | 桌面采用合并后的当前制品，账号与资料继续使用原目录，源码、入口与摘要可核查。 |

## 当前状态

ADM-M01—ADM-M04已完成开发验证，管理员目录保留20项入口，当前桌面采用合并制品。用户验收保持待确认，视觉检查未执行，完整产品其他未完成要求保持原状态。

## 页面用途与实际接入

| 页面 | 用途与源码消费者 |
|---|---|
| A01、A12、A14 | `MaintainerConfiguration`读取access技术范围；`MaintainerMemoryStatus`读取记忆技术元信息；`MaintainerAudit`读取获准动作记录。服务端访问范围由`check_technical_access`继续核查。 |
| F25、A02 | `MaintainerSimulationCenter`读取当前资料、系统状态和操作记录；接口目录使用`BossWorkspaceView`及正式模拟接口目录，提供人工调用。 |
| A03、A04、A11 | `MaintainerDatasets`读取当前Boss资料及生成目录；`MaintainerSimulationEvents`读取当前任务、反馈、事件和注入记录；`MaintainerContactsWorkspace`读取联系人及关联事项。 |
| A05、A06、A07 | `MaintainerPromptVersion`读取当前运行配置及自定义Prompt；`MaintainerSkillVersions`读取SOP与实际采用；`MaintainerKnowledgeWorkspace`读取知识来源和检索。 |
| A08、A09、A10、A13 | `MaintainerModelConnections`读取模型连接；`MaintainerConfiguration`读取tools；`MaintainerMetricsConfiguration`读取指标；`MaintainerScheduler`读取现有事件及正式调度配置。 |
| N12、A15、A16、F32、NATIVE | `BossRuntimeOverview`读取服务及运行概况；`MaintainerRuntimeRecords`读取模型与工具运行；`MaintainerEvaluation`读取实际运行及正式评测；`MaintainerLocalSystem`读取本机运行与交接；NATIVE保留应用设置。 |

隐藏N01、D08、D06、D07、F30、F31。认证和提示由对应流程显示，F30由运行记录进入，评测集中由A16访问。隐藏仅设置管理员导航的`directory=false`，合法直接页面、角色权限、未保存保护与服务端认证保持。Boss目录及全部业务页面未修改。

## 实施与验证

Given当前认证的MAINTAINER，When展开菜单及检索页面，Then六项隐藏入口均不显示，20项维护入口可以进入。Given当前认证的BOSS，Then五项主入口和原有合法关联页面保持一致，管理员页面仍然拒绝。

正式策略由`specs/menu-plan.json`提供，`delivered-navigation.ts`读取该策略，`scripts/prepare_boss_webui.py`将同一配置纳入构建。7项目录、完整路由及React输出检查通过，日志为`.work/simulation-20261028/admin-menu-unit.log`；5项真实浏览器跳转与History检查通过，日志为`admin-menu-routing.log`。严格TypeScript及Vite构建通过，日志为`admin-menu-tsc.log`、`admin-menu-build.log`；正式菜单配置与生成目录文件内容相同。

独立9092实例通过真实登录完成20项菜单进入、F30详情进入及返回、七项管理员资料页与四项Boss页面，共32项DOM检查；六项隐藏入口不能从目录检索，页面无脚本错误及横向越界。证据为`admin-ui-evidence.json`、`admin-menu-ui.log`。读取前后的完整业务对象摘要相同，实际Boss任务及管理员编号、标题、状态、期限、版本逐项一致；接口与权限结果见`admin-http-evidence.json`。

## 桌面版本与连续操作

当前制品为`.work/simulation-20261028/admin-dist`，`index.html` SHA256为`acc1f0018b16132edbe9757253e284eb49e79d3abdfd8f5f9027f5ba6c65bcc8`；216项源码与449项制品文件清单见`.work/simulation-20261028/admin-release-manifest.json`，清单SHA256为`dbb732ccadd421ad3b7f444f58a128903d8a57b9c658e3f15fad3b55f738dfb8`。采用正式桌面宿主及原来的资料、账号、桌面配置目录，启动入口为`bash scripts/run_comprehensive_simulation_local.sh --desktop`，桌面与WebUI入口共享端口，使用其中一个入口启动。

更新时确认在途Agent数量为零，通过原窗口关闭按钮执行正常关闭，应用自身未保存编辑保护继续生效。当前桌面PID34333、后端PID34342；正式生命周期记录`window_loaded`时间为`2026-10-28T03:04:32.275Z`。桌面已显示在前台，实际9082响应摘要与当前制品相同。原9072的PID93733及前端摘要保持一致。

当前桌面9082通过两端资料、运行配置、最近50项真实运行、角色隔离和私人正文隔离检查，见`.work/simulation-20261028/admin-desktop-http-evidence.json`。重新启动及检查前后业务对象摘要仍为`39cca01f76203ebb37cd88ac49f03be04654c92bfad9b9d463060bcec2c108b6`。没有创建业务事件、启用配置或执行新增模型请求。

使用现有MAINTAINER账号进入管理端：在模拟中心查看当前资料，进入A03核查明细，A04核查任务及反馈，A05读取当前运行配置，A13核查事件与期限，A16查看已有真实运行；从A15选择记录可进入F30并返回。目录和搜索均采用20项维护入口。Boss端继续使用原账号与五项主菜单。
