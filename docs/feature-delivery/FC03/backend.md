# FC03-N1 晨间事项领域

task_id=FC03-N1。当前状态来源为原始项目specs/feature-delivery.json及完整docs/FC03晨间事项工单.md，唯一活动功能FC03，二十二项等待同一候选独立验收。2026-10-24接管HEAD=31b6313，原五项未提交内容保持。

已完整读取工单、当前状态、N3 integration.md与public-progress.json，核查TodayAPI、ControlStore、当前目标/会议/私人日历/任务/承诺/事件领域、PRD8.1及适用LLD。采用S008；当前新增正式逐日投影、持久清单/详情/来源、排序及回执，不修改公共Page/Command/RoleChannel/UI或N3的8769fbe恢复实现。全部外部能力SIMULATED_FIRST；视觉未执行，STT暂停。

正式范围使用date及timezone（IANA），不可由客户端提供owner/namespace。清单使用list_id、list_version、snapshot_sha256绑定当前集合/对象/来源，排序同时核查date、timezone及expected_version。旧TodayAPI无参数调用及旧排序输入继续兼容。新接口与完整验证在本记录维护，N2/N3从同一Schema接收。

## 当前正式接口（morning.schema.json 1.0.0）

| 入口 | 正式输入 | 当前输出与语义 |
|---|---|---|
| TodayAPI.read(role, day=None) | 旧调用无day；新day={date,timezone} | 无day继续原接口，新day委派MorningAPI.read，不创建清单或授权 |
| MorningAPI.read(role, day) | BOSS，Day | 当前逐日View，list_id/list_version为null；只读预览 |
| MorningAPI.query(role, payload) | BOSS，Query={client_request_id,session_id,date,timezone} | 保存View，产生list_id/list_version；同编号同内容幂等，失败或未知只按原编号查询，不生成替代请求 |
| MorningAPI.read_list(role,list_id,historical=False) | BOSS、正式清单编号 | ReadList={adoption_state,result,binding_references,current_order}。当前对象/来源变化拒绝当前采用；历史保留编号/版本引用，隐藏失效私人内容与派生区间 |
| MorningAPI.detail(role,list_id,item_id) | BOSS、清单内事项 | Detail，保持清单/事项/对象版本，实际对象和准备原文；business_authorization_granted=false |
| MorningAPI.source(role,list_id,source_id) | BOSS、清单内实际当前来源 | SourceDetail，返回匹配原文/作者/时效/位置；拒绝无关或失效来源 |
| TodayAPI.reorder / MorningAPI.reorder | BOSS，Reorder={list_id,date,timezone,client_request_id,expected_version,snapshot_sha256,item_ids} | OrderResult；完整集合、快照和CAS核查后仅保存本人次序。操作继续使用boss.today.reorder，保留N3原编号只读恢复与重连保护 |
| MorningAPI.receipt(role,action,client_request_id) | BOSS；action=boss.morning.query或boss.today.reorder | Receipt；查询回执只返回list_id/版本/日期/时区/快照元信息，排序原回执保留已保存结果，不重新执行 |
| MorningInputAPI.catalog/load/receipt | 仅实际MAINTAINER；CoverageLoad | 明确FC03-COVERAGE-1、seed20261024的正式覆盖状态；技术载入不签发本人业务授权，不能注册为模型工具 |

新Query不接收问题正文、owner/namespace/dataset或confirmed；真实公共会话负责产生身份、请求与session_id，N2冻结日期和时区并通过实际工具调用query/read_list/detail/source。模型不能选择排序或维护载入能力。客户端晨间问题由N2/N3正式请求维护，不写入普通领域审计。

View字段：source_type、date/timezone、day_start/day_end、business_clock、read_at、data_as_of、items/excluded_items、snapshot_sha256、order_version/ordering_reason、coverage_state/missing_sources、profile、conflict_state/conflicts、source_statuses/source_coverage、preparation_materials、list_id/list_version。Item严格定义item_id/kind/object_id/version、title/category/state/reason、coordinator_id、due_at/starts_at/ends_at、important、source_refs、sorting_reasons、goal_matches、existing_measures、page_id/target_id/read_only。未知作者、期限、来源观察时间与完整覆盖不能补造。

范围规则：会议、私人占用及出行使用实际完整区间与所选日相交，跨日区间按当日界限核查；准备期限到达时纳入相关会议。当前未结束承诺、交办、待决定申请及经营事件作为持续待办，期限表达到期/逾期/未来截止，有not_before时核查适用日；已结束、取消与历史分别表达。过去/未来日期仍依据当前有效资料，缺少当时状态或预测时明确列出限制。源文档时效按实际业务时钟核查，发布时间与观察时间分别保存。

排序按当前有效重要事件规则、分类、明确匹配的本人已确认目标、期限及稳定编号；本人已保存次序在重要风险之后生效，新增事项采用默认排序。日期与IANA时区隔离；默认原老板时区继续采用旧today_order日期键，其他时区使用独立键，旧已保存次序保留。清单快照不随个人排序改变，但对象/来源/覆盖/业务时钟/目标/规则变化需要复核；read_list.current_order表达当前已保存次序，result保持原清单版本。

## 当前实现与限定验证

实现位于validation/boss_morning.py、boss_morning_projection.py、boss_morning_inputs.py；TodayAPI只增加逐日读取与新版排序的委派，原调用保留。Schema与正式生成定义为specs/morning.schema.json及morning-coverage.json；基础OpenAPI的x-fc03-morning及LLD-data记录相同语义。维护载入与查询分开授权，普通审计只保存请求、日期、清单和版本元信息。

Given 获准selection/1与实际ControlStore；When 经正式本人目标确认/撤销、会议确认、私人日历修改/删除、本人承诺、申请决定、本人计划及提醒入口更新当前资料，再调用晨间接口；Then 当前清单、范围、分类、准备来源、重要风险和既有措施与保存记录对应，变更使原清单停止当前采用。查询和排序不创建交办、发送、审批、通知或派发。全部新增业务前置通过正式API产生，没有替换数据库正文或构造来源许可。

45 passed，3.90秒；可接收原始XML为本目录check.xml。包含22项晨间领域用例、3项原TodayAPI消费者及20项受影响会议/本人计划领域检查；用例数量不表示FC03完整检查点得分。日期与IANA错误、跨日及25小时夏令时、来源撤销/过期、生成覆盖与CAS、目标确认/撤销、重要规则改变、新事项、私人删除/历史内容、并发请求/排序及同库重建均有实际断言。

```bash
validation/.venv/bin/python -m pytest -q app/tests/test_fc03_morning.py app/tests/test_boss_today.py app/tests/test_boss_meeting_changes.py app/tests/test_boss_owner_plans.py --basetemp=.work/pytest-fc03-domain-release -p no:cacheprovider --junitxml=docs/feature-delivery/FC03/check.xml --tb=short
```

workdir固定为/Users/liuhaoxian/.codex/worktrees/boss-business/Boss-Agent，SQLite与中间结果位于已忽略.work。必要业务失败证据为.work/fc03-day-red.xml中的原TodayAPI缺少day输入；正式逐日消费者与当前完整领域结果分别见.work/fc03-day-verified.xml及本目录check.xml。没有启动服务或操作用户进程、预览与数据。未重复FC01/FC02完整验收。

## 接收边界

N2从同一Schema接收实际日期/时区、持久query及清单/详情/来源读取，可信会话产生请求和session_id；运行记录仅保留list_id/list_version及对象/来源编号版本。N3接收真实本人认证、F01日期与问题、晨间Runtime、清单详情/来源/关联会议及返回、明确排序确认与原编号只读恢复。原公共排序动作名与旧回执兼容，新的Query/coverage动作尚未注册公共入口，不能据本领域提交声明公共路径完成。

完整FC03二十二项等待同一公共候选和N4独立验收；当前独立分子null，不启用FC04。实际SDK组合、公共权限/页面/Client、构建与制品一致性按接收后的准确版本验证。全部外部能力SIMULATED_FIRST；真实模型质量、外部投递、设备和视觉保持NOT_RUN，STT暂停。原五项未提交的授权消费工作保持，未纳入FC03提交。
