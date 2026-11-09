import asyncio
import os
import signal
import socket
import math
import hashlib
import io
import json
import logging
import sys
import zipfile
from contextlib import asynccontextmanager
from dataclasses import dataclass
from email.parser import BytesParser
from importlib.metadata import PathDistribution
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit

from aiohttp import web

from agent_run_tool_budget import RunToolBudget
from hermes_budget_gateway import ProviderGateway, RunBoundBudgetStore
from hermes_bridge import EngineEventSink, EngineProcessSupervisor
from hermes_process_evidence import HermesProcessEvidence
from hermes_transport import HermesTransport


logger = logging.getLogger(__name__)


_ADAPTER_RESOURCES = frozenset({
    "hermes_engine_entry.py", "hermes_transport_client.py", "hermes_tool_names.py", "hermes_tool_registration.py",
    "hermes_domain_schema.py", "hermes_meeting_brief_public.py", "agent_artifact_hermes.py", "agent_artifact_schema.json",
    "hermes_process_anchor.py", "hermes_start_gate.py", "hermes_parent_guard.py", "hermes_resource_exec.py",
})

_EXPERIMENTAL_PROFILE = '''(version 1)
(deny default)
(allow process-exec)
(allow signal (target self))
(allow sysctl-read)
(allow file-read-metadata)
(allow file-read* (literal "/"))
(allow file-read*
    (subpath "/System")
    (subpath "/bin")
    (subpath "/sbin")
    (subpath "/usr/bin")
    (subpath "/usr/sbin")
    (subpath "/usr/lib")
    (subpath "/usr/share")
    (subpath "/Library/Frameworks")
    (subpath "/private/var/db/timezone")
    (subpath (param "PYTHON_BASE"))
    (subpath (param "RUNTIME"))
    (subpath (param "ENGINE"))
    (subpath (param "ADAPTER"))
    (subpath (param "WORK")))
(allow file-write* (subpath (param "WORK")))
(allow file-read* (literal "/dev/null") (literal "/dev/zero") (literal "/dev/random") (literal "/dev/urandom"))
(allow file-write* (literal "/dev/null"))
(allow network-outbound (remote ip (param "ENDPOINT")))
'''


def _experimental_path(path, expected, *, descendant=False):
    supplied, boundary = Path(path), Path(expected)
    if not supplied.is_absolute() or not supplied.exists() or supplied != supplied.resolve(strict=True):
        raise ValueError("实验隔离路径无效或包含符号链接")
    if not boundary.exists() or boundary != boundary.resolve(strict=True):
        raise ValueError("实验隔离范围无效或包含符号链接")
    outside = not supplied.is_relative_to(boundary) or supplied == boundary if descendant else supplied != boundary
    if outside:
        raise ValueError("实验隔离路径超出受控范围")
    return supplied


def _experimental_adapter_paths(adapter):
    root = Path(__file__).resolve().parent.parent
    if not isinstance(adapter, dict) or set(adapter) != {"source_root", "wheel_path", "installed_directory"}:
        raise ValueError("引擎适配来源参数无效")
    _experimental_path(adapter["source_root"], root)
    _experimental_path(adapter["wheel_path"], root / ".work/upgrade2/u2-01/hermes-adapter-wheel-002/boss_agent_hermes_adapter-0.1.0-py3-none-any.whl")
    _experimental_path(adapter["installed_directory"], root / ".work/upgrade2/u2-01/hermes-adapter-env-001/lib/python3.14/site-packages")


def verify_experimental_adapter(source_root, wheel_path, installed_directory):
    root, wheel, installed = Path(source_root), Path(wheel_path), Path(installed_directory)
    if any(path.is_symlink() for path in (root, wheel, installed)) or not root.is_dir() or not wheel.is_file() or not installed.is_dir():
        raise ValueError("引擎适配制品路径不可核查")
    manifest = root / "hermes-engine-resources.txt"
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError("引擎适配资源清单不可核查")
    entries = manifest.read_text(encoding="utf-8").splitlines()
    if len(entries) != len(_ADAPTER_RESOURCES) or set(entries) != {"validation/" + name for name in _ADAPTER_RESOURCES}:
        raise ValueError("引擎适配资源清单不匹配")
    records = list(installed.glob("boss_agent_hermes_adapter-*.dist-info"))
    if len(records) != 1 or records[0].is_symlink() or not records[0].is_dir():
        raise ValueError("引擎适配安装记录不可核查")
    installed_metadata = PathDistribution(records[0]).metadata
    wheel_bytes = wheel.read_bytes()
    wheel_digest = hashlib.sha256(wheel_bytes).hexdigest()
    with zipfile.ZipFile(io.BytesIO(wheel_bytes)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("引擎适配 wheel 包含重复文件")
        if {name for name in names if "/" not in name} != _ADAPTER_RESOURCES:
            raise ValueError("引擎适配 wheel 资源清单不匹配")
        metadata_paths = [name for name in names if name.startswith("boss_agent_hermes_adapter-") and name.endswith(".dist-info/METADATA") and name.count("/") == 1]
        if len(metadata_paths) != 1:
            raise ValueError("引擎适配 wheel 元数据不可核查")
        wheel_metadata = BytesParser().parsebytes(archive.read(metadata_paths[0]))
        fields = ("Name", "Version", "Requires-Python")
        if wheel_metadata.get("Name") != "boss-agent-hermes-adapter" or any(not wheel_metadata.get(field) or wheel_metadata.get(field) != installed_metadata.get(field) for field in fields):
            raise ValueError("引擎适配元数据不匹配")
        for name in sorted(_ADAPTER_RESOURCES):
            original, target = root / "validation" / name, installed / name
            if original.is_symlink() or target.is_symlink() or not original.is_file() or not target.is_file():
                raise ValueError("引擎适配资源不可核查")
            source_bytes = original.read_bytes()
            if name not in names or source_bytes != archive.read(name) or source_bytes != target.read_bytes():
                raise ValueError("引擎适配资源内容不匹配")
    return {"entry": installed / "hermes_engine_entry.py", "wheel_sha256": wheel_digest, "version": wheel_metadata["Version"]}


def experimental_sandbox_command(command, process_config, installed_directory, profile_text, profile_sha256):
    from hermes_bridge import EngineProcessConfig

    if not isinstance(process_config, EngineProcessConfig) or not isinstance(command, list) or not command or any(not isinstance(item, str) or not item for item in command):
        raise ValueError("实验隔离命令无效")
    if not isinstance(profile_text, str) or not profile_text or not isinstance(profile_sha256, str) or hashlib.sha256(profile_text.encode("utf-8")).hexdigest() != profile_sha256:
        raise ValueError("实验隔离规则摘要不匹配")
    if profile_text != _EXPERIMENTAL_PROFILE:
        raise ValueError("实验隔离规则不匹配受控模板")
    endpoint = urlsplit(process_config.run.provider_url)
    if endpoint.scheme != "http" or endpoint.hostname != "127.0.0.1" or endpoint.port is None:
        raise ValueError("实验隔离通信端点无效")
    root = Path(__file__).resolve().parent.parent
    audit = root / ".work/upgrade2/u2-03/dependency-audit-001"
    runtime = _experimental_path(Path(process_config.python_executable).parent.parent, audit / "environment")
    _experimental_path(process_config.engine_dir, audit / "source")
    _experimental_path(installed_directory, root / ".work/upgrade2/u2-01/hermes-adapter-env-001/lib/python3.14/site-packages")
    workspace = _experimental_path(process_config.workspace, root / ".work/upgrade2/u2-03/isolated-workspaces", descendant=True)
    if workspace.name != process_config.run.run_id:
        raise ValueError("实验隔离工作目录与运行不匹配")
    executable = Path(process_config.python_executable)
    target = root / ".work/upgrade2/u2-01/python/cpython-3.14.9-macos-x86_64-none/bin/python3.14"
    if executable != runtime / "bin/python" or executable.resolve(strict=True) != _experimental_path(target, target):
        raise ValueError("实验隔离解释器不匹配")
    _experimental_path(process_config.runtime_dir, target.parent)
    _experimental_path(process_config.source_archive, root / ".work/upgrade2/u2-01/hermes.tar.gz")
    workspace_root = _experimental_path(process_config.workspace_root, root / ".work/upgrade2/u2-03/isolated-workspaces", descendant=True)
    if not workspace.is_relative_to(workspace_root) or workspace == workspace_root:
        raise ValueError("实验隔离工作目录与范围不匹配")
    profile = Path(process_config.isolation_profile)
    if profile not in {root / "app/tests/hermes_no_spawn.sb", root / "app/tests/hermes_isolation_adapter_candidate.sb"}:
        raise ValueError("实验隔离配置路径无效")
    _experimental_path(profile, profile)
    parameters = {"PYTHON_BASE": str(executable.resolve(strict=True).parent.parent),
                  "RUNTIME": str(executable.parent.parent.resolve(strict=True)),
                  "ENGINE": str(Path(process_config.engine_dir).resolve(strict=True)),
                  "ADAPTER": str(Path(installed_directory).resolve(strict=True)),
                  "WORK": str(Path(process_config.workspace).resolve(strict=True)),
                  "ENDPOINT": "localhost:" + str(endpoint.port)}
    args = ["/usr/bin/sandbox-exec"]
    for key, value in parameters.items():
        args.extend(["-D", key + "=" + value])
    return [*args, "-p", profile_text, *command]


def require_experimental_root_workspace(sink, authority):
    if authority is not None:
        raise ValueError("实验磁盘容量尚未绑定本人批准预算")
    with sink.store.connect() as db:
        db.execute("BEGIN")
        sink.store._require_lease(db, sink.config.run_id, sink.lease_owner, sink.config.lease_epoch)
        if sink.store.require_active_lineage(db, sink.config.run_id) != sink.config.run_id:
            raise ValueError("子运行共享磁盘容量尚未实现")


class HermesRuntimeTransport:
    def __init__(self, sink, scope, bridge, *, actor_id, space_id, capability, max_tools, provider_gateway=None, context_tools=None, artifact_tools=None, authority=None):
        if type(max_tools) is not int or max_tools <= 0:
            raise ValueError("工具预算无效")
        sink.require_tool_access(actor_id, space_id)
        budget = RunToolBudget(sink.store)
        with sink.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            sink.store._require_lease(db, sink.config.run_id, sink.lease_owner, sink.config.lease_epoch)
            root = sink.store.require_active_lineage(db, sink.config.run_id)
            current = db.execute("SELECT max_tools FROM agent_tool_budgets WHERE root_run_id=?", (root,)).fetchone()
            if current != (max_tools,):
                raise ValueError("运行工具预算未配置或不匹配")
        self.transport = HermesTransport(sink, capability, actor_id=actor_id, space_id=space_id,
                                         scope_service=scope, tool_budget=budget, bridge=bridge, context_tools=context_tools, artifact_tools=artifact_tools, authority=authority)
        if provider_gateway is not None:
            if not isinstance(provider_gateway, ProviderGateway) or not isinstance(provider_gateway.store, RunBoundBudgetStore):
                raise ValueError("模型网关需要运行预算")
            provider_sink = provider_gateway.store.sink
            if provider_sink.store.path.resolve() != sink.store.path.resolve() or provider_sink.config != sink.config or provider_sink.lease_owner != sink.lease_owner or provider_gateway.capability == capability:
                raise ValueError("模型网关与运行通信不匹配")
            if authority is not None:
                provider_gateway.store.bind_authority(authority)
        self.provider_gateway = provider_gateway
        self.authority = authority
        self.closed = False
        self.active = False
        self.started = False

    async def supervise(self, supervisor, *, interval=0.1):
        if not self.active or self.provider_gateway is None or not isinstance(supervisor, EngineProcessSupervisor):
            raise ValueError("运行通信与进程监督尚未装配")
        sink = self.transport.sink
        if supervisor.sink.config != sink.config or supervisor.sink.store.path.resolve() != sink.store.path.resolve() or supervisor.sink.lease_owner != sink.lease_owner or supervisor.process_evidence is None:
            raise ValueError("进程监督与运行通信不匹配")
        return await supervisor.monitor(interval=interval)

    @asynccontextmanager
    async def serve_prepared(self, listener, evidence, ticket, command, *, cwd, bootstrap, max_seconds):
        sink = self.transport.sink
        if not isinstance(evidence, HermesProcessEvidence) or evidence.store.path.resolve() != sink.store.path.resolve() or self.provider_gateway is None:
            raise ValueError("运行通信与进程记录未装配")
        if isinstance(max_seconds, bool) or not isinstance(max_seconds, (int, float)) or not math.isfinite(max_seconds) or max_seconds <= 0:
            raise ValueError("运行时限无效")
        expected = {"endpoint": sink.config.provider_url, "capability": self.transport.capability,
                    "provider_capability": self.provider_gateway.capability, "run_id": sink.config.run_id,
                    "engine_commit": sink.config.engine_commit}
        if bootstrap != expected:
            raise ValueError("运行通信启动信息不匹配")
        run_id, request_key = evidence.prepared_identity(ticket)
        if run_id != sink.config.run_id:
            raise ValueError("进程启动登记不属于当前运行")
        if self.authority is not None:
            self.authority.require()
        async with self.serve(listener):
            evidence.start_prepared(ticket, command, cwd=cwd, bootstrap=bootstrap)
            process = evidence.processes[(run_id, request_key)]
            try:
                supervisor = EngineProcessSupervisor(sink, process, process_group=True, process_evidence=evidence,
                                                     request_key=request_key, max_seconds=max_seconds, authority=self.authority,
                                                     usage_report=self.provider_gateway.store.usage_report)
                if self.authority is not None:
                    self.authority.require()
                yield supervisor
            finally:
                if process.poll() is None:
                    if os.getpgid(process.pid) != process.pid or os.getsid(process.pid) != process.pid:
                        raise ValueError("受管进程组已经失效")
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=10)
                evidence.observe_exit(sink.config.run_id, request_key)

    @asynccontextmanager
    async def serve(self, listener, *, vm_tls=None):
        from hermes_vm_channel import HermesVMServerTLS
        if self.closed or self.started:
            raise ValueError("运行通信服务已经关闭")
        if vm_tls is not None and not isinstance(vm_tls, HermesVMServerTLS):
            raise ValueError("虚拟机通信缺少受验证的 TLS 配置")
        if vm_tls is not None:
            vm_tls.__post_init__()
            sink = self.transport.sink
            access = vm_tls.access
            if access.bindings.store.path.resolve() != sink.store.path.resolve() or (access.run_id, access.owner, access.epoch) != (sink.config.run_id, sink.lease_owner, sink.config.lease_epoch):
                raise ValueError("虚拟机通信与运行租约不匹配")
            if self.authority is not None:
                self.authority.bind_vm_access(access)
        endpoint = urlsplit(self.transport.sink.config.provider_url)
        if isinstance(listener, HermesSharedListener):
            if vm_tls is None or listener.service.port != endpoint.port:
                raise ValueError("共享运行通信地址或身份无效")
            self.started = True
            try:
                async with listener.service.register(self, vm_tls):
                    self.active = True
                    logger.debug("运行通信开始 run=%s epoch=%s monotonic=%.6f", sink.config.run_id, sink.config.lease_epoch, monotonic())
                    yield
            finally:
                failure = sys.exc_info()[1]
                logger.debug("运行通信结束 run=%s epoch=%s monotonic=%.6f error=%s", sink.config.run_id, sink.config.lease_epoch, monotonic(), type(failure).__name__ if failure is not None else "NONE")
                self.active = False
                self.closed = True
                self.transport.capability = None
                if self.provider_gateway is not None:
                    self.provider_gateway.close()
            return
        if not isinstance(listener, socket.socket) or listener.family != socket.AF_INET or listener.type & socket.SOCK_STREAM != socket.SOCK_STREAM or listener.getsockname() != ("127.0.0.1", endpoint.port):
            raise ValueError("运行通信监听地址无效")
        self.started = True
        listener.setblocking(False)
        app = web.Application(client_max_size=4 * 1024 * 1024, middlewares=[vm_tls.require_peer] if vm_tls is not None else [])
        self.transport.install(app)
        if self.provider_gateway is not None:
            app.router.add_post("/chat/completions", self.provider_gateway.completions)
        runner = web.AppRunner(app)
        try:
            await runner.setup()
            await web.SockSite(runner, listener, ssl_context=vm_tls.context if vm_tls is not None else None).start()
            self.active = True
            yield
        finally:
            self.active = False
            self.closed = True
            self.transport.capability = None
            if self.provider_gateway is not None:
                self.provider_gateway.close()
            try:
                await runner.cleanup()
            finally:
                listener.close()


class HermesSharedListener:
    def __init__(self, service):
        self.service = service

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class HermesSharedRuntimeService:
    def __init__(self, port):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("共享运行通信端口无效")
        self.port = port
        self.lock = asyncio.Lock()
        self.entries = {}
        self.runner = None
        self.context = None
        self.peer_sha256 = None

    def listener(self):
        return HermesSharedListener(self)

    def _install_routes(self, app, transport):
        service = self

        class Router:
            def add_get(self, path, handler):
                self.add("GET", path, handler.__name__)

            def add_post(self, path, handler):
                self.add("POST", path, handler.__name__)

            def add(self, method, path, name):
                async def dispatch(request):
                    return await service.dispatch(request, name, provider=False)
                app.router.add_route(method, path, dispatch)

        class Routes:
            router = Router()

        transport.install(Routes())

        async def completions(request):
            return await service.dispatch(request, "completions", provider=True)
        app.router.add_post("/chat/completions", completions)

    async def dispatch(self, request, name, *, provider):
        authorization = request.headers.get("Authorization", "")
        entry = self.entries.get(authorization)
        if entry is None or entry[2] != provider:
            raise web.HTTPUnauthorized(text="运行通信身份不可核查")
        runtime, vm_tls, _ = entry
        if not runtime.active or runtime.closed:
            raise web.HTTPUnauthorized(text="运行通信已经关闭")

        async def invoke(current):
            sink = runtime.transport.sink
            stage = "AUTHORITY"
            try:
                if runtime.authority is not None:
                    runtime.authority.require()
                stage = "REQUEST"
                return await getattr(runtime.provider_gateway if provider else runtime.transport, name)(current)
            finally:
                failure = sys.exc_info()[1]
                logger.debug("运行请求结束 run=%s epoch=%s monotonic=%.6f operation=%s stage=%s error=%s status=%s", sink.config.run_id, sink.config.lease_epoch, monotonic(), name, stage, type(failure).__name__ if failure is not None else "NONE", getattr(failure, "status", None))

        return await vm_tls.require_peer(request, invoke)

    @asynccontextmanager
    async def register(self, runtime, vm_tls):
        from hermes_vm_channel import HermesVMServerTLS
        if not isinstance(runtime, HermesRuntimeTransport) or not isinstance(vm_tls, HermesVMServerTLS) or runtime.provider_gateway is None:
            raise ValueError("共享运行通信配置无效")
        vm_tls.__post_init__()
        keys = ("Bearer " + runtime.transport.capability, "Bearer " + runtime.provider_gateway.capability)
        if keys[0] == keys[1]:
            raise ValueError("运行通信凭据重复")
        async with self.lock:
            if any(key in self.entries for key in keys):
                raise ValueError("运行通信凭据已经登记")
            if self.runner is None:
                app = web.Application(client_max_size=4 * 1024 * 1024)
                self._install_routes(app, runtime.transport)
                runner = web.AppRunner(app)
                listener = None
                started = False
                try:
                    await runner.setup()
                    listener = socket.create_server(("127.0.0.1", self.port), family=socket.AF_INET)
                    listener.setblocking(False)
                    await web.SockSite(runner, listener, ssl_context=vm_tls.context).start()
                    self.runner, self.context, self.peer_sha256 = runner, vm_tls.context, vm_tls.peer_sha256
                    started = True
                finally:
                    if not started:
                        await runner.cleanup()
                        if listener is not None:
                            listener.close()
            elif self.context is not vm_tls.context or self.peer_sha256 != vm_tls.peer_sha256:
                raise ValueError("共享运行通信的虚拟机身份不一致")
            self.entries[keys[0]] = (runtime, vm_tls, False)
            self.entries[keys[1]] = (runtime, vm_tls, True)
            sink = runtime.transport.sink
            logger.debug("共享通信登记 run=%s epoch=%s monotonic=%.6f entries=%s", sink.config.run_id, sink.config.lease_epoch, monotonic(), len(self.entries))
        try:
            yield
        finally:
            async with self.lock:
                for key in keys:
                    if self.entries.get(key, (None,))[0] is not runtime:
                        raise ValueError("共享运行通信登记已经变化")
                    del self.entries[key]
                logger.debug("共享通信撤销 run=%s epoch=%s monotonic=%.6f entries=%s", sink.config.run_id, sink.config.lease_epoch, monotonic(), len(self.entries))
                if not self.entries:
                    runner = self.runner
                    self.runner, self.context, self.peer_sha256 = None, None, None
                    await runner.cleanup()
                    logger.debug("共享监听关闭 monotonic=%.6f", monotonic())


@dataclass(frozen=True)
class GuardedExecutionResult:
    state: str
    engine_exit: int | None
    descendants: str = "NOT_VERIFIED"


class HermesExecutionLifecycle:
    def __init__(self, transport, evidence):
        if not isinstance(transport, HermesRuntimeTransport) or not isinstance(evidence, HermesProcessEvidence):
            raise ValueError("执行服务缺少通信或进程记录")
        if transport.transport.sink.store.path.resolve() != evidence.store.path.resolve() or transport.provider_gateway is None:
            raise ValueError("执行服务的运行环境不一致")
        self.transport = transport
        self.evidence = evidence

    async def run(self, listener, ticket, command, *, cwd, bootstrap, max_seconds, interval=0.1):
        async with self.transport.serve_prepared(listener, self.evidence, ticket, command, cwd=cwd,
                                                 bootstrap=bootstrap, max_seconds=max_seconds) as supervisor:
            return await self.transport.supervise(supervisor, interval=interval)

    async def run_guarded_configured(self, listener, ticket, process_config, *, bootstrap, interval=0.1, experimental_adapter=None, experimental_sandbox=None, experimental_workspace=None):
        from hermes_bridge import EngineProcessConfig
        from hermes_process_manager import HermesProcessManager

        sink = self.transport.transport.sink
        if not isinstance(process_config, EngineProcessConfig) or process_config.run != sink.config:
            raise ValueError("受管引擎进程配置不匹配")
        if experimental_sandbox is not None and (experimental_adapter is None or not self.transport.provider_gateway.offline or not isinstance(experimental_sandbox, dict) or set(experimental_sandbox) != {"profile_text", "profile_sha256"}):
            raise ValueError("实验隔离需要适配来源与离线网关")
        if experimental_sandbox is not None:
            require_experimental_root_workspace(sink, self.transport.authority)
            from hermes_workspace_image import ExperimentalWorkspaceImage
            if not isinstance(experimental_workspace, dict) or set(experimental_workspace) != {"image", "disk_limit_bytes"} or not isinstance(experimental_workspace["image"], ExperimentalWorkspaceImage):
                raise ValueError("实验隔离需要独立磁盘容量与映像")
            experimental_workspace["image"].require_capacity(process_config.run.run_id, process_config.workspace, experimental_workspace["disk_limit_bytes"])
            _experimental_adapter_paths(experimental_adapter)
            experimental_sandbox_command([str(process_config.python_executable)], process_config,
                                         experimental_adapter["installed_directory"], **experimental_sandbox)
        elif experimental_workspace is not None:
            raise ValueError("实验映像需要实验隔离规则")
        else:
            HermesProcessManager.require_bound_isolation()
        entry = Path(__file__).with_name("hermes_engine_entry.py")
        if experimental_adapter is not None:
            if not isinstance(experimental_adapter, dict) or set(experimental_adapter) != {"source_root", "wheel_path", "installed_directory"}:
                raise ValueError("引擎适配来源参数无效")
            entry = verify_experimental_adapter(**experimental_adapter)["entry"]
        process_config.validate()
        resource_options = {}
        if experimental_sandbox is not None:
            resource_options = {"resource_script": Path(experimental_adapter["installed_directory"]) / "hermes_resource_exec.py",
                                "resource_python": process_config.python_executable}
        command = HermesProcessManager(sink, process_config)._resource_command([
            str(entry), str(process_config.engine_dir),
            "--max-rounds", str(process_config.max_rounds), "--max-seconds", str(process_config.max_seconds)], **resource_options)
        if experimental_sandbox is not None:
            command = experimental_sandbox_command(command, process_config, experimental_adapter["installed_directory"], **experimental_sandbox)
        else:
            command = HermesProcessManager(sink, process_config).bind_isolation_command(command)
        limits = {"file_bytes": process_config.max_file_bytes, "open_files": process_config.max_open_files,
                  "cpu_seconds": process_config.max_cpu_seconds}
        return await self.run_guarded(listener, ticket, command, cwd=process_config.workspace, bootstrap=bootstrap,
                                      max_seconds=process_config.max_seconds, interval=interval, limits=limits)

    async def run_guarded(self, listener, ticket, command, *, cwd, bootstrap, max_seconds, interval=0.1, limits=None):
        from hermes_anchor_evidence import HermesAnchorEvidence, reclaim_uncertain_anchor
        from hermes_anchor_supervisor import GuardedEngineSupervisor
        from hermes_process_anchor import AnchorProcessGroup, _resource_limited_command

        sink = self.transport.transport.sink
        gateway = self.transport.provider_gateway
        expected = {"endpoint": sink.config.provider_url, "capability": self.transport.transport.capability,
                    "provider_capability": gateway.capability, "run_id": sink.config.run_id,
                    "engine_commit": sink.config.engine_commit}
        if bootstrap != expected or isinstance(max_seconds, bool) or not isinstance(max_seconds, (int, float)) or not math.isfinite(max_seconds) or max_seconds <= 0:
            raise ValueError("受管引擎启动信息无效")
        if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not math.isfinite(interval) or interval <= 0:
            raise ValueError("进程检查间隔无效")
        _resource_limited_command(command, limits)
        run_id, request_key = self.evidence.prepared_identity(ticket)
        if run_id != sink.config.run_id:
            raise ValueError("进程启动登记不属于当前运行")
        options, encoded = self.evidence._launch_options(run_id, sink.config.lease_epoch, command, cwd, bootstrap)
        anchor_evidence = HermesAnchorEvidence(sink.store)
        authority = self.transport.authority
        if authority is not None:
            authority.require()
        async with self.transport.serve(listener):
            anchor = AnchorProcessGroup.start(command, cwd=options["cwd"], env=options["env"], bootstrap=encoded,
                                              deferred=True, guarded=True, limits=limits)
            bound = False
            try:
                self.evidence.bind_prepared_anchor(ticket, anchor)
                bound = True
                supervisor = GuardedEngineSupervisor(sink, anchor, anchor_evidence, request_key,
                                                     max_seconds=max_seconds, authority=authority,
                                                     usage_report=gateway.store.usage_report)
                if not self.transport.active or supervisor.sink is not sink or supervisor.anchor_evidence.store.path.resolve() != sink.store.path.resolve() or supervisor.anchor_request_key != request_key:
                    raise ValueError("受管进程监督与运行通信不匹配")
                if authority is not None:
                    authority.require()
                anchor_evidence.release(run_id, request_key, sink.lease_owner, sink.config.lease_epoch, anchor)
                state = await supervisor.monitor(interval=interval)
                return GuardedExecutionResult(state, supervisor.engine_exit)
            finally:
                reclaim_uncertain_anchor(anchor)
                if bound:
                    anchor_evidence.mark_uncertain(run_id, request_key, sink.lease_owner, sink.config.lease_epoch,
                                                   anchor, allow_released=True)


def record_vm_usage_if_current(sink, budget_store):
    from datetime import datetime
    from agent_run_store import utc_now
    if not isinstance(budget_store, RunBoundBudgetStore) or budget_store.sink is not sink:
        raise ValueError("虚拟机用量与运行不匹配")
    with sink.store.connect() as db:
        db.execute("BEGIN")
        lease = db.execute("SELECT lease_owner,lease_epoch,lease_expires_at,status FROM agent_runs WHERE run_id=?", (sink.config.run_id,)).fetchone()
    if lease is None or lease[0] != sink.lease_owner or lease[1] != sink.config.lease_epoch or lease[2] is None or datetime.fromisoformat(lease[2]) <= utc_now() or lease[3] in {"FAILED", "CANCELED", "SUCCEEDED", "INTERRUPTED"}:
        return None
    return budget_store.record_usage_snapshot()


def record_vm_exit_recovery(sink, access, usage_saved):
    from hermes_vm_identity import HermesVMRunAccess
    if not isinstance(sink, EngineEventSink) or not isinstance(access, HermesVMRunAccess) or type(usage_saved) is not bool or access.bindings.store.path.resolve() != sink.store.path.resolve() or (access.run_id, access.owner, access.epoch) != (sink.config.run_id, sink.lease_owner, sink.config.lease_epoch):
        raise ValueError("虚拟机取消收尾身份不可核查")
    with sink.store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        run = db.execute("SELECT status,cancel_requested_at FROM agent_runs WHERE run_id=?", (access.run_id,)).fetchone()
        if run is None:
            raise ValueError("虚拟机运行不存在")
        if run[0] in {"FAILED", "CANCELED", "SUCCEEDED", "INTERRUPTED"}:
            return None
        unit = access.require_final_in_transaction(db)
        if run[0] == "RUNNING" and run[1] is None and not usage_saved:
            target = "INTERRUPTED"
        elif run[0] == "CANCEL_REQUESTED" and run[1] is not None:
            target = "RECONCILING"
        elif run[1] is None:
            return None
        elif run[0] == "RECONCILING":
            return "RECONCILING"
        else:
            raise ValueError("虚拟机取消状态不可核查")
        final = db.execute("SELECT lease_epoch,vm_id,boot_id,unit,source FROM hermes_cpu_final_exits WHERE run_id=? AND request_key=?", (access.run_id, access.request_key)).fetchone()
        reservation = db.execute("SELECT lease_owner,lease_epoch,state FROM agent_concurrency_reservations WHERE run_id=? AND request_key=?", (access.run_id, access.request_key)).fetchone()
        if final != (access.epoch, access.vm_id, access.boot_id, unit, "SLICE_CPU_NSEC_V1") or reservation != (access.owner, access.epoch, "RELEASED"):
            raise ValueError("虚拟机取消退出尚未完成结算")
        db.execute("UPDATE agent_runs SET status=?,revision=revision+1 WHERE run_id=?", (target, access.run_id))
        sink.store._record_event(db, access.run_id, "STATUS_CHANGED", {"from": run[0], "to": target}, access.epoch)
        return target


def verified_vm_engine_exit(transport, access):
    from agent_run_result import AgentRunResult, vm_tree_exit_evidence
    from agent_run_business_receipts import RunBusinessReceipts
    from hermes_vm_identity import HermesVMRunAccess
    if not isinstance(transport, HermesRuntimeTransport) or not isinstance(access, HermesVMRunAccess) or transport.authority is None or transport.transport.context_tools is None:
        raise ValueError("虚拟机正常退出缺少运行授权或上下文")
    sink = transport.transport.sink
    if (access.run_id, access.owner, access.epoch) != (sink.config.run_id, sink.lease_owner, sink.config.lease_epoch):
        raise ValueError("虚拟机正常退出运行身份不匹配")
    transport.authority.require()
    context = transport.transport.context_tools
    artifact = transport.transport.artifact_tools
    preparation = artifact.preparation if artifact is not None else None
    brief = None
    if preparation is not None and context.skill.sop_id == "SOP04":
        from agent_artifact_meeting_brief import RuntimeMeetingBriefPreparation
        brief = RuntimeMeetingBriefPreparation(preparation, context.skill)
    with context.guarded_result(gate_check=transport.transport._require_gate) as db:
        transport.authority.require_in_transaction(db)
        rows, verified = vm_tree_exit_evidence(db, sink.config.run_id, sink.config.lease_epoch)
        if not verified or len(rows) != 1 or rows[0][0] != access.request_key:
            raise ValueError("客体进程退出范围尚未核查")
        cpu = db.execute("SELECT c.reserved_ns,b.limit_ns,(SELECT coalesce(sum(f.cpu_ns),0) FROM hermes_cpu_final_exits f JOIN hermes_cpu_reservations q ON q.run_id=f.run_id AND q.request_key=f.request_key WHERE q.root_run_id=c.root_run_id) FROM hermes_cpu_reservations c JOIN hermes_cpu_budgets b ON b.root_run_id=c.root_run_id WHERE c.run_id=? AND c.request_key=? AND c.lease_epoch=?", (sink.config.run_id, access.request_key, sink.config.lease_epoch)).fetchone()
        if cpu is None or any(type(value) is not int or value < 0 for value in cpu):
            raise ValueError("虚拟机最终 CPU 预算不可核查")
        cpu_exceeded = rows[0][17] > cpu[0] or cpu[2] > cpu[1]
        observation = db.execute("SELECT unit_state,result FROM hermes_cpu_exit_observations WHERE run_id=? AND request_key=?", (sink.config.run_id, access.request_key)).fetchone()
        if observation is None or observation[0] not in {"inactive", "failed"}:
            raise ValueError("客体引擎退出结果不可核查")
        run = db.execute("SELECT revision,goal_revision FROM agent_runs WHERE run_id=?", (sink.config.run_id,)).fetchone()
        result = sink.store.result_in_transaction(db, sink.config.run_id, run[1]) if run is not None else None
        starts = db.execute("SELECT payload FROM agent_run_events WHERE run_id=? AND lease_epoch=? AND type='RUN_STARTED' ORDER BY seq", (sink.config.run_id, sink.config.lease_epoch)).fetchall()
        finishes = db.execute("SELECT event_id,payload FROM agent_run_events WHERE run_id=? AND lease_epoch=? AND type='RUN_FINISHED' ORDER BY seq", (sink.config.run_id, sink.config.lease_epoch)).fetchall()
        failure = db.execute("SELECT 1 FROM agent_run_events WHERE run_id=? AND lease_epoch=? AND type='RUN_FAILED' LIMIT 1", (sink.config.run_id, sink.config.lease_epoch)).fetchone()
        if len(starts) > 1 or starts and json.loads(starts[0][0]) != {"engine_commit": sink.config.engine_commit}:
            raise ValueError("客体引擎启动事件不可核查")
        if len(finishes) > 1 or finishes and (json.loads(finishes[0][1]) != {"outcome": "ENGINE_COMPLETED"} or failure is not None):
            raise ValueError("客体引擎结束事件不可核查")
        if failure is not None or cpu_exceeded or not starts or observation != ("inactive", "success") or result is None or not finishes:
            transport.authority.require_in_transaction(db)
            if cpu_exceeded and db.execute("SELECT 1 FROM agent_run_events WHERE run_id=? AND lease_epoch=? AND type='RUN_FAILED' AND json_extract(payload,'$.error_code')='CPU_BUDGET_EXCEEDED'", (sink.config.run_id, sink.config.lease_epoch)).fetchone() is None:
                sink.store._record_event(db, sink.config.run_id, "RUN_FAILED", {"error_code": "CPU_BUDGET_EXCEEDED"}, sink.config.lease_epoch, "vm-cpu-budget-exceeded")
            elif failure is None:
                code = "CPU_BUDGET_EXCEEDED" if cpu_exceeded else "ENGINE_START_UNRECORDED" if not starts else "ENGINE_PROCESS_EXIT" if observation != ("inactive", "success") else "ENGINE_RESULT_MISSING"
                sink.store._record_event(db, sink.config.run_id, "RUN_FAILED", {"error_code": code}, sink.config.lease_epoch, "vm-engine-exit-failed")
            updated = db.execute("UPDATE agent_runs SET status='FAILED',lease_owner=NULL,lease_expires_at=NULL,revision=revision+1 WHERE run_id=? AND status='RUNNING' AND cancel_requested_at IS NULL AND lease_owner=? AND lease_epoch=?", (sink.config.run_id, sink.lease_owner, sink.config.lease_epoch))
            if updated.rowcount != 1:
                raise ValueError("客体引擎失败状态已经变化")
            sink.store._record_event(db, sink.config.run_id, "STATUS_CHANGED", {"from": "RUNNING", "to": "FAILED"}, sink.config.lease_epoch)
            return GuardedExecutionResult("FAILED", None, "VERIFIED_EXITED")
        business = RunBusinessReceipts(sink.store, transport.transport.scope_service) if RunBusinessReceipts.schema_state(db) else None
        results = AgentRunResult(sink.store, transport.transport.scope_service)
        inspection = results.inspect_completion_in_transaction(
            db, transport.authority, sink, run[0], result["event_id"], finishes[0][0],
            "vm-exit:" + finishes[0][0], artifact_preparation=preparation, runtime_meeting_brief=brief, business_receipts=business)
        if "PROCESS_GROUP_EXIT_UNVERIFIED" in inspection["blockers"]:
            raise ValueError("客体进程退出范围尚未核查")
        transport.authority.require_in_transaction(db)
        if inspection["completion_state"] == "PASS" and not inspection["blockers"]:
            results.finalize_success_in_transaction(db, sink, run[0], result["event_id"], finishes[0][0], "vm-exit:" + finishes[0][0])
            return GuardedExecutionResult("SUCCEEDED", None, "VERIFIED_EXITED")
    return GuardedExecutionResult("ENGINE_EXITED", None, "VERIFIED_EXITED")


def verified_vm_waiting_exit(transport, access, usage_saved):
    from agent_run_result import vm_tree_exit_evidence
    from hermes_vm_identity import HermesVMRunAccess
    if not isinstance(transport, HermesRuntimeTransport) or not isinstance(access, HermesVMRunAccess) or transport.authority is None or usage_saved is not True:
        raise ValueError("等待退出缺少运行授权或用量记录")
    sink = transport.transport.sink
    if (access.run_id, access.owner, access.epoch) != (sink.config.run_id, sink.lease_owner, sink.config.lease_epoch):
        raise ValueError("等待退出运行身份不匹配")
    with sink.store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        state = transport.authority.require_waiting_in_transaction(db)
        rows, verified = vm_tree_exit_evidence(db, access.run_id, access.epoch)
        if not verified or len(rows) != 1 or rows[0][0] != access.request_key:
            raise ValueError("等待退出范围尚未核查")
        cpu = db.execute("SELECT c.reserved_ns,b.limit_ns,(SELECT coalesce(sum(f.cpu_ns),0) FROM hermes_cpu_final_exits f JOIN hermes_cpu_reservations q ON q.run_id=f.run_id AND q.request_key=f.request_key WHERE q.root_run_id=c.root_run_id) FROM hermes_cpu_reservations c JOIN hermes_cpu_budgets b ON b.root_run_id=c.root_run_id WHERE c.run_id=? AND c.request_key=? AND c.lease_epoch=?", (access.run_id, access.request_key, access.epoch)).fetchone()
        if cpu is None or any(type(value) is not int or value < 0 for value in cpu) or rows[0][17] > cpu[0] or cpu[2] > cpu[1]:
            raise ValueError("等待退出 CPU 预算不可核查")
        observation = db.execute("SELECT unit_state,result FROM hermes_cpu_exit_observations WHERE run_id=? AND request_key=?", (access.run_id, access.request_key)).fetchone()
        starts = db.execute("SELECT seq,payload FROM agent_run_events WHERE run_id=? AND lease_epoch=? AND type='RUN_STARTED' ORDER BY seq", (access.run_id, access.epoch)).fetchall()
        waiting = db.execute("SELECT seq FROM agent_run_events WHERE run_id=? AND lease_epoch=? AND type='STATUS_CHANGED' AND json_extract(payload,'$.to')=? ORDER BY seq DESC LIMIT 1", (access.run_id, access.epoch, state)).fetchone()
        failed = db.execute("SELECT 1 FROM agent_run_events WHERE run_id=? AND lease_epoch=? AND type IN ('RUN_FAILED','RUN_FINISHED') LIMIT 1", (access.run_id, access.epoch)).fetchone()
        if observation != ("inactive", "success") or len(starts) != 1 or json.loads(starts[0][1]) != {"engine_commit": sink.config.engine_commit} or waiting is None or starts[0][0] >= waiting[0] or failed is not None:
            raise ValueError("等待退出引擎事件不可核查")
        transport.authority.require_waiting_in_transaction(db)
        return GuardedExecutionResult(state, None, "VERIFIED_EXITED")


class HermesVMExecutionLifecycle(HermesExecutionLifecycle):
    def __init__(self, transport, evidence, manager, host, vm_tls, guest_budget, workspace_access):
        from hermes_vm_channel import HermesVMServerTLS
        from hermes_vm_host import HermesVMHostClient
        from hermes_vm_manager import HermesVMManager
        super().__init__(transport, evidence)
        if not isinstance(manager, HermesVMManager) or not isinstance(host, HermesVMHostClient) or not isinstance(vm_tls, HermesVMServerTLS) or host.access != vm_tls.access or workspace_access != host.access:
            raise ValueError("虚拟机生命周期缺少一致的通信绑定")
        manager.require_live(host.access)
        sink = transport.transport.sink
        if host.access.bindings.store.path.resolve() != sink.store.path.resolve() or (host.access.run_id, host.access.owner, host.access.epoch) != (sink.config.run_id, sink.lease_owner, sink.config.lease_epoch):
            raise ValueError("虚拟机生命周期与运行租约不匹配")
        if transport.authority is None or not isinstance(guest_budget, dict):
            raise ValueError("虚拟机生命周期需要产品授权和客体额度")
        self.manager, self.host, self.vm_tls, self.guest_budget = manager, host, vm_tls, dict(guest_budget)
        self.workspace_access = workspace_access

    async def run_vm(self, listener, process_config, *, bootstrap, interval=0.5, technical_check=None):
        import asyncio
        sink = self.transport.transport.sink
        gateway = self.transport.provider_gateway
        expected = {"endpoint": sink.config.provider_url, "capability": self.transport.transport.capability,
                    "provider_capability": gateway.capability, "run_id": sink.config.run_id,
                    "engine_commit": sink.config.engine_commit}
        if technical_check is not None:
            fields = {"query", "path", "content", "hold_seconds"}
            if not gateway.offline or not isinstance(technical_check, dict) or not fields <= set(technical_check) <= fields | {"wait_question", "record_result"} or not isinstance(technical_check["query"], dict) or not isinstance(technical_check["path"], str) or not isinstance(technical_check["content"], str) or type(technical_check["hold_seconds"]) is not int or not 0 <= technical_check["hold_seconds"] <= min(90, process_config.max_seconds) or "wait_question" in technical_check and (not isinstance(technical_check["wait_question"], str) or not technical_check["wait_question"].strip() or len(technical_check["wait_question"]) > 2000) or "record_result" in technical_check and type(technical_check["record_result"]) is not bool:
                raise ValueError("技术检查输入不可核查")
            expected["technical_check"] = technical_check
        budget = self.guest_budget
        fields = {"rounds", "seconds", "memory_bytes", "processes", "cpu_percent", "open_files", "files", "file_bytes", "cpu_seconds"}
        if bootstrap != expected or set(budget) != fields or any(type(value) is not int or value <= 0 for value in budget.values()):
            raise ValueError("虚拟机启动信息或客体额度无效")
        if (budget["rounds"], budget["seconds"], budget["open_files"], budget["files"], budget["file_bytes"], budget["cpu_seconds"]) != (process_config.max_rounds, process_config.max_seconds, process_config.max_open_files, process_config.max_files, process_config.max_file_bytes, process_config.max_cpu_seconds):
            raise ValueError("客体额度与产品运行额度不一致")
        if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not math.isfinite(interval) or interval <= 0:
            raise ValueError("虚拟机检查间隔无效")
        self.transport.authority.require()
        self.manager.require_live(self.host.access)
        self.workspace_access.require_workspace_context()
        from hermes_cpu_budget import HermesCPUBudget
        cpu_budget = HermesCPUBudget(sink.store)
        attempted = False
        workspace_attempted = False
        settled = False
        waiting_exit = False
        stage = "WORKSPACE_PREPARE"
        async with self.transport.serve(listener, vm_tls=self.vm_tls):
            try:
                workspace_attempted = True
                logger.debug("虚拟机工作区准备开始：%s", sink.config.run_id)
                await asyncio.to_thread(self.host.prepare_workspace, budget, bootstrap)
                logger.debug("虚拟机工作区准备完成：%s", sink.config.run_id)
                stage = "AUTHORITY_AFTER_WORKSPACE"
                self.transport.authority.require()
                stage = "WORKSPACE_STATUS"
                await asyncio.to_thread(self.host.workspace_status, budget, bootstrap)
                attempted = True
                stage = "GUEST_START"
                logger.debug("虚拟机运行启动开始：%s", sink.config.run_id)
                await asyncio.to_thread(self.host.start, budget, bootstrap)
                logger.debug("虚拟机运行启动回执已读取：%s", sink.config.run_id)
                deadline = monotonic() + process_config.max_seconds
                sample_number = 0
                while monotonic() < deadline:
                    stage = "MANAGER_LIVE"
                    self.manager.require_live(self.host.access)
                    stage = "GUEST_INSPECT"
                    observed_state, state = await asyncio.to_thread(self.host.monitor_read, self.transport.authority, "inspect")
                    if observed_state != "RUNNING":
                        waiting_exit = True
                        break
                    if state["process_exited"] is None:
                        logger.debug("客体退出 run=%s epoch=%s monotonic=%.6f process_exited=%s", sink.config.run_id, sink.config.lease_epoch, monotonic(), state["process_exited"])
                        raise ValueError("客体进程退出范围尚未核查")
                    if state["process_exited"] is True:
                        break
                    sample_number += 1
                    stage = "CPU_SAMPLE"
                    sample = await asyncio.to_thread(cpu_budget.record_sample, self.host, "sample:" + str(sample_number), authority=self.transport.authority)
                    if sample in {"WAITING_INPUT", "WAITING_CONFIRMATION"}:
                        waiting_exit = True
                        break
                    if sample is None:
                        logger.debug("CPU 采样观察到退出 run=%s epoch=%s monotonic=%.6f state=EXITED_UNVERIFIED", sink.config.run_id, sink.config.lease_epoch, monotonic())
                        break
                    stage = "WAIT"
                    await asyncio.sleep(interval)
                else:
                    stage = "TIME_LIMIT"
                    raise TimeoutError("虚拟机运行时间已经结束")
            finally:
                failure = sys.exc_info()[1]
                logger.debug("运行生命周期收尾 run=%s epoch=%s monotonic=%.6f stage=%s error=%s", sink.config.run_id, sink.config.lease_epoch, monotonic(), stage, type(failure).__name__ if failure is not None else "NONE")
                try:
                    if attempted:
                        await asyncio.to_thread(self.host.stop)
                        await asyncio.to_thread(cpu_budget.record_unknown_exit, self.host)
                        observation = await asyncio.to_thread(cpu_budget.record_unknown_exit_observation, self.host)
                        logger.debug("客体最终观察 run=%s epoch=%s monotonic=%.6f unit_state=%s result=%s cpu_ns=%s", sink.config.run_id, sink.config.lease_epoch, monotonic(), observation["unit_state"], observation["result"], observation["cpu_ns"])
                        await asyncio.to_thread(cpu_budget.settle_final_exit, self.host)
                        await asyncio.to_thread(cpu_budget.cleanup_settled_exit, self.host)
                        settled = True
                finally:
                    try:
                        if workspace_attempted and not attempted:
                            await asyncio.to_thread(self.host.release_workspace)
                            await asyncio.to_thread(cpu_budget.record_unknown_exit, self.host)
                    finally:
                        if attempted:
                            usage_saved = False
                            usage_finished = False
                            try:
                                usage_saved = record_vm_usage_if_current(sink, gateway.store) is not None
                                usage_finished = True
                            finally:
                                failure = sys.exc_info()[1]
                                logger.debug("运行用量收尾 run=%s epoch=%s monotonic=%.6f completed=%s saved=%s error=%s status=%s", sink.config.run_id, sink.config.lease_epoch, monotonic(), usage_finished, usage_saved, type(failure).__name__ if not usage_finished and failure is not None else "NONE", getattr(failure, "status", None) if not usage_finished else None)
                                if settled:
                                    record_vm_exit_recovery(sink, self.host.access, usage_saved)
            if not settled:
                raise ValueError("客体进程退出范围尚未核查")
            if waiting_exit:
                return verified_vm_waiting_exit(self.transport, self.host.access, usage_saved)
            return verified_vm_engine_exit(self.transport, self.host.access)
