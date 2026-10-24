# MVP01采购成本连续体验

task_id=MVP01-N3。当前需求为原始项目docs/PRD.md MVP-1.0、specs/mvp-scope.json BOSS-MVP-1、docs/MVP01采购成本体验交付工单.md及决定D-MVP-20261024。执行状态由原始specs/feature-delivery.json唯一维护；MVP.C01—C12初始待核查，最终共同验收由用户与监督聊天完成。文档CURRENT，last_verified为2026-10-24。

## 已核查输入与当前范围

当前基线为10de6199e6d3a68f4fb7e44369f05ac1795c9e12。FC01采购计算/本人确认、FC02查询恢复及FC03真实账号/SDK/响应中断/DOM/构建证据按准确依赖复用。旧22项、28任务、23父任务、192检查点和后续队列保留历史；FC04—FC31为DEFERRED，不自动恢复。

读取当前PRD、MVP范围/工单/计划、FC01/FC02/FC03记录与候选摘要、SupplyQualityAPI、ProductFc01、BossSupplyQualityPanel、BossDesktop、RoleChannel、Electron启动及正式维护输入。当前采购场景为已有SI09模拟原料报告；两个期间的入库报告成本、单位和公式由现有领域确定性计算提供，不补造资料。

## 当前实现

今日入口、成本查询、原文和本人确认继续采用同一个采购报告。复用现有四项FC01读取准备工具、ProductFc01和本人采用动作，在公共层保存实际工具读取的查询结果及原编号，支持重新打开。本人明确确认前不创建协调任务；当前来源/版本变化由现有领域校验拒绝。

提供独立本机体验入口、账号位置、操作步骤、准确代码与制品。保持现有v6 Token、蓝绿白、Logo/大鹏与nanobot融合；当前导航限定MVP必要入口，其他已有实现保留。使用独立端口、SQLite及构建，保护用户预览。

ProductMVP继承现有ProductFc01，通过实际bossSupplyQualityRead、bossSupplyQualityQuery、bossEvidenceRead和bossSupplyQualityPrepare保存真实读取结果。两个期间的计算继续由现有SupplyQualityAPI完成。查询记录绑定当前本人、dataset/version、原请求、报告与全部来源版本/摘要；读取时重新核查报告及来源，当前报告失效时清除可采用结果。协调任务使用原有本人确认、版本核查和同意图幂等动作，任务关联不会使已保存采购报告失效。

BossMVPView在F01呈现报告选择、必要条件、两个期间结果、原文、本人确认、实际任务和查询历史。URL保留查询、来源与协调原编号；身份变化与选择更新采用epoch/generation、AbortController和读取序号保护。原生Client对boss.mvp.query和boss.fc01.coordinate禁止连接恢复重发。响应未知时只读原编号；明确本人确认前任务数量保持零。

RoleChannel在当前MVP范围注册公共读取、查询与取消入口。品牌资源使用标准URL解码并核查资源目录，返回实际文件及Content-Type；不存在或超出资源目录的请求返回404。prepare_mvp01通过真实维护账号、WebSocket正式导入动作和配置save/validate/activate初始化独立资料，不直接改写业务数据库。已完成目录只读取READY记录并核对范围、端口和制品摘要。

| 文件 | 职责 |
|---|---|
| validation/product_mvp.py | 现有FC01实际读取结果、报告/来源采用核查、保存查询及取消 |
| validation/application.py、role_channel.py | 当前执行范围、实际账号与会话、公共入口及品牌文件 |
| app/webui/BossMVPView.tsx、BossDesktop.tsx、boss-v6.css | MVP连续页面、必要导航、原编号恢复与既有v6样式 |
| app/webui/nanobot-mvp-request.patch | 在既有原生Client补丁之后禁止当前查询和本人协调重发 |
| scripts/prepare_mvp01.py、run_mvp01.command | 独立体验资料、正式配置和实际桌面启动 |
| app/tests/test_product_mvp.py、validation/desktop/check-mvp01.cjs | 当前连接的实际SDK、权限/来源、桌面连续流程及真实响应中断 |

## 验证与交付状态

开发状态为DEVELOPED，最终验收为PENDING_USER_ACCEPTANCE，MVP.C01—C12不登记共同通过。准确完整候选由原始specs/feature-delivery.json登记；本目录delivery.json保存实现提交、制品与必要证据，experience.md提供四项体验说明。

| 实际检查 | 命令与证据 | 结果 |
|---|---|---|
| 采购公共连接 | validation/.venv/bin/python -m pytest -q app/tests/test_product_mvp.py --basetemp=.work/pytest-mvp01-public-final -p no:cacheprovider --junitxml=evidence/feature-delivery/MVP01/public-query.xml --tb=short | 2 passed，10.81秒；实际SDK与四项工具、幂等、来源匹配、确认前无任务/授权、确认后单项任务、重读一致、无关来源与维护越权拒绝、来源撤回后禁止采用 |
| 当前桌面连续流程 | BOSS_PRODUCT_FRONTEND_DIR=当前工程/mvp01-n3-dist node validation/desktop/check-mvp01.cjs；mvp01-670717ca-08ef-4cdb-9d9d-7d37b1e73960.json | PASS；真实BOSS/MAINTAINER、必填条件、入库基期2000/本期2100 CNY/tonne、原文、明确确认、单项任务、刷新/重登/同库重启；查询与协调真实成功交付中断后各一次转发；维护403/匿名401；正文16/24、三尺寸及200%无整页溢出、renderer错误零；两份动画HTTP内容/摘要匹配、目录范围与404拒绝 |
| 实际体验入口 | node validation/desktop/check-mvp01-launcher.cjs；launcher.json | PASS；直接运行run_mvp01.command，默认9961/9962/19961与独立资料，隐藏Electron中真实本人登录及采购页面 |
| 工程 | .work/product/nanobot/webui中npm run build -- --outDir ../../../../mvp01-n3-dist；bash -n scripts/run_mvp01.command；git diff --check；cmp核对准备目录 | PASS；严格TypeScript、Vite 16.80秒；启动语法及BossDesktop/CSS输入逐字一致，MVP模块由显式export采用当前源码 |

公共桌面检查使用10071/10072/20071及10073代理。代理只中断实际成功响应的交付，没有替换接口或业务响应。默认体验资料与检查资料相互独立。检查结束后关闭自己启动的桌面及服务，用户运行入口时读取默认资料。旧FC01/FC02验收及FC03当前不变领域、实际SDK和来源消费者证据按原准确版本复用；FC03冻结制品摘要保持42c2e226574ea2e13dbb432586cbd893d86a37db37c391184e5d0de53d881208。

当前MVP制品为mvp01-n3-dist，manifest SHA256为279dfb0372e8abd63ae079cadf66ec6137deb6aabbb10da87c211afce5aae8cd，index SHA256为34a0b8f52ba9fe06d9a0479db6a6f59d5b3ff21163ae39bbd803a10612a4cbd0。原生Client SHA256为ee561f5b1757bb169f4820e25d27e7eaf6099b2bd2df91ead36502ee86edd4d5。构建输入在原FC03准备目录基础上通过文件编辑工具接收BossDesktop/CSS、BossMVPView显式export以及nanobot-mvp-request.patch；不运行会改写源码的准备脚本。

MVP.C08中必填、失败/未知状态及当前异步保护已经实现，来源失效有实际服务检查；空资料文案和较早响应保护由当前代码核查，开发证据不等同于完整用户验收。MVP.C09复用既有FC01领域与执行器的权限、版本、授权范围检查，新增公共入口有维护/匿名拒绝及来源失效证据。视觉、真实模型质量、外部发送与设备安装均未执行。

全部外部SIMULATED_FIRST，不新增真实请求；未知usage/cost为null，STT暂停，视觉/截图/图像禁止。开发完成后登记待共同验收，不能代用户登记通过。
