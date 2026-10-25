# FC01.C15 正文Token

task_id：FC01-N4-001；需求：FC01.C15、Desktop v6 typography、LLD-frontend第3节；状态来源为原始项目specs/feature-delivery.json。当前限定ACCEPTED；N4对准确候选c4bc673的C15独立复验及C18一致性检查通过，FC01十八项全部PASS。文档核查日期2026-10-24。

## 输入与实现

已读取N4的qa.md、verdict.json、cost-body-tokens-06d5c30.json、Desktop v6 design-tokens.json、LLD-frontend和实际组件/CSS。N4对06d5c30的C01—C14、C16/C17共16项PASS保留其原始依赖与版本。

app/webui/boss-v6.css中.boss-workspace-item p采用16px/24px。该规则覆盖成本报告六段正文、库存计算说明及使用相同容器的工作区正文。标签、small、键值元信息和输入规则保持其明确职责；字段标签14px/22px。

Given真实本机账号和经维护GUI导入的既有SIMULATED资料及四份成本报告；When本人打开F14两类成本报告和共享正文页面，并使用三种尺寸、200%和键盘导航；Then实际p的computed styles为16px/24px，合法字段标签14px/22px，整页没有横向溢出，当前操作能够通过键盘访问。来源输入复用app/tests/test_boss_material_cost_reports.py:reports_input，不新增业务事实。

## 构建与验证入口

产品和构建输入CSS SHA256均为3078c4dc678513f488050dae3c9b15dec07dbc57cce97fe69c7237f4ff7609da。独立制品fc01-n3-c15-runtime-dist，构建在.work/product/nanobot/webui执行npm run build -- --outDir ../../../../fc01-n3-c15-runtime-dist，16.13秒；原runtime-dist及预览保持原样。

index.html SHA256为06918aeef643bc4fef211bf3143709fdf4d44ec8d71113a5816a225eff6d46a7；asset-manifest.json SHA256为b35ffd1880cfc1ad42d1626b6e3c6bd5115977ef741b726b725e52905b258d8c。

检查入口validation/desktop/check-fc01-body-tokens.cjs，设置BOSS_PRODUCT_FRONTEND_DIR为本候选独立制品绝对路径。检查使用9571/9572/19571及validation/.work/fc01-c15-<唯一编号>，建立自己的账号、SQLite和Electron环境，结束时关闭自己的进程。报告为evidence/feature-delivery/FC01/fc01-c15-dd398d4e-a4d9-4e15-8e11-7ae6cd80c25d.json，结果PASS。两类报告各六段实际正文以及当前已呈现的共享正文均为16px/24px，字段标签14px/22px；19个相关页面读取、18次尺寸与页面组合、查询Enter、Tab、D06 Escape及返回焦点通过，renderer异常为零。全部产品命令workdir为本N3工程；未执行视觉、截图、图像查看和真实模型请求。

## 继续条件

本次产品修改仅为一条共享正文CSS规则；N4已确认其余十六项业务证据适用，并完成C15独立复验及C18一致性判定。N3核实c4bc673与制品摘要一致，FC01限定验收记录保存于acceptance.json，当前继续FC02。未重复业务全量检查，视觉及真实外部能力保持原未执行范围。
