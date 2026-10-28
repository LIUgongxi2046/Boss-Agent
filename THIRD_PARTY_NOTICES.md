# 第三方组件、素材与资料声明

核查日期：2026-10-28。状态：源码与直接依赖许可记录；完整发布制品的许可审查尚未完成。

Boss Agent 的 `AGPL-3.0-only` 适用于项目有权授权的原创内容。第三方软件、复制代码、图标、字体、图片和资料保留各自的版权与许可；独立商业授权同样不能替代第三方权利人的许可。本文件不表示全部传递依赖与实际发布制品已经完成审查。

## nanobot

本项目使用 `HKUDS/nanobot` 的 v0.3.5，固定提交为 `1bb712d3488915ca4ed9ccc1a93067ff722f5ab9`。获取入口与项目扩展采用 [prepare_boss_webui.py](scripts/prepare_boss_webui.py)，Python 依赖采用 [pyproject.toml](validation/pyproject.toml) 与对应锁文件。

上游代码采用 MIT License。项目复用并修改其界面与集成部分；Boss Agent 的许可声明不改变上游已有代码的 MIT 许可。分发原有代码或其重要部分时，必须保留以下完整声明：

```text
MIT License

Copyright (c) 2025-present Xubin Ren and the nanobot contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

仓库保留的上游许可全文位于 [evidence/T02/inventory/LICENSE](evidence/T02/inventory/LICENSE)；上游随包第三方声明全文位于 [evidence/T02/inventory/THIRD_PARTY_NOTICES.md](evidence/T02/inventory/THIRD_PARTY_NOTICES.md)。随包内容包括 Tabler Icons（MIT）、KaTeX（MIT）和 KaTeX Fonts（SIL OFL 1.1）。分发实际包含这些组件的前端制品时，需要同时携带对应版权、许可全文及字体保留名称声明。上游单独提供的 TUI 发行包具有其目标平台声明；本文件不表示 Boss Agent 已经分发该类制品。

## 前端直接运行依赖

下列版本及许可来自 [app/frontend/package.json](app/frontend/package.json) 与 [package-lock.json](app/frontend/package-lock.json)。构建工具不改变其包含在成品中的组件的许可。

| 组件 | 锁定版本 | 声明许可 |
|---|---|---|
| `@radix-ui/react-alert-dialog` | 1.2.1 | MIT |
| `@radix-ui/react-dialog` | 1.3.1 | MIT |
| `@radix-ui/react-dropdown-menu` | 2.2.1 | MIT |
| `@radix-ui/react-popover` | 1.1.15 | MIT |
| `@radix-ui/react-select` | 2.2.6 | MIT |
| `@radix-ui/react-slot` | 1.5.0 | MIT |
| `@radix-ui/react-tooltip` | 1.4.1 | MIT |
| `class-variance-authority` | 0.7.1 | Apache-2.0 |
| `clsx` | 2.1.1 | MIT |
| `diff` | 9.0.0 | BSD-3-Clause |
| `i18next` | 26.5.11 | MIT |
| `lucide-react` | 0.469.0 | ISC |
| `luxon` | 3.7.2 | MIT |
| `micromark-factory-space` | 2.1.0 | MIT |
| `qrcode` | 1.5.4 | MIT |
| `react` | 18.3.1 | MIT |
| `react-dom` | 18.3.1 | MIT |
| `react-i18next` | 17.1.9 | MIT |
| `react-syntax-highlighter` | 15.6.6 | MIT |
| `rehype-katex` | 7.0.1 | MIT |
| `remark-breaks` | 4.0.0 | MIT |
| `remark-gfm` | 4.0.1 | MIT |
| `remark-math` | 6.0.0 | MIT |
| `streamdown` | 2.5.0 | Apache-2.0 |
| `tailwind-merge` | 2.6.1 | MIT |

前端直接开发依赖同样来自上述锁文件：除 `typescript` 5.9.3 使用 Apache-2.0 外，其余直接开发依赖声明为 MIT。`katex` 0.16.47 虽列在 `devDependencies`，其渲染代码和字体可能进入前端制品，仍需保留实际随包的 MIT 与 OFL 声明。

## Python 直接依赖

下列版本来自 `validation/pyproject.toml`、`validation/uv.lock` 与当前已安装的 distribution metadata；许可使用 `License-Expression`、`License` 或许可分类信息，属于组件自身的声明。

| 组件 | 版本 | 声明许可 |
|---|---|---|
| `nanobot-ai` | 0.3.5 | MIT |
| `jsonschema` | 4.25.1 | MIT |
| `httpx` | 0.28.1 | BSD-3-Clause |
| `pytest` | 8.4.2 | MIT |
| `playwright` | 1.55.0 | Apache-2.0 |
| `markdown-it-py` | 4.2.0 | MIT |
| `packaging` | 26.3 | Apache-2.0 OR BSD-2-Clause |
| `PyYAML` | 6.0.3 | MIT |
| `bcrypt` | 5.0.0 | Apache-2.0 |
| `pypdf` | 5.9.0 | BSD-3-Clause |
| `python-docx` | 1.2.0 | MIT |
| `croniter` | 6.2.4 | MIT |
| `jsonlines` | 4.0.0 | BSD-3-Clause |

`jsonlines` 的 BSD-3-Clause 依据已安装发行包的 `jsonlines-4.0.0.dist-info/LICENSE.rst` 全文核对。上述清单包含验证工具，并不表示它们全部随桌面应用分发。

## Electron 与桌面工具

版本与许可来自 [validation/desktop/package.json](validation/desktop/package.json) 和 [package-lock.json](validation/desktop/package-lock.json)。

| 组件 | 锁定版本 | 声明许可 |
|---|---|---|
| `electron` | 45.0.0 | MIT |
| `@electron/packager` | 20.3.0 | BSD-2-Clause |
| `@playwright/test` | 1.55.0 | Apache-2.0 |
| `playwright` | 1.55.0 | Apache-2.0 |

Electron 自身使用 MIT，运行时包含 Chromium、Node.js 等第三方组件。分发桌面应用时，需要保留 Electron 发行包携带的 `LICENSE`、`LICENSES.chromium.html` 及其他适用声明，不能仅以本表替代完整运行时声明。

## 设计素材、资料与服务

- `Boss-Agent-Desktop-Complete-v7/`、`design/` 等目录中的图片、动画、字体和参考素材，需要根据实际来源核查授权。自行创作且有权授权的作品采用项目许可；第三方或权利尚未确认的素材不能仅因进入仓库就视为取得项目许可授权。品牌使用同时采用 [TRADEMARKS.md](TRADEMARKS.md)。
- 公开财报、经营基准和其他公开资料保留各自的作者、来源、原始期间及单位；公开可访问不代表可以任意再分发。资料的使用与分发需要分别核查权利。
- 模拟业务资料的用途与验证状态采用对应资料说明；用户导入的企业资料、联系人信息、账号和凭据不因使用本软件而适用 AGPL。
- DeepSeek 等模型服务及外部接口按各自服务条款使用，代码许可不包含服务账号、额度、数据传输或第三方系统的操作授权。

## 发布与分发检查

发布方需要根据实际源码、锁文件和发布制品，核对全部直接及传递依赖，生成对应版本的 SBOM 与许可材料，保留 MIT、BSD、ISC、Apache、OFL 等适用许可全文及声明。未知来源、未确认许可、不兼容义务、缺失必要声明、秘密或未经授权的资料，需要在发布前解决。

源码、桌面安装包和网络服务分别履行适用的 AGPL 义务。对应源码需要与实际提供的版本相符，并包含适用的构建、安装和运行材料；修改版本的网络交互需要提供协议要求的显著源码获取方式。本次许可文档补充不代表应用界面、安装包或完整发布制品已经通过上述检查。
