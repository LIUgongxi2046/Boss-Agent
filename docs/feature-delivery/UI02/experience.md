# UI02 连续操作

启动入口为 scripts/run_ui02.command，源码目录为 /Users/liuhaoxian/.codex/worktrees/boss-integration/Boss-Agent。制品位于 ui02-n3-dist，准确候选引用原始 specs/feature-delivery.json 的 candidate_commit；摘要及源码清单见当前交付记录和 candidate-inventory.json。

此入口使用独立 ui02-experience 资料与 10411/10412/20411 端口。账号、SQLite、会话和 Electron 配置均与当前用户体验分开，不自动读取或替换现有体验资料。初始化采用已有正式模拟输入，外部模式为 SIMULATED_FIRST；启动器只核查既有初始化结果，不自动更改模型、规则或账号。

## 本人使用

1. 打开 scripts/run_ui02.command，在本人入口点击“测试账号注入”，随后明确点击“登录”。填充操作保留原服务端认证。
2. 使用已有业务入口查看报告、交办、提醒和本人计划。进入“大鹏会话”后，通过“当前会话”选择记录，也可以新建或搜索会话。
3. 原生输入、响应和已保存会话均采用原生客户端；当前演示响应明确标注 SIMULATED。返回业务页面保留当前业务对象，前进、返回及刷新使用原会话和实际保存结果。
4. Meta/Control+K 打开当前已交付目录，Tab 在对话框内移动，Escape 关闭并恢复焦点。短窗口可以在原生内容区域滚动操作。
5. 未发送输入在业务页面之间保留；切换其他会话前核查未保存提示。本人确认、保存和启用继续分别操作，结果未知时查询原编号，导航不会重新提交。

## 维护使用

退出当前身份后，从“技术维护”入口填入对应账号并明确登录。进入“应用设置”，选择实际分类；设置读取、保存及错误采用原生 Settings 控制器。编辑后可以继续编辑，或者保留编辑离开，返回时仍有输入。维护不能读取本人会话或受限业务正文。语音转写保持暂停。

准确验证入口为 validation/desktop/check-ui02.cjs 与 validation/desktop/check-ui02-business.cjs，报告位于 evidence/feature-delivery/UI02。当前开发结果与用户验收分别登记。视觉、真实外部模型质量、真实外部投递和独立安装未执行，当前界面外观由用户判断。
