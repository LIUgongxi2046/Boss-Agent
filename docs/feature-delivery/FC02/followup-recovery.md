# 默认父查询切换正式场景的公共验证

## 任务身份

task_id为FC02-N3-FOLLOWUP-RECOVERY，关联FC02-N4-DOMAIN-FOLLOWUP-01及C03/C16、受影响的C12—C17/C19。唯一功能状态来源为原始项目specs/feature-delivery.json，完整FC02保持IN_PROGRESS。文档CURRENT，last_verified为2026-10-24，依据当前领域差异、实际公共SDK/WebSocket、SQLite、同库重启和界面重读。

N4对983b7287cf0e4c7050a109bc458f603308045f2d独立判定17/20、85%、FAIL/NO_GO，C05/C08/C11已通过；准确快照见independent-983b728.json。当前修复候选需要独立核查，不能直接继承原候选17项分数，FC03尚未启用。

## 检索与输入依据

完整读取N4当前verdict.json、qa.md、default-scenario-followup-983b728.json；读取N1 backend.md末尾、c707df80260c5181fd86861f284eaa8e63e567f7两个文件及记录31b6313db73bd1b379796f469121dfcb32e0c145。检索当前开发索引、boundary-adoption.md、candidate.json，核对query_metrics、require_current、dimensions、ProductBI、RoleChannel、正式Schema和实际SDK消费路径。

N1代码通过文件编辑工具逐项采用，仅validation/boss_bi_queries.py两行新增、一行移除及原样接收app/tests/test_fc02_followup_sources.py。当前领域文件SHA256为1a6237d88e51e6dbc660c0385ccdcdd02dd68c708238de636a3eef32a685317e，与N1固定983b728且采用同一差异的实际SDK组合相同。接收测试SHA256为c8b6247dca4352fa1d4923d42e3f5c5b4ab879bc3dfc18e4febced89a6a7a7cc。当前公开dimensions/source_ids、Schema、历史/异步及原生Client保护保留。

Red证据采用N4对准确983b728的实际公共与SDK记录，以及N1已保存的独立Red。没有重放N4原失败请求；当前全部修复检查使用独立数据和新请求编号。

## 当前功能与实现

| 文件 | identifier或入口 | 当前职责与使用方 |
|---|---|---|
| validation/boss_bi_queries.py | query_metrics / require_current | 同一事务内按父查询自身当前绑定核查来源、明细、定义和会话，通过后读取本次子场景；原请求摘要与幂等保持 |
| app/tests/test_fc02_followup_sources.py | 六项领域检查 | 默认到正式场景、跨场景、继承、父子来源撤销、换版/到期、会话、原回执和来源明细 |
| validation/desktop/check-fc02-followup.cjs | 实际公共WebSocket及界面重读 | 真实维护载入、默认父查询、boss.bi.follow_up、真实SDK、来源原文、重启、成功幂等、失败原请求与界面 |
| validation/fc02_followup_check.py | inspect / withdraw-child / withdraw-parent | 在本验证独立目录通过正式ControlStore控制来源，读取实际快照、计数及Runtime事实 |
| docs/feature-delivery/FC02/independent-983b728.json | 原候选独立结果 | 固定保存17/20、FAIL/NO_GO和准确来源证据，供新候选核查适用依赖 |

Given真实维护载入weighted-ratios且本人已有合法默认父查询，When公共boss.bi.follow_up明确覆盖scenario_id、source_ids和business_basis，Then实际新query_id绑定准确parent_query_id，继承当前/比较期间、产品、指标、地区及法人，overridden_fields为[business_basis,scenario_id,source_ids]，加权毛利率为14，四条明细和实际来源原文相符。父查询仍CURRENT，结果及初始八条资料摘要保持。

成功原请求在刷新、同库独立服务重启、历史和原编号读取时保留同一query_id，不执行第二次业务意图。相同成功请求验证幂等；同编号不同内容返回409。父来源撤销后公共追问返回410且不建立请求或运行。子来源撤销后实际Runtime保存FAILED和query_metrics/HTTPGone，没有子查询；界面通过原编号显示FAILED及NOT_FOUND_IN_CURRENT_STORE。观察时该失败动作没有WebSocket响应，报告仅以持久FAILED和只读回执确认失败，没有声明即时错误响应，也没有重放失败动作。成功子查询在来源撤销后按历史读取并显示HISTORICAL_REQUIRES_REQUERY。

## 决策与约束

本次产品变化限定领域资料读取顺序，没有修改字段、公开入口、Agent、前端、CSS或原生Client。owner/namespace/dataset、来源摘要、定义/明细、会话、模型冻结范围和权限继续执行实际核查。父子来源分别核查，不将子场景资料用于父查询绑定。

全部外部SIMULATED_FIRST，实际本地账号、SQLite、SDK、Registry和确定性工具执行。每次成功运行仅query_metrics/read_evidence，失败运行保存实际错误；usage/cost_total均null。task/authorization/outbox为零。视觉、真实模型质量、外部投递与设备安装NOT_RUN，STT暂停；用户预览、数据及其他角色目录保持。

## 验证与证据

| 验收 | 实际命令或入口 | 真实结果 | 适用版本与证据 |
|---|---|---|---|
| C03/C12/C13/C14/C19 | 当前组合六项新领域检查及三项受影响回归 | 9 passed，5.20秒，失败/错误/跳过均零 | evidence/feature-delivery/FC02/followup-integration.xml |
| C03/C10/C14/C15/C16/C17 | 真实MAINTAINER/BOSS、A04载入、默认父查询、实际公共boss.bi.follow_up、SDK、原文、刷新/同库重启、幂等/冲突、父子来源失效及失败原编号 | PASS；2查询、3运行、3公共请求；2运行成功、1运行FAILED；零业务写入和renderer错误 | evidence/feature-delivery/FC02/fc02-followup-e01e4b7a-3cf6-4881-aa78-add4d2b8f485.json |
| 相同领域组合的受限SDK消费者 | N1固定983b728采用同一领域差异，三个N2实际SDK入口 | 3 passed，6.92秒；仅采用该准确依赖证据，没有声明在N3重跑 | N1 .work/fc02-followup-sdk.xml，SHA256 ee033971f54b929c90e35c25b3a8f7ea131342a63a6f17ec05e3f77f6749a135 |
| 当前制品适用性 | 五份前端源码、patch、原生Client、manifest及index逐项SHA256核查；git diff限定产品变化 | PASS；当前制品可复用，没有重复构建或整套DOM | 当前公共验证启动断言及candidate.json |
| 工程检查 | git diff --check | PASS | 当前差异 |

领域命令为validation/.venv/bin/python -m pytest -q app/tests/test_fc02_followup_sources.py app/tests/test_fc02_bi_queries.py::test_fc02_followup_receipt_history_and_evidence_reopen app/tests/test_fc02_bi_queries.py::test_fc02_concurrent_same_request_creates_one_query app/tests/test_fc02_bi_queries.py::test_fc02_changed_definition_blocks_current_read_and_preserves_original_snapshot --basetemp=.work/pytest-followup-integration -p no:cacheprovider --junitxml=evidence/feature-delivery/FC02/followup-integration.xml --tb=short。

公共命令为BOSS_PRODUCT_FRONTEND_DIR指向当前目录fc02-n3-boundary-dist的绝对路径，运行node validation/desktop/check-fc02-followup.cjs。workdir均为N3目录；数据为validation/.work/fc02-followup-e01e4b7a-3cf6-4881-aa78-add4d2b8f485，端口9921/9922/19921，独立账号及Electron配置。程序保存实际查询、父编号、继承期间、来源、Runtime、错误、计数和摘要，不保存账号秘密。

N1六项领域及三项相关回归已在当前组合重新执行。相同组合的三个受限SDK入口覆盖默认父查询切换场景、同场景继承和模型替换来源拒绝；当前另行执行实际公共SDK路径，不用限定SDK证据代替公开验证。

## 制品与关联影响

复用fc02-n3-boundary-dist。manifest SHA256为633f8825cd5e62d2e2f5302e8b1ecd3df5cb1619bfcea10015e6cb404570b411，index SHA256为8418c85706ae46de4c34896339eccd45b4c8af0f24850a9da9fcf2d45e84bfd6，原生Client SHA256为48ae362a2d6ae0a3d817765a4e34459c3b77255e70bebd0205b7403c2fbe5527。五份正式前端及patch摘要保持candidate.json记录，程序启动逐项断言。无需再次应用原生patch。

N4对983b728已验证的17项作为原版本事实保存；C05/C08/C11的正式输入和公开结果无需重复制造。新候选仅领域三行变化，当前必要检查涵盖父子来源、继承、摘要/会话/权限、幂等、历史/原请求及SDK/公开消费者。其他通过结论由N4按准确依赖核查采用，不重复72/74项或FC01全量，不混合旧28项/192点。

## 未完成与继续条件

当前必要本地验证完成，完整FC02仍等待N4对准确新候选复验C03/C16和必要受影响范围。全部二十项PASS且N3确认提交、依赖及制品一致后，自动启用FC03并建立工单；此前不登记完整功能PASS。
