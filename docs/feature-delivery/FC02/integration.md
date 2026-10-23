# FC02 公共界面与集成

任务 FC02-N3，状态 IN_PROGRESS。当前功能与准确候选来源为原始项目 specs/feature-delivery.json，二十项检查点见 docs/FC02经营查询工单.md。当前公共组合已经具备独立验收入口，完整功能判定等待 N4；旧28项父任务、192点和FC01限定18/18分别保留。

## 接收与实现

接收 N1 fe3010563c6986eff6f0c26c1b5b2554d061cff6、4bcb0a937eaac5ae64031105ccfd2f7de413c8bb；接收 N2 15aeb1d1c61c50e5958565e2bb5c021c2b35fc79、738f5616ae03c951bd97c9abb4154de7937b79ef。领域代码、正式范围 Schema、Agent 工具与组合记录均在本候选内。全局索引登记各角色记录，原有未提交交接及原始证据保持。

接收N1正式场景9f44a1d4cb247c90afd5d7df5c8f9d62f884c7d3、2731df3fb9a6f6ffc405846a301505f0141ff1d5，对应当前f515905/4e6b8d6。六项正式生成场景及双方来源通过维护载入、本人维度和明确来源进入同一受限Runtime。A04维护、F03/N03选择和双方口径并列、D01实际作者与用途，以及连接中断后只读回执均已接收；详细依据、实现和复现见boundary-adoption.md。

validation/product_bi.py 提供认证请求生产者、独立请求工具范围、共享 Provider/Recorder 分派、原请求与实际 SDK request_id/run_id/session_id 的持久关联，以及维度、当前/历史读取、回执和取消。客户端只能提交问题、明确范围及原请求编号；owner、namespace、dataset 和 envelope 由当前认证与数据提供。query_metrics/read_evidence 使用同一正式组合 Schema，追问支持 comparison_scope 和明确新增可选字段，未指定字段继承持久快照。

application 使用同一实际 Nanobot AgentLoop。BI 请求仅开放 query_metrics/read_evidence，配置启用范围仍由维护身份管理；实际 Registry、模拟事件工具摘要和 Runtime 记录采用相同的两项工具。FC01 请求由原 FC01 Provider 和 Recorder 处理，BI 模块没有业务写入工具。模型参数必须匹配服务端冻结范围；模拟事件逐次消费本次实际工具返回，沿用会话历史时仍执行当前新查询。

RoleChannel 的 boss.bi.query、boss.bi.follow_up 和 boss.bi.cancel 使用当前账号、WebSocket、令牌有效期及本人角色。查询异步执行，取消只作用于该服务创建且属于当前数据范围的原请求。相同请求编号与相同内容读取保存结果，内容变化拒绝；取消、未知结果和来源变化后查询回执继续读取，不自动产生第二次查询意图。服务启动沿用 ProductRuntime 对未终止运行的恢复规则。

Runtime 保存 FC02、明确 SIMULATED 事件、真实工具摘要、查询编号、继承/覆盖字段、定义版本、明细与来源引用。问题正文和原始材料不进入技术记录，usage、cost_total 和 price_version 保持 null。公共读取继续执行当前来源、版本、摘要和本人数据范围核查；历史值明确表示是否需要重新查询。

## 公开入口与界面

GET /api/boss/ui/bi/dimensions 返回当前来源提供的维度、期间、指标定义和未知范围；GET /bi/query、/bi/receipt、/bi/history 分别读取已有查询、原请求及本人请求列表。全部需要 BOSS 身份，严格拒绝额外参数、重复字段和未登记路径。原始依据入口为 GET /api/boss/ui/metrics-evidence?query_id=...，实际明细与来源由持久查询读取。

F03/N03 使用 BossBIView，覆盖指标、地区/地区范围、产品、法人、当前与比较期间、币种、数量单位、交易范围、定义/目标版本、业务口径、结算、客户及资产/成本归属。可选未知信息保持 null。比较期间可以逐项明确指定业务条件，其余条件继承当前范围。继续追问显示父查询、明确覆盖字段及继承条件；修改问题或范围后清理旧结果和旧依据响应。当前来源、历史列表及原请求各自展示状态；来源410时仍可读取合法历史，HISTORICAL_REQUIRES_REQUERY明确显示且停止失效正文采用。实际401/403清理受保护内容并阻止其他响应恢复，具体实现和验证见history-recovery.md。

结果展示 BASE/CURRENT/CHANGE、对应单位、原始 Decimal 字符串、公式/定义与展示规则、可比性、覆盖及延迟/未同步未知、来源和更新时间、实际原始明细及资料缺口。来源入口使用当前查询返回的 source_id。刷新与重新登录后从持久原请求恢复范围和查询，不重新执行；当前来源变化后的历史结果进入重新查询状态。

字段标签14px/22px，输入、表格数值、正文和原始依据16px/24px；D01使用当前已接收原文Token。界面支持键盘与200%缩放，资料讨论不产生交办、批准或发送授权。没有客户端计算业务指标或预设业务答案。

specs/product-bi.openapi.yaml 0.3.0 登记全部公开输入、输出和 WebSocket 动作，含维护场景目录、载入与原回执、本人已载入列表、scenario_id/source_ids、来源选项和实际作者/用途。实际请求保存前通过公共 Schema 校验，领域再次执行正式 SCOPED 校验；实际维度、查询、回执、历史、场景目录和列表输出通过公共规范验证。runtime-records.schema.json 支持FC01/FC02及准确BI字段，保持私人正文不可读取。

## 验证与准确制品

当前24项正式场景及公共消费者PASS，另6项公共返回Schema与实际SDK消费者PASS，分别见boundary-consumers.xml和boundary-output.xml。维护目录与六场景实际载入、真实响应形成后中断连接、重连后仅转发一次并读取原回执、本人七项查询、双方100/120收入及各自原文、刷新和十八组尺寸PASS，见fc02-boundary-176212af-9f94-49fc-891f-04f8a7441691.json。加权毛利率14%，零分母及缺少利润保持null，延迟与未同步地区分别显示；实际7查询、7运行、6场景，原始selection资料摘要保持，task/authorization/outbox均零，renderer错误零。

同一制品的来源撤销后同库重启、历史及原请求、刷新、自然身份失效/重认证、退出、维护403、十二组历史尺寸和键盘PASS，见fc02-history-3984d0c8-83cb-4c2e-bc37-0307b28ab841.json。实际响应延迟检查PASS，见fc02-n3-timing-719b2fd4-0c29-4963-bdb8-95fe8532894e.json；较早回执不覆盖已编辑条件，较早原始依据不覆盖新查询，响应字节摘要在延迟前后相同。历史与异步主记录继续引用history-recovery.md、async-recovery.md，当前制品验证补充于boundary-adoption.md。

N4对faf66bf6c718b032e20a94231989894367a258c4独立确认16/20、BLOCKED，准确快照见independent-faf66bf.json。其74项证据运行于9026c8a，按301项依赖核查用于faf66bf；当前正式输入、Schema及公开消费者已有变化，新候选必须重新核查相应依赖，不能直接沿用旧分数。没有重复无变化74项全量或FC01业务全量。

标准 OpenAPI3.1 与 YAML 重复字段检查通过：.work/openapi-venv/bin/python validation/check_bi_public_spec.py。git diff --check 通过。没有复验无变化FC01业务全量或启用暂停的STT。

独立制品fc02-n3-boundary-dist，严格TypeScript/Vite构建PASS，15.14秒。manifest SHA256为633f8825cd5e62d2e2f5302e8b1ecd3df5cb1619bfcea10015e6cb404570b411，index.html SHA256为8418c85706ae46de4c34896339eccd45b4c8af0f24850a9da9fcf2d45e84bfd6。五份正式前端文件与构建输入摘要逐份相同。原生Client包含app/webui/nanobot-one-shot.patch的实际修改，连接恢复不重发场景载入；全新构建必须通过文件编辑工具采用该patch。具体输入摘要及构建步骤见candidate.json、boundary-adoption.md。已有用户预览和其他候选制品保持。

当前公开账号检查使用独立9841/9842/19841/9843、9761/9762/19761和9751/9752/19751/9753，均有独立账号与SQLite。新增场景的F03/N03/D01十八组尺寸与历史状态十二组尺寸均在当前制品通过；没有使用视觉功能。详细数据目录与命令见boundary-adoption.md。

外部API和模型事件全部SIMULATED_FIRST，本地认证、权限、SQLite、确定性业务、实际SDK与工具执行。视觉、真实模型质量、外部投递和设备安装未执行。测试数量不计入FC02二十项分数。

## 独立接收

N4从原始 specs/feature-delivery.json 的 candidate_commit 检出准确提交，按完整工单二十项验证。公共组合已经接收全部领域/Agent接口；完整独立重启、异常路径及各项业务验收由N4提供对应候选证据。发现功能失败时记录准确入口、参数、预期、实际和版本，再执行必要修复及受影响复验。FC02继续IN_PROGRESS，当前没有启用FC03。
