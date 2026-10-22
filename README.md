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
