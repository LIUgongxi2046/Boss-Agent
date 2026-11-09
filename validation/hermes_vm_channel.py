import hashlib
import hmac
import socket
import ssl
from dataclasses import dataclass

from aiohttp import web


def require_peer_certificate(certificate, peer_sha256):
    if not isinstance(peer_sha256, str) or len(peer_sha256) != 64 or any(character not in "0123456789abcdef" for character in peer_sha256):
        raise ValueError("虚拟机通信证书摘要无效")
    if not certificate or not hmac.compare_digest(hashlib.sha256(certificate).hexdigest(), peer_sha256):
        raise ValueError("虚拟机通信对方证书不匹配")


@dataclass(frozen=True)
class HermesVMServerTLS:
    context: ssl.SSLContext
    peer_sha256: str
    access: object

    def __post_init__(self):
        from hermes_vm_identity import HermesVMRunAccess
        if not isinstance(self.context, ssl.SSLContext) or self.context.protocol != ssl.PROTOCOL_TLS_SERVER:
            raise ValueError("虚拟机通信需要服务端 TLS 配置")
        if self.context.verify_mode != ssl.CERT_REQUIRED or self.context.minimum_version < ssl.TLSVersion.TLSv1_3:
            raise ValueError("虚拟机通信需要 TLS 1.3 和客户端证书验证")
        if not isinstance(self.peer_sha256, str) or len(self.peer_sha256) != 64 or any(character not in "0123456789abcdef" for character in self.peer_sha256):
            raise ValueError("虚拟机通信证书摘要无效")
        if not isinstance(self.access, HermesVMRunAccess):
            raise ValueError("虚拟机通信缺少运行绑定")

    @web.middleware
    async def require_peer(self, request, handler):
        transport = request.transport
        tls = transport.get_extra_info("ssl_object") if transport is not None else None
        certificate = tls.getpeercert(binary_form=True) if tls is not None else None
        if not certificate or not hmac.compare_digest(hashlib.sha256(certificate).hexdigest(), self.peer_sha256):
            raise web.HTTPForbidden(text="虚拟机通信身份不可核查")
        self.access.require()
        return await handler(request)


@dataclass(frozen=True)
class HermesVMClientTLS:
    context: ssl.SSLContext
    peer_name: str
    peer_sha256: str
    access: object

    def __post_init__(self):
        from hermes_vm_identity import HermesVMRunAccess
        if not isinstance(self.context, ssl.SSLContext) or self.context.protocol != ssl.PROTOCOL_TLS_CLIENT:
            raise ValueError("虚拟机通信需要客户端 TLS 配置")
        if self.context.verify_mode != ssl.CERT_REQUIRED or not self.context.check_hostname or self.context.minimum_version < ssl.TLSVersion.TLSv1_3:
            raise ValueError("虚拟机通信需要 TLS 1.3 和服务端证书验证")
        if not isinstance(self.peer_name, str) or not self.peer_name or not isinstance(self.peer_sha256, str) or len(self.peer_sha256) != 64 or any(character not in "0123456789abcdef" for character in self.peer_sha256):
            raise ValueError("虚拟机通信对方身份无效")
        if not isinstance(self.access, HermesVMRunAccess):
            raise ValueError("虚拟机通信缺少运行绑定")
        if self.peer_name != "boss-vm-" + self.access.vm_id + ".guest":
            raise ValueError("虚拟机通信名称与运行绑定不匹配")


def authenticate_vm_socket(connection, context, peer_sha256, *, server_side, server_hostname=None, timeout=10):
    if not isinstance(connection, socket.socket) or isinstance(connection, ssl.SSLSocket):
        raise ValueError("虚拟机通信需要未包装的实际连接")
    if not isinstance(context, ssl.SSLContext) or context.verify_mode != ssl.CERT_REQUIRED:
        raise ValueError("虚拟机通信需要验证双方证书")
    if context.minimum_version < ssl.TLSVersion.TLSv1_3:
        raise ValueError("虚拟机通信需要 TLS 1.3")
    if type(server_side) is not bool:
        raise ValueError("虚拟机通信身份无效")
    if not isinstance(peer_sha256, str) or len(peer_sha256) != 64 or any(character not in "0123456789abcdef" for character in peer_sha256):
        raise ValueError("虚拟机通信证书摘要无效")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 60:
        raise ValueError("虚拟机通信超时无效")
    if server_side:
        if server_hostname is not None:
            raise ValueError("服务端不能指定目标名称")
    elif not context.check_hostname or not isinstance(server_hostname, str) or not server_hostname:
        raise ValueError("客户端需要核查目标名称")
    connection.settimeout(timeout)
    secured = None
    accepted = False
    try:
        secured = context.wrap_socket(connection, server_side=server_side, server_hostname=server_hostname)
        certificate = secured.getpeercert(binary_form=True)
        require_peer_certificate(certificate, peer_sha256)
        accepted = True
        return secured
    finally:
        if not accepted:
            if secured is None:
                connection.close()
            else:
                secured.close()
