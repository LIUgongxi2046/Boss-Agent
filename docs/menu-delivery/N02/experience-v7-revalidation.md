# N02「聊天交办」当前版独立体验与验收入口

本文件服务 `MENU-N02` 26项稳定检查点，正式活动状态只看 `specs/feature-delivery.json`；此处不是额外进度源。最新用户决定 `D-NEXT-MENU-N02-20261025`，F01 只冻结旧工程、v7/用户验收仍后置；N03 不并行开发。

## 准确候选与作用范围

- 源码：`d1436abc614dbfeb842421b5b1bdefe53d9d5df9`，内含 N02 当前上下文/中断清理/返回重试修复；此前旧 N02 v6 `docs/menu-delivery/N02/delivery.json` 的26/26为历史候选，**不是当前新版**。
- 产品前端构建：GitHub Actions `40202750383` 中 `react-webui-build` 为 PASS，构建制品 `boss-agent-frontend-d1436abc614dbfeb842421b5b1bdefe53d9d5df9`，artifact ID `12603035088`。GitHub ZIP SHA256 `d436ac9bc8684d0a26a2c1b4f0e03a5b622a3d90d86b330e0cf782f37a019f3a`；仅静态前端和来源 manifest，无私密数据库、密码或 Mac 安装程序。2026-11-08 到期；此后仍可从锁定提交重新构建。
- 域/SDK定向检查：N02 `40202750401` 中 Node **4/4**、实际领域/附件/任务入口 **37/37**、原生 nanobot AgentLoop/SessionManager **59/59**，与上述源码是同一代码提交。综合桌面 workflow 的另一个历史 N03 Python job 仍失败，不能把整条运行标 PASS。
- 桌面版要求：用户实际 Intel Mac 上的**独立资料、合法人工登录和完整页面操作**；当前没有在用户 Mac 上执行，不能标定验收。

## 安全取用与独立启动

先下载上述 Github Actions archive，并使用**对应源码提交的隔离工作树**，不能在当前开发工作树执行 reset/checkout 来替换现有修改。解压在该工作树内一个**新建** `.work` 子目录，完整文件结构必须包含 `boss-compiled-build.json`、`boss-build-manifest.json`、`boss-native-patches.json` 和 `nanobot/nanobot/web/dist/index.html`。

仅在账号及数据环境**已经由用户明确授权并手动初始化**之后，使用 `scripts/run_n02_manual_review.command`；此入口是复用 `scripts/verify_f01_candidate.py` 实施通用编译制品只读校验，尽管脚本历史命名为 F01，所校验的是当前归档实际 commit/资源/锁定上游和第一方源码。它不会自动认证、自动初始化、读取凭据正文、访问个人旧资料、生成新业务模拟记录或退出运行中的用户程序。

```bash
# 在准确 d1436abc... 的隔离工作树根目录执行；文件和资料目录都位于该工作树内
export BOSS_N02_REVIEW_BUNDLE="$PWD/.work/<N02-artifact-dir>"
export BOSS_N02_REVIEW_WORK_DIR="$PWD/validation/.work/menu-n02-v7-review-<new-unique-name>"
bash scripts/run_n02_manual_review.command
```

入口默认新端口 `11421 / 11422 / 21421`；覆盖所有受保护的旧 F01/N02/UI02/MVP 端口检查，并拒绝非本项目、缺少隔离账号或已有实例记录的目录。**无需执行上述命令来确认本次 GitHub 代码提交**：它是给用户日后独立人工体验使用的前置条件清单。原 `scripts/run_menu_n02.command` 仍指向 v6 旧制品，不代表本版已通过。

## 当前实际 N02 操作验收

1. 以本人身份手动登录，在同一 Shell 开始新聊天并切换/搜索历史；无聊时不编造历史内容。验证中文输入、IME、换行、多轮和合法文件上传，切换前的未发送输入受 D06 保护。
2. 从 F01 已保存清单或 F06 当前任务进入 N02，检查实际对象/来源版本、会话绑定与清单/任务状态；切换账号或切换不同会话时，不得延续先前任务的私人上下文。
3. 在当前聊天查看原生执行步骤、实际 run_id、工具、来源与真实产物。人工断开连接后不能继续把上轮运行、附件、任务绑定标记为当前已核查；重连后重读现行资料。
4. 从原消息打开合法任务、来源及运行记录，再返回 N02：保留原消息/阅读位置与焦点，长对话历史阅读不自动滚到底部；发生位置恢复错误时支持**鼠标点击与键盘 Enter/Space 的重新定位原消息**，Tab导航本身不删除待恢复位置，显式其它交互可以结束恢复。
5. 对当前可用的模拟发件、联系人核查、任务创建或回复进行独立本人确认；成功后只读原请求回执与同库重读，模拟送达不谎称外部送达；丢响应不自动发第二次。恢复/取消不把已保存任务当成自动完成。
6. 用 `1440×1024`、`1280×800`、`1024×768`、200% 缩放逐区域核查已加载原 N02 v7 长页：公共框架、会话栏、执行区、侧栏、文件和Dialog、标签、间距/控件尺寸、焦点和滚动。**最新 v7 源 HTML/CSS/JS/字体/素材未获原字节，因此本项当前不能执行“成对”比较，也不允许截图替代。**

停止条件：若真实 Mac 上的登录或原生 N02 会话无法执行，保留详细实际错误与源码、制品摘要；不要在原 F01/N02/UI02/MVP 实例中绕行验证。STT/F27 保持暂停，外部继续 SIMULATED_FIRST。PRD 和 N02.C01—C26 的所有原始义务继续有效。

**当前记录**：新版完整 `0/26`、视觉 `NOT_RUN`、用户 `PENDING_USER_ACCEPTANCE`；聚焦源码测试和单独前端构建已通过，不等于 Mac GUI 或 v7 已验收。
