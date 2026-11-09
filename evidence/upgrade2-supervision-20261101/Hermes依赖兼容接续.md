# U2-01 Hermes 依赖兼容接续

核查日期：2026-11-02。工作目录为 Boss-Agent，分支 `main`，HEAD `72d9ed63937ffca5adc525a694d0d27a13297c2c`；活动任务 `UPGRADE-2-EXECUTION`。本次只读核查官方发行和现有独立环境，没有修改产品版本、依赖、锁文件或用户实例，没有外部模型请求。`df -h .` 显示项目卷可用约 4.3 GiB；没有重复下载大型制品或创建完整新环境。

## 当前固定版本

固定 Hermes commit `903230b1e23e0c496b28e5d2e8c4f2639cd506b6`；U2-01 记录其归档 SHA-256 为 `2902bae7c50d1a93b10cc7a42042dc0c54a40f8b665de91b54e88553f20cff7b`。本次现有源码 `pyproject.toml` SHA-256 为 `8c9de0a63a81281a24c721f45051fe9fcf8e09ac6ea4ed4ac95e3b96f049b5e3`，`uv.lock` SHA-256 为 `e6d08c634c3f9a252a896135a9c30324776fa343ce68432e88d22f2968f257e2`。官方[固定源码](https://raw.githubusercontent.com/NousResearch/hermes-agent/903230b1e23e0c496b28e5d2e8c4f2639cd506b6/pyproject.toml)说明运行支持 Python 3.14；较低版本范围供旧安装更新使用。不能仅依据版本声明选择 Python 3.12 或 3.13 作为完整运行对象。

复验 `uv pip check --python .work/upgrade2/u2-03/clean-hermes/.venv/bin/python`：Python 3.14.9 检查 248 个包，报告 `browser-harness` 要求 `pillow==12.3.0`，现安装 `13.0.0`。原始发行元数据不兼容；上游锁文件覆盖不改变该事实。[PyPI 发行记录](https://pypi.org/project/browser-harness/)列出的 0.1.13 wheel SHA-256 为 `2491459e4bfc0ee8aea22dc6c4680fc0f791b7ba553446323c50d2883449d769`；其发行对应源码 commit `c24e5072ee66f8499bacd663f4f4bcb089bc4492`。

## 官方发行与可审查修复

[Hermes 官方发行](https://github.com/NousResearch/hermes-agent/releases)当前最新正式版本为 v0.22.5，commit `bf0203a794a07aac3ff764972ab9087baa4e4f4e`；U2-01 已核查其直接依赖仍存在相同冲突。v0.22.4 commit `4d04303818b61bf3aa09278af48356315515965b` 的官方源码归档 SHA-256 为 `808464c45097ebc4febaed2d08bb936095262c6997ba7c49ee1a0c4e7f7c593e`。该版本同时要求 Pillow 12.3.0 与 browser-harness 0.1.13；本次对既有独立 Python 3.14.9 环境执行 `uv pip check --python .work/upgrade2/u2-01/v0224-resolve-env/bin/python`，105 个已安装包的元数据检查通过。Pillow 官方[安全公告](https://github.com/python-pillow/Pillow/security/advisories/GHSA-8g5g-8vmr-9782)列出 12.3.0 为受影响版本，13.0.0 为修复版本；该环境不能登记为满足安全条件的候选。

对 v0.22.4 环境执行 `PYTHONPATH="$PWD/validation" HERMES_HOME="$PWD/.work/upgrade2/dependency-resolution-001/home" TMPDIR="$PWD/.work/upgrade2/dependency-resolution-001/temp" PYTHONDONTWRITEBYTECODE=1 .work/upgrade2/u2-01/v0224-resolve-env/bin/python app/tests/hermes_release_compat_probe.py`，结果 `registry=PASS`，注册的两项简报工具保持关闭，`run_conversation` 包含 `user_message` 参数。此结果仅覆盖该探针；全部业务工具、正式引擎、真实认证、隔离与业务流程尚未验证。

[browser-harness PR 931](https://github.com/browser-use/browser-harness/pull/931)提出把 Pillow 固定版本从 12.3.0 更新至 13.0.0，当前为 Open；[PR 935](https://github.com/browser-use/browser-harness/pull/935)也处于 Open。官方主线[项目声明](https://raw.githubusercontent.com/browser-use/browser-harness/main/pyproject.toml)和 PyPI 当前发行仍为 0.1.13、要求 Pillow 12.3.0。所查正式发行尚未提供同时满足固定 Hermes 的 Pillow 13 要求和 browser-harness 元数据的版本组合。

## 本地修复候选

已核查上游 PR 931 和 PR 935 的完整差异，均将 `pyproject.toml` 的 `pillow==12.3.0` 改为 `pillow==13.0.0`。以已核对 SHA-256 的官方 0.1.13 sdist 为来源，建立本地版本 `0.1.13+boss.1`；`pyproject.toml` 仅更改本地版本标识及 Pillow 版本，源码和资源通过符号链接引用只读缓存。`verify_source.py` 使用 `tarfile` 将 17 项源码及资源、README 和 LICENSE 与原始归档逐字节比较，检查构建配置仅含上述两项变化，结果通过。官方源码 commit 为 `c24e5072ee66f8499bacd663f4f4bcb089bc4492`，sdist SHA-256 为 `284dc547a042c309feafd9a9f4a74b2a8651b7963ea3ac6cb2f2d64889f6a8f3`。

候选 `browser_harness-0.1.13+boss.1-py3-none-any.whl` SHA-256 为 `5bdfdba0941698345166fe21a107d3ab2521c6817aa461f6ba3c0ea325b845cb`，位于 `.work/upgrade2/dependency-resolution-001/dist/`。使用 setuptools 84.0.0 构建，依赖、许可及项目链接继续保留；17 项源码及资源与归档逐字节比较通过。该 wheel 为本地修订，不代表上游发行。实际构建需要上述只读缓存路径与发行归档，正式交付仍须形成可重建输入并核对缓存来源。

在独立 Python 3.14.9 环境安装该 wheel 及完整固定 Hermes 源码的 `[all]` 依赖，`uv pip check` 检查 103 个包通过。Hermes 源码归档直接构建 wheel 被其 `setup.py` 正式拒绝；采用独立源码输入的 editable 安装。安装使用已缓存 `cryptography==50.0.2` wheel，SHA-256 为 `38f7d8fc8e36b30e01d3e38e1c9397292052bb1f21b8c7ffbdf4611be45c400c`；其构建来源尚须完整核查，其他解析出的传递依赖也尚未形成带制品摘要的锁文件。现有安装结果不能替代可重建交付。

`image_probe.py` 使用项目品牌图实际执行 `browser_harness.video_render.contact_sheet` 和 `masked_frame`，输出尺寸检查通过；安装后的 `browser_harness.run --help` 正常执行。实际 Hermes `hermes_release_compat_probe.py` 的 registry 检查通过，`run_conversation` 包含 `user_message`。以上检查未连接浏览器、未访问用户账号、未调用模型，也未验证图像处理的所有分支。

独立浏览器 CDP 检查使用新的 Chrome 资料目录与禁止非本机网络的 `sandbox-exec` 规则；Chrome 的子进程反复报告 `sandbox initialization failed: Operation not permitted`，Chrome 主进程退出码为 -5，通信进程连接返回拒绝。未关闭 Chrome 沙箱；该检查没有完成浏览器 CDP 通信。检查程序等待了其创建的主进程，系统拒绝 `pgrep` 读取进程列表，全部后代退出尚未证明。检查使用独立目录，没有连接用户账号。

接收前仍须核查完整锁文件与全部制品摘要、真实隔离浏览器 CDP 调用、全部业务工具和受管隔离；本地候选尚未替换产品环境。官方兼容发行仍可作为后续可审查来源。本次结果不能登记完整产品或全链路通过。

## 固定依赖范围与安装输入

PRD2.0 U2-FR-04 要求 Markdown、PDF、DOCX、XLSX、PPTX 的读取和生成。固定 Hermes 的 `documents` 声明 DOCX、XLSX、PPTX、PDF 所需库，`documents-pdf` 声明 PDF 提取库；基础依赖及 `[all]` 包含 `mcp` 和 `web`，对应 HLD 的工具通信与可配置文本研究。语音任务继续暂停，其他未选择的 extra 保留，不能据此登记其能力通过；额外渠道及模型 Provider 的实际接入仍需逐项确认。

`compare_dependencies.py` 按发行元数据、当前 macOS x86_64 和 Python 3.14 标记递归检查：基础依赖涉及 66 包，`[all]` 涉及 103 包，增加 `documents` 和 `documents-pdf` 后涉及 114 包，缺少项为零；环境实际为 115 包，另有不在该依赖闭包内的 `tzdata`。先前 248 包环境来自 `--all-extras`，包括上述范围以外的 Provider、渠道、语音及其他扩展。其 `discord.py[voice]` 要求 `PyNaCl<1.6`，而上游锁文件覆盖为 `>=1.6,<1.7`；这是额外依赖冲突，相关功能若需启用须重新解析和验证，不能由当前检查覆盖。

从原固定 Hermes `uv.lock` 使用 `uv export --frozen --no-dev --extra all --extra documents --extra documents-pdf --no-emit-project --no-emit-package browser-harness --format requirements-txt` 导出 `.work/upgrade2/dependency-resolution-001/official-constraints.txt`，SHA-256 为 `fa84b738cbd74262e5dadd5993541a3aad74234caafcf06f8b6bf710de2f7307`；其中保留上游制品 URL 对应的 SHA-256 清单，`protobuf==6.33.6`、`python-dateutil==2.9.0.post0` 与原锁文件一致。候选 wheel 单独使用前述本地摘要。此清单是原锁定版本的约束导出，尚不是经过完整制品来源验证的交付锁。

在独立环境执行 `uv pip install --no-config --index-url https://pypi.org/simple --python .work/upgrade2/dependency-resolution-001/venv/bin/python --find-links .work/upgrade2/dependency-resolution-001/dist --find-links .work/upgrade2/u2-01/cache/sdists-v10/pypi/cryptography/50.0.2/SPx47DgXdR41HzBv -c .work/upgrade2/dependency-resolution-001/official-constraints.txt --editable '.work/upgrade2/dependency-resolution-001/cache/sdists-v10/path/7f514581f9b997f3/xYP5jZaAg8X-8QWQ/src[all,documents,documents-pdf]'`，解析 114 包，安装后 `uv pip check` 检查 115 包通过；原有较新传递依赖已恢复至上游锁定版本。该命令依赖当前缓存路径，不能直接作为独立交付安装入口。

## Linux 目标制品

官方 [PyPI 发行记录](https://pypi.org/project/cryptography/50.0.2/)提供 `cryptography-50.0.2-cp311-abi3-manylinux_2_28_x86_64.whl`，标记为 CPython 3.11 起的 stable ABI 与 glibc 2.28 起的 Linux x86_64。已从官方文件地址下载至 `.work/upgrade2/dependency-resolution-001/linux-artifacts/`，实际 SHA-256 `4061c0079120205fb760c58acab6443e217307dcf05e3702cf970e0689972856`，与 PyPI 和原固定 `uv.lock` 相符。PyPI 页面记录其发布证明，实际目标 Python 的 wheel 标签和 glibc 版本仍须在虚拟机核查；该 wheel 未在 Linux 安装或执行。

使用 `uv pip compile --no-config --offline --python-version 3.14 --python-platform x86_64-unknown-linux-gnu --generate-hashes --no-emit-package hermes-agent --find-links .work/upgrade2/dependency-resolution-001/dist --find-links .work/upgrade2/dependency-resolution-001/linux-artifacts --constraint .work/upgrade2/dependency-resolution-001/official-constraints.txt --output-file .work/upgrade2/dependency-resolution-001/linux-dependencies.txt .work/upgrade2/dependency-resolution-001/linux-requirements.in` 生成目标依赖清单，SHA-256 `9fcc7a1ff57801629b62c78c57a482d572125bf6cb8a6e7194bc399cb847bdb8`。该文件包含本地 browser-harness wheel 的摘要、官方 cryptography Linux wheel 摘要、固定版本及各发行制品允许摘要；省略 Hermes editable 项以便目标目录选择。对应解析输入 `linux-requirements.in` 中的 Hermes 路径属于本机临时构建输入，不能直接用于其他机器。

目标接收需提供固定 Hermes 归档、核验过的候选 wheel、Linux 依赖清单、获准包源和固定 Python 3.14 运行环境；先在目标上验证归档及清单摘要，再使用 `uv pip install --require-hashes --find-links <候选wheel目录> --find-links <Linux制品目录> -r linux-dependencies.txt` 安装依赖。Hermes 官方拒绝普通 wheel 构建，目标必须采用经核验的独立源码目录，以 `uv pip install -c linux-dependencies.txt --find-links <候选wheel目录> --find-links <Linux制品目录> --editable '<固定源码目录>[all,documents,documents-pdf]'` 完整解析安装，并再次执行 `uv pip check` 和运行验证。上述目标命令尚未执行，源码目录准备方式及实际目标环境权限需要集成核查。

本机使用 `uv 0.13.5` 执行 `uv pip install --no-config --index-url https://pypi.org/simple --python .work/upgrade2/dependency-resolution-001/venv/bin/python --python-platform x86_64-unknown-linux-gnu --only-binary :all: --require-hashes --find-links .work/upgrade2/dependency-resolution-001/dist --find-links .work/upgrade2/dependency-resolution-001/linux-artifacts --target .work/upgrade2/dependency-resolution-001/linux-target -r .work/upgrade2/dependency-resolution-001/linux-dependencies.txt`，解析并安装 114 个 Linux 目标 wheel，包管理器按清单核验制品摘要。目标目录约 341 MiB；这些文件在 macOS 上准备，没有在 Linux 执行。目标解释器、实际平台标签及完整 Hermes 运行仍须在虚拟机验证。

相同命令改为 `--offline`、去除 `--index-url`，并将目标目录改为 `.work/upgrade2/dependency-resolution-001/linux-offline-check`，使用该任务目录的 uv 缓存再次安装 114 包成功；该检查表明本机缓存可供重复安装，不证明缓存可以独立迁移或替代逐个发行 wheel 的正式材料。

固定 Hermes 源码归档 `.work/upgrade2/u2-01/hermes.tar.gz` 约 85 MiB，复验 SHA-256 为 `2902bae7c50d1a93b10cc7a42042dc0c54a40f8b665de91b54e88553f20cff7b`。本地候选的上游发行归档、候选 `pyproject.toml`、wheel 与核对程序均位于 `.work/upgrade2/dependency-resolution-001/`。修订差异 `browser-harness-candidate.patch` SHA-256 为 `b86ab0185faceef15a2300cece8b2554f9167d73506b5cdfa904f30174b89245`，对候选配置的逆向只读适用性检查通过；源码修改须由文件编辑工具实施。候选实际源码引用只读缓存，正式重建仍需在授权范围内提供完整固定源码输入。安装命令中的目标目录和候选制品目录由集成负责人指定，不能引用本机随机缓存作为交付依赖。

Linux 安装工具固定为 [uv 0.13.5 的官方 wheel](https://pypi.org/project/uv/0.13.5/)，文件 `.work/upgrade2/dependency-resolution-001/linux-artifacts/uv-0.13.5-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl`，实际 SHA-256 `fa8d26e08e34c29c0c4e820cf3181757086d547240b4f4d31ff1d8bd810ca946`，与 PyPI 记录一致。该文件尚未在 Linux 运行；目标准备须确认 Python 的 `ensurepip` 和 wheel 安装条件，完成后核查 `uv --version`。

固定 Linux Python 输入为 `cpython-3.14.9+20261021-x86_64-unknown-linux-gnu-install_only.tar.gz`，来源为 [python-build-standalone 20261021 发行](https://github.com/astral-sh/python-build-standalone/releases/tag/20261021)。已续传至 `.work/upgrade2/dependency-resolution-001/linux-artifacts/cpython-3.14.9-linux.tar.gz`，大小 76,270,309 字节，实际 SHA-256 `dfa4c5a40c47f338f41658017be550c72247c391e6bfb1fa4da03ebc8451abdf`，与固定 Hermes `pm/lock.json` 相符。目标 Python 解释器、构建工具、Hermes 完整独立源码与 editable 安装，以及目标平台运行仍未完成；不能将目标制品摘要检查登记为完整交付通过。
