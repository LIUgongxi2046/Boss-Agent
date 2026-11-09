import hashlib
import sys
from pathlib import Path

from hermes_bridge import EngineEventSink, EngineProcessConfig
from hermes_process_launch import process_launch_options


class IsolationBoundaryUnavailable(RuntimeError):
    code = "ISOLATION_PROOF_UNAVAILABLE"

    def __init__(self, report):
        super().__init__("可信隔离证明不可用，禁止创建 Hermes 进程")
        self.report = report


class HermesProcessManager:
    def __init__(self, sink: EngineEventSink, process_config: EngineProcessConfig):
        if not isinstance(sink, EngineEventSink) or not isinstance(process_config, EngineProcessConfig):
            raise ValueError("缺少运行入口或进程配置")
        if sink.config != process_config.run:
            raise ValueError("进程配置与运行入口不匹配")
        self.sink = sink
        self.process_config = process_config

    def _resource_command(self, engine_arguments, *, resource_script=None, resource_python=None):
        config = self.process_config
        config.validate_resource_limits()
        if not isinstance(engine_arguments, list) or any(not isinstance(value, str) or not value for value in engine_arguments):
            raise ValueError("引擎启动参数无效")
        executable = Path(config.python_executable)
        if not executable.is_absolute() or not executable.is_file():
            raise ValueError("引擎执行文件无效")
        script = Path(__file__).with_name("hermes_resource_exec.py") if resource_script is None else Path(resource_script)
        interpreter = Path(sys.executable) if resource_python is None else Path(resource_python)
        if not script.is_absolute() or not script.is_file() or not interpreter.is_absolute() or not interpreter.is_file():
            raise ValueError("资源限制执行入口无效")
        return [str(interpreter), str(script),
                "--file-bytes", str(config.max_file_bytes), "--open-files", str(config.max_open_files),
                "--cpu-seconds", str(config.max_cpu_seconds), str(executable), *engine_arguments]

    @staticmethod
    def inspect_isolation():
        return {"status": "NOT_VERIFIED", "code": "ISOLATION_PROOF_UNAVAILABLE", "backend": "UNAVAILABLE",
                "launch_allowed": False, "checks": {"filesystem": "NOT_VERIFIED", "network_and_system_services": "NOT_VERIFIED",
                "resource_limits": "NOT_VERIFIED", "descendant_cleanup": "NOT_VERIFIED", "runtime_binding": "NOT_VERIFIED"}}

    @staticmethod
    def require_isolation():
        raise IsolationBoundaryUnavailable(HermesProcessManager.inspect_isolation())

    @staticmethod
    def require_bound_isolation():
        raise IsolationBoundaryUnavailable(HermesProcessManager.inspect_isolation())

    def bind_isolation_command(self, command):
        if not isinstance(command, list) or not command or any(not isinstance(value, str) or not value for value in command):
            raise ValueError("隔离命令无效")
        raise IsolationBoundaryUnavailable(HermesProcessManager.inspect_isolation())

    def start(self, *, actor_id, space_id):
        self.sink.require_tool_access(actor_id, space_id)
        self.process_config.validate()
        self._resource_command([])
        process_launch_options(self.process_config.workspace)
        with self.sink.store.connect() as db:
            db.execute("BEGIN")
            self.sink.store._require_lease(db, self.sink.config.run_id, self.sink.lease_owner, self.sink.config.lease_epoch)
            root = self.sink.store.require_active_lineage(db, self.sink.config.run_id)
            current = db.execute("SELECT actor_id,space_id,status,cancel_requested_at FROM agent_runs WHERE run_id=?", (self.sink.config.run_id,)).fetchone()
            if current is None or current != (actor_id, space_id, "RUNNING", None):
                raise ValueError("运行身份、状态或取消检查未通过")
            migration = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", ("hermes_budget_001",)).fetchone()
            with (Path(__file__).parent / "migrations/hermes_budget_001.sql").open("rb") as source:
                digest = hashlib.file_digest(source, "sha256").hexdigest()
            if migration is None or migration[0] != digest:
                raise ValueError("模型预算迁移尚未完成或摘要不符")
            budget = db.execute("SELECT request_limit FROM hermes_model_budgets WHERE root_run_id=?", (root,)).fetchone()
            if budget is None or budget[0] != self.sink.config.request_limit:
                raise ValueError("运行模型预算未配置或不匹配")
            used = db.execute("SELECT COUNT(*) FROM hermes_model_requests WHERE root_run_id=?", (root,)).fetchone()[0]
            if used >= budget[0]:
                raise ValueError("运行模型请求额度不足")
        self.require_isolation()
