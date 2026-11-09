import asyncio
import socket
import ssl
import sys

from hermes_vm_channel import require_peer_certificate


async def relay_streams(left_reader, left_writer, right_reader, right_writer):
    async def forward(reader, writer):
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    return
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
    def __init__(self, context, host_name, host_certificate_sha256, host_port):
        if not isinstance(context, ssl.SSLContext) or context.protocol != ssl.PROTOCOL_TLS_CLIENT or context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname or context.minimum_version < ssl.TLSVersion.TLSv1_3:
            raise ValueError("客体运行通信需要双向 TLS 1.3")
        if not isinstance(host_name, str) or not host_name or not isinstance(host_certificate_sha256, str) or len(host_certificate_sha256) != 64 or any(character not in "0123456789abcdef" for character in host_certificate_sha256):
            raise ValueError("宿主通信身份无效")
        if type(host_port) is not int or not 1 <= host_port <= 0xffffffff:
            raise ValueError("宿主 Virtio Socket 端口无效")
        self.context, self.host_name, self.host_certificate_sha256, self.host_port = context, host_name, host_certificate_sha256, host_port

    async def _handle(self, reader, writer):
        connection = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
        connection.setblocking(False)
        connected = False
        try:
            await asyncio.wait_for(asyncio.get_running_loop().sock_connect(connection, (socket.VMADDR_CID_HOST, self.host_port)), 10)
            remote_reader, remote_writer = await asyncio.open_connection(sock=connection, ssl=self.context,
                server_hostname=self.host_name, ssl_handshake_timeout=10)
            connected = True
            try:
                tls = remote_writer.get_extra_info("ssl_object")
                require_peer_certificate(tls.getpeercert(binary_form=True) if tls is not None else None, self.host_certificate_sha256)
                await relay_streams(reader, writer, remote_reader, remote_writer)
            finally:
                remote_writer.close()
                await remote_writer.wait_closed()
        finally:
            if not connected:
                connection.close()
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
        return await asyncio.start_server(self._handle, sock=listener)
