# 前端构建输入

固定上游为 `HKUDS/nanobot` commit `1bb712d3488915ca4ed9ccc1a93067ff722f5ab9`，`webui` tree 为 `bb1aa81aa1a85533010e8201a8376615be8cc437`，`nanobot/channels` tree 为 `6569cc8cd4f0065eaebe7c9b1b3b94f703294e75`，`packages/client-events` tree 为 `c71921224c7b72ee0179699391aba476e587156c`。源码输入包含这些目录及上游 LICENSE。渠道目录由上游 TypeScript 配置与插件入口引用，客户端事件模块由会话客户端和流处理引用。

产品模块来源为 `app/webui/`，清单为 `frontend-source-resources.txt`。产品依赖声明和锁文件为 `app/frontend/package.json` 与 `app/frontend/package-lock.json`；完整安装必须按锁文件核查。设计资源、下列补丁及本文件列于 `frontend-build-resources.txt`。

本次独立检查使用 Node 24.13.0 和 npm 11.6.2；`app/frontend/.node-version` 记录该 Node 版本。独立 Vite 配置在读取构建输入前检查运行中的 Node 版本，版本不一致时拒绝构建。此版本对应当前已执行检查，其他版本尚未验证。

固定上游的产品集成差异以以下完整补丁供审查：

| 文件 | 覆盖范围 |
|---|---|
| `upstream-app-complete.patch` | 认证、Shell、会话容器、导航与晨间交接 |
| `upstream-session-client.patch` | 客户端重连与业务请求回执 |
| `upstream-settings.patch` | 设置导航与未保存修改保护 |
| `upstream-thread-shell.patch` | 会话 Shell 接口与阅读状态 |
| `upstream-thread-composer.patch` | 输入草稿、标签与建议入口 |
| `upstream-thread-viewport.patch` | 会话阅读位置与历史状态 |
| `upstream-localization.patch` | 默认语言与品牌文案 |
| `upstream-tool-activity.patch` | 工具事件显示 |
| `upstream-thread-motion.patch` | 会话跟随与流式刷新 |
| `upstream-build-config.patch` | TypeScript 与 Vite 依赖解析 |
| `upstream-index.patch` | HTML 入口品牌信息 |

当前执行规则要求使用文件编辑工具修改代码；补丁用于审查和逐项核查，不能作为程序化修改源码的授权。`scripts/audit_frontend_source.py` 检查仓库根目录、固定 commit、WebUI、渠道及客户端事件 tree、相关路径的 Git 状态和 11 项补丁对 index 的适用性；忽略文件不在检查范围。`scripts/prepare_boss_webui.py` 会程序化修改源码，当前规则下不能执行。

`vite.independent.config.mts` 在上游 `webui` 工作目录核查固定 Vite 配置摘要，并在项目配置中声明对应插件、分包、压缩、开发服务和测试设置；通过 alias 引用本项目 `app/webui`，使用独立目录内锁文件一致的依赖，并将设计资源写入独立输出。它要求显式指定 `BOSS_FRONTEND_UPSTREAM`、`BOSS_FRONTEND_DEPENDENCIES` 和尚不存在的绝对路径 `BOSS_FRONTEND_OUTPUT`。上游 `webui/node_modules` 须指向该独立安装的依赖；产品源码不需要复制。上游目录存在 `.env` 配置文件时入口拒绝构建。该入口不能代替完整源码来源核查、依赖安装生命周期和正式验收。

`tsconfig.independent.json` 采用项目根目录下 `vendor/nanobot` 作为固定上游输入位置，直接引用 `app/webui` 及上游 `webui/node_modules`；该目录需要实际提供已核查的上游源码及符合文件编辑规则的产品集成。使用该布局时，可从项目根目录执行上游 `webui/node_modules/.bin/tsc --noEmit -p app/frontend/tsconfig.independent.json`。随后在上游 `webui` 目录使用锁定依赖中的 Vite 与 `vite.independent.config.mts` 执行构建。输出目录的父目录必须位于项目 `.work`，输出目录须不存在；构建不会清理已有目录。

独立配置已在临时目录链接指向项目内人工集成输入的条件下完成 TypeScript 检查和 Vite 构建；该链接仅用于验证，已移除。项目尚未提供 `vendor/nanobot` 正式输入，临时输入和配置检查不证明正式交付或完整来源。

完整构建仍需在可审查的固定上游输入中，以符合文件编辑规则的方式完成上述产品集成、提供产品模块和设计资源、安装并核查锁定依赖，随后运行 TypeScript 和 Vite 构建并核查制品来源。现有静态预览使用来源尚未核验的本机依赖和有未提交修改的上游工作目录，不作为正式构建证据。

在独立源码分发目录中，`npm ci --ignore-scripts --no-audit --no-fund` 已按当前锁文件安装依赖；该检查未执行安装脚本，也未证明构建工具的安装脚本和完整前端构建。正式构建使用的源码、资源和依赖必须在同一独立输入中核查，不能引用现有开发目录的 `node_modules` 代替锁文件安装。
