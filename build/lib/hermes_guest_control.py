import asyncio
import hashlib
import json
import socket
import ssl
from contextlib import AsyncExitStack
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from aiohttp import web

from hermes_guest_systemd import HermesGuestSystemd
from hermes_guest_proxy import HermesGuestRuntimeProxy
from hermes_vm_channel import require_peer_certificate


class HermesGuestServer:
    def __init__(self, runner, server):
        self.runner = runner
        self.server = server

    async def cleanup(self):
        async with AsyncExitStack() as stack:
            stack.push_async_callback(self.server.wait_closed)
            stack.push_async_callback(self.runner.cleanup)
            stack.callback(self.server.close)


class HermesGuestControl:
    def __init__(self, manager, runtime_proxy, tls_context, host_certificate_sha256):
        if not isinstance(manager, HermesGuestSystemd):
            raise ValueError("客体控制需要 systemd 管理器")
        if not isinstance(runtime_proxy, HermesGuestRuntimeProxy):
            raise ValueError("客体控制需要运行通信转发")
        if not isinstance(tls_context, ssl.SSLContext) or tls_context.protocol != ssl.PROTOCOL_TLS_SERVER or tls_context.verify_mode != ssl.CERT_REQUIRED or tls_context.minimum_version < ssl.TLSVersion.TLSv1_3:
            raise ValueError("客体控制需要双向 TLS 1.3")
        if not isinstance(host_certificate_sha256, str) or len(host_certificate_sha256) != 64 or any(character not in "0123456789abcdef" for character in host_certificate_sha256):
            raise ValueError("宿主证书摘要无效")
        self.manager = manager
        self.runtime_proxy = runtime_proxy
        self.tls_context = tls_context
        self.host_certificate_sha256 = host_certificate_sha256
        self.runs = {}
        self.locks = {}
        self.references = {}

    @web.middleware
    async def authorize(self, request, handler):
        transport = request.transport
        secured = transport.get_extra_info("ssl_object") if transport is not None else None
        certificate = secured.getpeercert(binary_form=True) if secured is not None else None
        require_peer_certificate(certificate, self.host_certificate_sha256)
        return await handler(request)

    async def identity(self, request):
        if request.query:
            raise web.HTTPBadRequest(text="客体身份请求无效")
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
        if str(UUID(boot_id)) != boot_id:
            raise ValueError("客体启动身份不可核查")
        return web.json_response({"boot_id": boot_id})

    async def start(self, request):
        if request.query or request.content_type != "application/json":
            raise web.HTTPBadRequest(text="客体启动请求无效")
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {"run_id", "epoch", "boot_id", "budget", "bootstrap"}:
            raise web.HTTPBadRequest(text="客体启动字段无效")
        if not isinstance(body["run_id"], str) or str(UUID(body["run_id"])) != body["run_id"] or type(body["epoch"]) is not int or body["epoch"] <= 0 or not isinstance(body["boot_id"], str) or str(UUID(body["boot_id"])) != body["boot_id"]:
            raise web.HTTPBadRequest(text="客体运行身份无效")
        if not isinstance(body["bootstrap"], dict) or not isinstance(body["bootstrap"].get("endpoint"), str):
            raise web.HTTPBadRequest(text="客体通信入口无效")
        endpoint = urlsplit(body["bootstrap"]["endpoint"])
        if endpoint.scheme != "http" or endpoint.hostname != "127.0.0.1" or not endpoint.port or endpoint.username or endpoint.password or endpoint.path not in ("", "/") or endpoint.query or endpoint.fragment:
            raise web.HTTPBadRequest(text="客体通信入口无效")
        key = (body["run_id"], body["epoch"])
        async with self.locks.setdefault(key, asyncio.Lock()):
            return await self._start(body, endpoint, key)

    async def _start(self, body, endpoint, key):
        if Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip() != body["boot_id"]:
            raise web.HTTPConflict(text="客体启动身份已经变化")
        digest = hashlib.sha256(json.dumps(body, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        unit, created = self.manager.identities.reserve_start(body["run_id"], body["epoch"], body["boot_id"], digest)
        if not created:
            return web.json_response({"unit": unit, "state": "UNKNOWN"})
        self.runs[key] = (digest, unit, body["boot_id"], None, None)
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server = None
        process = None
        reference = None
        watch = None
        started = False
        try:
            listener.bind(("127.0.0.1", endpoint.port))
            listener.listen()
            server = await self.runtime_proxy.listen(listener)
            from hermes_guest_unit_reference import HermesGuestUnitWatch
            watch = await HermesGuestUnitWatch.prepare(body["run_id"], body["epoch"], body["boot_id"])
            returned_unit, process, encoded = self.manager.launch(body["run_id"], body["epoch"], body["boot_id"], body["budget"], body["bootstrap"], defer_bootstrap=True)
            if returned_unit != unit:
                raise ValueError("客体 unit 与运行身份不一致")
            reference = await watch.acquire()
            if process.poll() is not None:
                raise ValueError("客体运行在授权前已经退出")
            try:
                process.stdin.write(encoded)
            finally:
                process.stdin.close()
            self.runs[key] = (digest, unit, body["boot_id"], process, server)
            self.references[key] = reference
            started = True
        finally:
            async with AsyncExitStack() as stack:
                if not started:
                    stack.callback(listener.close)
                    if server is not None:
                        stack.push_async_callback(server.wait_closed)
                        stack.callback(server.close)
                    if reference is not None:
                        stack.push_async_callback(reference.close)
                    if process is not None:
                        stack.callback(self.manager.identities.record_unknown_exit, body["run_id"], body["epoch"], body["boot_id"])
                        stack.callback(self.manager.identities.mark_stopped, body["run_id"], body["epoch"], body["boot_id"])
                        stack.push_async_callback(asyncio.to_thread, self.manager.stop, body["run_id"], body["epoch"])
                        if process.stdin is not None and not process.stdin.closed:
                            stack.callback(process.stdin.close)
                if watch is not None:
                    stack.callback(watch.close)
        return web.json_response({"unit": unit, "state": "UNKNOWN"})

    async def stop(self, request):
        if request.query or request.content_type != "application/json":
            raise web.HTTPBadRequest(text="客体停止请求无效")
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {"run_id", "epoch", "boot_id"} or not isinstance(body["run_id"], str) or type(body["epoch"]) is not int or not isinstance(body["boot_id"], str):
            raise web.HTTPBadRequest(text="客体停止字段无效")
        if str(UUID(body["run_id"])) != body["run_id"] or body["epoch"] <= 0 or str(UUID(body["boot_id"])) != body["boot_id"]:
            raise web.HTTPBadRequest(text="客体停止身份无效")
        key = (body["run_id"], body["epoch"])
        async with self.locks.setdefault(key, asyncio.Lock()):
            return await self._stop(body, key)

    async def _stop(self, body, key):
        saved = self.runs.get(key)
        if (saved is not None and saved[2] != body["boot_id"]) or Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip() != body["boot_id"]:
            raise web.HTTPConflict(text="客体运行身份不可核查")
        try:
            _, existed = self.manager.identities.mark_stopped(body["run_id"], body["epoch"], body["boot_id"])
            if not existed:
                return web.json_response({"state": "UNKNOWN"})
            self.manager.identities.record_unknown_exit(body["run_id"], body["epoch"], body["boot_id"])
            state = await asyncio.to_thread(self.manager.stop, body["run_id"], body["epoch"])
            reference = self.references.get(key)
            if reference is not None:
                observation = await reference.observe()
                self.manager.identities.record_exit_observation(body["run_id"], body["epoch"], body["boot_id"], observation)
        finally:
            async with AsyncExitStack() as stack:
                if saved is not None and saved[4] is not None:
                    stack.push_async_callback(saved[4].wait_closed)
                    stack.callback(saved[4].close)
                reference = self.references.pop(key, None)
                if reference is not None:
                    stack.push_async_callback(reference.close)
        return web.json_response({"state": state})

    async def exit_receipt(self, request):
        if request.query or request.content_type != "application/json":
            raise web.HTTPBadRequest(text="客体退出查询请求无效")
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {"run_id", "epoch", "boot_id"}:
            raise web.HTTPBadRequest(text="客体退出查询字段无效")
        if not isinstance(body["run_id"], str) or str(UUID(body["run_id"])) != body["run_id"] or type(body["epoch"]) is not int or body["epoch"] <= 0 or not isinstance(body["boot_id"], str) or str(UUID(body["boot_id"])) != body["boot_id"]:
            raise web.HTTPBadRequest(text="客体退出查询身份无效")
        result = self.manager.identities.read_exit(body["run_id"], body["epoch"], body["boot_id"])
        return web.json_response(result)

    async def exit_observation(self, request):
        if request.query or request.content_type != "application/json":
            raise web.HTTPBadRequest(text="客体退出观察请求无效")
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {"run_id", "epoch", "boot_id"}:
            raise web.HTTPBadRequest(text="客体退出观察字段无效")
        if not isinstance(body["run_id"], str) or str(UUID(body["run_id"])) != body["run_id"] or type(body["epoch"]) is not int or body["epoch"] <= 0 or not isinstance(body["boot_id"], str) or str(UUID(body["boot_id"])) != body["boot_id"]:
            raise web.HTTPBadRequest(text="客体退出观察身份无效")
        return web.json_response(self.manager.identities.read_exit_observation(body["run_id"], body["epoch"], body["boot_id"]))

    async def inspect(self, request):
        if request.query or request.content_type != "application/json":
            raise web.HTTPBadRequest(text="客体查询请求无效")
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {"run_id", "epoch", "boot_id"} or not isinstance(body["run_id"], str) or type(body["epoch"]) is not int or not isinstance(body["boot_id"], str):
            raise web.HTTPBadRequest(text="客体查询字段无效")
        saved = self.runs.get((body["run_id"], body["epoch"]))
        if Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip() != body["boot_id"]:
            raise web.HTTPConflict(text="客体运行身份不可核查")
        self.manager.identities.read_control(body["run_id"], body["epoch"], body["boot_id"])
        exited = saved[3].poll() is not None if saved is not None and saved[3] is not None else None
        unit = "boss-" + body["run_id"] + "-" + str(body["epoch"]) + ".service"
        return web.json_response({"unit": unit, "process_exited": exited, "state": "UNKNOWN"})

    async def cpu(self, request):
        if request.query or request.content_type != "application/json":
            raise web.HTTPBadRequest(text="客体 CPU 查询请求无效")
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {"run_id", "epoch", "boot_id"}:
            raise web.HTTPBadRequest(text="客体 CPU 查询字段无效")
        run_id, epoch, boot_id = body["run_id"], body["epoch"], body["boot_id"]
        if not isinstance(run_id, str) or str(UUID(run_id)) != run_id or type(epoch) is not int or epoch <= 0 or not isinstance(boot_id, str) or str(UUID(boot_id)) != boot_id:
            raise web.HTTPBadRequest(text="客体 CPU 查询身份无效")
        key = (run_id, epoch)
        async with self.locks.setdefault(key, asyncio.Lock()):
            saved = self.runs.get(key)
            if Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip() != boot_id or saved is None or saved[2] != boot_id or saved[3] is None or saved[3].poll() is not None:
                raise web.HTTPConflict(text="客体 CPU 运行身份不可核查")
            if self.manager.identities.read_control(run_id, epoch, boot_id) != "RESERVED":
                raise web.HTTPConflict(text="客体 CPU 运行已经停止")
            value = await asyncio.to_thread(self.manager.cpu_usage, run_id, epoch)
            if saved[3].poll() is not None:
                raise web.HTTPConflict(text="客体 CPU 运行已经退出")
            return web.json_response({"unit": saved[1], "boot_id": boot_id, "cpu_ns": value})

    def application(self):
        app = web.Application(client_max_size=16384, middlewares=[self.authorize])
        app.on_cleanup.append(self.cleanup)
        app.router.add_post("/internal/v1/guest/identity", self.identity)
        app.router.add_post("/internal/v1/guest/start", self.start)
        app.router.add_post("/internal/v1/guest/stop", self.stop)
        app.router.add_post("/internal/v1/guest/inspect", self.inspect)
        app.router.add_post("/internal/v1/guest/cpu", self.cpu)
        app.router.add_post("/internal/v1/guest/exit", self.exit_receipt)
        app.router.add_post("/internal/v1/guest/exit-observation", self.exit_observation)
        return app

    async def cleanup(self, app):
        async with AsyncExitStack() as stack:
            for reference in tuple(self.references.values()):
                stack.push_async_callback(reference.close)
            self.references.clear()

    async def listen(self, listener):
        if not isinstance(listener, socket.socket) or listener.family != socket.AF_VSOCK or listener.type & socket.SOCK_STREAM != socket.SOCK_STREAM:
            raise ValueError("客体控制需要 Virtio Socket 监听器")
        if self.tls_context.verify_mode != ssl.CERT_REQUIRED or self.tls_context.minimum_version < ssl.TLSVersion.TLSv1_3:
            raise ValueError("客体控制需要双向 TLS 1.3")
        listener.setblocking(False)
        runner = web.AppRunner(self.application())
        started = False
        try:
            await runner.setup()
            server = await asyncio.get_running_loop().create_server(runner.server, sock=listener, ssl=self.tls_context)
            started = True
            return HermesGuestServer(runner, server)
        finally:
            if not started:
                await runner.cleanup()
                listener.close()
