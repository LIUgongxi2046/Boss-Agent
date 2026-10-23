# FC01 公共集成开发记录

task_id：FC01-N3；需求：FR-14/21/06/28/29；验收：FC01.C01—C18。
状态来源：原始项目 specs/feature-delivery.json；当前 IN_PROGRESS，十八项尚待同一候选独立验收，视觉 NOT_RUN。

## 当前代码与依据

2026-10-23 接收 9bd2f9f 为 bb2b7a6，接收 daedc63 为 a989c6b；保留全部 read-scope 内容。已读取当前计划、工单、状态、W3 停止交接、S008 规则，检索当前 PRD/HLD/LLD、公开组件、工具及 T11 索引。历史 869 项结果仅适用已提交 1.7.0。

## 当前实现与约束

入口：真实登录、A03 明确导入、F14/F21 查询及协调、F06 发送反馈和本人完成。外部请求保持 SIMULATED_FIRST，本地业务服务及 SQLite 真实执行。模型字段和维护身份不能替代本人决定。公共入口由 N3 维护，领域及 Agent 接收准确提交。不操作默认预览端口及数据，不终止其他进程；中间结果使用忽略的 .work 与 validation/.work。

## 验证与证据

读取、运行配置、成本与公共采购品质检查 52 passed，命令为 validation/.venv/bin/python -m pytest app/tests/test_product_read_scope.py app/tests/test_product_runtime_configuration.py app/tests/test_boss_material_cost_reports.py app/tests/test_product_supply_quality.py --basetemp=validation/.work/fc01-n3-read-cost -q -p no:cacheprovider --junitxml=evidence/T09/w3-20261023/fc01-read-cost.xml。新增期间筛选接收后另执行成本及模拟查询的直接回归 91 passed，入口 test_boss_material_cost_reports.py、test_boss_simulation.py、test_boss_simulation_api.py；证据 evidence/T09/w3-20261023/fc01-report-filters.xml。
BossResearchSourcesTool 在准备阶段限定 research，执行阶段独立拒绝非研究投影；实际 SQLite 内容保持不变。独立前端目录选择及范围拒绝检查另有 2 passed，入口 app/tests/test_product_frontend_directory.py。
实际 React、领域及 SQLite 组件检查通过七类行为：库存计算、两类报告成本、协调填写、本人确认控制、保存重读、专业状态独立及来源变化拒绝采用。证据 .work/fc01-n3-cost-components/result.json。命令使用 NODE_PATH 指向本工程 .work/product/nanobot/webui/node_modules，执行 node evidence/T12/verify_supply_quality_ui.mjs 及绝对依赖目录、输出目录参数；认证通道和视觉不属于该组件结果。

## 独立构建及运行入口

现有依赖完成当前筛选 TypeScript/Vite 构建，16.84 秒；命令在 .work/product/nanobot/webui 执行 npm run build -- --outDir ../../../../fc01-n3-filter-dist。制品位于本工程 fc01-n3-filter-dist，未替换默认预览；日志 .work/fc01-n3-filter-build.log。成本组件源码与构建输入 SHA256 均为 9cc9732a9069e15174ddb513c16b7d043aae3dee5fea42824dacc3be2c5781cb；筛选组件与构建输入均为 8edfc1a58ade875a5a0386b483a3633d8bdf986aaf8b885c19252ba7e07498af。
index.html SHA256 为 e69b4c307c1901955f059fb8004d149984f3f934511ea24c18f4c73417562a08；asset-manifest.json SHA256 为 033a282ec1a1a4bd8488157c191f55c4e36026055a56f2ba04e30d616d30648c。
运行时 BOSS_PRODUCT_UI=1，BOSS_PRODUCT_FRONTEND_DIR 使用候选检出下独立构建绝对路径；BOSS_APPLICATION_WORK_DIR 使用候选检出下 validation/.work/fc01-qa 的绝对路径；BOSS_APPLICATION_PORTS 使用 business=9071、webui=9072、gateway=19071。实际启动入口 validation/application.py；本机账号通过 scripts/provision_boss_accounts.py --directory <独立数据目录>/accounts 建立。不得使用默认预览数据，不能据本记录自动请求真实模型。当前应用模型传输尚待 SIMULATED 适配接入，候选仅供本地界面与领域核查准备。

## 接收与后续条件

N1 确认 9bd2f9f992014c7760b751afaacbf2ea0e2af1a7 为领域 1.8.0，新增授权消费文件尚未验收。公共接收限于已提交内容。N2 当前适配及 N4 独立判定尚待对应记录。
F14/F21 通过正式 SimulationAPI 提供原料、产品、法人、资产/成本归属、批次、客户、币种和期间筛选。筛选原始记录与完整库存计算分别标明，当前结果变化后不展示旧筛选记录。
真实认证隐藏桌面检查 PASS：evidence/T11/w3-local-20261023/supply-quality-4707e9e1-1fa8-425f-9db7-d3f283696ec1.json。覆盖维护 SUCCESS/EMPTY/FAILED/TIMED_OUT 导入及撤销、角色拒绝、筛选与键盘提交、不完整期间、D06、协调未知结果和原请求恢复、实际发送反馈与本人完成、重启、来源更新与撤销、三种尺寸及200% DOM范围。运行命令使用 BOSS_PRODUCT_FRONTEND_DIR 指向本工程 fc01-n3-filter-dist、BOSS_APPLICATION_PORTS 为 business=9071/webui=9072/gateway=19071，执行 node validation/desktop/check-supply-quality.cjs。所有进程与数据由该检查独立建立，检查退出时关闭自身进程；模型请求和外部投递为零，视觉 NOT_RUN。
当前候选为阶段检查用途，完整功能尚待 N2 提供准确可接收提交、稳定 context_provider 与模拟事件生产者接口；随后 N3 完成实际认证上下文、对象/内容/来源/请求绑定生产者、配置准入、公开 Runtime 注册及界面准备结果采用。不得使用 N2 尚未提交文件作为候选已接收代码。N4 需要对该组合候选执行十八项独立验收。read-scope 的 A08 模式选择与完整恢复检查保持未验收，当前不扩大为全部维护后台。N4 对准确候选十八项 PASS 后才能推进 FC02。
