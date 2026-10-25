# FC03晨间事项公共集成

## 任务身份与状态

task_id为FC03-N3，development_record为本文件。需求与验收依据为原始项目docs/FC03晨间事项工单.md中的FR-01、BR-01、AC-01-S/E及完整22项。唯一功能状态来源为原始项目specs/feature-delivery.json；完整候选编号以该来源为准，当前公共实现编号与制品摘要在public-progress.json登记。

FC03为IN_PROGRESS，N4完整22项尚未独立运行，分子null。公共流程已经实现，最终制品的公共业务、恢复、同库重启及DOM检查通过。文档CURRENT，last_verified为2026-10-24。FC02准确候选4d55773的20/20 PASS/GO及版本/制品确认保存在FC02 acceptance；FC04尚未启用。旧28项、23项及192点维持各自既有语义。

## 检索与正式输入

读取PRD第8.1节及共通权限/状态，HLD，LLD-data/backend/agent/frontend，交互O01/O02/O03/O07/O21和E01—E06，Desktop v6 F01 HTML、desktop/F01.txt及design-tokens.json。检索并核实TodayAPI、MorningAPI、ControlStore、正式维护输入、公共Page/Command、RoleChannel、实际SDK/Registry/Recorder、原生Client、F01及交办确认。没有使用视觉功能。

| 正式生产者 | 生产提交 | N3接收提交及采用内容 |
|---|---|---|
| N1领域 | e3faa5dcd90831d5e84e42c6ca66b418f85b767c | 03e3bb8；morning.schema.json 1.0.0、MorningAPI、逐日投影、正式覆盖输入、TodayAPI兼容入口 |
| N2执行基础 | 5aca0f3dee6202943c57d5c3b287e2640d4333fb | 1be9c68；可信范围、实际SIMULATED事件、SDK Hook及异常终态 |
| N2正式适配 | 42f949eda36b7bee4e5c5ece8da44e586fbd2b43 | 9172cbc；todayRead、morningListRead、morningDetailRead、morningSourceRead及清单/原文版本引用 |

N1逐日领域及相关消费者45项通过，原始报告为check.xml。N2正式组合8项、受影响基础消费者6项分别见formal-check.xml和consumer-check.xml。N2基础19项接收文件为agent-check.xml，生产目录原始路径为check.xml；不声称这两份不同生产者的报告具有相同内容。candidate-inventory.json核对生产提交中的九份关键领域/Schema/Agent文件与N3当前内容，并登记全部构建及执行输入摘要。

## 当前公共使用流程

本人进入F01后，业务日期和IANA时区由正式服务返回；日期编辑实际调用晨间预览，较早日期响应不能覆盖当前选择。预览不生成清单。不同日期按正式范围呈现会议、本人日历、承诺、任务、申请和经营事件，当前有效目标、规则、合并关系、期限和已有措施均来自N1投影。部分覆盖、未更新、未同步、缺少来源、结束时间未知和目标未确认保持各自说明。

本人提交晨间问题时，公共入口生成服务端session，并冻结真实认证主体、资料范围、日期、快照和本人次序。实际Nanobot SDK仅取得当前启用的四项晨间读取工具；维护配置必须明确启用这些工具及足够调用轮次。模型不能提供owner、namespace、dataset、本人排序或业务授权。清单通过实际todayRead→MorningAPI.query持久保存，后续清单、详情和原文读取采用相同list_id/list_version及来源版本。

结果展示三分类数量、逐项参与原因、处理人、期限、状态、排序理由、目标、已有措施、准备材料、冲突及来源覆盖。来源入口读取本次清单绑定的有效原文，显示作者、版本、发布/更新时间与原始位置。事项、来源选择和清单原编号保存在URL，关联会议返回、刷新和退出重登后根据当前权限重新读取。历史采用失效时，使用N1受限历史投影，清除私人正文、事项和派生时段，并要求重新查询。

本人调整完整事项次序并明确保存，通过正式list_id/date/timezone/snapshot/CAS及本人权限核查。排序仅改变当前业务日与时区下的本人次序；当前有效重要事项及新增对象继续按N1规则处理。晨间查询、覆盖载入与本人排序在原生Client连接恢复时均不重发。未知结果保留原编号，只读取原回执；未知排序继续禁止再次保存或改变日期。实际终态回执使页面恢复相应结果。

继续讨论显式绑定已选当前清单，实际SDK读取原清单及其依据；不新增晨间清单。准备交办进入F06的当前晨间事项核查和既有BR-C02本人确认。公共创建的可选morning_reference在同一创建事务中核查清单/事项/快照/来源，并保存与实际任务的关联。当前交办入口支持的来源必须属于选中事项；资料范围未满足时保持等待核查。准备、查询和排序不会自动创建、发送、批准或完成交办。

维护身份通过A04的正式晨间覆盖定义和载入动作创建独立SIMULATED覆盖资料，提供生成作者、版本、日期/时区和用途。原始资料时间保持；未更新和未同步地区分别呈现。载入没有真实企业资料、第三方授权、外部调用或本人业务授权声明。

## 代码与实际消费者

| 位置或identifier | 当前职责 |
|---|---|
| validation/public_morning.py、BossPageAPI | 严格单值日期参数、当前/历史清单、详情、原文、领域原回执、维护覆盖目录与载入回执 |
| validation/product_morning.py | 可信公共请求、服务端session、冻结读取范围、实际SIMULATED事件、SDK执行、原请求/运行/清单回执、历史与取消 |
| validation/product_bi.py、application.py | 共享Provider/Recorder按可信请求选择实际执行器；正式工具进入可用目录，维护配置决定实际启用集合 |
| validation/role_channel.py | 实际账号/会话控制下的晨间WebSocket动作、公共原请求与历史读取；身份期限和连接状态参与校验 |
| validation/boss_command_api.py | 正式维护覆盖载入；本人创建时核查morning_reference并保留当前任务关联；既有本人确认及发送边界继续采用 |
| app/webui/BossMorningView.tsx、BossToday.tsx | F01日期/问题、正式清单、详情/来源/准备材料、冲突、目标、分类、完整本人次序、原回执和异步/身份保护 |
| app/webui/BossMorningPreparation.tsx、BossAssignmentFlow.tsx | F06当前对象/来源读取、版本绑定、既有独立确认和当前交办来源范围 |
| app/webui/MaintainerMorningCoverage.tsx | A04正式定义、日期/时区、CAS载入、生成用途和原编号只读恢复 |
| specs/product-morning.openapi.yaml、runtime-records.schema.json | 公共请求/回执/历史与晨间引用规范；FC03运行仅记录安全ID、版本、配置、工具和来源引用 |
| validation/desktop/fc03_morning_proxy.py、check-fc03-morning.cjs | 中断真实成功响应的交付，核对仅一次转发、实际回执、页面、权限、Token与同库服务重启 |

运行记录保留request/session/run、配置与四项工具、morning_context、清单/事项/来源版本及实际异常终态。SIMULATED明确，未知usage/cost保持null；问题、标题、私人正文和凭据不进入普通运行或维护投影。

## 实际验证

| 场景 | 实际命令及原始证据 | 当前结果 |
|---|---|---|
| 公共接口与SDK组合 | pytest test_public_morning.py test_product_morning_runtime.py test_boss_command_api.py -k 'morning or create_is_atomic or conflicting_key or invalid_reference'；morning-public-combination-green.xml | 9 passed，3.69秒，14 deselected；涵盖四项公共晨间、两项实际SDK和三项既有创建消费者 |
| SDK/Schema/共享消费者 | pytest test_product_morning_runtime.py test_product_bi_runtime.py -k 'morning or actual_runtime_followup or refuses_untrusted'；morning-sdk-schema-and-shared.xml | 5 passed，12.03秒，2 deselected；实际取消、工具未启用拒绝、同键异内容、公共Schema、清单讨论/回执和两项经营查询消费者 |
| 共享FC01执行器 | pytest test_product_morning_runtime.py -k fc01_shared_dispatch；morning-fc01-shared.xml | 1 passed，3.58秒，3 deselected；三个实际服务同时注册时，当前FC01准备流程采用原有工具、执行器和Recorder |
| 公共最终检查 | pytest test_public_morning.py；morning-public-final.xml | 4 passed，3.28秒；公开读取/原文/历史、覆盖、本人排序、晨间交办引用Schema及无效主体/事项/版本拒绝 |
| 页面业务与故障交付 | node validation/desktop/check-fc03-morning.cjs；fc03-morning-64c57e60-ba28-4dac-8899-95f8d6f510f2.json | PASS；独立账号/SQLite/9951、9952、19951及9953代理；三项真实成功交付中断后各仅一次转发；原回执、刷新、未知排序、同库重启、原清单讨论和交办准备；三尺寸及200%稳定后无整页溢出；正文/原文16/24，辅助14/22，输入16；renderer错误零 |
| 工程 | .work/product/nanobot/webui：npm run build -- --outDir ../../../../fc03-n3-morning-dist；git diff --check | 严格TypeScript通过，Vite构建14.80秒；构建日志为.work/fc03-morning-build.log |

测试使用获准初始资料和真实公共维护动作。代理仅中断服务端真实成功结果的交付，未替换响应、制造业务记录、模拟接口或直接修改检查数据库。完整检查不使用视觉、截图或图像查看。N1/N2已验证且当前依赖摘要相同的领域/执行证据按准确输入采用，不重跑其全量或FC02完整20项。

## 构建与独立验收

当前独立制品为fc03-n3-morning-dist，manifest SHA256为42c2e226574ea2e13dbb432586cbd893d86a37db37c391184e5d0de53d881208，index SHA256为9c5c5e2cd05358cc9d8284794a40fb47c5237dd650f7f0ee9e6d0fb43e84f134。BossDesktop、BossAssignmentFlow和CSS与准备目录的实际构建输入逐字一致。三个新增准备模块通过显式export引用当前正式源码；BossMorningView进一步直接采用当前BossToday。完整输入、451份制品文件及九份生产者输入的SHA256由candidate-inventory.json登记，原生Client同时采用nanobot-one-shot.patch和nanobot-today-order.patch。

复现时使用文件编辑工具接收正式源码和上述输入，并以相同Node依赖、TypeScript/Vite配置执行记录中的构建命令；不执行会改写源码的准备脚本。validation/fc03_candidate_inventory.py只读取源码/生产提交/制品并写入JSON证据。候选需要原始功能状态中的准确commit、public-progress.json、制品目录及完整输入摘要共同核查。

N4须对准确完整候选独立执行全部22项及其异常/权限/来源检查。N3核对独立结果、代码、输入和制品一致后才能登记FC03通过并继续FC04。当前完整22项未宣称PASS；视觉、真实模型质量、外部送达及设备验收均为NOT_RUN，STT保持PAUSED，全部外部API为SIMULATED_FIRST。
