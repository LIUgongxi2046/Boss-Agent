# 正式经营边界与双方口径的公共采用

## 任务身份

task_id：FC02-N3-BOUNDARY-ADOPTION。需求为FC02.C05/C08/C11，以及受影响的C01/C02/C03/C10/C12—C19。唯一功能状态来源为原始项目specs/feature-delivery.json。文档CURRENT，last_verified为2026-10-24，依据当前源码、实际接口、SDK、桌面行为及同一构建制品。

当前公共实现与必要本地验证已完成，完整FC02保持IN_PROGRESS。N4对faf66bf6c718b032e20a94231989894367a258c4独立确认16/20、BLOCKED；准确记录保存为independent-faf66bf.json。当前候选需要N4独立验证全部二十项；本地用例数量不作为功能分数。

## 检索与输入依据

读取当前FC02工单、integration.md、history-recovery.md、async-recovery.md、开发索引、N1 backend.md及N4 verdict.json；核对BossBIView、ProductBI、Page/Command、当前维护页面、正式Schema与构建输入。读取N1的9f44a1d4cb247c90afd5d7df5c8f9d62f884c7d3、2731df3fb9a6f6ffc405846a301505f0141ff1d5，接收为f515905和4e6b8d6，保留已有comparison_scope、明确overrides及历史/异步保护。

正式生成器FC02-BI-1、seed20261024、用途FC02_BEHAVIOR_VALIDATION，提供weighted-ratios、zero-denominators、missing-numbers、delayed-records、unsynchronized-records、basis-conflict。默认selection/1资料保持原始摘要。生成资料明确SIMULATED_GENERATOR、允许用途、来源版本、有效期、本人范围，real_enterprise_data及third_party_authorization均为false。

## 当前功能与实现

| 文件 | identifier或入口 | 当前职责与使用方 |
|---|---|---|
| validation/public_bi_scenarios.py | loaded_scenarios / dimension_options | 从当前SQLite和来源读取场景、作者、用途、有效性及来源选项，提供公开只读投影 |
| validation/boss_command_api.py | boss.simulation.bi_scenario.load | 真实MAINTAINER调用正式BIScenarioAPI；载入不注册为模型工具 |
| validation/boss_page_api.py | /api/boss/ui/admin/bi-scenarios、/bi-scenario-receipt | 维护目录及原请求回执；严格角色、参数检查；D01保留来源实际作者和用途字段 |
| validation/product_bi.py | /api/boss/ui/bi/scenarios、/bi/dimensions | 本人读取已载入场景、明确来源与正式维度，沿用可信请求和受限Runtime |
| validation/boss_bi_queries.py | BIQueryAPI.dimensions | 接收正式scenario_id/source_ids，明确来源过滤后调用同一query_inputs |
| specs/bi-query.schema.json | bi_follow_up.overrides | 接收正式场景及来源字段；保留既有明确覆盖与比较字段 |
| specs/product-bi.openapi.yaml | 0.3.0 | 公开目录、列表、回执、维度、来源和载入动作规范；连接恢复不重放载入 |
| app/webui/MaintainerBIScenarios.tsx | A04 | 目录、CAS版本、正式载入、原请求编号和只读恢复；未知结果期间禁止第二次载入 |
| app/webui/BossBIView.tsx | F03/N03 | 实际场景和来源选择；当前身份、来源维度与查询快照一致；保留历史和异步保护 |
| app/webui/BIBasisComparison.tsx | 不同口径并列 | 用户分别保留两项正式查询，各自读取原文、原始值、来源、作者、用途和采用状态；URL持久编号 |
| app/webui/BossDesktop.tsx、boss-v6.css | A04/F03/N03/D01 | 当前维护入口、原文作者投影、正文Token和尺寸响应 |
| app/webui/nanobot-one-shot.patch | PendingWebUIRequest / handleOpen | 原生Client保存action；仅场景载入在连接恢复时拒绝重发，提示读取原回执 |

本人选择不同场景后创建明确的新查询意图；选择同一场景中的另一口径与来源后按已有FOLLOW_UP执行，保留真实父查询及明确覆盖字段。来源维度始终由正式资料生成；财务来源撤销后仍可明确选择有效业务来源。既有历史值、原请求、来源失效和身份清理行为保持。

并列入口最多保留两项查询，通过各自query_id读取持久结果及当前来源。条件相同时明确表示双方口径；条件不同时提示核查期间、指标和范围。客户端显示原始Decimal字符串，全部业务计算由正式工具执行。失效历史保留原值并要求重新查询，当前正文不再采用。解释与讨论的task/authorization/outbox数量均为零。

## 决策与约束

维护载入使用真实角色、当前namespace/owner/dataset、CAS、幂等、SQLite事务及正式生成器。未知结果只按原client_request_id读取回执；实际Client重连不再次转发该载入动作。回执缺失保持未知，界面不自动创建新的载入意图。

业务Runtime继续仅开放query_metrics/read_evidence，实际SDK、Registry和Recorder采用当前冻结参数。模型不决定本人范围、来源有效性或授权。正式SIMULATED事件消费本次实际工具返回。全部外部API为SIMULATED_FIRST，usage和cost_total为null；视觉、真实模型质量、外部投递及设备安装NOT_RUN，STT暂停保持。

## 验证与证据

| 验收 | 实际输入与操作 | 真实结果 | 证据 |
|---|---|---|---|
| C01/C02/C05/C08/C11/C13/C16 | 正式目录与六场景；真实SQLite、MAINTAINER/BOSS/匿名；实际SDK查询及来源过滤 | 24项PASS，含18项正式场景和6项公共消费者 | evidence/feature-delivery/FC02/boundary-consumers.xml |
| 公开输出规范 | 目录、已载入列表、默认与场景维度、RECORDED及NOT_FOUND_IN_CURRENT_STORE；实际返回通过JSON Schema | 6项PASS；公共消费者含Schema验证 | evidence/feature-delivery/FC02/boundary-output.xml |
| C05/C08/C11/C14/C15/C16/C17/C18 | A04正式载入六场景，真实载入响应形成后中断连接；只读原回执；本人执行七项查询及两项口径并列、刷新、D01、十八组尺寸 | PASS；载入仅转发一次；毛利率14%；零分母null；缺少利润null；延迟/未同步地区region-1；双方收入100/120；7查询、7运行、6场景、零业务写入、零renderer错误 | evidence/feature-delivery/FC02/fc02-boundary-176212af-9f94-49fc-891f-04f8a7441691.json |
| C10/C12/C14/C15/C18 | 正式来源撤销、同库独立服务重启、历史与原请求、刷新、自然身份失效/重认证、退出、维护403、十二组历史尺寸与键盘 | PASS；原编号/原值保持，失效正文不采用 | evidence/feature-delivery/FC02/fc02-history-3984d0c8-83cb-4c2e-bc37-0307b28ab841.json |
| C03/C15 | 实际HTTP响应延迟，较早依据及初始回执在新查询或编辑之后交付，核对前后字节摘要 | PASS；用户新范围与新查询保持 | evidence/feature-delivery/FC02/fc02-n3-timing-719b2fd4-0c29-4963-bdb8-95fe8532894e.json |
| 工程及规范 | 严格TypeScript/Vite构建、标准OpenAPI3.1及YAML重复字段检查、git diff --check | PASS；构建15.14秒 | .work/fc02-boundary-build.log、validation/check_bi_public_spec.py |

Red来源为真实公共目录尚未接收与载入动作尚未接收的失败断言，见boundary-public-red.xml；当前Green为boundary-public-green.xml。上述证据均来自真实服务、账号、数据库、当前正式生成器与实际SDK，不替代N4的独立功能判定。

公共测试命令：validation/.venv/bin/python -m pytest app/tests/test_product_bi_scenarios.py app/tests/test_product_bi_runtime.py app/tests/test_fc02_bi_scenarios.py -q -p no:cacheprovider --basetemp=.work/pytest-fc02-boundary-consumers --junitxml=evidence/feature-delivery/FC02/boundary-consumers.xml。新增返回规范检查运行前两份测试，证据为boundary-output.xml。

桌面命令使用BOSS_PRODUCT_FRONTEND_DIR的本目录绝对路径fc02-n3-boundary-dist，分别运行node validation/desktop/check-fc02-boundary.cjs、check-fc02-history.cjs、check-fc02-timing.cjs。独立数据分别保存在validation/.work/fc02-boundary-176212af-9f94-49fc-891f-04f8a7441691、fc02-history-3984d0c8-83cb-4c2e-bc37-0307b28ab841及对应timing目录。端口分别为9841/9842/19841/9843、9761/9762/19761、9751/9752/19751/9753。没有操作用户预览或其他角色进程。

## 构建与一致性

制品fc02-n3-boundary-dist，manifest SHA256为633f8825cd5e62d2e2f5302e8b1ecd3df5cb1619bfcea10015e6cb404570b411，index SHA256为8418c85706ae46de4c34896339eccd45b4c8af0f24850a9da9fcf2d45e84bfd6。五份正式前端文件与.work/product/nanobot/webui/src/boss-agent对应输入逐份摘要相同。

全新构建必须通过文件编辑工具将五份正式文件更新到当前nanobot构建输入，并在项目根目录使用apply_patch < app/webui/nanobot-one-shot.patch。该patch只适用于尚未包含相同修改的原生Client；当前已应用，不能再次应用。原生Client SHA256为48ae362a2d6ae0a3d817765a4e34459c3b77255e70bebd0205b7403c2fbe5527，patch SHA256为98137a7b05abecf3ace02cff41d03f0243e248de898376727075a9765edadbcd。在.work/product/nanobot/webui执行npm run build -- --outDir ../../../../fc02-n3-boundary-dist。

N4可以核查上述准确制品及源码摘要后使用独立副本；新的构建需要包含原生Client修改。候选摘要登记全部源文件与制品摘要。

## 关联影响与继续条件

当前场景输入已由N1正式提供并由公开消费者接收，N2实际两项工具可直接消费，未修改N2专有文件。当前24项与新增Schema六项仅覆盖实际变化；FC01及无变化业务全量没有重复执行。已有74项证据适用9026c8a，N4曾在301项依赖核对后用于faf66bf；当前正式Schema、领域输入及公开消费者已有变化，必须由N4核查新候选适用依赖，不能直接将旧16/20登记为新候选分数。

独立功能判定保持PENDING_CURRENT_CANDIDATE。N4在准确提交独立确认20/20 PASS，N3核实提交与制品一致后自动启用FC03；此前保持FC02活动。

