import asyncio
import socket

from hermes_guest_proxy import relay_streams
from hermes_vm_channel import HermesVMClientTLS, HermesVMServerTLS, require_peer_certificate


class HermesWorkspaceRelay:
    def __init__(self, tls, target_port, *, authority=None, target_tls=None):
        if not isinstance(tls, HermesVMServerTLS):
            raise ValueError("工作区通信需要虚拟机身份绑定")
        if type(target_port) is not int or not 1 <= target_port <= 65535:
            raise ValueError("工作区服务端口无效")
        if authority is not None:
            from hermes_run_authority import HermesRunAuthority
            if not isinstance(authority, HermesRunAuthority) or authority.vm_access != tls.access:
                raise ValueError("工作区通信与产品授权不匹配")
        if target_tls is not None and not isinstance(target_tls, HermesVMClientTLS):
            raise ValueError("工作区目标需要虚拟机身份绑定")
        if target_tls is not None and target_tls.access.bindings.store.path.resolve() != tls.access.bindings.store.path.resolve():
            raise ValueError("工作区目标与运行数据库不匹配")
        self.tls = tls
        self.authority = authority
        self.target_tls = target_tls
        self.target_port = target_port
        self.context = tls.access.require_workspace_context()
        self.target_context = target_tls.access.require_workspace_context() if target_tls is not None else None
        if self.target_context is not None and target_tls.access.run_id != self.target_context["root_run_id"]:
            raise ValueError("工作区目标需要根运行虚拟机")
        if self.target_context is not None and any(self.context[name] != self.target_context[name] for name in ("root_run_id", "root_epoch", "max_files", "max_bytes")):
            raise ValueError("工作区目标与根运行额度不匹配")
        self.server = None
        self.connections = set()
        self.targets = set()
        self.tasks = set()
        self.watcher = None
        self.closed = False

    def require_current(self):
        self.tls.__post_init__()
        if self.target_tls is not None:
            self.target_tls.__post_init__()
        if self.closed or self.tls.access.require_workspace_context() != self.context:
            raise ValueError("工作区通信身份已经失效")
        if self.authority is not None:
            if self.authority.vm_access != self.tls.access:
                raise ValueError("工作区通信与产品授权不匹配")
            self.authority.require()
        if self.target_tls is not None and self.target_tls.access.require_workspace_context() != self.target_context:
            raise ValueError("工作区目标身份已经失效")

    async def revalidate(self):
        valid = False
        try:
            self.require_current()
            valid = True
        finally:
            if not valid:
                await self.close()

    async def _watch(self):
        valid = False
        try:
            while not self.closed:
                self.require_current()
                await asyncio.sleep(0.1)
            valid = True
        finally:
            if not valid:
                await self.close()

    async def _handle(self, reader, writer):
        if self.closed or len(self.connections) >= 16:
            writer.close()
            await writer.wait_closed()
            return
        self.connections.add(writer)
        task = asyncio.current_task()
        self.tasks.add(task)
        remote = None
        try:
            secured = writer.get_extra_info("ssl_object")
            require_peer_certificate(secured.getpeercert(binary_form=True) if secured is not None else None,
                                     self.tls.peer_sha256)
            self.require_current()
            if self.target_tls is None:
                target_reader, remote = await asyncio.open_connection("127.0.0.1", self.target_port)
            else:
                target_reader, remote = await asyncio.open_connection("127.0.0.1", self.target_port,
                    ssl=self.target_tls.context, server_hostname=self.target_tls.peer_name, ssl_handshake_timeout=10)
                target_secured = remote.get_extra_info("ssl_object")
                require_peer_certificate(target_secured.getpeercert(binary_form=True) if target_secured is not None else None,
                                         self.target_tls.peer_sha256)
            self.targets.add(remote)
            self.require_current()
            await relay_streams(reader, writer, target_reader, remote, require_access=self.require_current)
        finally:
            self.connections.discard(writer)
            writer.close()
            if remote is not None:
                self.targets.discard(remote)
                remote.close()
                await remote.wait_closed()
            await writer.wait_closed()
            self.tasks.discard(task)

    async def listen(self, listener):
        if self.server is not None or self.closed:
            raise ValueError("工作区通信服务状态无效")
        if not isinstance(listener, socket.socket) or listener.family != socket.AF_INET or listener.type & socket.SOCK_STREAM != socket.SOCK_STREAM or listener.getsockname()[0] != "127.0.0.1":
            raise ValueError("工作区通信需要本机监听器")
        self.require_current()
        listener.setblocking(False)
        self.server = await asyncio.start_server(self._handle, sock=listener, ssl=self.tls.context,
                                                 ssl_handshake_timeout=10)
        self.watcher = asyncio.create_task(self._watch())
        return self

    async def close(self):
        self.closed = True
        if self.server is not None:
            self.server.close()
        connections = tuple(self.connections)
        for writer in (*connections, *tuple(self.targets)):
            writer.transport.abort()
        for task in tuple(self.tasks):
            await task
        if self.server is not None:
            await self.server.wait_closed()
