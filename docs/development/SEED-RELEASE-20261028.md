# 仿真初始化与main提交

任务ID：`SEED-RELEASE-20261028`。唯一状态来源：`specs/feature-delivery.json`。源码基线：`9cd9888490521242def326f475c93823a68ec95b`及当前未提交修改。用户授权：提交并推送代码到main，将可以重建的仿真资料整理为初始化脚本一并上传。

## 依据与范围

已完整读取开发接手与执行规范、当前正式状态、`SIMULATION-20261028`、`ADMIN-MENU-20261028`、初始化源码、许可文档及文档同步记录。继续采用S008任务记录与实际验证要求。允许修改初始化脚本、对应测试、使用说明和任务记录，并提交当前已核查的产品源码、规范、许可及文档。现有桌面、9072实例、账号、业务记录、会话和模型配置保持；初始化验证使用项目内独立忽略目录。

资料来源为`specs/public-business-baseline.json`及`validation/boss_comprehensive_simulation.py`，真实经营基准和模拟人物、日期、任务与事件分别表达。初始化不复制当前数据库、已保存回答、会话、密码、令牌或模型密钥，不创建模型验证或评测成功记录。

## 验收

| ID | 行为 |
|---|---|
| SEED01 | 新目录通过正式脚本生成完整业务资料及本机随机账号，十四项接口非空，Boss与管理员读取同一空间。 |
| SEED02 | 重复执行保留已有本人操作、账号、配置及已保存资料，异常参数在写入前报告。 |
| SEED03 | 上传源码及公开基准足以执行初始化；依赖、构建、账号与模型配置说明可复用，敏感文件及运行产物不进入提交。 |
| SEED04 | 当前代码与相关文档经检查后提交至main，推送origin并核对远端提交。 |

## 当前实施

`scripts/prepare_comprehensive_simulation.py`提供创建及重复初始化，复用正式`populate`及`provision_accounts`。本次补充显式账号初始化、输入检查及两端资料规模报告。运行模型继续采用使用者在本机配置的凭据；初始化不发送外部请求。

## 验证与提交

19项初始化、幂等、异常输入、十四项业务接口及管理员投影检查通过，命令为`validation/.venv/bin/python -m pytest app/tests/test_simulation_initializer.py app/tests/test_comprehensive_simulation.py app/tests/test_admin_current_projection.py -q --basetemp .work/seed-release-20261028/pytest-final`，日志为`.work/simulation-20261028/initializer-final.log`。新目录及账号实际创建；重复执行保留本人取消记录、完整业务对象和原有随机密码；无时区、早于基准日期、不完整账号及无效配置来源均在业务写入前拒绝。

当前7项React及导航检查通过，源码未改变的5项History与32项认证DOM证据沿用管理员任务的明确版本；当前桌面及9072服务继续使用原进程。17份相关文档的288项本地引用、145项Schema引用、11项WebSocket动作及命令语法检查通过。Git机密检查与暂存差异格式检查通过。初始化及管理员资料检查程序随源码提供，不需要模型凭据；现有GitHub Actions配置保持。

公开验证摘要随源码保存于[evidence/simulation-20261028/verification.json](../../evidence/simulation-20261028/verification.json)，包含明确范围、公开基准摘要和已执行结果，不包含原始回答、会话或凭据。初始化使用说明见[仿真数据初始化](../仿真数据初始化.md)。已存在的未完成验收报告继续保留在本机，未纳入本次提交。

代码提交为`636ba070a0111adfccc587e225a972ae8e5d0a05`，已经推送到`origin/main`；`git ls-remote`确认远端main与该提交完全一致。通过GitHub连接核实当前账号与仓库所有者均为`LIUgongxi2046`，账号ID一致，具备push权限。仓库为公开的`LIUgongxi2046/Boss-Agent`。

最终提交内容检查覆盖85项文件、358项本地链接、28项Python语法和8项结构化文件；当前机密检查与差异格式检查通过。提交仅包含源码、初始化脚本、公开基准、测试、规范、许可、文档和不含私密正文的验证摘要。用户验收与完整产品未完成要求保持原状态。
