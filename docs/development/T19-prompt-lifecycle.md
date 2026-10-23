# A05 Prompt 版本配置和运行上下文采用（T19）

日期：2026-10-23。实现状态：**部分技术功能真实接入；A19、A24、Mac 高保真视觉验收仍未通过**。

## 与 PRD / Desktop v6 的对应

参照 [PRD](../PRD.md) 中 FR-24、FR-26、FR-30、WF-AD05，以及原始高保真页面
`Boss-Agent-Desktop-Complete-v6/pages/A05-Prompt版本.html`。
页面沿用既定 Logo、大鹏形象、蓝绿白、左侧模块、中央编辑区域、右侧版本/工具边界布局。
所有 UI 差异仍需在目标 macOS Intel 上由截图与原稿逐页对比，**目前不存在像素级验收回执**。

## 本批已完成的真实功能

1. **草稿**：MAINTAINER 身份在 A05 保存 Prompt，支持秘书职责、表达要求、任务提示三类。后端在 `validation/boss_prompt_config.py` 固定类型、标题/长度/变更说明和最多五条来源 ID，来源每次用当前权限、文档版本进行校验；拒绝疑似 Key 的内容。草稿使用 CAS 版本并在 SQLite 保留历史。
2. **静态校验**：同一 Prompt 当前版本通过结构及来源检查才进入 `VALIDATED_STATIC_ONLY`。这是静态约束检查，**不是模型质量、防注入或独立评测**。
3. **启用和停用**：仅技术维护人可执行 `boss.prompt.activate`、`boss.prompt.deactivate`。当前活跃指针按类别保存并有版本冲突保护，不修改老板业务操作权限。
4. **真实采用边界**：启动中的 `validation/application.py` 的 `RuntimeContextBlock` 每次调用时读取 `active_runtime_prompts`。新加 `record_runtime_context_load` 在正式 SQLite 写入该 Prompt ID/版本/哈希、运行上下文调用次数与时间，**不记录 Prompt 正文、老板记忆、API Key 或模型内部推理**。激活后若还没有真正的上下文调用，状态显示 `NOT_OBSERVED`；上下文被读取时显示 `RUNTIME_CONTEXT_PROVIDER_INVOKED`。被停用或来源失效的旧版本不再进入下一轮上下文，也不产生新的采纳记录。
5. **v6 A05 页面**：`app/webui/MaintainerPromptVersion.tsx` 提供类别切换、草稿编辑、来源、变更原因、当前校验和启停、历史文本逐行差异、最近实际加载时间、原始幂等回执重查。前后端均校验角色；同名、旧版、未经校验或过期来源不能作为当前版本生效。

## 权限和实际能力界限

Prompt 技术配置与老板身份、业务授权、工具权限分开管理；它不能让 MAINTAINER 代替老板发送消息、批准申请、确认交办完成或读取私人正文。当前源代码在运行时设置独立的 `guidance_authority_boundary`，但该提示本身不是安全边界；BOSS 写入还需由 `RoleChannel` 和 `BossCommandAPI` 执行服务端检查。

上下文调用次数只证明该配置已被传给 nanobot 上下文构造过程，**尚不能证明它完成了一次 DeepSeek API 请求，无法证明模型真的正确采用、更不能代表通过最终评测。** 真实 Prompt/模型质量测试仍需独立运行并记录模型版本、调用 ID、用量和最终结果。

## 本轮验证和未完成事项

新增 `app/tests/test_boss_prompt_context_adoption.py` 验证配置保存/校验/启停、角色隔离、停用与来源撤销后不再加载、真实上下文钩子记录次数、无私密正文进入记录、旧版本可审阅，以及 v6 页面动作映射。CI 内只使用合成资料，未使用任何真实 DeepSeek Key。

待办：完整 Prompt 自动化质量评测、SOP 和 Tools 实际采用一致性、不同会话与模型请求关联、Mac 实机的加载与 UI 逐页截图比对、E01—E06 异常及冷启动恢复，以及 T24/T25/T26 的交付验收。项目总体状态保持开发中，不能因配置界面可用而将 A05 或 A19 标为完整 PASS。
