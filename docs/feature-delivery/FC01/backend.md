# FC01 业务数据与领域服务

## 接管与范围

- task_id：FC01-N1；状态来源为原始项目 specs/feature-delivery.json，当前 FC01 的十八项完整检查点待候选验收。
- 目录：/Users/liuhaoxian/.codex/worktrees/boss-business/Boss-Agent；分支 codex/business；接管 HEAD 为 9bd2f9f992014c7760b751afaacbf2ea0e2af1a7。
- 2026-10-23 核实五项未提交内容：docs/LLD-backend.md、docs/development/T14.md、app/tests/test_boss_authorized_execution.py、validation/boss_authorized_execution.py、docs/development/SESSION-HANDOVER-W1.md。全部保留；新增授权消费未验收，失败证据保持原路径。
- 当前范围为 FC01.C02—C14 所需领域、Schema 与接收接口；公共入口、Runtime 注册、N2 和 N4 专有文件由对应角色维护。
- 已完整读取原始项目功能计划、FC01 工单、功能状态及本目录停止交接，重新完整读取适用 AGENTS.md；采用 S008 及开发记录、执行、验证规范。
- 全部外部输入与发送均 SIMULATED_FIRST；本地身份、权限、SQLite、CAS、幂等与异常执行真实行为；本人决定不得由模型代替。

## 当前接收基线

9bd2f9f 提供 1.8.0 报告成本领域及私有组件；关联主记录 docs/development/T12.md、T13.md、T14.md。evidence/T13/material-cost-reports-1.8.0.json 保存 20 项成本检查、647 项回归及 React/SQLite 证据。当前继续核查源码摘要与必要接口。证据不包含未提交授权消费文件，不能表示公共候选通过。

## 检查点与接收状态

FC01.C02—C14 已核查当前领域入口及对应既有验证。当前没有统一候选，完整功能 PASS 尚未判定。FC01.C05 增加报告期间与成本归属筛选；当前变更仅涉及查询领域、Schema、基础 OpenAPI、对应测试、数据设计与本记录。

## 1.8.0 接收清单

- 四项连续提交：f4ab453（显式导入、协调及私有组件）、45eec11（当前来源消费者）、4e7c452（当前 SQLite 恢复）、9bd2f9f（报告成本）。接收者按自己的当前代码逐项集成，不能覆盖已有修改。
- 领域打包：validation/boss_supply_quality.py、boss_supply_quality_views.py、boss_material_costs.py，以及当前 business.py、controls.py、boss_source_access.py、boss_source_policy.py、boss_simulation_api.py、boss_assignment_sources.py 和它们已经引用的领域模块。
- 规范：specs/openapi.yaml、data-dictionary.json、business-tools.schema.json、simulation-query.schema.json、simulated-supply-quality.schema.json、supply-quality-results.schema.json、assignment-source-review.schema.json、runtime-records.schema.json、runtime-events.schema.json。当前基础版本 1.8.0；本次增加可选 cost_owner_id 查询字段和 SI09/SI10 期间语义，原输入保持兼容。
- 私有组件：app/webui/BossSupplyQualityPanel.tsx（成本、当前依据及协调）和既有 BossSupplyQualityView；当前组件使用完整计算投影。公共筛选、D06、导航、Client/Provider、Token 及 Runtime 由 N3 接收维护。
- 报告输入 material_cost_report.data：report_id、material_id、legal_entity_id、asset_owner_id、cost_owner_id、ownership_type、customer_id、cost_type、report_scope_id、cost_basis_id、scope_description、period_start、period_end、inventory_ids、quantity、total_cost、quantity_unit、currency、state。cost_owner_id 可为 null；金额和数量为十进制字符串或 null。
- SI09.supply[].cost_reports[]：cost_type、cost_owner_id、report_scope_id、cost_basis_id、scope_description、currency、quantity_unit、current、baseline、comparison_state、unit_cost_change、total_cost_change、formula、missing_fields。current/baseline 保留 report_id、source_id、source_version、period_start、period_end、quantity、total_cost、unit_cost。未知归属返回 UNKNOWN_COST_OWNER，停止跨期比较。

## 正式接口与本人决定

| 使用方 | 入口 | 必要语义 |
|---|---|---|
| N2/N3 查询 | SupplyQualityAPI(store).read("BOSS", "SI09"或"SI10") / read_http(role, query_string) | 完整当前计算投影，仅 interface_id；包含 review_sha256、当前可采用记录及来源状态 |
| N2/N3 筛选 | SimulationAPI(store).query("BOSS", {interface_id, object_ids, filters}) / query_http | 当前来源保护、客户端不得提交 owner/namespace；支持 material_id、legal_entity_id、asset_owner_id、cost_owner_id、ownership_type、product_ids、customer_id、batch_id、currency、source_version、period_start、period_end |
| N3 维护 | SupplyQualityAPI.execute("MAINTAINER", IMPORT_ACTION或WITHDRAW_ACTION, payload) | SUCCESS/EMPTY/FAILED/TIMED_OUT、原回执与版本；失败及超时分别502/504，不能改成成功 |
| N3 本人确认 | SupplyQualityAPI.execute("BOSS", COORDINATE_ACTION, payload) | 签发创建授权并保存任务，仅本人公共确认入口调用；模型不能调用此方法签发授权 |
| N2 既有授权消费 | Store.invoke("create_assignment"或"send_assignment", payload) | 已有合法 authorization_id、完整内容、envelope、idempotency_key；单次授权、实际时效、撤销、CAS及当前来源检查 |
| N2 查询任务 | Store.invoke("read_assignment", {envelope, task_id}) | 正式 Schema 投影；保留同一 task_id 与版本 |
| N3 回执恢复 | SupplyQualityAPI.receipt(role, action, client_request_id) / receipt_http | 按原动作身份及当前空间读取原结果；原编号未知时保留，不能据此判定未执行 |
| N3 后续本人操作 | BossCommandAPI.execute(role, action, payload) | boss.assignment.send、boss.simulation.feedback、boss.assignment.complete 分别按角色执行；Agent 不调用签发本人授权的公共动作 |

CoordinateInput 必填 client_request_id、interface_id、origin_entity_type、origin_record_id、origin_version、review_sha256、purpose、coordinator_id、due_at、timezone、evidence_requirements。当前来源摘要重新核查后，同一事务保存授权、任务、来源绑定、协调关联、回执及审计。原专业事件与库存状态保持独立。

Store.invoke 的写入内容必须与已有授权 payload 完整一致；envelope 包含 request_id、session_id、owner_id、execution_namespace、dataset_id、dataset_version。来源读取采用 SimulationAPI 的 source_refs/source_statuses；需要原文时复用当前公共来源入口与 require_current_business_source，不得只检查 document.VALID。发送领域原字段 message_status=SENT 且 source_type=SIMULATED，公共层继续表达 SENT_SIMULATED 与未验证送达。

## BDD 与实际证据

- 当前五份领域/Schema 源码 SHA256 及 `.work/w1-material-cost-owned.xml`、`.work/material-cost-owned-ui/result.json` 的 SHA256 全部与 evidence/T13/material-cost-reports-1.8.0.json 一致。复用 647 项已提交验证及 React/SQLite 结果；没有重跑全量。
- Given 明确 SIMULATED 报告与真实 SQLite，When 重建 ControlStore/SimulationAPI 并按业务时区完整日期和成本归属查询，Then 返回两个当前报告，维护只获得相同对象元信息，HTTP 与直接查询一致，其他归属为空。
- Red：`validation/.venv/bin/python -m pytest -q app/tests/test_boss_material_cost_reports.py -k fc01 --basetemp=.work/pytest-fc01-report-filters-red -p no:cacheprovider --junitxml=.work/fc01-report-filters-red.xml --tb=short`；1 failed / 6 passed，合法报告筛选被 Schema 拒绝。
- Green及受影响回归：`validation/.venv/bin/python -m pytest -q app/tests/test_boss_material_cost_reports.py app/tests/test_boss_supply_quality.py app/tests/test_boss_simulation_api.py --basetemp=.work/pytest-fc01-report-filters-green -p no:cacheprovider --junitxml=.work/fc01-report-filters-green.xml --tb=short`；124 passed，24.16秒。包含实际导入/失败回执、查询权限、CAS、并发、协调创建/发送/反馈/本人完成、来源变更、独立数据库重读及实际 Registry 检查。
- 无新增模型、网络或外部系统请求；中间结果仅本目录 `.work`，已被 gitignore 覆盖，未操作其他服务进程。

## 接收条件

向 N2 提供查询、来源、协调与已有授权交办接口；向 N3 提供 1.8.0 文件与字段清单、私有组件版本和可接收提交。仅依据 FC01 需求与当前代码确认必要缺口。视觉未执行；真实外部模型与投递未执行。

## 当前交接与下一动作

- 当前可接收领域提交：daedc63927030f0df95119f2138ea0d7802543a2；五文件包含查询、成本测试、Schema、基础 OpenAPI 与 LLD-data。原五项未提交内容完整保留。本记录为独立文档提交。
- 当前 124 项检查适用于 daedc63；647 项及 React 证据适用于 9bd2f9f，查询模块变化涉及的范围已由本次 124 项覆盖。其余既有证据按原版本及范围引用，不能声称当前候选重新通过 647 项。
- OpenAPI3.1 与 YAML 重复字段检查通过：`.work/design-venv/bin/python evidence/T06/validate_openapi.py`；`git diff --check` 通过。
- 已向 N2/N3 发送接收清单、daedc63、本人确认边界、完整投影与筛选查询的区别。统一索引由 N3 添加 FC01-N1 唯一条目，N1不编辑公共索引。
- 已读取 Desktop v6 design-tokens.json 与 F14/F21/F06/D06 文字依据；当前领域变更不修改 UI。Agent/Frontend 独立 LLD 在本目录未发现，公共接入按当前工单及对应角色的当前设计维护。
- 当前 N1 领域接收已就绪。后续必要条件为 N3 接收准确提交并提供统一候选、N2绑定正式查询与已有授权执行、N4复现当前候选。收到当前功能的领域缺陷及最小复现后继续对应修复；不重复运行无变化全量验证，不启用 FC02。
- FC01.C01、C07—C08 的公共本人决定绑定、C12—C13 的公共连接/身份恢复、C15—C18 的 UI/Runtime/独立组合验收仍由对应角色在同一候选核查。本记录仅提供领域证据，全部十八项保持全局状态来源的实际判定。
