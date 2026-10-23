# Boss-Agent · 老板专用 Agent

基于 **HKUDS/nanobot v0.3.5 + Electron 45.0.0 + DeepSeek** 改造，使用已确认的 **Boss-Agent Desktop v6.0** 蓝绿白高保真设计与“大鹏”IP。业务主体只有一位老板，技术维护身份独立，其他人员仅为模拟联系人或资料来源。

## 当前状态

- **架构**：T04 / A04 静态设计通过；`docs/HLD.md` 与 `specs/hld-72-page-map.json` 固定 72 页架构映射。
- **第一批前端与数据接入**：`app/webui/BossDesktop.tsx`、`app/webui/boss-v6.css`、`validation/boss_page_api.py` 已入库；实际业务指标由原有 Tool/SQLite 返回；提供身份受控的 72 页导航。当前 13 页部分接入代码，59 页仍待正式业务实现；尚未实现的页面不显示伪造操作成功。
- **开源源码不复制入库**：`scripts/prepare_boss_webui.py` 固定拉取上游 commit 并在本地私有目录叠加增量代码，保证上游可追溯且复用原生会话/设置功能。
- **开发和验收**：T11 正在进行，T05—T10 与 T18—T26 的完整专业设计/功能开发和产品验收仍有待办。没有声称已经在目标 Mac 安装/运行或通过视觉像素验收。

## 本机 DeepSeek 凭据配置（已支持用户提供的文件）

**不要把 API Key 写进终端命令、代码、截图或 GitHub。** 本次上传的凭据仅核验了格式；本机的软件通过服务端文件引用读取，不在 GitHub Actions 中使用真实 Key。

请将已提供的 `boss agent.md` 保留在本机项目根目录（如果原先就在这个位置，无须重复复制）。首次在本机运行：

```bash
python3 scripts/configure_local_deepseek.py
# 文件保存在其他本机目录时可用 --source 指定文件路径，不要传 Key 本身
# 需先安装 validation/.venv，才能进行真实 API 检查
cd validation && uv sync --locked && cd ..
validation/.venv/bin/python scripts/check_local_deepseek.py
```

`scripts/configure_local_deepseek.py` 只创建 Git 忽略、权限 0600 的本地密钥文件和无密钥的连接引用。真实连通性检测可能有少量模型费用；成功回执只含模型标识、响应 ID 与 Token，不保存 Key 和正文。启动桌面研发版后，可运行 `validation/.venv/bin/python scripts/check_local_boss_agent.py` 做本机真实 DeepSeek 会话与模拟经营查询联调。

## 本地开发（macOS Intel）

前提：Git、Node.js 24、Python 3.12、uv、可用的网络及本机授权的 DeepSeek 密钥。首次克隆项目后：

```bash
python3 scripts/prepare_boss_webui.py --build
cd validation && uv sync --locked && cd ..
npm --prefix validation/desktop ci
bash scripts/run_boss_local.sh
```

登录使用本地生成的 `validation/.work/application/access.json` 中的 BOSS 或 MAINTAINER 凭据，请勿提交或分享该文件。模型密钥只能通过服务端引用配置；不要放在仓库、前端或命令参数。

```bash
python -m pytest -q app/tests/test_boss_page_api.py
```

实际构建、单测状态看 [GitHub Actions](https://github.com/LIUgongxi2046/Boss-Agent/actions)。桌面宿主目前仍引用开发态 Python 工程，**不是正式的已签名可分发应用**。详细范围、问题和后续任务见 [首批开发记录](docs/development/T11.md)。

## 文档

[产品 PRD](docs/PRD.md) · [最终 HLD](docs/HLD.md) · [72 页实施映射](docs/HLD-72页面实现映射.md) · [高保真 v6 预览](Boss-Agent-Desktop-Complete-v6/index.html)


## 第二批交办闭环（开发中）

F06 采用服务端事务完成“创建交办→模拟发送→维护端模拟反馈→老板确认完成/批准延期/取消”链路；由 nanobot 已认证 WebSocket `requestMutation` 转到 `RoleChannel`，在同一个 SQLite 事务写授权、对象状态、幂等回执及最小审计。MAINTAINER 只有模拟反馈能力，无法代老板决定。T18/T19 整体功能仍未完成，详见 [老板端开发记录](docs/development/T18.md)、[维护端开发记录](docs/development/T19.md) 和 [72 页当前实现状态](specs/page-service-map.json)。

本机 Desktop v6 UI 截图与原图差异核查：

```bash
cd validation/desktop && npx playwright install chromium && cd ../..
node scripts/visual_qa.cjs --role BOSS --pages F01,F06,N02,N05
python3 scripts/visual_diff.py --role boss
```

这些命令要求本地研发版服务已运行；Pillow 仅在差异分析阶段额外安装。截图存于忽略的 `.work/visual-qa/`，绝不表示目前已经完成 72 页像素验收。


## 第三批：真实模型运行可观测（待 Mac 联调）

F24 老板运行详情与 A15 维护记录可读取本机 DeepSeek 实际响应 ID、请求次数、Tool 事件、Token 用量及未覆盖费用范围，模型没响应过就明确展示“未观察到”，不会将配置状态冒充实际运行。真实模型测试、真实 Electron 交互和最终 v6 像素比对仍待目标 Mac 运行。

[DeepSeek 接入开发记录](docs/development/T16.md) · [72 页现有组件与 API 接入状态](specs/page-service-map.json) · [GitHub Actions](https://github.com/LIUgongxi2046/Boss-Agent/actions)


## 第四批：会议纪要与模拟审批

F05 采用意见、建议、明确决定和交办草稿四类分类，真实保存纪要与来源/版本，老板明确确认后才记录已确认纪要；不会自动给联系人发交办。F07 先在 A03 明确录入模拟申请及附件，老板才能按当前版本和 CNY 金额/附件逐项决定同意、拒绝或请求补充。请求补充后由维护端按版本更新材料，旧审批对新金额失效；无资金交易或专业放行。

本轮 Desktop v6 还校正 1440×1024 主视口的 204px 侧栏、64px 顶栏、146px 主 Hero / 122px 紧凑 Hero、20px 圆角及 278px 右侧信息栏，并在 1024px 下切换 60px 图标侧栏。请参考 [F05/F07 开发记录](docs/development/T18-meeting-approval.md)。视觉截图检查脚本已支持源尺寸比较，但**目标 Mac 的真实截图和最终像素级验收仍未完成**。

## 第五批：F08 消息与 F12 私人安排

F08 实现版本化草稿、本人单独确认模拟发送、模拟发件箱和署名模拟回复，关联已独立发送的交办时更新真实进展但不自动标记完成。FR12 私人日程支持 BOSS-only 编辑、删除和仅 busy/起止时间/时区的模拟分享及撤销，技术维护端无法读取私人正文。真实外部发送、实际日历共享与彻底擦除备份不在已完成功能范围。

[业务实现与测试记录](docs/development/T18-message-calendar.md) · [72页实施映射](specs/page-service-map.json)。界面沿用固定 Desktop v6 品牌与交互规格，但尚未通过目标 Mac 的逐页截图像素对照。


### 功能先于数据：当前交易与失败恢复

针对 F05/F06/F07/F08/F12 和记忆/提醒动作，已增加受本人或维护角色约束的**原始幂等请求回执重查**，并补了 F08 任务发送边界、联系人有效期、附件去重、F12 工作会议冲突的服务端预检与失效 busy 分享预览。不会把模型超时直接当成“没有执行”，也不会在没有真实外部通道时宣称送达。

具体覆盖、接口和剩余未通过项见 [F08/FR12 迭代记录](docs/development/T18-message-calendar.md) 与 [逐页映射](specs/page-service-map.json)；本次未扩充农业样本或模拟指标数据。


## 第六批：F04 会前材料功能闭环

按照 PRD FR04 和原始 Desktop v6 F04 页面，新增真实的会前材料准备业务：从目前已获准的会议、参会人 ID、历史承诺、已发送和待办任务、有效文档来源及固定现有经营明细形成**可核查的材料状态**；保存时使用 BOSS-only、CAS版本校验和 SQLite 幂等事务，后续撤销资料或新增关联交办会触发 NEEDS_REVIEW，不静默重写历史。

UI 恢复原稿 4 项筛选与“议题/历史承诺/待决定/材料缺口”四页签，继续沿用既定 Logo、大鹏素材、卡片与左右栏结构。缺口索取由本人明确确认后只保存 F08 DRAFT，**不自动发送、不标记会议举行**。尚缺真实企业会议、会议信息改期、准备期限来源和真实外部资料发送等能力；高保真截图/目标 macOS Intel/DeepSeek 联调仍需完成，不能将本次部分实现写成完整 PRD 验收通过。

[完整开发记录](docs/development/T18-meeting-brief.md) · [逐页实施映射](specs/page-service-map.json)。

## 第七批：F05 确认纪要逐项交办到 F06

按 PRD FR05/FR06 新增一次性、版本化的纪要条目关联交办：只有已确认纪要的 ASSIGNMENT_DRAFT 才能在本人逐项核对负责人、期限、证据并单独授权后创建 OPEN 任务；独立 F06 再确认才可模拟发送。F05/F06 能相互回查纪要版本、条目ID、来源与当前任务状态；并发重复提交只有一个任务，重新确认的新纪要版本可以另行授权，不覆盖旧任务。失效来源的历史引用仅保留类型和元信息，不返回撤销前的正文。

该功能仍是获准模拟业务，不包括真实收件投递和 macOS 实机像素验收。[业务实现和安全记录](docs/development/T18-minute-task-chain.md) · [72页映射](specs/page-service-map.json)。


## 第七批：A05 Prompt版本生命周期

A05 现有独立的技术配置页面，可保存/校验/启用/停用 Prompt 版本、对照上一历史修订，并通过真实 nanobot RuntimeContextBlock 的调用记录查看已启用配置是否被运行时加载。草稿、静态校验、启用指针与运行采纳**分别持久化且状态不同**；没有观察到实际加载时不会显示成功。本功能不会修改老板业务授权或 API Key。

详见 [A05 Prompt开发记录](docs/development/T19-prompt-lifecycle.md)。实际 DeepSeek 接口完成、模型质量评估及目标 Mac UI 像素级比对仍待完成。


## 第八批：F06 独立催办与 A13 技术调度

新增由老板单独授权的 F06 模拟催办，在任务已发送且处于等待或进行中时，严格校验稳定收件人、来源版本和模拟时间，24 小时内重复催办由服务端拒绝。F06/N05 查询同一条实际 SQLite 模拟催办记录，送达、回复与完成仍分别核查。

A13 技术维护端已支持调度草稿保存、规则校验、启用、暂停、恢复、取消，以及在已启用的模拟技术计划下对**一个指定事件版本**执行手动模拟调度。手动动作与原 CronService 复用相同的到期、静默和去重逻辑。模拟数据库里的 DELIVERED 并不证明真实系统通知或外部收件人已收到。被取消的原计划不可自动恢复。所有调度配置与老板业务授权分开。

[调度与催办开发记录](docs/development/T17.md) · [逐页实现映射](specs/page-service-map.json)。本次仅新增功能代码和测试，目标 Mac 休眠唤醒、系统通知权限、真实调度恢复和 v6 逐页像素对照仍未验收。
