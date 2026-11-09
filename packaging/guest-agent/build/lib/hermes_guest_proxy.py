import asyncio
import argparse
import socket
import ssl
import subprocess
import sys
from pathlib import Path
from uuid import UUID

from hermes_vm_channel import require_peer_certificate


async def relay_streams(left_reader, left_writer, right_reader, right_writer, *, require_access=None):
    async def forward(reader, writer):
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    return
                if require_access is not None:
                    require_access()
                writer.write(data)
                await writer.drain()
        finally:
            writer.close()

    try:
        async with asyncio.TaskGroup() as group:
            group.create_task(forward(left_reader, right_writer))
            group.create_task(forward(right_reader, left_writer))
    finally:
        left_writer.close()
        right_writer.close()
        await left_writer.wait_closed()
        await right_writer.wait_closed()


class HermesGuestRuntimeProxy:
    def __init__(self, context, host_name, host_certificate_sha256, host_port, *, credentials_directory=None, vm_id=None, dependencies=None):
        if not isinstance(context, ssl.SSLContext) or context.protocol != ssl.PROTOCOL_TLS_CLIENT or context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname or context.minimum_version < ssl.TLSVersion.TLSv1_3:
            raise ValueError("客体运行通信需要双向 TLS 1.3")
        if not isinstance(host_name, str) or not host_name or not isinstance(host_certificate_sha256, str) or len(host_certificate_sha256) != 64 or any(character not in "0123456789abcdef" for character in host_certificate_sha256):
            raise ValueError("宿主通信身份无效")
        if type(host_port) is not int or not 1 <= host_port <= 0xffffffff:
            raise ValueError("宿主 Virtio Socket 端口无效")
        self.context, self.host_name, self.host_certificate_sha256, self.host_port = context, host_name, host_certificate_sha256, host_port
        self.credentials_directory, self.vm_id, self.dependencies = credentials_directory, vm_id, dependencies

    async def listen_isolated(self, run_id, epoch, supervisor_unit, port):
        if sys.platform != "linux" or not isinstance(run_id, str) or str(UUID(run_id)) != run_id or type(epoch) is not int or epoch <= 0:
            raise ValueError("客体运行代理身份无效")
        if not isinstance(self.vm_id, str) or str(UUID(self.vm_id)) != self.vm_id:
            raise ValueError("客体运行代理缺少虚拟机身份")
        credentials = Path(self.credentials_directory) if self.credentials_directory is not None else None
        dependencies = Path(self.dependencies) if self.dependencies is not None else None
        if credentials is None or dependencies is None or not credentials.is_absolute() or credentials.resolve(strict=True) != credentials or not dependencies.is_absolute() or dependencies.resolve(strict=True) != dependencies:
            raise ValueError("客体运行代理路径不可核查")
        from hermes_vm_credentials import load_vm_credentials
        loaded = load_vm_credentials(credentials, self.vm_id, "guest")
        if (loaded.peer_name, loaded.peer_sha256) != (self.host_name, self.host_certificate_sha256):
            raise ValueError("客体运行代理凭据已经变化")
        if not isinstance(supervisor_unit, str) or not supervisor_unit.startswith("boss-") or not supervisor_unit.endswith(".service") or type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("客体运行代理配置无效")
        unit = "boss-runtime-proxy-" + run_id + "-" + str(epoch) + ".service"
        state = await asyncio.to_thread(subprocess.run, ["/usr/bin/systemctl", "show", unit, "--property=ActiveState", "--value"],
                                        check=True, capture_output=True, text=True, timeout=15)
        if state.stdout.strip() not in {"inactive", "failed"}:
            raise ValueError("客体运行代理已经存在")
        command = ["/usr/bin/systemd-run", "--unit=" + unit.removesuffix(".service"), "--property=Type=notify",
                   "--property=NotifyAccess=all", "--property=PrivateNetwork=yes", "--property=KillMode=control-group",
                   "--property=BindsTo=" + supervisor_unit, "--property=After=" + supervisor_unit,
                   "--setenv=PYTHONPATH=" + str(dependencies), sys.executable, str(Path(__file__).resolve()),
                   "--credentials", str(credentials), "--vm-id", self.vm_id, "--host-port", str(self.host_port), "--port", str(port)]
        started = False
        try:
            await asyncio.to_thread(subprocess.run, command, check=True, timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            started = True
            return HermesGuestPrivateProxyServer(unit)
        finally:
            if not started:
                await asyncio.to_thread(subprocess.run, ["/usr/bin/systemctl", "stop", unit], check=True, timeout=30,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    async def _handle(self, reader, writer, writers):
        writers.add(writer)
        connection = None
        connected = False
        try:
            connection = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
            connection.setblocking(False)
            await asyncio.wait_for(asyncio.get_running_loop().sock_connect(connection, (socket.VMADDR_CID_HOST, self.host_port)), 10)
            remote_reader, remote_writer = await asyncio.open_connection(sock=connection, ssl=self.context,
                server_hostname=self.host_name, ssl_handshake_timeout=10)
            writers.add(remote_writer)
            connected = True
            try:
                tls = remote_writer.get_extra_info("ssl_object")
                require_peer_certificate(tls.getpeercert(binary_form=True) if tls is not None else None, self.host_certificate_sha256)
                await relay_streams(reader, writer, remote_reader, remote_writer)
            finally:
                writers.discard(remote_writer)
                remote_writer.close()
                await remote_writer.wait_closed()
        finally:
            if not connected and connection is not None:
                connection.close()
            writers.discard(writer)
            writer.close()
            await writer.wait_closed()

    async def listen(self, listener):
        if sys.platform != "linux":
            raise ValueError("客体运行通信需要 Linux Virtio Socket")
        if not isinstance(listener, socket.socket) or listener.family != socket.AF_INET or listener.type & socket.SOCK_STREAM != socket.SOCK_STREAM or listener.getsockname()[0] != "127.0.0.1":
            raise ValueError("客体运行通信需要本机监听器")
        if self.context.verify_mode != ssl.CERT_REQUIRED or not self.context.check_hostname or self.context.minimum_version < ssl.TLSVersion.TLSv1_3:
            raise ValueError("客体运行通信需要双向 TLS 1.3")
        listener.setblocking(False)
        writers = set()
        tasks = set()
        state = {"closed": False}
        async def handle(reader, writer):
            if state["closed"]:
                writer.transport.abort()
                return
            task = asyncio.current_task()
            tasks.add(task)
            try:
                await self._handle(reader, writer, writers)
            finally:
                tasks.discard(task)
        server = await asyncio.start_server(handle, sock=listener)
        return HermesGuestProxyServer(server, writers, tasks, state)


class HermesGuestProxyServer:
    def __init__(self, server, writers, tasks, state):
        if not isinstance(server, asyncio.Server) or not isinstance(writers, set) or not isinstance(tasks, set) or state != {"closed": False}:
            raise ValueError("客体转发服务状态无效")
        self.server, self.writers, self.tasks, self.state = server, writers, tasks, state

    def close(self):
        self.state["closed"] = True
        self.server.close()
        for writer in tuple(self.writers):
            writer.transport.abort()
        for task in tuple(self.tasks):
            task.cancel()

    async def wait_closed(self):
        await self.server.wait_closed()
        tasks = tuple(self.tasks)
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=15)
            if pending:
                raise TimeoutError("客体转发连接未关闭")
            failures = [task.exception() for task in done if not task.cancelled() and task.exception() is not None]
            if failures:
                raise ExceptionGroup("客体转发连接关闭失败", failures)


class HermesGuestPrivateProxyServer:
    def __init__(self, unit):
        self.unit = unit

    def close(self):
        loaded = subprocess.run(["/usr/bin/systemctl", "show", self.unit, "--property=LoadState", "--value"],
                                check=True, capture_output=True, text=True, timeout=15).stdout.strip()
        if loaded == "not-found":
            return
        if loaded != "loaded":
            raise ValueError("客体运行代理状态不可核查")
        state = subprocess.run(["/usr/bin/systemctl", "show", self.unit, "--property=ActiveState", "--value"],
                               check=True, capture_output=True, text=True, timeout=15).stdout.strip()
        if state in {"inactive", "failed"}:
            return
        subprocess.run(["/usr/bin/systemctl", "stop", self.unit], check=True, timeout=30,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    async def wait_closed(self):
        loaded = await asyncio.to_thread(subprocess.run, ["/usr/bin/systemctl", "show", self.unit, "--property=LoadState", "--value"],
                                         check=True, capture_output=True, text=True, timeout=15)
        if loaded.stdout.strip() == "not-found":
            return
        if loaded.stdout.strip() != "loaded":
            raise ValueError("客体运行代理状态不可核查")
        result = await asyncio.to_thread(subprocess.run, ["/usr/bin/systemctl", "show", self.unit, "--property=ActiveState", "--value"],
                                         check=True, capture_output=True, text=True, timeout=15)
        if result.stdout.strip() not in {"inactive", "failed"}:
            raise ValueError("客体运行代理仍在运行")


async def serve_private(args):
    from hermes_vm_credentials import load_vm_credentials
    credentials = load_vm_credentials(args.credentials, args.vm_id, "guest")
    proxy = HermesGuestRuntimeProxy(credentials.client, credentials.peer_name, credentials.peer_sha256, args.host_port)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", args.port))
    listener.listen()
    server = await proxy.listen(listener)
    try:
        subprocess.run(["/usr/bin/systemd-notify", "--ready"], check=True, timeout=15,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        await asyncio.Event().wait()
    finally:
        server.close()
        await server.wait_closed()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--vm-id", required=True)
    parser.add_argument("--host-port", type=int, required=True)
    parser.add_argument("--port", type=int, required=True)
    asyncio.run(serve_private(parser.parse_args()))


if __name__ == "__main__":
    main()
