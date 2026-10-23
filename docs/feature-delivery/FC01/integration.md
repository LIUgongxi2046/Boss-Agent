# FC01 公共集成开发记录

task_id：FC01-N3；需求：FR-14/21/06/28/29；验收：FC01.C01—C18。
状态来源：原始项目specs/feature-delivery.json；当前FC01限定ACCEPTED。N4对c4bc67355611bc019f3fa1ab5e6fee19e8b2af10判定18/18 PASS/GO，N3已核实集成版本及制品摘要一致，结果保存于acceptance.json。视觉NOT_RUN；当前功能已推进FC02。

## 当前代码与依据

2026-10-23 接收 9bd2f9f 为 bb2b7a6、daedc63 为 a989c6b、N2 ebc9035 为 3096a1e、N1 eda67b6 接收记录为 8315b09；保留全部 read-scope 内容及停止交接。已读取当前计划、工单、状态、W3 停止交接、S008 规则，检索当前 PRD/HLD/LLD、公开组件、工具及 T11 索引。历史 869 项结果仅适用已提交 1.7.0。

## 当前实现与约束

入口：真实登录、A03 明确导入、F14/F21 查询及协调、F06 发送反馈和本人完成。外部请求保持 SIMULATED_FIRST，本地业务服务及 SQLite 真实执行。模型字段和维护身份不能替代本人决定。公共入口由 N3 维护，领域及 Agent 接收准确提交。不操作默认预览端口及数据，不终止其他进程；中间结果使用忽略的 .work 与 validation/.work。

## 验证与证据

读取、运行配置、成本与公共采购品质检查 52 passed，命令为 validation/.venv/bin/python -m pytest app/tests/test_product_read_scope.py app/tests/test_product_runtime_configuration.py app/tests/test_boss_material_cost_reports.py app/tests/test_product_supply_quality.py --basetemp=validation/.work/fc01-n3-read-cost -q -p no:cacheprovider --junitxml=evidence/T09/w3-20261023/fc01-read-cost.xml。新增期间筛选接收后另执行成本及模拟查询的直接回归 91 passed，入口 test_boss_material_cost_reports.py、test_boss_simulation.py、test_boss_simulation_api.py；证据 evidence/T09/w3-20261023/fc01-report-filters.xml。
BossResearchSourcesTool 在准备阶段限定 research，执行阶段独立拒绝非研究投影；实际 SQLite 内容保持不变。独立前端目录选择及范围拒绝检查另有 2 passed，入口 app/tests/test_product_frontend_directory.py。
实际 React、领域及 SQLite 组件检查通过七类行为：库存计算、两类报告成本、协调填写、本人确认控制、保存重读、专业状态独立及来源变化拒绝采用。证据 .work/fc01-n3-cost-components/result.json。命令使用 NODE_PATH 指向本工程 .work/product/nanobot/webui/node_modules，执行 node evidence/T12/verify_supply_quality_ui.mjs 及绝对依赖目录、输出目录参数；认证通道和视觉不属于该组件结果。

## 独立构建及运行入口

当前C15修复制品完成TypeScript/Vite构建，16.13秒；命令在.work/product/nanobot/webui执行npm run build -- --outDir ../../../../fc01-n3-c15-runtime-dist。制品位于本工程fc01-n3-c15-runtime-dist，原runtime-dist和默认预览保留；日志.work/fc01-c15-build.log。产品与构建输入CSS摘要均为3078c4dc678513f488050dae3c9b15dec07dbc57cce97fe69c7237f4ff7609da。固定上游保持nanobot 1bb712d3488915ca4ed9ccc1a93067ff722f5ab9、nanobot-ai 0.3.5；没有安装或更新依赖。
当前index.html SHA256为06918aeef643bc4fef211bf3143709fdf4d44ec8d71113a5816a225eff6d46a7；asset-manifest.json SHA256为b35ffd1880cfc1ad42d1626b6e3c6bd5115977ef741b726b725e52905b258d8c。C15定向记录见[正文Token](body-tokens.md)。原06d5c30的业务证据绑定其原runtime-dist摘要2ed4feb29e03162f3ff2c5580d3379c55d71284933c8afaaab1b0df6442b665e，按不变业务依赖保留，不能将旧制品摘要用于新CSS候选。
运行时 BOSS_PRODUCT_UI=1，BOSS_PRODUCT_FRONTEND_DIR 使用候选检出下独立构建绝对路径；BOSS_APPLICATION_WORK_DIR 使用候选检出下 validation/.work/fc01-qa 的绝对路径；BOSS_APPLICATION_PORTS 使用 business=9371、webui=9372、gateway=19371。实际启动入口 validation/application.py；本机账号通过 scripts/provision_boss_accounts.py --directory <独立数据目录>/accounts 建立。新增独立数据配置包含 maxToolResultChars=200000；已有配置不会被自动改写，准备准入会检查完整投影实际长度和当前容量。不得使用默认预览数据。产品模式实际采用 Fc01SimulatedProvider，没有外部网络客户端；STT继续暂停。

## 接收与后续条件

N1 确认 9bd2f9f992014c7760b751afaacbf2ea0e2af1a7 为领域 1.8.0，新增授权消费文件尚未验收，当前没有接收这些未提交文件。N2 当前专有适配已经接收，完整功能仍待N4独立判定。
F14/F21 通过正式 SimulationAPI 提供原料、产品、法人、资产/成本归属、批次、客户、币种和期间筛选。筛选原始记录与完整库存计算分别标明，当前结果变化后不展示旧筛选记录。
真实认证隐藏桌面检查 PASS：evidence/T11/w3-local-20261023/supply-quality-4707e9e1-1fa8-425f-9db7-d3f283696ec1.json。覆盖维护 SUCCESS/EMPTY/FAILED/TIMED_OUT 导入及撤销、角色拒绝、筛选与键盘提交、不完整期间、D06、协调未知结果和原请求恢复、实际发送反馈与本人完成、重启、来源更新与撤销、三种尺寸及200% DOM范围。运行命令使用 BOSS_PRODUCT_FRONTEND_DIR 指向本工程 fc01-n3-filter-dist、BOSS_APPLICATION_PORTS 为 business=9071/webui=9072/gateway=19071，执行 node validation/desktop/check-supply-quality.cjs。所有进程与数据由该检查独立建立，检查退出时关闭自身进程；模型请求和外部投递为零，视觉 NOT_RUN。
## 公共Runtime与本人采用

validation/product_fc01.py 使用真实 RoleChannel 认证连接、当前令牌、到期时间及退出状态生产准备请求。请求Schema实际消费 specs/product-fc01.openapi.yaml。协调字段与来源摘要在启动前形成 input_bindings；工具消费该冻结内容，模型参数不能签发新绑定。产品配置显式允许十八项目录，默认启用范围保持原五项。准备需要维护通过正式保存、校验、启用接口选择四项FC01读取准备工具及至少五轮；公开检查使用原五项加四项FC01工具、六轮、700输出Token。本人决定和发送授权均不注册为模型工具。
模拟事件依次消费 bossSupplyQualityRead、bossSupplyQualityQuery、bossEvidenceRead、bossSupplyQualityPrepare 的实际返回，再给本人表单准备结果。准备阶段任务、授权与发件均没有新增。F14/F21通过本人按钮采用同一准备请求与内容；真实领域再次检查当前来源、负责人、期限、CAS及幂等，正式任务关联保存到原运行 owner_task_links。公开运行任务读取接口及维护详情实际消费该关联。D06保护准备内容和未知请求；原准备状态查询不启动第二次Runtime，失败、取消及超时使用原运行终态。配置启用、模型执行、本人采用和专业状态分别维护。
RuntimeRecorder公共扩展保留配置、工具Schema/实现摘要、模拟模型事件、来源版本、准备摘要和任务关联；用量和费用保持null。维护运行详情明确显示SIMULATED。原文、目的正文、凭据及模型回答不进入技术运行记录。未知写入继续通过正式领域原请求回执恢复。

## 本批有效验证

- ebc9035适配在本目录1.8.0组合执行：32 passed，证据 fc01-runtime-combination.xml；当前公共读取、运行配置、采购品质与独立制品路径34 passed，证据 fc01-current-public-regression.xml。
- 成本及品质来源分别进入实际Runtime并由本人采用，含正式任务关联读取：4 passed，证据 fc01-public-runtime-links.xml；两类报告成本2100/2150与实际准备均核实。Schema直接检查16 passed，证据 fc01-public-schema.xml。以上XML均位于 evidence/T09/w3-20261023，检查范围存在交集，不合并为功能分数。
- 四份公共OpenAPI扩展通过标准3.1及YAML重复字段检查，入口 validation/check_fc01_public_spec.py，执行环境 .work/openapi-venv，结果 .work/fc01-public-openapi.log。公开Schema为product-fc01/product-runtime/product-auth/product-skills，核心接收1.8.0。
- 最终实际认证Runtime/准备/本人采用/D06/Token检查PASS：evidence/T11/w3-local-20261023/fc01-runtime-e667c8cd-29d5-441d-85ce-0ca08f2d81a0.json。入口 validation/desktop/check-fc01-runtime.cjs，独立9371/9372/19371与自动新建账号及数据。
- 当前采购品质导入、筛选、未知请求、发送反馈、本人完成、重启、来源撤销及三种尺寸和200%检查PASS：evidence/T11/w3-local-20261023/supply-quality-9a690268-c79b-4fd6-8d6d-1eda4e789acc.json。入口 validation/desktop/check-supply-quality.cjs，独立9071/9072/19071。
- 共享文字样式变更的70个页面、72次角色与页面组合DOM检查PASS，renderer异常为零：evidence/T09/w3-20261023/page-dom-cf87b74e-4714-45b5-bb68-7d0261f4a6d1.json。入口 validation/desktop/check-pages.cjs，独立9471/9472/19471。业务动作及561状态不由该读取检查验收。

## 独立验收继续条件

N4对准确候选c4bc673已给出C01—C18全部PASS/GO，18/18、100%，没有当前缺陷或阻止限定功能交付的条件；原始判定、preflight-c4bc673.json、body-tokens-c4bc673.json及verdict-consistency-c4bc673.json位于N4目录。N3核实当前集成HEAD、CSS及制品manifest一致，签收记录见[限定验收](acceptance.json)。十六项业务证据按不变依赖复用，C15实际独立复验，未重复业务全量检查。当前工单为原始项目docs/FC02经营查询工单.md，active_feature_id推进FC02。视觉、真实外部模型质量、外部送达及设备安装均NOT_RUN；旧28项父任务与192点保持原语义。read-scope的A08模式选择及完整维护恢复范围保持原独立验收责任。
