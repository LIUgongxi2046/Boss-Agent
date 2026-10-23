# FC02 公共界面与集成

task_id：FC02-N3；当前IN_PROGRESS，二十项完整验收来源为原始项目docs/FC02经营查询工单.md及specs/feature-delivery.json。文档有效性CURRENT，核查日期2026-10-24。产品基线c4bc673，保留已有未提交交接及原始证据。

## 输入与当前代码

已读取FR-03完整8.3、经营指标12.1、公共权限/来源/异常规则、适用LLD、F03原始设计文字、BossDesktop的F03/N03及BossPageAPI._metrics、boss_metrics.py与对应检查。现有query_metrics/read_evidence及query_source_binding继续使用；F03当前产品选择、BASE/CURRENT表及固定来源入口尚未满足完整连续查询、变化量、可见上下文和原始依据展示要求。

FC01限定验收18/18 PASS已核实，保存于../FC01/acceptance.json；集成HEAD与该候选一致，manifest摘要匹配N4。旧28项父任务及192点没有改变。当前只推进FC02，不复验无变化FC01业务。

## 四角色接收与继续条件

N1提供当前查询/比较/覆盖/来源及持久恢复接口、Schema和准确提交；N2提供BI专有工具、可信上下文及明确模拟事件接口；N3负责公共认证/请求生产者、F03/N03/D01完整界面和统一Runtime注册；N4依据当前工单建立二十项独立验收。角色记录为各自目录docs/feature-delivery/FC02。当前候选尚未发布，必要新字段尚待正式接收，不能根据固定基线缩减工单。

当前可独立执行：核查现有公开查询范围与结果消费者、F03精度/变化/来源展示及请求范围变化后的状态行为；依据现有正式字段进行修复与必要真实验证。完整可编辑维度和Runtime连续追问在领域/Agent接收版本明确后接入，不能自造字段或模型权限。

全部外部SIMULATED_FIRST；本地账号、权限、SQLite、来源及实际工具执行；视觉NOT_RUN，STT暂停。不操作默认预览、其他角色目录或进程。独立数据/端口/构建仅用于当前变化的必要验证。
