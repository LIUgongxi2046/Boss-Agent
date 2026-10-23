# FC02 公共界面与集成

task_id：FC02-N3；当前IN_PROGRESS，二十项完整验收来源为原始项目docs/FC02经营查询工单.md及specs/feature-delivery.json。文档有效性CURRENT，核查日期2026-10-24。产品基线c4bc673，保留已有未提交交接及原始证据。

## 输入与当前代码

已读取FR-03完整8.3、经营指标12.1、公共权限/来源/异常规则、适用LLD、F03原始设计文字、BossDesktop的F03/N03及BossPageAPI._metrics、boss_metrics.py与对应检查。现有query_metrics/read_evidence及query_source_binding继续使用；F03当前产品选择、BASE/CURRENT表及固定来源入口尚未满足完整连续查询、变化量、可见上下文和原始依据展示要求。

FC01限定验收18/18 PASS已核实，保存于../FC01/acceptance.json；集成HEAD与该候选一致，manifest摘要匹配N4。旧28项父任务及192点没有改变。当前只推进FC02，不复验无变化FC01业务。

## 四角色接收与继续条件

N1提供当前查询/比较/覆盖/来源及持久恢复接口、Schema和准确提交；N2提供BI专有工具、可信上下文及明确模拟事件接口；N3负责公共认证/请求生产者、F03/N03/D01完整界面和统一Runtime注册；N4依据当前工单建立二十项独立验收。角色记录为各自目录docs/feature-delivery/FC02。当前候选尚未发布，必要新字段尚待正式接收，不能根据固定基线缩减工单。

## 当前公开增量

BossPageAPI._metrics在调用查询前拒绝额外范围字段和重复参数。新增GET /api/boss/ui/metrics-evidence?query_id=...，由服务端从持久查询取得实际detail_refs/source_ids和本人范围，调用正式read_evidence；当前来源、版本和摘要再次核查。维护/匿名/额外owner参数分别拒绝，来源撤销后停止采用当前正文，历史query记录保留。

F03/N03显示正式CHANGE及对应单位、原始Decimal字符串、公式/定义/展示精度、当前查询编号、覆盖和来源更新时间。原始依据按钮读取本次query_id的匹配记录；来源入口使用当前结果返回的source_id。产品选择变化会清理旧结果、取消旧读取，响应与当前产品范围及query_id核查。BI字段标签14px/22px、输入/数值/实际D01原文16px/24px；没有客户端重新计算指标或预设图形。

当前可编辑范围仍沿用已接收正式products字段；完整地区/法人/期间/币种/定义、连续追问继承、原请求与历史恢复、BI实际Runtime链路需要N1/N2的准确提交及正式Schema。新公共规范specs/product-bi.openapi.yaml为0.1.0，明确当前范围，不表示完整FC02已接收。当前没有收到各角色FC02接收记录，不读取旧聊天或将FC01工具链当作BI交付。

## 当前验证与独立制品

实际权限、来源、查询绑定与SQLite重读及直接相关回归16 passed：validation/.venv/bin/python -m pytest app/tests/test_product_bi_queries.py app/tests/test_boss_page_api.py app/tests/test_boss_metrics.py --basetemp=validation/.work/fc02-public-bi-green -q -p no:cacheprovider --junitxml=evidence/feature-delivery/FC02/public-bi-green.xml。原始检查证据按自身版本保存，完整功能分数仍为待核实，不能用用例数量代替二十项。

标准OpenAPI3.1和YAML重复字段检查PASS：.work/openapi-venv/bin/python validation/check_bi_public_spec.py；结果.work/fc02-public-openapi.log。业务输入输出继续由Store实际校验，公共扩展引用正式QueryResult及当前evidence_output语义。

TypeScript/Vite构建PASS，13.41秒；在.work/product/nanobot/webui执行npm run build -- --outDir ../../../../fc02-n3-query-dist。独立制品fc02-n3-query-dist，原FC01制品及预览保留。manifest SHA256为c3aae3a090d420976bd4ab0b30a9f4e88f8080a1b8778c32a34176d33118db31，index.html SHA256为445d7008b5b997946a20a2716e0616c8bd44b4f578ea1fd6ad5f117935e3e102；产品和构建输入的BossDesktop/CSS摘要分别一致。

真实本机账号公开增量检查PASS：evidence/feature-delivery/FC02/fc02-bi-4f402a77-eb22-449c-982e-b039010b1a40.json。命令设置BOSS_PRODUCT_FRONTEND_DIR为本目录fc02-n3-query-dist绝对路径，执行node validation/desktop/check-fc02-bi.cjs；使用9671/9672/19671及独立账号/SQLite。覆盖实际产品范围、变化单位、精度与公式、原查询依据、角色及额外字段拒绝、实际数值/原文Token、已加载F03/N03/D01的18次尺寸页面组合及Enter/Tab；renderer异常为零。模型请求为零，视觉NOT_RUN。

## 后续接收条件

本候选是公开查询的阶段增量，不能要求N4按完整二十项登记PASS。N1需要交付完整维度/可比/覆盖/原始精度及历史与恢复接口；N2需要交付BI专有真实Registry、明确模拟事件及可信上下文接口。N3随后接收字段及当前状态传播，完成完整页面、公开生产者与单一Runtime接入，提供完整组合候选。N4可依据工单完成验收准备及当前证据适用性核查；完整二十项只在准确组合候选验证。没有重跑无变化FC01业务全量检查，旧父任务及全队列保持原义。

全部外部SIMULATED_FIRST；本地账号、权限、SQLite、来源及实际工具执行；视觉NOT_RUN，STT暂停。不操作默认预览、其他角色目录或进程。独立数据/端口/构建仅用于当前变化的必要验证。
