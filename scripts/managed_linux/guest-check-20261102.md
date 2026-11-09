# U2-03 独立客体检查

2026-11-02，用户授权本次新建虚拟机的技术账号登录。以下结果摘自串行终端工具输出；本次未连接产品账号或外部模型。登录和提权凭据未保存到本记录。

```text
uname -a
Linux boss-isolation 6.12.107+deb13-amd64 #1 SMP PREEMPT_DYNAMIC Debian 6.12.107-1 (2026-08-29) x86_64 GNU/Linux

dpkg-query -W linux-image-amd64
linux-image-amd64  6.12.107-1

python3 --version
Python 3.13.5
```

以 `dpkg-query -W` 将包清单保存在客体 `/root/boss-package-inventory.tsv`，共 263 行，SHA-256 `987ca02fdff2b2366a398363465fcea76223cb943379862360da45e0a33a05a5`。该清单记录已安装包和版本，尚未包含安装包制品摘要。

`lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINTS` 显示 `vda` 为 6G 系统盘，`vdb` 为独立 2G 工作区。`vdb` 格式化为 ext4 后挂载至 `/srv/boss-workspace`；`findmnt` 返回 `/dev/vdb ext4 rw,nosuid,nodev,relatime`。以技术账号在该目录创建检查文件，`stat` 返回所有者和组均为 `isolation`。当前挂载为本次会话操作，重启后自动挂载尚未配置或验证。

[guest-workspace-probe.sh](guest-workspace-probe.sh) 在独立工作区使用两个客体技术账号创建各自的目录和文件；对应账号创建文件成功，两个账号互相读取时均返回 `Permission denied`，输出 `OWNER_ACCESS_ALLOWED` 和 `CROSS_ACCESS_REJECTED`。脚本 SHA-256 `ab8c3ef38a1c50a482e832057bcef856ef24d39355a3945a7733db22971e42c4`。结果仅覆盖所测 Linux 账号和目录权限，不证明产品运行身份、挂载范围或特权进程隔离。

`ip -brief address` 仅列出 `lo`，IPv4 与 IPv6 路由查询均为空。虚拟机配置没有网络设备；未执行外部目标连接或 DNS 查询，无法据此声明全部网络边界通过。

```text
cat /sys/fs/cgroup/cgroup.controllers
cpuset cpu io memory hugetlb pids rdma misc

cat /sys/fs/cgroup/cgroup.subtree_control
cpu memory pids
```

在 `/sys/fs/cgroup/boss-probe` 写入并重读 `pids.max=64`、`memory.max=1073741824`、`memory.swap.max=0`、`cpu.max=100000 100000`。将 `pids.max` 临时设为 1 后，在组内尝试启动额外进程，shell 返回 `Cannot fork`，`pids.events` 返回 `max 1`。

另建内存检查组，设置 `memory.max=16777216`、`memory.swap.max=0`，在组内以 `dd` 向客体独立共享内存文件写入 32 MiB；进程返回 `Killed`，`memory.events` 包含 `max 36`、`oom 1`、`oom_kill 1`。检查文件随后清除。另建 CPU 检查组并设置 `cpu.max=10000 100000`，运行实际 `yes` 进程后，`cpu.stat` 显示 `nr_periods 148`、`nr_throttled 146`、`throttled_usec 13099333`；使用 `cgroup.kill` 后 `populated 0`。这些检查只覆盖所测限制和进程，不证明 Hermes 的累计 CPU 时间、并发预算或完整资源治理。

在该组内启动进入新会话的 `sh` 和其 `sleep` 子进程，检查输出：

```text
cat /sys/fs/cgroup/boss-probe/cgroup.procs /sys/fs/cgroup/boss-probe/cgroup.events
648
649
populated 1
frozen 0

ps -o pid,ppid,sid,comm -p 648,649
    PID    PPID     SID COMMAND
    648       1     648 sh
    649     648     648 sleep
```

向该组 `cgroup.kill` 写入 `1` 后，`cgroup.events` 返回 `populated 0`、`frozen 0`，同一 `ps` 查询仅返回表头。该次结果覆盖一个独立会话及子进程。

后续使用 [guest-cgroup-probe.sh](guest-cgroup-probe.sh) 在四组独立会话中并发启动进程及子进程；脚本 SHA-256 `6b6cdf2325493fc80dd83275b94785165e9141d4e1ad307444b0769f78415925`。实际输出包含：

```text
TREE_PROCESS_COUNT 12
sh: 1: cannot create /sys/fs/cgroup/cgroup.procs: Permission denied
CGROUP_ESCAPE_REJECTED
populated 0
frozen 0
TREE_RECLAIMED
```

该次检查覆盖普通技术账号向根 cgroup 迁移时的拒绝和四组并发后代回收；脚本所在共享目录为只读。仍需检查并发创建期间的回收竞争、正式管理进程异常、宿主重启和实际 Hermes 生命周期。

独立客体内的技术管理进程异常检查使用 [guest-manager-probe.sh](guest-manager-probe.sh)，SHA-256 `101f2d4aa6801314dde0330b5cc09fe32c673c9c40072f0d130ec57e50e277be`。技术管理进程启动四组受管进程后，以 `SIGKILL` 结束该管理进程；随后 `cgroup.procs` 仍列出 12 个进程。由独立控制终端向该组 `cgroup.kill` 写入 `1` 后，`cgroup.events` 返回 `populated 0`、`frozen 0`，检查时未发现本次 `sleep 300` 进程。该检查证明管理进程结束本身不能作为全部受管进程退出的证据；本次独立控制终端执行了显式回收，没有验证自动监督、VM 管理器异常或真实 Hermes 恢复。

后续使用 [guest-guardian-probe.py](guest-guardian-probe.py) 执行独立监督技术检查，脚本 SHA-256 `c5f952d00cfbf67a81d18a2da0a2d2e8504797cf29f093761ba54b43527b5751`。监督进程创建技术管理进程并通过 Linux `pidfd` 观察退出；检查时受管组含 12 个进程，管理进程收到 `SIGKILL` 后输出 `MANAGER_RETURN -9` 和 `GUARDIAN_RECLAIMED`，`cgroup.events` 返回 `populated 0`、`frozen 0`。另一次结束监督进程自身后，受管组仍为 `populated 1`；技术控制终端结束管理进程并显式回收后为 `populated 0`。该程序仅为独立客体探针，没有产品运行、租约或虚拟机身份绑定；监督进程自身异常、宿主异常及恢复仍需正式实现与验证。

随后使用客体 systemd 瞬态服务和 [guest-systemd-probe.sh](guest-systemd-probe.sh) 检查服务主进程异常退出。脚本 SHA-256 `330fbbc67967159c3199b2308c144224dd16bd265e4eea4eee33fc6c3507cad6`。`systemd-run --unit=boss-systemd-probe --property=Type=exec --property=KillMode=control-group /bin/bash /mnt/boss-probe/guest-systemd-probe.sh` 返回服务启动；核查时服务为 `active`，主进程 PID 614，服务 cgroup 含 13 个进程。对主进程发送 `SIGKILL` 后，`systemctl show` 返回 `Result=signal`、`ActiveState=failed`、`SubState=failed`，`ControlGroup` 为空；查询本次 `sleep 300` 进程无结果。该检查覆盖一次 systemd 服务主进程异常与四组独立会话后代，不证明宿主异常、VM 身份绑定或产品恢复。systemd 官方 [systemd.kill](https://www.freedesktop.org/software/systemd/man/latest/systemd.kill.html) 说明 `KillMode=control-group` 对停止服务时剩余的组内进程执行清理；本次结论以客体实际输出为准。

## Virtio Socket 技术检查

`vsock-probe.swift` 使用 Apple Virtualization.framework 创建无网络设备的独立虚拟机、Virtio Socket 和只读 Virtio 文件共享。宿主以系统随机数生成临时检查凭据及每次连接的随机 challenge，客体程序 `guest-vsock-probe.py` 使用 Python 标准库 HMAC-SHA256 回应；宿主使用 CryptoKit 核验。凭据未写入本记录或源码。

```text
VSOCK_AUTHENTICATED
VSOCK_RESPONSE OK

VSOCK_REJECTED
VSOCK_RESPONSE DENIED

touch /mnt/boss-probe/access-check
touch: cannot touch '/mnt/boss-probe/access-check': Read-only file system
```

正确凭据与错误凭据各检查一次，客体未连接外部网络。此技术程序只验证单次 challenge 响应和共享目录的只读行为；凭据分发、VM 身份绑定、访问范围、请求协议、拒绝服务、并发及产品接入尚未验证，不能作为正式通信准入。

检查结束后在客体执行 `poweroff`，再停止技术终端；宿主进程查询未发现本次虚拟机程序。关闭时宿主卷可用约 4.3 GiB。跨运行文件范围、完整资源治理及完整故障恢复保持未验证。
