import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

from aiohttp import web
from nanobot.config.loader import load_config, save_config

from business import checksum, encode, now, require
from boss_execution_scope import NAMESPACE, validate_namespace
from boss_v7_datasets import CATALOG, DatasetWorkspace
from boss_v7_store import optional, rows

TRANSITION_KIND = "execution_transition"
PENDING = {"REQUESTED", "PENDING_RUNTIME"}
TECHNICAL_KINDS = frozenset({"configuration", "configuration_revision", "configuration_draft",
    "model_connection_active", "model_connection_draft", "model_connection_revision", "model_connection_validation",
    "prompt_active", "prompt_active_revision", "prompt_draft", "prompt_revision"})


def restart_execution(namespace, entrypoint, *arguments):
    selected = validate_namespace(namespace)
    path = Path(entrypoint).resolve(strict=True)
    require(path.is_file(), "重启入口必须为实际文件")
    os.environ["BOSS_EXECUTION_NAMESPACE"] = selected
    os.execv(sys.executable, [sys.executable, str(path), *arguments])


def pending_transition(db, namespace):
    records = [record for record in rows(db, TRANSITION_KIND, CATALOG)
               if record["state"] in PENDING and namespace in {record["previous_namespace"], record["namespace"]}]
    require(len(records) <= 1, "执行空间存在多个未完成切换")
    return records[0] if records else None


def transition_status(db, request_id):
    record = optional(db, TRANSITION_KIND, request_id, CATALOG)
    if record is None:
        return None
    return {key: record[key] for key in ("request_id", "action", "state", "namespace", "previous_namespace",
        "dataset_id", "dataset_version", "requested_at", "activated_at", "runtime_adopted_at", "error")}


def record_interrupted(store):
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        record = pending_transition(db, NAMESPACE)
        if record is not None:
            record.update(state="INTERRUPTED" if record["previous_namespace"] == NAMESPACE else "RUNTIME_START_FAILED",
                          error="服务未完成此次切换，请查询原请求并核查服务记录")
            store.put(db, CATALOG, TRANSITION_KIND, record["request_id"], record)


class ExecutionTransition:
    def __init__(self, store, runtime, work_directory, stop_event):
        self.store, self.runtime = store, runtime
        self.work = Path(work_directory).resolve()
        self.stop_event = stop_event
        self.runtime_stopped = False
        self.available = False
        require(runtime.store.path.resolve() == store.path.resolve(), "切换服务必须使用当前运行资料")

    def request(self, db, action, payload):
        require(self.available and not self.runtime_stopped, "执行空间切换服务尚未就绪", web.HTTPServiceUnavailable)
        require(set(payload) == {"client_request_id", "dataset_id", "expected_dataset_version", "expected_namespace",
                                "impact_version", "confirmed"}, "执行空间切换字段无效", web.HTTPBadRequest)
        require(payload["confirmed"] is True, "切换执行空间需要明确确认", web.HTTPBadRequest)
        require(payload["expected_namespace"] == NAMESPACE, "当前执行空间已经变化")
        require(pending_transition(db, NAMESPACE) is None, "当前执行空间已有切换请求")
        workspace = DatasetWorkspace(self.store, self.runtime)
        current_impact = workspace.impact(db)
        saved_impact = optional(db, "dataset_reset_impact", "current")
        require(saved_impact is not None and saved_impact["version"] == payload["impact_version"] == current_impact["version"],
                "资料或会话已经变化，需要重新核查影响")
        definition = workspace.definition(db, payload["dataset_id"])
        require(definition["version"] == payload["expected_dataset_version"], "数据集版本已经变化")
        workspace.validate(db, definition)
        initial = self.store.get(db, NAMESPACE, "initial", "snapshot")
        if action == "reset":
            require(initial["dataset_id"] == definition["id"] and initial["dataset_version"] == definition["version"],
                    "重置只能采用当前已载入的数据集")
        target = "execution-" + str(uuid4())
        record = {"request_id": payload["client_request_id"], "action": action, "state": "REQUESTED",
            "namespace": target, "previous_namespace": NAMESPACE, "dataset_id": definition["id"],
            "dataset_version": definition["version"], "facts_sha256": definition["facts_sha256"],
            "impact_version": current_impact["version"], "requested_at": now(), "activated_at": None,
            "request_pid": os.getpid(),
            "runtime_adopted_at": None, "error": None, "native_config_sha256": self.runtime.snapshot()["config_sha256"],
            "previous_native_workspace": str(self.runtime.loop.sessions.workspace),
            "previous_media_directory": str(self.runtime.conversation_attachments.media_root) if self.runtime.conversation_attachments else None,
            "previous_sessions_directory": str(self.runtime.loop.sessions.sessions_dir)}
        self.checked_native_configuration(record)
        self.store.put(db, CATALOG, TRANSITION_KIND, record["request_id"], record)
        return transition_status(db, record["request_id"])

    def enqueue(self, receipt):
        with self.store.connect() as db:
            record = optional(db, TRANSITION_KIND, receipt["request_id"], CATALOG)
        if record is not None and record["state"] == "REQUESTED" and record["previous_namespace"] == NAMESPACE:
            self.available = False
            asyncio.get_running_loop().call_soon(self.stop_event.set)

    def checked_native_configuration(self, record):
        root = self.work / "spaces" / validate_namespace(record["namespace"])
        require(not (self.work / "spaces").is_symlink() and not root.exists(), "目标原生目录已经存在或不符合要求")
        source = self.runtime.config.path
        require(hashlib.sha256(source.read_bytes()).hexdigest() == record["native_config_sha256"], "原生配置已经变化")
        config = load_config(source)
        for provider in config.providers.model_dump().values():
            if isinstance(provider, dict):
                credential = provider.get("api_key")
                require(not credential or credential.startswith("${") and credential.endswith("}"),
                        "原生凭据需要采用服务端环境变量引用，不能复制凭据正文")
        config.agents.defaults.workspace = str(root / "workspace")
        return root, config

    def prepare_native_configuration(self, record):
        root, config = self.checked_native_configuration(record)
        root.mkdir(parents=True, mode=0o700)
        destination = root / "config.json"
        save_config(config, destination)
        destination.chmod(0o600)
        declaration = root / "runtime-scope.json"
        declaration.write_text(encode({"schema_version": 1, "configuration_path": str(destination)}))
        declaration.chmod(0o600)
        return {"configuration_path": str(destination), "configuration_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
                "workspace": str(root / "workspace"), "sessions_root": str(root / "sessions")}

    def finish_stopped_runtime(self):
        require(self.runtime_stopped, "原生运行尚未停止，不能提交空间切换")
        with self.store.connect() as db:
            record = pending_transition(db, NAMESPACE)
        if record is None:
            return None
        require(record["state"] == "REQUESTED" and record["previous_namespace"] == NAMESPACE, "当前进程不能提交此切换")
        native = self.prepare_native_configuration(record)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            require(pending_transition(db, NAMESPACE) == record, "切换请求已经变化")
            workspace = DatasetWorkspace(self.store, self.runtime)
            manifest = workspace.stage_execution(db, record["dataset_id"], record["dataset_version"], record["namespace"], NAMESPACE)
            require(manifest["facts_sha256"] == record["facts_sha256"], "切换资料与确认时内容不一致")
            retained = []
            for kind, identifier, body in db.execute("SELECT kind,id,body FROM objects WHERE namespace=? ORDER BY kind,id", (NAMESPACE,)).fetchall():
                value = json.loads(body)
                if kind in TECHNICAL_KINDS or kind in {"technical_active", "technical_draft", "technical_revision"} and value["domain"] in {"access", "tools"}:
                    self.store.put(db, record["namespace"], kind, identifier, value)
                    retained.append({"kind": kind, "id": identifier, "sha256": checksum(value)})
            schedule = self.store.get(db, record["namespace"], "schedule", "current")
            schedule["enabled"] = False
            self.store.put(db, record["namespace"], "schedule", "current", schedule)
            prepared = [(kind, identifier, json.loads(body)) for kind, identifier, body in db.execute(
                "SELECT kind,id,body FROM objects WHERE namespace=? AND kind<>'execution_space' ORDER BY kind,id", (record["namespace"],))]
            manifest.update(prepared_content_sha256=checksum(prepared), native=native, retained_technical=retained,
                            transition_request_id=record["request_id"])
            self.store.put(db, record["namespace"], "execution_space", "current", manifest)
            archive = {"namespace": NAMESPACE, "dataset_id": self.store.get(db, NAMESPACE, "initial", "snapshot")["dataset_id"],
                       "state": "READ_ONLY", "archived_at": now(), "replaced_by": record["namespace"],
                       "native_workspace": record["previous_native_workspace"], "sessions_directory": record["previous_sessions_directory"],
                       "media_directory": record["previous_media_directory"],
                       "sessions": [{key: item[key] for key in ("key", "created_at", "updated_at")}
                                    for item in self.runtime.loop.sessions.list_sessions()]}
            self.store.put(db, CATALOG, "execution_archive", NAMESPACE, archive)
            adopted = workspace.commit_execution(db, record["namespace"], NAMESPACE, record["facts_sha256"])
            record.update(state="PENDING_RUNTIME", activated_at=adopted["activated_at"], native=native)
            self.store.put(db, CATALOG, TRANSITION_KIND, record["request_id"], record)
        return record["namespace"]

    def mark_adopted(self):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            record = pending_transition(db, NAMESPACE)
            if record is not None and record["state"] == "REQUESTED" and record["previous_namespace"] == NAMESPACE:
                record.update(state="INTERRUPTED", error="服务重新启动，原切换请求没有自动重发")
                self.store.put(db, CATALOG, TRANSITION_KIND, record["request_id"], record)
                record = None
            manifest = optional(db, "execution_space", "current")
            if record is None and manifest is not None and manifest.get("transition_request_id"):
                record = optional(db, TRANSITION_KIND, manifest["transition_request_id"], CATALOG)
                if record is not None and record["state"] == "ADOPTED":
                    record = None
            if record is None:
                self.available = True
                return
            require(record["state"] in {"PENDING_RUNTIME", "RUNTIME_START_FAILED"} and record["namespace"] == NAMESPACE,
                    "切换请求尚未完成服务停止")
            manifest = self.store.get(db, NAMESPACE, "execution_space", "current")
            native = manifest["native"]
            require(self.runtime.config.path.resolve() == Path(native["configuration_path"]).resolve()
                    and self.runtime.loop.sessions.workspace.resolve() == Path(native["workspace"]).resolve()
                    and self.runtime.loop.sessions.sessions_dir.is_relative_to(Path(native["sessions_root"])),
                    "原生运行没有采用目标执行空间")
            require(self.runtime.snapshot()["config_sha256"] == native["configuration_sha256"], "原生运行没有采用准备配置")
            adopted_at = now()
            record.update(state="ADOPTED", runtime_adopted_at=adopted_at, error=None)
            manifest.update(state="ACTIVE", runtime_adopted_at=adopted_at, runtime_pid=os.getpid())
            self.store.put(db, NAMESPACE, "execution_space", "current", manifest)
            self.store.put(db, CATALOG, TRANSITION_KIND, record["request_id"], record)
        self.available = True
