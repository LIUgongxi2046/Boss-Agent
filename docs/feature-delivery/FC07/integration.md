# FC07交办与承诺公共集成

task_id=FC07-N3；需求来源为原始docs/FC07交办与承诺工单.md、当前PRD迭代节及完整PRD第8.6节FR-06/BR-06/AC-06-S/E、BR-C02与E01—E06。唯一执行来源为原始specs/feature-delivery.json，baseline=boss-fc07-coverage-20261024-v1，共12项。当前开发证据覆盖工单限定要求，用户验收PENDING_USER_ACCEPTANCE；准确候选与构建摘要引用本目录delivery.json。文档CURRENT，last_verified=2026-10-24。

## 当前依据与检索

复用MVP候选931c8dd5a4b9c39c5044b940be057b683b0bc49a及原F06/N05，原MVP十二项用户验收仍待确认。读取当前PRD、计划、工单、HLD及LLD-data/backend/agent/frontend相关状态、身份和接口章节；检索开发索引、MVP01、任务、承诺、反馈、来源、提醒与Runtime记录。采用S008，完整限定要求保持不变。

N1正式c13996a43ec663fef639a375ff16c38f5f9d5774以2a845771f89852ae2c235edae7a42622f00cdfae接收：承诺当前来源、延期申请与单次决定、领域Schema及56项相关证据。N2正式c6834f96376d18f14793bc2a4c3e6c4ca568f282以198ae569c5ddbe881d26badd54569127b8272aa3接收：fc07_agent两项读取工具、Provider/Recorder及14项和认证撤销检查。candidate-inventory.json逐字节核查正式生产者模块；原授权消费未完成文件保持原归属。

## 当前实施范围与约束

| 文件与identifier | 当前行为及使用方 |
|---|---|
| BossDesktop、BossMVPView、BossTaskCenter | 从采购记录进入同一task_id；F06/N05与原文保持对象和返回位置，未保存编辑使用D06；任务与本人承诺分别管理 |
| BossAssignmentFlow、useTransaction | 目的、负责人、时区、期限、产物、版本、反馈证据、消息与授权可读；发送、催办、延期批准/拒绝、取消、完成分别确认；原未知请求仅查询回执 |
| BossPersonalCommitments | 创建前读取当前来源及版本，完成前独立读取当前证据；创建、延期、取消、完成使用正式服务，显示期限事件与修订历史 |
| BossAssignmentSourceReview | 读取正式来源Projection；本人来源确认保存原动作、对象和编号，刷新后仅查询原回执 |
| BossAssignmentPreparation、ProductAssignment | 真实BOSS请求冻结当前task/version和来源摘要，同一Nanobot执行两项限定读取；不同任务不采用旧编号，准备没有业务授权 |
| application、product_bi、product_mvp、RoleChannel | 使用同一现有Runtime；FC07请求限定两项读取，MVP成本查询限定原四项；服务端检查当前角色与有效连接 |
| BossCommandAPI、BossPageAPI、BossRecoveryAPI | 接收正式延期动作、历史和原回执；传播反馈证据版本/状态、历史标记、当前来源及承诺历史；私人正文仅BOSS读取 |
| nanobot-fc07-request.patch、原生Client | 交办、本人承诺及模拟反馈连接恢复后不重发；URL仅保存原编号、动作和对象，不保存私人正文 |
| prepare_fc07.py、run_fc07.command | 保留同一MVP资料及账号，经正常维护配置入口启用必要读取；使用独立制品，保留原MVP入口 |

公开字段见specs/product-assignment.openapi.yaml，Runtime字段见runtime-records.schema.json，相关LLD已同步。延期决定在同一领域事务执行独立本人授权、CAS和幂等；来源失效不能用于完成；取消后反馈仅入历史。任务结束仅停止其提醒，原经营事件保持独立状态。没有新增业务数据库或第二套任务状态，无DDL迁移。

保留MVP启动入口、资料、冻结制品和无关未提交内容。检查使用独立端口与SQLite，不操作用户正在使用的预览。正式FC07入口使用原MVP同一SQLite和账号。全部外部SIMULATED_FIRST，STT暂停，视觉未执行，源码由文件编辑工具维护。

## 当前验证

| 验收ID | 当前实际断言与原始证据 |
|---|---|
| C01 | 采购记录进入同一task_id，读取原文、刷新和返回保持对象；当前journey报告 |
| C02 | 当前来源读取后创建承诺，独立证据后完成；领域验证非空/有效来源和失效拒绝；journey、domain-check.xml |
| C03 | 分别发送和催办形成实际模拟消息及授权，未确认不发送；journey、恢复报告 |
| C04 | 正常维护反馈提交署名进展后IN_PROGRESS，原文/证据可读，重复反馈不重复生效；journey、公开检查及领域检查 |
| C05 | 申请保留旧期限，批准形成新期限，拒绝保留期限及理由；领域覆盖单次决定、并发和同编号异内容；journey、公开Schema检查 |
| C06 | 结果先进入RESULT_SUBMITTED；当前原文可读；领域覆盖缺少/换版证据及最新结果要求，来源确认不代替重新提交；journey、domain-check.xml |
| C07 | 本人完成后COMPLETED_CONFIRMED，期限事件CANCELED；领域确认经营事件保持OPEN；journey、domain-check.xml |
| C08 | 取消后迟到反馈仅入历史，任务持续CANCELED，消息保留、催办停止；journey、公开检查、领域检查 |
| C09 | 公共角色拒绝、严格Schema、日志正文排除；领域与Agent覆盖对象/空间/资料/confirmed注入及认证撤销；未注册本人决定工具 |
| C10 | 实际发送、来源确认、承诺创建成功后中断响应，每项原编号仅一次实际转发；刷新仅查询原回执，未知Escape关闭被拒绝、Tab焦点保持；重登/重启保持对象；恢复与journey报告 |
| C11 | 实际SDK/Registry读取当前任务/来源，Runtime通过当前Schema；同一Runtime后续MVP仅四项工具；Agent覆盖失败/取消/超时和撤销；public-sdk-schema.xml |
| C12 | 严格TypeScript/Vite通过；F06/N05三个窗口与100%/200%缩放无整页横向溢出，正文16/24；当前启动文件实际登录并核查已有业务记录保持；journey、launcher.json、inventory |

当前公共检查5 passed，11.14秒，原始public-sdk-schema.xml。生产者领域56项和Agent14项加认证撤销证据保持限定范围，没有换算用户验收数量。全部前置来自正式API、实际SDK、获准selection/1和正常导入；故障检查仅中断真实成功响应，不伪造响应或直接改写业务记录。准确当前报告由delivery.json关联。

```bash
validation/.venv/bin/python -m pytest -q app/tests/test_fc07_public.py app/tests/test_product_assignment.py app/tests/test_product_mvp.py --basetemp=.work/pytest-fc07-public-schema -p no:cacheprovider --junitxml=evidence/feature-delivery/FC07/public-sdk-schema.xml --tb=short
BOSS_PRODUCT_FRONTEND_DIR="$PWD/fc07-n3-dist" node validation/desktop/check-fc07-journey.cjs
BOSS_PRODUCT_FRONTEND_DIR="$PWD/fc07-n3-dist" node validation/desktop/check-fc07-recovery.cjs
node validation/desktop/check-fc07-launcher.cjs evidence/feature-delivery/FC07/fc07-recovery-a002cae9-f1e9-4315-873f-84233f270cde.json
```

workdir固定为/Users/liuhaoxian/.codex/worktrees/boss-integration/Boss-Agent。当前fc07-n3-dist采用已准备固定nanobot WebUI；BossDesktop及CSS镜像与正式源码逐字节一致，Flow/TaskCenter/SourceReview/MVPView导出canonical实现，新Preparation由canonical组件直接引用。原生Client保持现有补丁和当前fc07请求补丁；实际输入及制品SHA256见candidate-inventory.json。在.work/product/nanobot/webui执行npm run build -- --outDir ../../../../fc07-n3-dist，严格TypeScript/Vite通过，日志.work/fc07-build.log。没有执行自动改写源码的准备脚本。

## 交付与后续

启动入口和完整步骤见experience.md。当前macOS本机依赖现有Electron/Python环境，没有独立安装包或跨系统通过声明；无新真实外部模型或消息请求，usage/cost未知保持null。视觉及用户验收未执行。

完整工单开发交付单独登记DEVELOPED_PENDING_USER_ACCEPTANCE，原始状态保留MVP与FC07用户待验收历史。FC04通过完整工单和唯一活动状态接续，角色启动由原监督安排；没有创建聊天、子代理或向运行角色发送消息。
