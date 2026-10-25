# MENU-N03-N1 经营关注领域

task_id=MENU-N03-N1；marker=MENU-N03-START-20261025；依据原始docs/menu-delivery/N03.md的C01—C26及完整产品FR-02/03/14—23。当前唯一菜单N03，正式状态由N3维护specs/feature-delivery.json，本记录不登记完整菜单或用户验收通过。last_verified=2026-10-25，领域状态MODULE_CHECKS_PASSED。原五项未提交内容保持。

实施提交a38bf9b41f5b1f88d08ebbac10b62a2610962515，分支codex/business，共6份领域、Schema、检查、记录及索引文件。N3/N2按该准确增量接收，公共路由和实际Agent消费仍待各自接收。

## 当前依据与边界

完整读取当前工单和适用AGENTS，沿用S008任务记录、实施与接口检查规范。核查准确PRODUCT基准3d04f28d6d3b7d53b58a1a69b085a54ca1cc6f57的BossSectorAPI、正式BI计算、SimulationAPI、供应品质、经营提醒、任务和来源规则；验证时PRODUCT HEAD为ba59c33bc3cc6b914bdd0b0792aeedc49b3f2220，相关领域文件与基准相同。PRODUCT目录为/Users/liuhaoxian/.codex/worktrees/boss-integration/Boss-Agent，仅作只读依赖。记忆索引没有本任务相关证据。

新增validation/boss_business_overview.py，规范specs/business-overview.schema.json 1.0.0。只读采用真实Store；不新增查询、任务、授权、通知动作、DDL或另一AgentLoop。没有修改公共BossPageAPI/Command/RoleChannel/application/Shell/认证，没有启动产品、预览、桌面或使用用户实例。SIMULATED_FIRST，STT及视觉继续暂停。

## 正式接口与范围

构造器BusinessOverviewAPI(store)。调用方传入的role必须来自可信认证，payload没有owner/namespace/dataset。匿名401、维护403；额外、无效或未支持范围400；旧快照409；上游错误在当前位置抛出，不返回替代成功。

| 函数签名 | 输入 | 输出及事务 |
|---|---|---|
| dimensions(BOSS) | 无payload | 当前正式记录提供的法人ID、区域ID、期间、已验证IANA时区及attention枚举；独立只读事务 |
| read(BOSS,scope) | Scope严格字段见下表 | View；同一BEGIN事务核查范围、权限、来源、指标、专题、提醒及关联 |
| project_in_transaction(BOSS,db,scope) | 相同Scope，db为调用方现有只读事务 | 相同View；不另开写入事务 |
| detail(BOSS,{scope,page_id,snapshot_sha256}) | page_id限定F14—F23，摘要来自同一scope的View | 当前topic、来源、范围及时间；重新读取并核查快照，变化409 |

公共路由建议：本人读取GET /api/boss/ui/business-overview/dimensions；范围和详情采用POST /api/boss/ui/business-overview/read、POST /api/boss/ui/business-overview/detail，JSON分别为上述Scope和Detail。路由尚未注册，N3负责公共适配，讨论工具由N2按准确接口采用。POST读取用于传递严格结构，操作仍为只读。

| Scope字段 | 精确语义 |
|---|---|
| legal_entity_id | dimensions.legal_entity_ids中的正式ID；不按名称猜测 |
| region_id | 正式区域ID或null；null明确表示没有区域限制，有区域限制时缺少区域证明的对象不进入专题当前结果 |
| period_start / period_end | dimensions.periods提供的完整起止日期；包括获准selection期间和正式记录明确报告期间，不分摊未知日期区间 |
| timezone | 当前已验证本人IANA时区；不支持的时区明确拒绝 |
| attention | ALL、OWNER_INVOLVEMENT、SOURCE_REVIEW；不接受自由文字并暗中忽略 |

草稿由客户端维护，read只采用明确提交的scope，View.applied_scope原样返回。dimensions的法人/区域来自当前获准明细和正式对象元信息，期间来自明确报告字段；维度可读不表示相应数值已通过当前来源检查。当前数据资格在read内重新核查。

## JSON字段与业务采用

View严格根字段：source_type=SIMULATED、projection=business-overview、applied_scope、dimensions、scope_application、metrics、metric_missing_fields、metric_scope、metric_coverage、query_handoff、query_handoff_unavailable_reason、topics、alerts、alert_scope_exclusions、associations、sources、excluded_records、unclassified_records、business_at、read_at、coverage_state=PARTIAL、snapshot_sha256，以及恒false的business_authorization_granted/business_mutation_performed。

metrics复用正式BI的_period_rows及_aggregate，只采用当前有效finance-note和明确法人/区域/期间的原始明细。逐项metric_id/value/unit/formula/definition_version/precision/business_as_of/source_refs；数值为Decimal字符串，缺少或零分母保持null。metric_scope=WATER_FEED_EXTERNAL_SALES_ONLY，metric_coverage保存实际record_id/version、缺少区域和SCOPED_AVAILABLE/PARTIAL/UNAVAILABLE。这些金额和比率不作为原料价格、领用成本或农业专业结果。query_handoff仅在有效当前/比较期间及完整区域条件下提供正式F03范围参数，包含原source_ids、业务口径、单位及比较期间；否则null，公共入口须说明当前需要的有效查询条件。

topics按F14—F23固定十项顺序，title/purpose来自现有获准SECTORS定义。每项包含page_id/title/purpose、availability、data_as_of、latest_source_published_at、records、missing_fields、scope_application、related_sales_source_refs及uses。可读状态PARTIAL、NEEDS_REVIEW、SOURCE_NOT_AVAILABLE、FILTER_EMPTY分别表示部分正式对象、需要复核、没有本专题当前资料和关注条件筛除结果。data_as_of采用实际observed_at；发布时间单独保存，不代替业务观察时间。F19 uses为BROILER/EGG/MILK/BEEF；当前共享页面对应F19、V19-EGG、V19-MILK、V19-BEEF，完整专业菜单仍由后续工单管理。

供应对象和质量对象复用SimulationAPI的正式选择及_protect来源/传递采用规则。法人只通过对象明确legal_entity_id或显式批次/库存ID关系核查；跨法人或无法确认关系时排除。区域限制不从相近名称推断。F14采用材料行情/合同/库存/领用/成本报告/配方的合法明确对象，F21提供生产批次、追溯、专业记录、反馈及事件的有限质量关系，均保留完整专题缺口。记录逐项kind/id/version/state/adoption_state/source_refs/facts，facts仅提供当前通过检查的归属、单位、币种、报告期间及专业/检验状态；来源失效时facts=null。没有将生产批次推断为苗种批次，也没有将未确认用途的农业观察推断为禽畜或完整养殖专题。unclassified_records明确保存已获准但专题适用关系不足的对象；excluded_records说明法人或区域无法确认的类型与原因。

scope_application明确：指标采用完整所选期间；专题是business_at时点的当前状态，报告期间随facts明确返回，不作为所选期间流量合计；提醒采用实际比较期间及selection财政资料范围；关联采用正式来源关系，不作为任务创建期间。attention过滤专题、提醒和关联，指标保留为已应用法人/区域/期间的上下文。需要本人参与的专题没有自动专业分类时不编造提醒。

alerts复用BusinessAlertsAPI.project_in_transaction，保留原事件、通知、规则版本、参与原因、已有措施、处理人、缺少字段及状态。范围只从实际生成器保存的比较期间和正式selection来源范围确定，无法证明范围时不采用；alert_scope_exclusions分别给出范围和关注条件排除数量。来源变化后保留正式历史事件元信息及NEEDS_REVIEW，facts/当前通知等正文采用资格继续由原领域决定。读取不调度、知晓、暂缓、关闭或发送。

associations仅从正式任务的source_refs与当前范围的明确来源关系采用，逐项kind/id/version/state/adoption_state/source_refs/relation=EXPLICIT_SOURCE_REFERENCE。OWNER_INVOLVEMENT进一步限定实际提醒已有措施中的任务；SOURCE_REVIEW限定正式NEEDS_REVIEW。来源撤销后历史引用和状态仍可辨，当前业务采用需要原领域重新核查。

sources逐项source_id/version/status/sha256/metadata，SQL先限制当前namespace、本人access_scope、source_id和SIMULATED类型，再核查source_validity及external_adoption。当前metadata包含实际作者、类型、发布时间、观察时间、有效期、范围和原文定位；失效或无权时不返回metadata。sha256覆盖当前完整正式来源对象，供版本变化核查。snapshot_sha256覆盖当前范围、资料、对象及正式结果，read_at不参与摘要；detail重新计算并拒绝已变化的引用。未提供任意客户端来源或对象ID入口。

## 当前验证

2026-10-25，11项限定检查通过，用时3.22秒，原始结果domain-check.xml。数据均为N1独立.work/pytest-menu-n03-delivery下的真实SQLite，来自正式初始化、本人Command服务、获准supply-quality-v1.yaml导入及经营提醒定义。没有mock、替换业务正文、外部网络或用户实例。

实际拒绝6类非法/未支持法人、区域、期间、时区、关注条件和额外身份字段请求，均为400；匿名401、维护403；来源撤销后指标null、查询入口null，旧快照409。成功检查覆盖原始毛利率8.00%、十专题顺序和四用途、真实供应/质量资料、未分类农业范围、精确区域限制、正式报告期间、来源复核、经营提醒与通知/规则独立状态、真实任务关联及稳定版本。同库重开结果摘要一致，所有读取前后的objects/audit/idempotency完全相同；旧范围提醒被明确排除，来源失效后的历史提醒保持NEEDS_REVIEW且facts=null。

```bash
env PYTHONDONTWRITEBYTECODE=1 MENU_N02_PRODUCT_ROOT=/Users/liuhaoxian/.codex/worktrees/boss-integration/Boss-Agent PYTHONPATH=/Users/liuhaoxian/.codex/worktrees/boss-business/Boss-Agent/validation validation/.venv/bin/python -m pytest -q app/tests/test_menu_n03_overview.py --basetemp=.work/pytest-menu-n03-delivery -p no:cacheprovider --junitxml=docs/menu-delivery/N03/domain-check.xml --tb=short
```

验证工作目录为/Users/liuhaoxian/.codex/worktrees/boss-business/Boss-Agent。PYTHONDONTWRITEBYTECODE=1阻止依赖目录生成缓存，现有检查审计禁止socket.connect。生成前磁盘249MiB；没有创建全仓副本。git diff --check通过。

## 接收与未完成范围

N3需要公共注册、完整设计与交互、范围草稿/应用和返回状态、实际页面、共享入口及独立交付；N2需要实际工具与同一SDK对准确scope/topic/snapshot/source版本的消费。N1本次交付提供这些消费者的数据接口，不表示上述公共与Agent行为已经完成。未来完整专题、真实外部接入、STT、视觉和用户验收均未登记通过。唯一26项状态继续读取N3正式记录。

query_handoff_unavailable_reason在不可进入当前比较查询时明确说明FINANCE_SOURCE状态、NO_EXTERNAL_SALES_ROWS_FOR_SCOPE、REGION_COVERAGE_INCOMPLETE或NO_PRIOR_COMPARISON_PERIOD；可进入时为null。公共入口不能把query_handoff=null显示为已完成查询，也不应提交缺少条件的动作。
