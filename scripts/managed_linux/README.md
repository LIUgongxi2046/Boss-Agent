# 受管 Linux 技术验证入口

本目录保存 U2-03 独立虚拟机技术验证使用的 Swift 源码、签名权限及 Debian 安装介质的串行启动配置。入口使用 Apple Virtualization.framework，配置 2 个虚拟 CPU、2 GiB 内存及零网络设备；它属于技术验证程序，尚未接入产品，也未证明正式隔离。

本次采用 macOS 13.7.8、Apple Swift 5.8.1 和 x86_64 宿主。Debian 13.7.0 amd64 netinst 映像的 SHA-256 为 `a7ef94ac2fb9a7fec454552abd629b7cc9d5155c886165a45649f5ce6167e355`；签名清单与撤销状态检查限制见 [U2-03](../../docs/development/U2-03.md)。安装映像和虚拟磁盘属于本机材料，不包含在源码目录。

从项目根目录编译并签名，输出目录需事先存在：

```bash
TMPDIR="$PWD/.work/upgrade2/managed-linux-001" swiftc -module-cache-path .work/upgrade2/managed-linux-001/swift-module-cache scripts/managed_linux/efi-probe.swift -o .work/upgrade2/managed-linux-001/source-build-vm
codesign --force --sign - --entitlements scripts/managed_linux/virtualization.entitlements .work/upgrade2/managed-linux-001/source-build-vm
codesign --verify --verbose=2 .work/upgrade2/managed-linux-001/source-build-vm
```

程序第一个参数为环境目录。`installed` 模式连接 `system.raw` 和 `workspace.raw`，使用 `efi.nvram`；当前实现还会打开同目录下的 Debian ISO。`efi-serial` 模式额外连接 `boot.cdr` 和 Debian ISO；`linux-probe` 使用 `install-vmlinuz` 和 `install-initrd.gz`，该模式只用于技术探针。各模式的程序签名及宿主权限均需实际核查。不要将安装入口用于现有用户实例。

串行启动介质由经摘要核验的 ISO 中的 `EFI`、`.disk`、`boot/grub`、`install.amd/gtk/vmlinuz` 和 `install.amd/initrd.gz` 生成。将内核及 initrd 保存为启动介质中的 `install.amd/vmlinuz` 和 `install.amd/initrd.gz`，使用文件编辑工具按 [serial-installer.patch](serial-installer.patch) 保存 GRUB 配置及标记文件，再将介质转换为可由框架读取的磁盘映像。本次介质为 128 MiB FAT 磁盘，`boot.cdr` 的 SHA-256 为 `73a466f7e9db5806292db5cb58da61ca031c426a953f4c3f27eb9e1decdfd18f`。介质包含启动配置及安装器材料；完整系统重建还需固定安装包清单、环境、签名验证与实际验证。

本次安装的系统盘和 EFI 变量属于独立运行数据。用户已授权对该新建虚拟机使用技术账号；[technical-console.exp](technical-console.exp) 从终端读取密码并建立串行会话，密码不写入该文件。使用技术入口时继续保护业务账号和用户资料。客体检查与实际范围见 [guest-check-20261102.md](guest-check-20261102.md)；局部结果不能代替完整隔离验收。

[vsock-probe.swift](vsock-probe.swift) 提供 Virtio Socket 的技术检查和宿主运行转发入口。宿主以相同 Swift 编译命令和 `virtualization.entitlements` 签名；`HermesVMManager` 核查制品摘要、虚拟机身份和受限凭据，再创建宿主进程。宿主控制身份请求已通过真实虚拟机和双向 TLS 检查；产品派发、工作区映射和异常恢复仍需验证。

Virtio Socket 技术入口要求环境目录中存在 `machine-identity`。在独立环境目录首次使用时，通过已编译入口的 `--init-identity` 参数及该文件的绝对路径创建；通过 `--check-identity` 参数及同一路径读取 SHA-256。入口禁止覆盖现有文件，读取时拒绝符号链接、其他用户拥有的文件及其他用户可访问的权限。该文件由宿主生成，需与独立虚拟机数据一起保存。框架机器标识、客体启动代次、运行租约及通信身份尚未形成可信绑定，这个技术入口不能用于正式产品准入。

技术入口可通过环境变量 `BOSS_VSOCK_FORWARD_PORT` 指定宿主回环 TCP 端口，将客体连接的原始字节转发至该端口；同时通过 `BOSS_VSOCK_CONTROL_PORT` 指定宿主回环控制端口，将宿主连接转发至客体 Virtio Socket 1025。`BOSS_VSOCK_DEPENDENCIES` 和 `BOSS_VSOCK_ENGINE` 指定只读依赖目录及固定引擎源码目录。两条路径各最多同时接受 16 条连接，运行转发模式不配置串行终端。转发程序不解析通信内容，也不单独认证通信双方；连接目标必须提供双向 TLS 及运行授权。对应客体 `HermesGuestRuntimeProxy` 使用 TLS 连接宿主 Virtio Socket，并向客体回环端口转发。宿主控制身份和客体运行转发已通过双向 TLS 技术检查；完整产品生命周期尚未验证。

`hermes_vm_credentials.py` 的 `--machine-sha256` 参数接收技术入口 `--check-identity` 返回的机器摘要，`--directory` 指定新建凭据目录；父目录必须属于当前用户且权限限制为本人访问。生成结果将宿主和客体密钥分置于 `host`、`guest` 子目录，管理器只共享 `guest` 目录。客体 agent 的 `--install-shared-credentials` 入口要求 root 私有 tmpfs 目录 `/run/boss-vm`，以及该目录内的专用只读挂载 `credential-share`；安装后卸载共享。客体启动入口为 [guest-vm-agent-start.sh](guest-vm-agent-start.sh)，systemd 服务配置为 [boss-vm-agent.service](boss-vm-agent.service)，`/etc/boss-vm/identity` 提供 `BOSS_VM_ID`，`/etc/boss-vm/workspace` 提供 `BOSS_WORKSPACE_UUID`。[guest-workspace-mount.sh](guest-workspace-mount.sh) 按配置的 UUID 核查并挂载 2 GiB ext4 工作区，运行目录位于磁盘内的 `runs`；挂载权限不符时清理本次建立的挂载。客体 agent 在控制监听器准备完成后通知 systemd 服务就绪。目标客体已安装并实际检查自启动、磁盘只读拒绝及重复启动；资源额度、产品派发和完整恢复仍待验证。
