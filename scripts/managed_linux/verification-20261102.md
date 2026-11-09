# U2-03 技术入口核查输出

日期：2026-11-02。以下命令与输出摘自本次工具结果；空输出及退出状态均如实记录。虚拟机未在本次核查中启动，客体未认证。

```text
swiftc --version
Apple Swift version 5.8.1 (swiftlang-5.8.0.124.5 clang-1403.0.22.11.100)
Target: x86_64-apple-darwin22.6.0
exit_code: 0
```

```text
sw_vers
ProductName: macOS
ProductVersion: 13.7.8
BuildVersion: 22H730
exit_code: 0
```

```text
cmp scripts/managed_linux/efi-probe.swift .work/upgrade2/managed-linux-001/efi-probe.swift
exit_code: 0
```

```text
cmp scripts/managed_linux/virtualization.entitlements .work/upgrade2/u2-03/virtualization-capability.entitlements
exit_code: 0
```

```text
TMPDIR="$PWD/.work/upgrade2/managed-linux-001" swiftc -module-cache-path .work/upgrade2/managed-linux-001/swift-module-cache scripts/managed_linux/efi-probe.swift -o .work/upgrade2/managed-linux-001/source-build-vm
exit_code: 0
```

```text
codesign --force --sign - --entitlements scripts/managed_linux/virtualization.entitlements .work/upgrade2/managed-linux-001/source-build-vm
exit_code: 0
```

```text
codesign --verify --verbose=2 .work/upgrade2/managed-linux-001/source-build-vm
.work/upgrade2/managed-linux-001/source-build-vm: valid on disk
.work/upgrade2/managed-linux-001/source-build-vm: satisfies its Designated Requirement
exit_code: 0
```

只读挂载实际使用的 `boot.cdr` 至 `.work/upgrade2/managed-linux-001/boot-volume` 后执行：

```text
git apply --reverse --check --directory=.work/upgrade2/managed-linux-001/boot-volume scripts/managed_linux/serial-installer.patch
exit_code: 0
```

```text
cmp .work/upgrade2/managed-linux-001/install-vmlinuz .work/upgrade2/managed-linux-001/boot-volume/install.amd/vmlinuz
exit_code: 0
```

```text
cmp .work/upgrade2/managed-linux-001/install-initrd.gz .work/upgrade2/managed-linux-001/boot-volume/install.amd/initrd.gz
exit_code: 0
```

只读介质随后卸载，输出为 `"disk2" ejected.`、退出状态 0。编译和配置核查的范围不包含完整系统重建、客体运行或隔离验收。
