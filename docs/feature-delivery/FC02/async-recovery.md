# 初始回执与条件编辑的异步顺序

task_id：FC02-N4-UI-ASYNC-01，关联FC02.C03/C15。需求和状态引用原始FC02工单及specs/feature-delivery.json。当前IN_PROGRESS，N4对9026c8a的最新独立结果为12/20、FAIL/NO_GO。

已读取N4当前qa.md、verdict.json、timing-scoped-9026c8a.json、真实时序程序及HTTP/WebSocket代理。入口为真实老板查询后刷新F03，延迟已经由真实服务返回的初始回执，在用户编辑产品范围后交付同一响应字节。验收要求为保留编辑条件及未提交状态，较早回执不替换新条件或恢复旧答案。

本目录validation/desktop/check-fc02-timing.cjs及fc02_timing_proxy.py复用已核查的实际转发检查，使用独立9751/9752/19751、代理9753、账号和SQLite。代理只延迟交付真实响应，核查前后字节摘要相同，不替换数据或模型返回。较早原始依据响应晚于新查询的情况同时验证。外部SIMULATED_FIRST，视觉未执行。

当前状态IMPLEMENTED，完整功能等待N4在准确新候选复验。BossBIView.loadReceipt采用回执时同时核查认证范围、原请求顺序和generation；当前条件经过编辑后，较早初始回执不替换范围、未提交状态或结果。恢复期间保持合法条件可编辑；未带原编号的自动最近请求恢复也需要匹配初始化时的编辑状态。新查询或明确选择历史请求各自使用实际新请求状态。

真实时序检查PASS：evidence/feature-delivery/FC02/fc02-n3-timing-0aa94d7d-c7d7-49de-9bfc-6f198b3989f0.json。设置BOSS_PRODUCT_FRONTEND_DIR为本目录fc02-n3-history-dist绝对路径，执行node validation/desktop/check-fc02-timing.cjs。两项实际时序分别验证较早原始依据晚于新查询和较早初始回执晚于产品编辑；后者保留product-1、表格数量0、未提交提示数量1。两项原始响应交付前后的SHA256及字节数量分别一致，程序没有修改响应正文。

同一制品的来源撤销、同库重启、历史和原请求、权限、自然身份失效及12组DOM检查PASS，见history-recovery.md及对应当前证据。manifest为c66d167f9b6e7187dd47c1cb76db7350941153a3f9be98bf54d90585728a2475，TypeScript/Vite构建通过；正式源码与构建输入一致。领域、Agent及正式输入没有改变，没有重复无变化74项全量。

准确实现提交和候选记录以candidate.json及原始功能状态为准；N4需在同一新候选复验C03/C15及关联恢复。C05/C08/C11保留N1正式边界输入条件，不补造经营数据或双方来源许可；FC03尚未启用。
