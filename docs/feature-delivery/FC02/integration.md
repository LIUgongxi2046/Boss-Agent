# FC02 公共界面与集成

任务 FC02-N3，状态 IN_PROGRESS。当前功能与准确候选来源为原始项目 specs/feature-delivery.json，二十项检查点见 docs/FC02经营查询工单.md。当前公共组合已经具备独立验收入口，完整功能判定等待 N4；旧28项父任务、192点和FC01限定18/18分别保留。

## 接收与实现

接收 N1 fe3010563c6986eff6f0c26c1b5b2554d061cff6、4bcb0a937eaac5ae64031105ccfd2f7de413c8bb；接收 N2 15aeb1d1c61c50e5958565e2bb5c021c2b35fc79、738f5616ae03c951bd97c9abb4154de7937b79ef。领域代码、正式范围 Schema、Agent 工具与组合记录均在本候选内。全局索引登记各角色记录，原有未提交交接及原始证据保持。

validation/product_bi.py 提供认证请求生产者、独立请求工具范围、共享 Provider/Recorder 分派、原请求与实际 SDK request_id/run_id/session_id 的持久关联，以及维度、当前/历史读取、回执和取消。客户端只能提交问题、明确范围及原请求编号；owner、namespace、dataset 和 envelope 由当前认证与数据提供。query_metrics/read_evidence 使用同一正式组合 Schema，追问支持 comparison_scope 和明确新增可选字段，未指定字段继承持久快照。

application 使用同一实际 Nanobot AgentLoop。BI 请求仅开放 query_metrics/read_evidence，配置启用范围仍由维护身份管理；实际 Registry、模拟事件工具摘要和 Runtime 记录采用相同的两项工具。FC01 请求由原 FC01 Provider 和 Recorder 处理，BI 模块没有业务写入工具。模型参数必须匹配服务端冻结范围；模拟事件逐次消费本次实际工具返回，沿用会话历史时仍执行当前新查询。

RoleChannel 的 boss.bi.query、boss.bi.follow_up 和 boss.bi.cancel 使用当前账号、WebSocket、令牌有效期及本人角色。查询异步执行，取消只作用于该服务创建且属于当前数据范围的原请求。相同请求编号与相同内容读取保存结果，内容变化拒绝；取消、未知结果和来源变化后查询回执继续读取，不自动产生第二次查询意图。服务启动沿用 ProductRuntime 对未终止运行的恢复规则。

Runtime 保存 FC02、明确 SIMULATED 事件、真实工具摘要、查询编号、继承/覆盖字段、定义版本、明细与来源引用。问题正文和原始材料不进入技术记录，usage、cost_total 和 price_version 保持 null。公共读取继续执行当前来源、版本、摘要和本人数据范围核查；历史值明确表示是否需要重新查询。

## 公开入口与界面

GET /api/boss/ui/bi/dimensions 返回当前来源提供的维度、期间、指标定义和未知范围；GET /bi/query、/bi/receipt、/bi/history 分别读取已有查询、原请求及本人请求列表。全部需要 BOSS 身份，严格拒绝额外参数、重复字段和未登记路径。原始依据入口为 GET /api/boss/ui/metrics-evidence?query_id=...，实际明细与来源由持久查询读取。

F03/N03 使用 BossBIView，覆盖指标、地区/地区范围、产品、法人、当前与比较期间、币种、数量单位、交易范围、定义/目标版本、业务口径、结算、客户及资产/成本归属。可选未知信息保持 null。比较期间可以逐项明确指定业务条件，其余条件继承当前范围。继续追问显示父查询、明确覆盖字段及继承条件；修改问题或范围后清理旧结果和旧依据响应。

结果展示 BASE/CURRENT/CHANGE、对应单位、原始 Decimal 字符串、公式/定义与展示规则、可比性、覆盖及延迟/未同步未知、来源和更新时间、实际原始明细及资料缺口。来源入口使用当前查询返回的 source_id。刷新与重新登录后从持久原请求恢复范围和查询，不重新执行；当前来源变化后的历史结果进入重新查询状态。

字段标签14px/22px，输入、表格数值、正文和原始依据16px/24px；D01使用当前已接收原文Token。界面支持键盘与200%缩放，资料讨论不产生交办、批准或发送授权。没有客户端计算业务指标或预设业务答案。

specs/product-bi.openapi.yaml 0.2.0 登记全部公开输入、输出和 WebSocket 动作。实际请求保存前通过公共 Schema 校验，领域再次执行正式 SCOPED 校验；实际维度、查询、回执及历史输出通过公共规范验证。runtime-records.schema.json 支持FC01/FC02及准确BI字段，保持私人正文不可读取。

## 验证与准确制品

当前必要组合回归78 passed，13.80秒；证据 evidence/feature-delivery/FC02/integrated-final.xml。范围包含领域与Agent、实际SDK与共享Provider/Recorder、公开权限/来源、SQLite回执、FC01受影响准备消费者和Runtime配置。最终请求编号检查另见 public-runtime-green.xml。测试 basetemp 全部位于 validation/.work，没有采用 mock 或伪造业务返回。

标准 OpenAPI3.1 与 YAML 重复字段检查通过：.work/openapi-venv/bin/python validation/check_bi_public_spec.py。git diff --check 通过。没有复验无变化FC01业务全量或启用暂停的STT。

独立制品 fc02-n3-scoped-dist，TypeScript/Vite构建通过，15.42秒；在 .work/product/nanobot/webui 执行 npm run build -- --outDir ../../../../fc02-n3-scoped-dist。manifest SHA256为03ea8a455e7cdc5c49d6a30b57ca385bac575acc24fda23e64b2510a5c7413bc，index.html SHA256为68f2f03188c1dd44242c28b06e067ca0035275e0bf6dbb1984000747e2ccb08a。BossBIView、BossDesktop、CSS的正式源码与构建输入摘要分别一致。已有用户预览和FC01制品保持。

实际公开账号桌面检查 PASS：evidence/feature-delivery/FC02/fc02-scoped-33ace095-ecd7-447f-aefa-5ce0c52e14b5.json。运行命令为设置 BOSS_PRODUCT_FRONTEND_DIR 到本目录 fc02-n3-scoped-dist 的绝对路径后执行 node validation/desktop/check-fc02-scoped.cjs；使用独立9681/9682/19681端口、账号和SQLite。检查基线变化、product-1追问/4条明细、新比较条件不可比、实际两项工具及查询关联、刷新/重新登录恢复、401/403、文字Token、Enter/Tab和F03/N03/D01共18组窗口尺寸/缩放组合；renderer异常为零。

外部API和模型事件全部SIMULATED_FIRST，本地认证、权限、SQLite、确定性业务、实际SDK与工具执行。视觉、真实模型质量、外部投递和设备安装未执行。测试数量不计入FC02二十项分数。

## 独立接收

N4从原始 specs/feature-delivery.json 的 candidate_commit 检出准确提交，按完整工单二十项验证。公共组合已经接收全部领域/Agent接口；完整独立重启、异常路径及各项业务验收由N4提供对应候选证据。发现功能失败时记录准确入口、参数、预期、实际和版本，再执行必要修复及受影响复验。FC02继续IN_PROGRESS，当前没有启用FC03。
