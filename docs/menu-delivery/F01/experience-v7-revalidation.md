# F01 当前版独立核验入口（不代表验收通过）

- 功能：`MENU-F01` 今日工作；唯一当前状态：`specs/feature-delivery.json`
- 来源：必须与 `boss-compiled-build.json.repo_commit` 的完整 Git 提交一致
- 设计：Desktop v7 对应 F01 全长页面及其真实 HTML/CSS/JS/素材；当前尚无可读取的原始 v7 ZIP 字节，设计结构验收不得标记通过
- 运行：用户自己在受保护的 Intel Mac 环境中手动执行，GitHub CI 的 Linux/Node 结果不能代替 Mac GUI 验收
- 外部：`SIMULATED_FIRST`，语音/STT暂停，不恢复定时任务

## 1. 获取与准确对应

GitHub Actions `Boss-Agent desktop integration` 中成功的 `react-webui-build` 任务会发布 `boss-f01-frontend-<commit>` 制品。该制品只含编译后的前端静态资源和三个非凭据摘要文件，不包含本地数据库、账号或 Electron 安装包。下载归档并在对应源码工作树内部的**新建** `.work` 子目录解压，文件结构应当为：

```
<artifact-root>/
  boss-compiled-build.json
  boss-build-manifest.json
  boss-native-patches.json
  nanobot/nanobot/web/dist/index.html
  nanobot/nanobot/web/dist/assets/...
```

使用**隔离工作树**打开该制品记载的准确 `repo_commit`，不要重置或覆盖当前工作的 Git 工作树，也不要替换已有用户运行实例。完整源码引用及 sha256 由下列只读检查核验：

```bash
python3 scripts/verify_f01_candidate.py --bundle "$PWD/.work/<new-artifact-directory>" --require-head
```

检查包括实际资源逐文件 SHA-256、index.html、第一方叠加文件与原生 nanobot 补丁清单、固定上游版本、本地 HEAD 与未提交修改。遇到任意不匹配直接停止，而不是使用现存旧制品继续报告成功。

## 2. 保持用户实例不受影响

本轮只提供**显式人工启动**的受控入口 `scripts/run_f01_manual_review.command`。此前 `scripts/run_menu_f01_rework.command` 属于旧 v6 制品，不用于验证当前 main。新入口绝不调用旧 `prepare_menu_f01_rework.py` / `prepare_menu_n02.py` 的自动登录或初始化过程；不读取账号密码内容，不自动发业务消息，不自动调度。

需由用户预先**手动准备一个全新的** `validation/.work/menu-f01-v7-review-<unique-name>` 本机账号环境，保留现有业务与登录状态；未准备则只报错退出。隔离工作目录必须是 `validation/.work` 的直接子目录，源码/制品必须处于当前工程内部。程序检查待用的端口不属于保留集合且尚未被监听，默认新端口 `11321 / 11322 / 21321`，任何冲突拒绝执行，不停止进程。

当账号资料、依赖和制品已**由本人显式准备并确认**后：

```bash
export BOSS_F01_REVIEW_BUNDLE="$PWD/.work/<new-artifact-directory>"
export BOSS_F01_REVIEW_WORK_DIR="$PWD/validation/.work/menu-f01-v7-review-<unique-name>"
bash scripts/run_f01_manual_review.command
```

这仅启动由用户明确选择的隔离 Mac 应用；登录仍由用户在 UI 手动进行。当前不应声称上述完整 Mac 流程已在 GitHub CI 中被实际运行；它只提供可核验入口。技术维护配置、模拟输入准备及本人授权仍须按原有真实业务流程处理，不用脚本生成成功样例。

## 3. F01 18 项核验顺序

逐项只使用与上述 `repo_commit`、编译文件摘要及独立运行环境一致的证据：

| 检查点 | 必须验证的具体现场结果 |
|---|---|
| C01/C02 | v7 真正加载的 F01 全长首页、导航/大鹏、自然语言、三类当前事项、右侧资料；逐区布局与当前页面同窗口对照 |
| C03 | 业务日期、IANA 时区、非法值、日界、来源截至与读取时间 |
| C04 | 八类当前获准来源、缺口与真实数量、覆盖不确定与失效 |
| C05 | 三类分类、当前来源计数、处理人/期限/参与原因/状态 |
| C06/C07 | 事件合并、同版本来源、当前风险/本人次序解释 |
| C08 | 筛选分类中的鼠标/键盘排序、保存 CAS、错误后不丢编辑、重载保持 |
| C09/C10 | 选中详情与来源原文、撤销/历史/迟到响应、会议/承诺/冲突/时区与隐私 |
| C11 | 晨间问题通过真实 SessionManager/AgentLoop、同一线程持续讨论、异常不报成功 |
| C12 | 当前事项的合法来源与会议关联进入 F06，老板明确创建/发送/完成互不混淆 |
| C13 | 查看来源、会议、进入交办、返回并恢复分类/日期/焦点/滚动 |
| C14 | 刷新、退出重登、同库服务重新读取记录，引用不混用旧版本 |
| C15 | 空/加载/断网/取消/失败/无权/未知回执与恢复 |
| C16/C17 | 未认证或维护越权、私人正文保护、CAS/重复/授权或来源撤销、未知结果不重放 |
| C18 | 1440×1024、1280×800、1024×768、200% 与键盘/滚动/弹窗交互；当前准确 Mac 独立启动器与制品一致 |

这些是原18项稳定编号的索引，不新增第二套独立进度源。具体采样/数值/断言应登记于 `docs/menu-delivery/F01/integration.md` 并按原 `specs/feature-delivery.json` 更新。未获新授权，不执行截图/图像查看或自动登录；视觉与用户验收依然独立等待。

## 4. 当前不可越过的完成边界

v7 完整包存于历史 Library 记录，但原始 HTML、加载 CSS/JS 与素材字节当前不可读取，无法形成 v7 设计到当前源码同环境 DOM/样式差异闭环。目标 Mac 的合法真实手动登录及整页使用也尚未由本会话执行。此两类证据缺少时，不得标 `MENU-F01.C01`、`C02`、`C18` 等相关项新版完整通过，也不得宣布 F01 18/18 或用户已验收。旧 v6 18项记录单独保留。
