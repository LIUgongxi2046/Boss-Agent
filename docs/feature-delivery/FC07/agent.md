# FC07 Agent开发记录

task_id=FC07-N2，当前明确对象的读取/来源及SDK适配IMPLEMENTED，等待N1必要新语义与N3公共接收；需求来源为原始docs/FC07交办与承诺工单.md、PRD当前迭代节及完整FR-06。稳定分母12，开发完成与用户验收分别记录；MVP用户验收仍待确认。代码基线42f949e，公共接收基线931c8dd。核查日期2026-10-24，文档有效性CURRENT。

已读取当前PRD、迭代计划、工单、功能状态、SOP06主记录、适用AGENTS.md、HLD身份边界及LLD-agent交办/授权章节。原始feature-delivery尚保留MVP状态，按最新明确指令推进FC07，正式更新归N3。继续采用S008开发与记录规范，不修改公共文件或领域状态。

当前现有接口：BossTasksReadTool读取本人任务与承诺投影；BusinessTool/read_assignment读取正式任务状态；BossAssignmentSourcesReadTool/AssignmentSourcesAPI读取当前来源、版本及结果证据资格。create_assignment/send_assignment已由Fc01Tool消费已有授权，身份、内容、幂等与授权由可信生产者提供。SOP06的催办/延期/取消/完成/来源确认均属于本人页面动作，不能直接注册其自动签发授权的领域入口。新增授权消费语义等待N1准确接口；不接收未验收boss_authorized_execution文件。

当前必要补充限定为当前任务的版本/来源绑定读取及实际Runtime链路；准备结果供本人页面核查，不能从模型表达生成本人决定。

## 接口接收清单

| 接口 | 当前职责与采用方式 | 版本/状态及使用方 |
|---|---|---|
| BossTasksReadTool / BossPageAPI任务投影 | 本人任务、反馈、承诺和来源审阅；零业务写入 | 既有接口复用，公共TaskCenter及列表读取由N3保持；不把本人承诺ID当作交办task_id |
| BusinessTool/read_assignment | 正式task_id输入，可信envelope注入，实际Store.invoke返回当前任务 | 本次Fc07ReadTool复用，模型不能变更当前选择的task_id |
| BossAssignmentSourcesReadTool / AssignmentSourcesAPI.read | 返回当前task版本、来源pinned/current版本、binding_state、review_sha256和结果证据资格 | 本次工具复用，失效来源保持明确状态且无原文片段；不确认来源或完成任务 |
| Fc01Tool/create_assignment、send_assignment | 复用已存在本人授权，完整内容摘要、authorization_id及idempotency_key由可信生产者绑定 | 不重新实现、不自动注册；N3确有当前已授权执行请求时按既有工厂选择准确集合 |
| Fc01Tool.receipt(params) | 原幂等键及内容摘要读取，零重放 | 已有授权消费的只读恢复；本人页面原请求继续使用原正式恢复入口，不新建编号 |
| 本人创建/发送/催办/延期/取消/完成及承诺动作 | 当前对象、来源、内容、版本和确认分别经真实本人页面核查 | 不作为模型确认工具。新增延期决定/承诺来源条件等待N1准确提交后由N3接收 |

当前完整语义缺口由N1负责：本人承诺创建的非空来源，延期申请合法期限，以及批准/拒绝单次决定和可重读旧/新期限及理由。N1当前记录基线9fa1600，FC07正式增量尚未提交；本次没有读取或恢复未验收授权消费文件，也没有为未来接口添加猜测字段。

## FC07专有适配

版本1.0.0，validation/fc07_agent。register_fc07_tools(registry,store,context_provider)仅注册read_assignment、assignmentSourcesRead；重复名称在修改Registry前拒绝。参数沿用当前正式Adapter，额外confirmed/owner/envelope等输入被拒绝。该集合专用于明确选中的已保存交办，不扩展到本人承诺写入或通用页面访问。

Fc07Context字段为role、owner_id、namespace、dataset_id、dataset_version、request_id、session_id、active、task_id、task_version、review_sha256。N3从真实本人会话、当前选中任务与AssignmentSourcesAPI实际输出建立上下文；任务与来源摘要必须来自服务端当前资料，不能依据待执行模型参数即时生成绑定，不能把构造dataclass当作生产身份或授权。

每次调用核查当前BOSS、有效空间、owner/dataset、实际任务版本及当前来源复核摘要；实际Runtime还核查同库、namespace、request_id、session_id及sender_id。调用前后重新读取范围，页面换任务、反馈导致版本变化、来源/证据换版或身份失效时停止旧请求。当前来源已失效时，新绑定只能读取正式NEEDS_REVIEW及缺少条件，不能恢复失效原文或把任务改成完成。

Fc07SimulatedProvider使用async(messages,tools)->LLMResponse明确模拟事件接口，严格检查两项工具集合。实际Nanobot/AgentLoop/Registry先调用read_assignment，再从实际返回task_id调用assignmentSourcesRead；模型输出的状态和来源资格取自实际结果，owner_decision_required=true只表示交接本人页面，不代表业务已经发送或完成。没有网络客户端或预设成功、自动重试、模型签发授权。

Fc07RuntimeRecorder/Fc07RuntimeHook复用现有准入、工具定义/实现摘要、配置/Prompt版本及终态，feature_id=FC07、source_type=SIMULATED。assignment_context关联task_id/task_version/review_sha256；tool_results关联实际任务状态与版本、来源pinned/current版本、复核摘要和结果摘要，不保存purpose、问题、原文片段、私人正文或凭据。失败/取消/超时及撤销后保留已读取对象引用，未知usage/cost_total/price_version为null。contract.py的interface_contract提供实际两项Tool Schema、上下文字段和技术记录接收字段。

## 当前限定证据

准确领域/公共基线931c8dd5a4b9c39c5044b940be057b683b0bc49a；独立检出validation/.work/fc07-mvp931，其他角色目录只读。检查前置通过正式SupplyQualityAPI维护导入获准supply-quality-v1.yaml，再由明确BOSS协调入口保存一项任务；没有伪造授权、来源或改写数据库业务记录。

check.xml：14 passed，10.25秒。覆盖任务与来源读取同一task_id/版本、零新增任务/消息/授权、角色/身份/空间/数据/任务/来源版本拒绝、模型换任务及confirmed注入、来源撤销停止旧绑定及隐藏原文、实际SDK消费当前任务及来源、失败/取消/超时和技术日志正文排除。revocation.xml：1 passed、14 deselected，5.28秒，只补查SDK读取后认证撤销停止后续工具并保留首项引用。源码未影响的检查没有重复运行。两个结果不换算十二项功能分数。

```bash
env PYTHONDONTWRITEBYTECODE=1 FC07_DOMAIN_ROOT=/Users/liuhaoxian/.codex/worktrees/boss-sop-writes/Boss-Agent/validation/.work/fc07-mvp931 validation/.venv/bin/python -m pytest app/tests/fc07_agent -q -p no:cacheprovider --basetemp=validation/.work/fc07-agent-check --junitxml=validation/.work/fc07-agent-check.xml
```

workdir固定为/Users/liuhaoxian/.codex/worktrees/boss-sop-writes/Boss-Agent。数据库与中间结果位于已忽略validation/.work。socket.connect审计拒绝外部请求；没有启动服务/端口或操作用户预览，没有运行FC01/FC02/FC03全量、视觉或用户验收。

## 公共接收与必要剩余

N3接收本独立模块，提供真实认证与当前对象生产者，采用请求级两项工具集合、Fc07SimulatedProvider及Fc07RuntimeRecorder，并接收contract.py技术扩展Schema/构建依赖；本人决定继续交接F06/N05。现有准备内容及合法已有授权执行继续复用，不因目录或方法名称增加模型权限。

等待N1当前必要新语义的准确提交、Schema及状态/回执要求，之后只补查受影响字段与实际消费者；N3负责公共完整连续流程和准确可启动候选。本次适配及限定证据不能登记FC07十二项开发完成或用户通过，不同步开发FC04。MVP共同验收仍保持PENDING；真实模型质量/外部送达/视觉未执行，STT暂停。
