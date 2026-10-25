# FC02-N1 经营查询领域

状态来源：原始项目 specs/feature-delivery.json 与 docs/FC02经营查询工单.md；当前 FC02 IN_PROGRESS，完整二十项等待同一候选独立验收。

2026-10-24 接管基线 eda67b6，原有五项未提交内容保持。检索 T13、FR-03、BR-C02/C03/C04、query_metrics/read_evidence、boss_metrics、当前正式工具 Schema 与来源绑定。采用 S008，继续限定业务目录和正式领域规范；公共入口与全局索引由 N3 维护。

现有 Decimal 聚合、基线比较和当前来源绑定复用。必要补充为正式范围查询、可比性及未知覆盖、幂等请求、持久上下文追问、当前与历史重读及查询回执。新范围通过 query_mode=SCOPED 明确进入，既有输入保持兼容。正式 Schema、实现及证据随当前任务更新，不扩大本人授权。

当前工作对应 FC02.C02—C15 与 C19 的领域部分；真实账号、公共 UI/Runtime 及独立组合验收由 N2/N3/N4 在同一候选核查。所有外部能力 SIMULATED_FIRST，视觉未执行。

## 版本与接收文件

领域主体提交 fe3010563c6986eff6f0c26c1b5b2554d061cff6；当前同一任务补充归属比较和本记录，最终补充提交由当前分支后续 commit 标识。原有 docs/LLD-backend.md、docs/development/T14.md、app/tests/test_boss_authorized_execution.py、validation/boss_authorized_execution.py、SESSION-HANDOVER-W1.md 不进入接收内容。

必须接收 validation/business.py、boss_metrics.py、boss_bi_queries.py，specs/bi-query.schema.json、business-tools.schema.json、openapi.yaml，以及 app/tests/test_fc02_bi_queries.py。本次没有变更 selection 初始快照、现有来源正文、业务数据或公共入口。

正式 Schema 使用 business.SPEC.io_schema：原 selection-probe 定义、business-tools 扩展及 bi-query 扩展组合，保留 legacy_query_input/output。bi-query.schema.json 为明确的组合扩展，不能脱离基础定义独立解析实例。Tool Registry 使用同一组合，query_input/query_output 采用 oneOf 保留既有输入兼容。N2 已依据该正式定义准备 SCOPED 消费，公共打包必须包含新模块及 Schema。

## 输入、继承与输出

`Store.invoke("query_metrics", payload)` 的新正式输入通过 `query_mode="SCOPED"` 选择，其他旧输入继续原有行为。`BIQueryAPI.query("BOSS", payload)` 仅接收正式 SCOPED 输入。envelope 由公共真实认证提供，模型不能自行填写 owner/namespace/dataset；领域校验当前 active 空间及 boss-1、selection/1。查询没有本人授权签发能力。

必填字段：query_mode、envelope、question、metric_ids、region_id、product_ids、legal_entity_id、period_start、period_end、comparison_start、comparison_end、currency、quantity_unit、trade_scope、definition_version、business_basis、settlement_state。

可选字段：region_ids、customer_id、ownership_type、asset_owner_id、cost_owner_id、target_version、comparison_scope、parent_query_id。region_ids 需要包含 region_id。comparison_scope 只覆盖比较方业务维度；比较期间仍使用 comparison_start/end，不接受被忽略的期间或指标字段。归属和目标未知保持 null；不得根据法人、联系人或模型推断归属。

当前获准定义及可用维度由 `BIQueryAPI.dimensions("BOSS")` 实际读取，包含 available_dimensions、periods、metric_definitions、source_id/source_version、PARTIAL 和缺少范围。现有资料为 region-1、product-1/2、entity-1、CNY、tonne、EXTERNAL_SALES、definition_version=1、SELECTION_REPORTED、SETTLED。未知目标及归属不填默认事实。语法合法但没有相符资料的筛选返回 UNAVAILABLE 和 null，不复制原范围数值。期间必须完整且起止顺序有效；不进行未获来源支持的币种或单位换算。

输出保留 query_id、envelope、values、detail_refs、sources、missing_fields、unexplained_causes；新增 context_snapshot、coverage、comparison、parent_query_id、overridden_fields、source_type、queried_at。values 继续包含 BASE/CURRENT/CHANGE、Decimal字符串或null、unit、formula、definition_version、display_rounding。未知定义的公式为 DEFINITION_NOT_PROVIDED。原始值使用十进制字符串，展示舍入不能覆盖原值。

coverage.state 为 PARTIAL/UNAVAILABLE；periods 保留每个期间的 record_count、已观察地区及起止日期；missing_regions 表达本次选择但缺少的地区。delayed_regions/unsynchronized_regions 在资料没有同步属性时为 null，不能将空列表表达为已经核查没有延迟。未知同步情况同时写入 missing_fields。资料明确提供 DELAYED/UNSYNCHRONIZED 时保留对应范围并停止全范围变化结论。

comparison.state 为 COMPARABLE/INCOMPARABLE/INSUFFICIENT_EVIDENCE，reasons 保存不相容字段。单位、币种、法人、交易、定义、目标、口径、结算、归属、地区、产品、期间时长、重叠期间及覆盖逐项检查；条件不相容不计算 CHANGE。毛利率变化使用百分点，其余使用百分比。零分母/零基期返回 null 并保留未定义原因。混合不相容资产/成本归属不能产生合并总量；原明细仍可查看。

## 持久追问与重读

| 入口 | 输入 | 当前行为 |
|---|---|---|
| BIQueryAPI.follow_up | BOSS、bi_follow_up：envelope、parent_query_id、question、overrides | 读取正式父查询快照，仅指定字段覆盖；服务端再次核查同一会话与当前来源，产生匹配新 query_id |
| BIQueryAPI.read | BOSS、query_id、historical=false | 返回 bi_read：adoption_state=CURRENT、result；当前来源、明细或定义变化时拒绝采用 |
| BIQueryAPI.read | BOSS、query_id、historical=true | 原查询结果和来源版本保持，状态为 HISTORICAL_CURRENT 或 HISTORICAL_REQUIRES_REQUERY；没有返回旧来源正文，当前来源权限变化仍拒绝 |
| BIQueryAPI.receipt | BOSS、session_id、request_id | 返回 bi_receipt；RECORDED 包含原查询历史投影；NOT_FOUND_IN_CURRENT_STORE 保持结果未知，不重新执行 |
| Store.invoke/read_evidence | envelope、query_id、source_ids、detail_refs | 核查实际当前绑定，读取匹配明细及原文；无明细结果允许空 detail_refs，仍可打开对应来源；拒绝交叉查询和重复明细 |

查询、不可变 query_source_binding 和 bi_query_receipt 在同一 BEGIN IMMEDIATE 事务保存。回执键为 namespace/session_id/request_id，完整 payload 摘要不一致拒绝；并发相同请求只产生一个查询。绑定包含 owner/dataset、来源版本/完整摘要、明细摘要、指标定义摘要及当时原文/明细快照。读写后重建 ControlStore/BIQueryAPI 继续读取同一对象。退出、刷新、取消和超时的公开生产者由 N3 保留原请求编号，不得自动产生第二次意图。

源 document、业务时钟、当前授权范围沿用实际服务；来源变更、失效、撤销或定义/明细变化后，当前正文与采用拒绝。历史原值和回执保留其当时版本，不用当前资料补造旧绑定。财务/业务口径分别通过明确业务范围呈现，冲突字段保留；原因缺少时只列材料需求，不根据职位或已有基线推断。

## 验证

- Red：`.work/fc02-domain-red.xml`，9 failed；合法 SCOPED 输入被原 Schema 拒绝，原 Decimal 聚合未保留长小数。运行入口为本目录 validation/.venv/bin/python -m pytest app/tests/test_fc02_bi_queries.py，所有 basetemp 位于本目录已忽略的 .work。
- 当前受影响回归：`validation/.venv/bin/python -m pytest -q app/tests/test_fc02_bi_queries.py app/tests/test_boss_metrics.py app/tests/test_boss_tool_sources.py app/tests/test_boss_simulation_api.py app/tests/test_boss_supply_quality.py::test_actual_nanobot_registry_publishes_current_schema_and_reads_coordination_task --basetemp=.work/pytest-fc02-handoff -p no:cacheprovider --junitxml=.work/fc02-handoff.xml --tb=short`，155 passed，15.84秒。该结果适用未知同步字段修订后的代码。
- 随后未知定义公式的必要复验：`.work/fc02-definition-final.xml`，20 passed，1.36秒。当前归属比较补充的必要复验使用 `.work/fc02-scope-final.xml`，21 passed，2.24秒；该结果适用于当前最终领域代码，其他155项证据按其实际版本与范围复用。
- 覆盖明确基线独立复算、范围变化未知、期间不可比、比例重新汇总、长Decimal、身份与来源拒绝、同键冲突、并发单次查询、追问字段继承、独立 SQLite 重读、当前原文匹配、来源撤销后的历史回执、定义版本变化和真实 Registry 的正式 Schema。
- OpenAPI3.1/重复字段检查通过：`.work/design-venv/bin/python evidence/T06/validate_openapi.py`；git diff --check 通过。没有运行无变化FC01全量检查、外部API或视觉，没有启动或操作其他进程。

## 接收与必要剩余

N2 在空闲状态已收到 fe30105 和正式接口，继续接收其独立 BI Runtime 检查；N3 运行时仅只读，不发送追加消息。统一索引由 N3 添加 FC02-N1 对应本记录。后续以 N3 准确组合候选及 N4 实际失败定位继续领域修复。

公共 authenticated envelope 生产者、F03/N03/D01 全部字段/继承显示、原请求管理、账号与连接恢复、Client/Provider 和 Runtime 采用由 N2/N3 接收。现有字段、来源、明细和定义均来自真实本地服务，外部输入明确 SIMULATED；完整专业业务数据、真实外部模型、视觉及设备不在本记录声明通过。

当前状态为领域 IMPLEMENTED、已提供可接收提交，完整 FC02 仍 IN_PROGRESS。不能将155项测试数量计为二十项功能检查点，也不关闭旧父任务或启用FC03。

## 正式边界输入接管

2026-10-24，依据 N1-FC02-BOUNDARY-INPUTS-20261024-0407，读取 N4 的 boundary-inputs-9026c8a.json、最新 FC02 工单及候选 faf66bf 的适用差异。当前分支基线4bcb0a9，原五项未提交保留。C05/C08/C11需要正式可复现的模拟经营资料和双方来源；本次补充范围为固定版本的经营场景生成/载入、当前查询选择、来源绑定及相关本地验证。默认 selection/1 八条明细和快照保持；维护载入仅创建模拟资料，不产生本人业务授权。公共注册、配置和页面由 N3 接收，运行期间不发送追加消息。

### 当前可接收交付

领域提交 `9f44a1d4cb247c90afd5d7df5c8f9d62f884c7d3`，基于4bcb0a9。接收九文件：validation/boss_bi_scenarios.py、boss_bi_queries.py、boss_simulation_api.py；specs/bi-scenarios.json、bi-scenario-input.schema.json、bi-query.schema.json、openapi.yaml；app/tests/test_fc02_bi_scenarios.py；docs/LLD-data.md。本记录随后独立提交。原五项未提交内容保持，不进入接收。

生成版本 FC02-BI-1、seed=20261024、allowed_use=FC02_BEHAVIOR_VALIDATION，规范JSON参数摘要da40102d4d942b8d6c5cbf80a9e81d197df810eec8f1ee5edd1b6585293ea136。seed标识固定可复现参数，生成器不执行随机采样。specs/bi-scenarios.json保存明确数值与状态参数，没有预设查询答案。记录由成熟JSON读取、JSON Schema校验、现有SQLite对象与来源机制保存；未直接修改检查数据库或初始快照。

### 六类正式场景

| scenario_id | 输入与用途 | 正式查询可观察结果 |
|---|---|---|
| weighted-ratios | 同期间两产品数量1/9、收入100/900、成本50/810 | 原始明细重算毛利率及单吨毛利均为14；两产品比率的简单平均为30，不能作为聚合结果 |
| zero-denominators | 明确数量/收入/成本均为0 | 毛利率及单吨毛利为null，保留ZERO_DENOMINATOR_UNDEFINED；零基期变化为null |
| missing-numbers | 数量null、收入100、成本null | 已知收入保留，数量、毛利及相关比例为null，缺少字段明确列出 |
| delayed-records | 明确DELAYED，数量2、收入100、成本80 | 已观察局部数值可查；delayed_regions包含region-1，整体变化不计算 |
| unsynchronized-records | 明确UNSYNCHRONIZED，数量/收入/成本均为null | unsynchronized_regions包含region-1；数值未知，不能填零或推断完整范围 |
| basis-conflict | 同期间/指标/单位，两种独立模拟口径各有来源 | FINANCIAL_REPORTED收入100、成本70；BUSINESS_REPORTED收入120、成本72。两者均数量10；分别查询、分别取证，不根据职位或来源名称选取数值 |

每类均使用BASE/CURRENT两个获准期间、region-1、entity-1、product-1或product-2、CNY、tonne、EXTERNAL_SALES、SETTLED、definition_version=1。普通五类business_basis=SIMULATED_BOUNDARY；双方口径场景使用表内两个business_basis。资料仅为用户授权的FC02程序行为验证，不能宣称实际企业经营情况或第三方授权。

### 维护载入与原回执

- `BIScenarioAPI(store).catalog("MAINTAINER")`：读取固定生成版本、参数、用途及场景定义。
- `BIScenarioAPI(store).execute(role, "boss.simulation.bi_scenario.load", payload)`，或直接`load(role,payload)`：仅实际已认证MAINTAINER可以载入，BOSS/匿名拒绝。公共层必须提供真实role，模型不得提供或选择该动作。
- Load必填 client_request_id、mode=SIMULATED、scenario_id、generator_version=FC02-BI-1、seed=20261024、expected_version；初次版本为"0"，后续使用当前实际版本。未知字段、任意records替换、owner/namespace注入、REAL模式或不符参数400；未知未载入场景查询404，CAS/同键异内容409，来源撤销或过期410，越权403/未认证401。
- `BIScenarioAPI(store).receipt("MAINTAINER", client_request_id)`：当前空间原载入回执；没有查到保持NOT_FOUND_IN_CURRENT_STORE，不执行载入。
- 同一事务保存bi_scenario、document、历史、FTS、原回执及只含元信息的审计；并发同编号只保存一个版本。旧空间原编号不能在新空间重新载入；撤销的来源不能重新启用。

载入示例：

```json
{"client_request_id":"fc02-load-weighted-1","mode":"SIMULATED","scenario_id":"weighted-ratios","generator_version":"FC02-BI-1","seed":20261024,"expected_version":"0"}
```

结果按LoadResult Schema返回action、原请求编号、scenario_id/version、source_ids/source_versions、record_count、生成版本、seed、manifest_sha256、用途及external_service_invoked=false。manifest_sha256为解析后参数对象的规范JSON摘要；source published_at/received_at使用实际时间，valid_from使用明确业务时钟，valid_until为该业务时钟之后30天。可复现性指相同版本、参数、期间下的记录，不伪造物理接收时间。

### 来源与查询绑定

普通场景来源ID为`sim-bi:<scenario_id>:SIMULATED_BOUNDARY`。双方场景的准确来源为`sim-bi:basis-conflict:FINANCIAL_REPORTED`及`sim-bi:basis-conflict:BUSINESS_REPORTED`，初次version均为"1"，修订通过CAS递增；每一方拥有各自原文、数值及定义快照。

source保留SIMULATED、author_kind=SIMULATED_GENERATOR、author_display_name=FC02本地确定性模拟资料生成器、generator_author_id=code:validation/boss_bi_scenarios.py@FC02-BI-1、author_contact_id=sim-bi-generator:<business_basis>，以及实际维护创建身份、owner/dataset/namespace、business_basis与说明、参数摘要、访问范围、有效期、用途、位置和时间。author_contact_id明确标识自动生成器，没有创建人物账号或借用真实人员署名。real_enterprise_data=false、third_party_authorization=false、business_authorization_granted=false；权限来自当前真实服务端身份与范围，原文不授予业务动作权限。

正式SCOPED输入新增可选scenario_id与source_ids。没有scenario_id时继续使用原selection/1八条明细及finance-note；有scenario_id时仅读取已经正式载入的场景，不替换默认数据。`BIQueryAPI.dimensions("BOSS", scenario_id)`给出该场景实际维度与来源。source_ids需要属于所选场景，可明确选择所需一方；不能借此读取其他来源。

两方并列需要对相同当前及比较期间、metric_ids、产品/地区/法人、单位/币种分别执行两个正式查询。第一方设置scenario_id=basis-conflict、business_basis=FINANCIAL_REPORTED、source_ids=[sim-bi:basis-conflict:FINANCIAL_REPORTED]；第二方设置business_basis=BUSINESS_REPORTED及其准确source_ids。查询使用各自新request_id，不能以新内容复用旧请求编号。

result.sources、detail_refs与context_snapshot采用实际当前输入；`read_evidence`只接受本次query_id内匹配的明细和准确source_ids，按实际来源返回原文，拒绝明细与来源不符。绑定同时保存scenario_id、document_snapshots、全部来源版本与摘要、明细及定义摘要。更换源版本、撤销、到期后拒绝当前采用，历史投影保留当时结果、来源及原请求。失效的财务来源不会阻止另一个当前有效业务来源的独立查询。SimulationAPI的SI07/SI08查询也使用同一场景明细与来源绑定。

### 本次必要验证

- Red：`.work/fc02-boundary-behavior-red.xml`，正式query_metrics拒绝scenario_id，业务断言失败1项；作为输入缺口证据。开发环境收集结果不计为业务Red。
- 受影响验证：`validation/.venv/bin/python -m pytest -q app/tests/test_fc02_bi_scenarios.py app/tests/test_fc02_bi_queries.py app/tests/test_boss_metrics.py app/tests/test_boss_tool_sources.py app/tests/test_boss_simulation_api.py --basetemp=.work/pytest-fc02-input-delivery -p no:cacheprovider --junitxml=.work/fc02-input-delivery.xml --tb=short`，172 passed，18.87秒。
- 最终来源权限修订及实际Registry：`.work/fc02-input-final.xml`，19 passed，3.67秒；包括18项正式场景检查及已有实际nanobot Registry对当前Schema的消费。
- 最终owner/dataset/namespace元信息修订：`validation/.venv/bin/python -m pytest -q app/tests/test_fc02_bi_scenarios.py --basetemp=.work/pytest-fc02-input-scope-final -p no:cacheprovider --junitxml=.work/fc02-input-scope-final.xml --tb=short`，18 passed，0.93秒。其他证据按其准确版本和受影响范围复用，不将这些数量相加为功能分数。
- 实际验证涵盖正式载入、不同权重的两类比例、零分母、缺少值、DELAYED/UNSYNCHRONIZED、双方当前原文与生成作者、角色及注入拒绝、并发单次写入、CAS与历史版本、同库服务重建、原回执重读、撤销与过期、重置空间及原编号拒绝、独立数据库可复现、默认快照摘要保持和真实查询投影。
- OpenAPI3.1及YAML重复字段检查通过，git diff --check通过。全部中间数据位于本目录已忽略.work，未访问外部API、未操作其他服务或预览、未执行视觉。

### 公共接收条件

N3在当前候选逐项接收9f44a1d，保留其已有历史、异步恢复和bi_follow_up.overrides扩展。本次没有修改其公共文件；接收时在该已扩展overrides中补充scenario_id/source_ids，不能整份覆盖公共Schema。

公共维护入口负责注册catalog、正式load动作及原载入回执；老板入口负责明确场景选择、将scenario_id/source_ids绑定真实请求与继承快照，读取当前场景dimensions，展示双方同期间查询及各自原文。Runtime仍仅使用已批准query_metrics/read_evidence，不能注册维护载入为模型工具，也不能将模拟来源当作本人授权。

业务输入和本地领域验证已就绪。C05/C08/C11需要N3接入公开操作和准确候选后由N4独立复验；本地输入通过不代表二十项完整PASS，不启用FC03。
