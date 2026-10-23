# FC03晨间事项公共集成

## 任务身份与当前范围

task_id为FC03-N3，development_record为本文件。完整需求与22项检查点引用原始项目docs/FC03晨间事项工单.md，唯一状态来源specs/feature-delivery.json。FC02在准确候选4d55773取得独立20/20 PASS/GO并由N3确认版本/制品一致后继续本功能，acceptance已保存。

FC03 IN_PROGRESS，尚无完整组合候选或独立得分。当前完成本人排序未知结果的公开恢复路径，验证覆盖C14/C16/C18/C21的相关部分；不能据此登记整个检查点或全部22项通过。文档CURRENT，last_verified为2026-10-24。

## 检索与输入依据

读取PRD8.1/BR-01/AC-01-S/E及共通权限/状态、LLD-data/backend/agent/frontend、交互O01/O02/O03/O07/O21与E01—E06、Desktop v6 F01 HTML/文字元信息和design-tokens.json；未使用视觉。检索T11、TodayAPI、BossToday、BossDesktop、公共Page/Command、BossRecoveryAPI、BossTodayReadTool及当前Runtime。

已有分类/关系合并和排序CAS可复用；正式逐日范围、晨间可信请求/实际SDK结果、同版本详情、完整冲突/覆盖需按N1/N2正式接口完成。四角色完整工单已建立；N1负责领域/正式Schema，N2负责受限Tool与SIMULATED事件，N3负责公开消费者及候选，N4负责独立22项。

当前排序采用既有TodayAPI.reorder与/api/boss/ui/operation-status，不修改领域语义或新造字段。所有数据由当前获准初始资料和正式本人保存动作产生。缺少原回执继续表示未知，不证明未执行；维护和匿名权限仍由真实服务检查。

## 当前公开实现

| 文件 | identifier或入口 | 当前行为 |
|---|---|---|
| app/webui/BossToday.tsx | save / recover | 首次本人明确保存生成一次client_request_id；URL仅保留todayOrderRequest编号；未知期间禁止再次保存，只读查询原编号；RECORDED后重读实际排序 |
| app/webui/BossToday.tsx | token / epoch / sequence | 身份变化清理本组件编辑与回执状态，取消旧读取；较早身份或回执不覆盖新状态；已知HTTP拒绝保持错误并允许核查当前资料 |
| app/webui/BossDesktop.tsx | readTodayOrder / BossToday | 实际原生Mutation执行首次排序，独立HTTP只读恢复，不调用会重新执行的通用保存路径 |
| app/webui/nanobot-today-order.patch | pending boss.today.reorder | 实际原生Client连接恢复时终止该动作的重发，提示读取原请求；原有场景载入保护保持 |
| validation/desktop/fc03_order_proxy.py | 实际HTTP/WebSocket转发 | 实际排序成功响应形成后中断连接；保持真实请求/结果，记录转发次数、版本与响应摘要 |
| validation/desktop/check-fc03-order.cjs | F01本人保存与恢复 | 真实账号、正式排序、连接中断、只读原回执、刷新、未知编号及维护/匿名拒绝 |

Given本人调整当前完整事项集合并明确保存，When服务端已经记录版本1而响应交付中断，ThenClient不重发保存；页面保留原编号，通过只读回执恢复RECORDED，并重读相同正式次序。刷新继续恢复原编号，不创建新的排序意图。NOT_FOUND_IN_CURRENT_STORE继续显示未知，保存入口不可用；主动读取该回执没有写入。

当前修改未接入新的日期/时区、晨间问题或清单版本字段；这些字段从N1同一正式Schema接收。正式晨间只读Runtime不使用通用聊天的宽工具范围，也不能签发排序或业务授权。

## 实际验证与证据

| 场景 | 实际命令或入口 | 结果与证据 |
|---|---|---|
| Red | 在已验收fc02-n3-boundary-dist运行当前排序恢复验收；实际保存响应形成后中断连接 | 业务恢复断言未满足，原始证据evidence/feature-delivery/FC03/fc03-order-01a66cb5-63f9-432d-acd9-3f99f3956a92.json |
| Green | BOSS_PRODUCT_FRONTEND_DIR为本目录fc03-n3-order-dist绝对路径；node validation/desktop/check-fc03-order.cjs | PASS；真实保存仅转发一次、版本1与完整集合匹配；只读原回执和刷新保持；未知回执不写入；维护403/匿名401。evidence/feature-delivery/FC03/fc03-order-e9244282-e72d-4a7e-9d59-1fdbe2fbb55b.json |
| 受影响领域消费者 | validation/.venv/bin/python -m pytest -q app/tests/test_boss_today.py --basetemp=.work/pytest-fc03-existing-today -p no:cacheprovider --junitxml=evidence/feature-delivery/FC03/today-existing.xml --tb=short | 3 passed，0.56秒；CAS/幂等/同库重读、来源变化拒绝、身份和关联事件合并 |
| 工程 | 在.work/product/nanobot/webui运行npm run build -- --outDir ../../../../fc03-n3-order-dist；git diff --check | 严格TypeScript/Vite PASS，15.01秒；差异检查PASS |

当前公共验证数据为validation/.work/fc03-order-e9244282-e72d-4a7e-9d59-1fdbe2fbb55b，独立账号、SQLite及9941/9942/19941/9943端口。没有修改用户预览或其他角色进程。测试没有替换业务资料、模拟响应或伪造保存结果；代理只中断实际响应的交付。

## 构建与后续使用

当前独立制品fc03-n3-order-dist的manifest SHA256为e60089dfdb81777241d7615a92ab3a12e1580271513a4819cbd8828345098fcd，index SHA256为8f2054bf88be7a6e1434836065f0007cf1bd164077fe030716ddbb1e95d58ede。BossToday源码与构建输入均为f02f96a68320b57c899bf405f86c3d442a997aff1af1024e422d84da70ea1f15，BossDesktop均为7cd4411843f5b45892f7a2b0c674abfbc76e9ce38fe9113fbf46e22e2b0d9cce。

原生Client SHA256为dd5a98697609ac316d41889387a71d3f4898a51e1a409cc25bb1ef30a259f3f0；本次patch SHA256为1c4c6dfe94250ebcc35335e7f3b3f272e37dc71a3bed99e432725eb92406a9ce。全新构建通过文件编辑工具采用当前正式文件，依次采用原nanobot-one-shot.patch和nanobot-today-order.patch；当前构建已经包含两项，不能再次应用。FC02准确制品保持原目录与摘要，当前FC03制品未作为完整候选发布。

## 未完成与接收条件

N1尚需提供日期/时区、完整纳入范围、有效规则与排序理由、来源覆盖、真实冲突和准备材料、持久清单/详情/来源版本及排序兼容的正式接口与Schema。N2尚需提供使用同一正式版本的可信晨间请求、受限读取工具、实际SIMULATED事件、运行/结果/回执关联与失败终态。当前核查两角色目录尚无FC03交付记录，未采用未提交接口假设。

接口到达后N3逐项接收，完成F01日期/晨间问题/分类详情/冲突/来源/本人排序/恢复及全部必要公共消费者，提供准确完整候选。N4独立确认22项并由N3核实版本/制品后继续FC04。当前局部实现不登记功能PASS，未执行完整22项、视觉、真实模型质量、外部投递或设备验收；全部外部SIMULATED_FIRST，STT暂停，旧父任务未验收语义保持。
