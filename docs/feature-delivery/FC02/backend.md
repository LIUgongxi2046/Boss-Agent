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
