import ast
import configparser
import hashlib
import json
import secrets
import socket
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from filelock import FileLock


FINDER_DIGEST = "0ff5e04898a29ef836859d5e957bf0f9e2942ab953382360558cff55f308e604"
FINDER_NAME = "__editable___hermes_agent_0_0_0_finder"
PTH_NAME = "__editable__.hermes_agent-0.0.0.pth"


class ArtifactWorkspaceOwnership:
    def __init__(self, store, mapping, *, allow_migration=False):
        from agent_artifact_workspace import ArtifactWorkspace
        from agent_run_store import RunStore
        if not isinstance(store, RunStore) or not isinstance(mapping, ArtifactWorkspace):
            raise ValueError("成果目录归属需要运行数据库和目录映射")
        self.store, self.mapping = store, mapping
        script = (Path(__file__).parent / "migrations/upgrade2_artifact_workspace_001.sql").read_text(encoding="utf-8")
        digest = hashlib.sha256(script.encode("utf-8")).hexdigest()
        with FileLock(str(store.path) + ".migration.lock", timeout=10), store.connect() as db:
            row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", ("upgrade2_artifact_workspace_001",)).fetchone()
            if row is None:
                if not allow_migration or db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_artifact_workspaces'").fetchone() is not None:
                    raise ValueError("成果目录归属迁移尚未完成")
                db.executescript("BEGIN IMMEDIATE;\n" + script)
                db.execute("INSERT INTO agent_schema_migrations VALUES (?,?)", ("upgrade2_artifact_workspace_001", digest))
            elif row[0] != digest:
                raise ValueError("成果目录归属迁移摘要不符")

    def create_or_open(self, sink):
        if sink.store.path.resolve() != self.store.path.resolve():
            raise ValueError("成果目录与运行数据库不一致")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.store._require_lease(db, sink.config.run_id, sink.lease_owner, sink.config.lease_epoch)
            self.store.require_active_lineage(db, sink.config.run_id)
            run = db.execute("SELECT status,cancel_requested_at FROM agent_runs WHERE run_id=?", (sink.config.run_id,)).fetchone()
            if run != ("RUNNING", None):
                raise ValueError("成果运行状态不可用")
            root = self.mapping._path(sink.config.run_id).parent
            root_identity = self.mapping._identity(root)
            row = db.execute("SELECT root_path,root_device,root_inode,directory_device,directory_inode FROM agent_artifact_workspaces WHERE run_id=?", (sink.config.run_id,)).fetchone()
            if row is None:
                directory = self.mapping.create(sink.config.run_id)
                identity = self.mapping._identity(directory)
                db.execute("INSERT INTO agent_artifact_workspaces VALUES (?,?,?,?,?,?)", (sink.config.run_id, str(root), *root_identity, *identity))
                return directory
            directory = self.mapping.open(sink.config.run_id)
            if row != (str(root), *root_identity, *self.mapping._identity(directory)):
                raise ValueError("成果运行目录身份已经变化")
            return directory


@dataclass(frozen=True)
class HermesDeploymentConfig:
    engine_dir: Path
    source_archive: Path
    runtime_dir: Path
    python_executable: Path
    workspace_root: Path
    isolation_profile: Path
    provider_port: int
    provider_key: str | None = field(repr=False)
    offline: bool
    vm_manager: object | None = field(default=None, repr=False)
    artifact_manifest: Path | None = None
    guest_install_evidence: Path | None = None
    isolation_evidence: Path | None = None
    deployment_authorization: Path | None = None


def require_application_deployment(deployment, *, product_mode, run_port):
    if deployment is None:
        return None
    if not isinstance(deployment, HermesDeploymentConfig) or not product_mode or run_port is None:
        raise ValueError("运行部署配置需要产品模式和运行接口")
    if deployment.offline:
        if deployment.provider_key is not None:
            raise ValueError("离线运行网关不能携带模型凭据")
    else:
        if not isinstance(deployment.provider_key, str) or not deployment.provider_key.strip():
            raise ValueError("在线运行需要模型凭据")
        if deployment.deployment_authorization is None:
            raise ValueError("在线运行需要正式部署授权")
    return deployment


@dataclass(frozen=True)
class HermesExecutionAssembly:
    lifecycle: object
    listener: socket.socket
    bootstrap: dict
    request_key: str
    request_digest: str


class HermesExecutionFactory:
    def __init__(self, services, deployment, *, artifact_workspace=None):
        from hermes_product import HermesProductServices
        from hermes_vm_manager import HermesVMManager
        if not isinstance(services, HermesProductServices) or not isinstance(deployment, HermesDeploymentConfig):
            raise ValueError("执行工厂需要产品服务及可信部署配置")
        if artifact_workspace is not None and artifact_workspace is not services.artifact_workspace:
            raise ValueError("成果工作区与产品服务不一致")
        paths = (deployment.engine_dir, deployment.source_archive, deployment.runtime_dir, deployment.python_executable,
                 deployment.workspace_root, deployment.isolation_profile)
        if any(not isinstance(path, Path) or not path.is_absolute() for path in paths):
            raise ValueError("部署路径必须使用绝对路径")
        if type(deployment.provider_port) is not int or not 1 <= deployment.provider_port <= 65535 or type(deployment.offline) is not bool:
            raise ValueError("部署网关配置无效")
        if not deployment.offline and (not isinstance(deployment.provider_key, str) or not deployment.provider_key):
            raise ValueError("部署网关凭据不可用")
        if deployment.vm_manager is not None and not isinstance(deployment.vm_manager, HermesVMManager):
            raise ValueError("部署虚拟机管理器不可核查")
        if deployment.vm_manager is not None and deployment.vm_manager.runtime_port != deployment.provider_port:
            raise ValueError("虚拟机运行端口与产品网关不匹配")
        self.services, self.deployment = services, deployment
        from hermes_runtime_transport import HermesSharedRuntimeService
        self.shared_runtime = HermesSharedRuntimeService(deployment.provider_port) if deployment.vm_manager is not None else None

    def readiness_blockers(self):
        cached = getattr(self, "_readiness_cache", None)
        if cached is not None:
            return list(cached)
        from hermes_deployment_manifest import verify_deployment_authorization, verify_deployment_manifest
        blockers = verify_deployment_manifest(self.deployment.artifact_manifest, self.deployment)
        blockers.extend(verify_deployment_authorization(self.deployment.deployment_authorization, self.deployment.artifact_manifest, self.deployment))
        self._readiness_cache = tuple(blockers)
        return list(blockers)

    def prepare(self, request, run_id, next_epoch):
        from agent_run_dispatcher import AgentRunDispatcher
        from hermes_bridge import EngineProcessConfig, EngineRunConfig
        if str(UUID(run_id)) != run_id:
            raise ValueError("运行编号无效")
        self.services.recovery.channel.require_run_api_role(request)
        with self.services.store.connect() as db:
            db.execute("BEGIN")
            _, budget = AgentRunDispatcher(self.services).approved_budget_in_transaction(db, run_id)
        config = self.deployment
        from hermes_cpu_budget import vm_cpu_allocation_seconds
        cpu_seconds = vm_cpu_allocation_seconds(budget) if config.vm_manager is not None else budget["cpu_seconds"]
        run = EngineRunConfig(run_id, next_epoch, "903230b1e23e0c496b28e5d2e8c4f2639cd506b6",
                              "http://127.0.0.1:" + str(config.provider_port), budget["model_requests"])
        return EngineProcessConfig(run, config.engine_dir, config.source_archive, config.runtime_dir,
            config.python_executable, config.workspace_root, config.workspace_root / run_id, config.isolation_profile,
            budget["rounds"], budget["tools"], budget["seconds"], budget["concurrency"], budget["context_tokens"],
            budget["files"], budget["file_bytes"], budget["open_files"], cpu_seconds)

    def artifact_preparation(self, sink, budget):
        from agent_artifacts import ArtifactPreparation
        mapping = self.services.artifact_workspace
        if mapping is None:
            return None
        with sink.store.connect() as db:
            db.execute("BEGIN")
            sink.store._require_lease(db, sink.config.run_id, sink.lease_owner, sink.config.lease_epoch)
            root = sink.store.require_active_lineage(db, sink.config.run_id)
            row = db.execute("SELECT max_files,max_bytes FROM agent_file_budgets WHERE root_run_id=?", (root,)).fetchone()
            if row != (budget["files"], budget["file_bytes"]):
                raise ValueError("运行文件预算尚未配置或已经变化")
        ArtifactWorkspaceOwnership(sink.store, mapping).create_or_open(sink)
        return ArtifactPreparation.for_run_workspace(self.services.scope.store, mapping, run_gate=sink,
            scope_service=self.services.scope, max_files=budget["files"], max_bytes=budget["file_bytes"])

    def assemble(self, request, sink, budget, plan_digest):
        from business import checksum
        from hermes_budget_gateway import ProviderGateway, RunBoundBudgetStore
        from hermes_context_tools import HermesContextTools
        from hermes_memory_adapter import HermesMemoryAdapter
        from hermes_process_evidence import HermesProcessEvidence
        from hermes_run_authority import HermesRunAuthority
        from hermes_runtime_transport import HermesExecutionLifecycle, HermesRuntimeTransport, HermesVMExecutionLifecycle
        from hermes_skill_adapter import HermesSkillAdapter
        services = self.services
        authority = HermesRunAuthority(services, request, sink, plan_digest, budget, execution_factory=self)
        authority.require()
        selection = services.broker.method_selection
        skills = services.recovery.channel.skills
        if selection is None or skills is None:
            raise ValueError("运行方法服务尚未准备")
        method = selection.require_current(sink)
        if method["sop_id"] == "SOP03":
            from hermes_bi_authority import HermesBIQueryAuthority
            HermesBIQueryAuthority(services.scope).bind_epoch(authority)
        memory = HermesMemoryAdapter(services.scope.store, services.scope, run_gate=sink)
        skill = HermesSkillAdapter(services.scope.store, services.scope, skills.catalog, skills.drafts,
                                   run_gate=sink, sop_id=method["sop_id"])
        context = HermesContextTools.assemble(memory, skill)
        binding = services.recovery.authorize_start(request, sink)
        capability, provider_capability = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        provider = ProviderGateway(RunBoundBudgetStore(sink), provider_capability,
                                   self.deployment.provider_key, offline=self.deployment.offline)
        artifact_tools = None
        preparation = self.artifact_preparation(sink, budget)
        if preparation is not None:
            from hermes_artifact_transport import HermesArtifactTransport
            artifact_tools = HermesArtifactTransport(preparation, request, services.recovery.channel)
            artifact_tools.authorize()
        transport = HermesRuntimeTransport(sink, services.scope, services.bridge, actor_id=binding["actor_id"],
            space_id=binding["space_id"], capability=capability, max_tools=budget["tools"],
            provider_gateway=provider, context_tools=context, artifact_tools=artifact_tools, authority=authority)
        evidence = HermesProcessEvidence(services.store)
        request_key = "dispatch:" + sink.config.run_id + ":" + str(sink.config.lease_epoch)
        if self.deployment.vm_manager is None:
            lifecycle = HermesExecutionLifecycle(transport, evidence)
        else:
            host, vm_tls, guest_budget = self.deployment.vm_manager.prepare(sink, request_key,
                self.deployment.workspace_root / sink.config.run_id, budget)
            lifecycle = HermesVMExecutionLifecycle(transport, evidence, self.deployment.vm_manager, host, vm_tls, guest_budget, host.access)
        bootstrap = {"endpoint": sink.config.provider_url, "capability": capability,
                     "provider_capability": provider_capability, "run_id": sink.config.run_id,
                     "engine_commit": sink.config.engine_commit}
        request_digest = checksum({"run_id": sink.config.run_id, "lease_epoch": sink.config.lease_epoch,
                                   "plan_digest": plan_digest, "budget": budget})
        listener = self.shared_runtime.listener() if self.shared_runtime is not None else socket.create_server(("127.0.0.1", self.deployment.provider_port), family=socket.AF_INET)
        return HermesExecutionAssembly(lifecycle, listener, bootstrap, request_key, request_digest)


def require_editable_runtime_binding(python_executable, engine_dir):
    executable = Path(python_executable)
    engine = Path(engine_dir).resolve(strict=True)
    site = executable.parent.parent / "lib/python3.14/site-packages"
    if not executable.is_absolute() or not site.is_dir() or site.is_symlink():
        raise ValueError("Hermes 独立依赖目录不可核查")
    config = configparser.ConfigParser(interpolation=None)
    config.read_string("[venv]\n" + (executable.parent.parent / "pyvenv.cfg").read_text(encoding="utf-8"))
    if config.getboolean("venv", "include-system-site-packages") or config.get("venv", "implementation") != "CPython" or not config.get("venv", "version_info").startswith("3.14."):
        raise ValueError("Hermes Python 环境配置不可核查")
    records = list(site.glob("hermes_agent-*.dist-info"))
    if len(records) != 1 or records[0].name != "hermes_agent-0.0.0.dist-info" or records[0].is_symlink():
        raise ValueError("Hermes 安装记录不可核查")
    metadata = json.loads((records[0] / "direct_url.json").read_text(encoding="utf-8"))
    if metadata != {"url": engine.as_uri(), "dir_info": {"editable": True}}:
        raise ValueError("Hermes 安装来源与核查源码目录不一致")
    pth = site / PTH_NAME
    if list(site.glob("*.pth")) != [pth] or pth.is_symlink() or pth.read_text(encoding="utf-8") != "import " + FINDER_NAME + "; " + FINDER_NAME + ".install()":
        raise ValueError("Hermes 启动路径配置不可核查")
    if any(site.glob("sitecustomize.*")) or any(site.glob("usercustomize.*")) or any((site / "__pycache__").glob(FINDER_NAME + ".*.pyc")):
        raise ValueError("Hermes 启动路径包含未经核查的代码")
    finder = site / (FINDER_NAME + ".py")
    if finder.is_symlink() or not finder.is_file():
        raise ValueError("Hermes 源码查找器不可核查")
    tree = ast.parse(finder.read_text(encoding="utf-8"))
    mappings = {}
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id in {"MAPPING", "NAMESPACES"}:
            if node.target.id in mappings:
                raise ValueError("Hermes 源码查找器配置重复")
            mappings[node.target.id] = ast.literal_eval(node.value)
            node.value = ast.Constant(value=None)
    if set(mappings) != {"MAPPING", "NAMESPACES"} or hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest() != FINDER_DIGEST:
        raise ValueError("Hermes 源码查找器内容不可核查")
    paths = mappings["MAPPING"]
    namespaces = mappings["NAMESPACES"]
    if not isinstance(paths, dict) or not isinstance(namespaces, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in paths.items()) or any(not isinstance(k, str) or not isinstance(v, list) or any(not isinstance(item, str) for item in v) for k, v in namespaces.items()):
        raise ValueError("Hermes 源码查找器路径无效")
    for path in [*paths.values(), *(item for values in namespaces.values() for item in values)]:
        if not Path(path).is_absolute() or not Path(path).resolve().is_relative_to(engine):
            raise ValueError("Hermes 源码查找器指向未经核查的目录")
