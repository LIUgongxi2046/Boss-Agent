# Boss-Agent · 老板专用 Agent

基于 **HKUDS/nanobot v0.3.5 + Electron 45.0.0 + DeepSeek** 改造，使用已确认的 **Boss-Agent Desktop v6.0** 蓝绿白高保真设计与“大鹏”IP。业务主体只有一位老板，技术维护身份独立，其他人员仅为模拟联系人或资料来源。

## 当前状态

- **架构**：T04 / A04 静态设计通过；`docs/HLD.md` 与 `specs/hld-72-page-map.json` 固定 72 页架构映射。
- **第一批前端与数据接入**：`app/webui/BossDesktop.tsx`、`app/webui/boss-v6.css`、`validation/boss_page_api.py` 已入库；实际业务指标由原有 Tool/SQLite 返回；提供身份受控的 72 页导航。尚未实现的页面不显示伪造操作成功。
- **开源源码不复制入库**：`scripts/prepare_boss_webui.py` 固定拉取上游 commit 并在本地私有目录叠加增量代码，保证上游可追溯且复用原生会话/设置功能。
- **开发和验收**：T11 正在进行，T05—T10 与 T18—T26 的完整专业设计/功能开发和产品验收仍有待办。没有声称已经在目标 Mac 安装/运行或通过视觉像素验收。

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
