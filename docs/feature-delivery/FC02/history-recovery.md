# 来源失效后的历史查询与原请求恢复

task_id：FC02-N4-UI-HISTORY-01；需求来源为FC02工单C12/C14、PRD来源采用与持久恢复规则。唯一功能状态来源为原始项目specs/feature-delivery.json；本项IMPLEMENTED，当前FC02 IN_PROGRESS，完整功能等待N4对准确新候选复验。N4对9026c8a的最新独立判定为FAIL/NO_GO，12/20通过。

已读取N4的qa.md、verdict.json、withdrawn-ui-9026c8a.json，以及当前BossBIView、领域历史/回执接口、真实账号和桌面程序。修复范围仅为本目录公开界面及其必要检查，领域保持当前来源拒绝和合法历史读取规则。使用S008；文档有效性CURRENT，2026-10-24。

验收：Given真实本人账号已经取得持久查询，When正式撤销来源并在同库重启，Then当前来源继续410，历史列表与原请求按实际200显示，保留原query_id和HISTORICAL_REQUIRES_REQUERY；原始正文不可采用，无第二次查询或业务动作。身份失效、退出及跨角色时清理受保护内容并拒绝读取。来源与历史读取各自展示状态，错误不作为当前成功结果。

验证入口为validation/desktop/check-fc02-history.cjs，使用本目录独立账号、SQLite、9761/9762/19761；validation/fc02_history_check.py只调用正式ControlStore撤销、正式配置接口和读取实际对象计数。外部SIMULATED_FIRST，视觉未执行，不操作用户预览或其他角色资源。

## 当前实现

BossBIView的当前维度、历史列表、原请求分别读取和显示加载、成功及失败状态。dimensions返回410时保留当前来源错误；history及receipt按实际成功结果显示。原请求可以由URL编号读取，也可以从当前本人历史列表选择或自动读取最近编号。历史条件和原始数值来自持久快照，状态明确为HISTORICAL_REQUIRES_REQUERY，当前原始依据和原文按钮禁用，维度不可采用时停止新查询。

fetchJSON在实际401/403时清理问题、条件、结果、依据、历史和原请求，401继续触发既有重新认证流程。同一认证范围内的其他未完成读取不能恢复已清理内容；身份、历史请求和回执分别核查当前请求顺序。原请求较早回执需要匹配当前编辑状态才可采用，维度随后返回时保留已恢复的查询快照。手动恢复保留独立的当前来源错误。

改动仅涉及BossBIView及本任务检查、记录和构建目录配置。领域、Agent、正式Schema、Runtime、账号服务、D01和公共CSS保持当前接收代码；没有扩大授权、读取失效正文或自动重新执行查询。F03/N03复用原有正文与字段Token。

## 验证与制品

公开真实账号检查PASS：evidence/feature-delivery/FC02/fc02-history-6e8d0b95-f990-481e-a585-de0c060a2fa3.json。命令为设置BOSS_PRODUCT_FRONTEND_DIR指向本目录fc02-n3-history-dist，再执行node validation/desktop/check-fc02-history.cjs。

实际检查正常查询、对应原始依据、product-1追问，随后通过正式ControlStore撤销finance-note/1并关闭及重新启动本次独立服务。确认当前维度/查询/原始依据410，历史与原请求200；保留同一query_id、产品/指标/法人条件及HISTORICAL_REQUIRES_REQUERY。带原编号、历史按钮、无原编号最近请求、刷新及同库重启均能够读取；使用键盘Enter恢复。当前原始依据和原文按钮禁用，页面没有失效原文或原始依据正文。

查询、Runtime及原请求数量在恢复前后均为2，task/authorization/outbox均为0。实际30秒令牌自然失效返回401并清理BI，重新认证能够恢复合法历史；退出后清理，维护角色四项BI读取均403且不能进入BI界面。来源失效状态下F03/N03的三种窗口尺寸及100%/200%共12组DOM检查通过，没有整页溢出。视觉未执行。

TypeScript与Vite独立构建PASS，14.10秒；构建命令为在.work/product/nanobot/webui执行npm run build -- --outDir ../../../../fc02-n3-history-dist。manifest SHA256为c66d167f9b6e7187dd47c1cb76db7350941153a3f9be98bf54d90585728a2475，index.html SHA256为39b597fd3398b368dcc290d93bfbaeefd159f743211c10df45b8606a3557d78b。实际通过检查使用同一manifest；正式BossBIView与构建输入SHA256均为7d0fda5afaf184d922449a1d5aa5e695fae8b0b57a7b09aaaf01f721dabd1eb5。git diff --check通过。

## 独立接收与关联影响

准确候选以原始功能状态的candidate_commit及本目录candidate.json为准。本任务修复C12/C14公共恢复，关联C03/C15时序验证见async-recovery.md，当前本地验证不能登记完整功能PASS。N4继续在准确新候选复验受影响恢复、时序与权限；C05/C08/C11需要N1正式边界输入。全部二十项同候选PASS并确认制品一致后，N3才能启用FC03。

复用N4在9026c8a取得的未变更领域、Agent、Runtime及共享消费者证据，未重复74项全量。已有用户预览、其他角色资源和原始证据保持；STT暂停、外部SIMULATED_FIRST、视觉未执行等限制保持。
