import asyncio
import json
import os
from typing import Literal
from uuid import uuid4

from aiohttp import web
from pydantic import BaseModel, ConfigDict, Field

from business import checksum, encode, now, require
from boss_v7_store import NAMESPACE, optional, rows, text
from connection import RecordedProvider

PROVIDERS = {
    "deepseek": {"label": "DeepSeek", "credential": "DEEPSEEK_API_KEY", "base_url": "https://api.deepseek.com"},
    "openai": {"label": "OpenAI GPT", "credential": "OPENAI_API_KEY", "base_url": "https://api.openai.com/v1"},
}
CAPABILITIES = {"TEXT": "文本回答", "TOOL_CALLING": "工具调用", "STREAMING": "流式输出"}
PENDING = {"QUEUED", "RUNNING"}
VALIDATION_FIELDS = ("id", "version", "state", "at", "error", "capabilities", "usage", "cost", "pricing_version")


class ModelValues(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    provider: Literal["deepseek", "openai"]
    api_type: Literal["chat_completions"]
    model_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]*$")
    credential_reference: str
    timeout_seconds: int = Field(ge=1, le=600)
    max_tool_rounds: int = Field(ge=1, le=12)
    pricing_version: Literal["UNVERIFIED"]
    capabilities: list[Literal["TEXT", "TOOL_CALLING", "STREAMING"]] = Field(min_length=1, max_length=3)
    change_note: str = Field(min_length=1, max_length=4000)


def active_runs(db):
    return [row for row in rows(db, "runtime_run") if row["status"] in {"QUEUED", "RUNNING", "WAITING_INPUT"}
            and row["finished_at"] is None]


def checked_values(raw):
    values = ModelValues.model_validate(raw).model_dump()
    require(values["credential_reference"] == PROVIDERS[values["provider"]]["credential"],
            "凭据引用与Provider不一致", web.HTTPBadRequest)
    require(len(set(values["capabilities"])) == len(values["capabilities"]), "验证能力重复", web.HTTPBadRequest)
    values["change_note"] = text(values["change_note"], "变更说明")
    values["capabilities"] = sorted(values["capabilities"])
    return values


class ModelConnections:
    def __init__(self, store, runtime=None):
        self.store, self.runtime = store, runtime
        self.tasks = {}

    def recover(self):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for record in rows(db, "model_connection_validation"):
                if record["state"] in PENDING:
                    record.update(state="INTERRUPTED", at=now(), error="服务重新启动；原验证没有自动重发")
                    self._save_validation(db, record)

    async def close(self):
        tasks = tuple(self.tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for record in rows(db, "model_connection_validation"):
                if record["state"] in PENDING:
                    record.update(state="INTERRUPTED", at=now(), error="服务停止；原验证没有自动重发")
                    self._save_validation(db, record)

    def read(self, db):
        active = optional(db, "model_connection_active", "current")
        current = self.store.get(db, NAMESPACE, "configuration", "current")
        drafts = rows(db, "model_connection_draft")
        revisions = rows(db, "model_connection_revision")
        validations = rows(db, "model_connection_validation")
        identifiers = sorted({row["id"] for row in drafts + revisions} | ({active["id"]} if active else set()))
        connections = []
        for identifier in identifiers:
            draft = next((item for item in drafts if item["id"] == identifier), None)
            enabled = active if active and active["id"] == identifier else None
            history = sorted((item for item in revisions if item["id"] == identifier), key=lambda item: int(item["version"]), reverse=True)
            selected = draft or enabled or history[0]
            connections.append({"id": identifier, "title": PROVIDERS[selected["values"]["provider"]]["label"] + " · " + selected["values"]["model_id"],
                                "draft": draft, "current": enabled, "history": history,
                                "validations": [{key: row[key] for key in VALIDATION_FIELDS}
                                                for row in sorted(validations, key=lambda row: row["at"], reverse=True) if row["object_id"] == identifier]})
        adoption = [{"run_id": row["run_id"], "connection_id": row["model_connection"]["id"],
                     "version": row["model_connection"]["version"], "model_id": row["runtime"]["model_id"],
                     "at": row["started_at"], "state": row["status"]}
                    for row in rows(db, "runtime_run") if row.get("model_connection")]
        return {"connections": connections, "active_connection_id": active["id"] if active else None,
                "configuration_version": current["version"], "runtime_mode": "EXTERNAL_PROVIDER" if active else "SIMULATED_FIRST",
                "active_run_count": len(active_runs(db)), "adoption": sorted(adoption, key=lambda row: row["at"], reverse=True),
                "options": {"providers": [{"id": name, "label": item["label"]} for name, item in PROVIDERS.items()],
                    "api_types": [{"id": "chat_completions", "label": "Chat Completions"}],
                    "credentials": [{"id": item["credential"], "label": item["credential"] + (" · 已配置" if os.environ.get(item["credential"]) else " · 未配置")}
                                    for item in PROVIDERS.values()],
                    "pricing": [{"id": "UNVERIFIED", "label": "尚无已核实价格；费用保持未知"}],
                    "capabilities": [{"id": key, "label": label} for key, label in CAPABILITIES.items()]}}

    def mutate(self, api, db, action, payload):
        identifier = payload.get("object_id")
        draft = optional(db, "model_connection_draft", identifier) if isinstance(identifier, str) else None
        if action == "save":
            api._exact(payload, {"client_request_id", "object_id", "expected_version", "values"})
            require(identifier is None or draft is not None, "模型连接不存在", web.HTTPNotFound)
            require(payload["expected_version"] == (draft["version"] if draft else "0"), "模型草稿版本已变化")
            require(not draft or not draft["validation"] or draft["validation"]["state"] not in PENDING,
                    "当前连接验证尚未结束")
            values = checked_values(payload["values"])
            identifier = identifier or "model-" + str(uuid4())
            if draft:
                self.store.put(db, NAMESPACE, "model_connection_revision", identifier + ":" + draft["version"], draft)
            record = {"id": identifier, "version": str(int(draft["version"]) + 1) if draft else "1", "values": values,
                      "content_sha256": checksum(values), "state": "DRAFT_UNVALIDATED", "created_at": now(), "validation": None}
            self.store.put(db, NAMESPACE, "model_connection_draft", identifier, record)
            return {"object_id": identifier, "version": record["version"], "state": record["state"]}
        fields = {"client_request_id", "object_id", "expected_version", "expected_content_sha256"}
        if action == "validate":
            fields.add("external_request_confirmed")
        if action == "activate":
            fields |= {"confirmation", "expected_active_connection_id", "expected_active_version", "expected_configuration_version"}
        api._exact(payload, fields)
        require(draft is not None and draft["version"] == payload["expected_version"]
                and draft["content_sha256"] == payload["expected_content_sha256"], "模型草稿版本或内容已变化")
        if action == "cancel":
            require(draft["validation"] and draft["validation"]["state"] == "QUEUED", "只能取消尚未执行的验证")
            record = optional(db, "model_connection_validation", draft["validation"]["id"])
            record.update(state="CANCELED", at=now(), error=None)
            self._save_validation(db, record)
            return {"object_id": identifier, "version": draft["version"], "state": "CANCELED"}
        require(self.runtime is not None, "当前Runtime尚未准备", web.HTTPServiceUnavailable)
        if action == "validate":
            require(payload["external_request_confirmed"] is True, "实际外部请求需要明确确认", web.HTTPForbidden)
            require(not draft["validation"] or draft["validation"]["state"] not in PENDING, "当前验证正在执行")
            require(bool(os.environ.get(draft["values"]["credential_reference"])), "服务端凭据尚未配置", web.HTTPBadRequest)
            asyncio.get_running_loop()
            record = {"id": "model-validation-" + str(uuid4()), "object_id": identifier, "version": draft["version"],
                      "state": "QUEUED", "at": now(), "error": None, "capabilities": [], "usage": None, "cost": None,
                      "pricing_version": draft["values"]["pricing_version"], "values": draft["values"],
                      "content_sha256": draft["content_sha256"], "request_id": payload["client_request_id"],
                      "credential_sha256": checksum(os.environ[draft["values"]["credential_reference"]]),
                      "external_request_count": 0, "external_request_confirmed": True}
            self._save_validation(db, record)
            return {"object_id": identifier, "version": draft["version"], "state": "QUEUED", "validation_id": record["id"]}
        require(action == "activate" and payload["confirmation"] is True, "启用模型需要明确确认", web.HTTPForbidden)
        active = optional(db, "model_connection_active", "current")
        current = self.store.get(db, NAMESPACE, "configuration", "current")
        require(payload["expected_active_connection_id"] == (active["id"] if active else None)
                and payload["expected_active_version"] == (active["version"] if active else "0")
                and payload["expected_configuration_version"] == current["version"], "当前启用配置已经变化")
        validation = draft["validation"]
        require(validation and validation["state"] == "PASSED" and set(validation["capabilities"]) == set(CAPABILITIES),
                "启用需要当前版本的文本、工具调用和流式输出验证")
        require(not active_runs(db), "当前存在运行任务，请等待结束后启用模型")
        values = checked_values(draft["values"])
        require(bool(os.environ.get(values["credential_reference"])), "服务端凭据尚未配置", web.HTTPBadRequest)
        validation_record = optional(db, "model_connection_validation", validation["id"])
        require(validation_record is not None and validation_record["content_sha256"] == draft["content_sha256"]
                and validation_record["credential_sha256"] == checksum(os.environ[values["credential_reference"]]),
                "连接内容或服务端凭据已经变化，请重新验证")
        activated = {**draft, "state": "ACTIVE", "activated_at": now()}
        updated = {**current, "version": str(int(current["version"]) + 1), "provider": values["provider"],
                   "api_type": values["api_type"], "model_id": values["model_id"], "timeout": values["timeout_seconds"],
                   "max_output_tokens": self.runtime.snapshot()["max_output_tokens"],
                   "max_tool_rounds": values["max_tool_rounds"], "model_connection": {"id": identifier, "version": draft["version"]},
                   "enabled": True, "activated_at": activated["activated_at"]}
        self.runtime.apply_model(activated, updated)
        self.store.put(db, NAMESPACE, "configuration_revision", current["version"], current)
        self.store.put(db, NAMESPACE, "configuration", "current", updated)
        self.store.put(db, NAMESPACE, "model_connection_active", "current", activated)
        self.store.put(db, NAMESPACE, "model_connection_draft", identifier, activated)
        self.store.put(db, NAMESPACE, "model_connection_revision", identifier + ":" + draft["version"], activated)
        return {"object_id": identifier, "version": draft["version"], "state": "ACTIVE", "configuration_version": updated["version"]}

    def _save_validation(self, db, record):
        self.store.put(db, NAMESPACE, "model_connection_validation", record["id"], record)
        draft = optional(db, "model_connection_draft", record["object_id"])
        require(draft is not None, "验证对象不存在")
        if draft["version"] == record["version"]:
            draft["validation"] = {key: record[key] for key in VALIDATION_FIELDS}
            self.store.put(db, NAMESPACE, "model_connection_draft", draft["id"], draft)
        else:
            revision_id = record["object_id"] + ":" + record["version"]
            revision = optional(db, "model_connection_revision", revision_id)
            require(revision is not None, "验证对象的历史版本不存在")
            revision["validation"] = {key: record[key] for key in VALIDATION_FIELDS}
            self.store.put(db, NAMESPACE, "model_connection_revision", revision_id, revision)
        row = db.execute("SELECT result FROM idempotency WHERE namespace=? AND operation=? AND key=?",
                         (NAMESPACE, "boss.technical.models.validate", record["request_id"])).fetchone()
        if row:
            receipt = json.loads(row[0])
            receipt["result"]["state"] = record["state"]
            db.execute("UPDATE idempotency SET result=? WHERE namespace=? AND operation=? AND key=?",
                       (encode(receipt), NAMESPACE, "boss.technical.models.validate", record["request_id"]))
        db.execute("INSERT INTO audit(namespace,operation,input,output,created_at) VALUES(?,?,?,?,?)",
                   (NAMESPACE, "model_connection.validation_state", encode({"validation_id": record["id"], "object_id": record["object_id"], "version": record["version"]}),
                    encode({"state": record["state"], "external_request_count": record["external_request_count"]}), now()))

    def enqueue(self, receipt):
        result = receipt["result"]
        if receipt["action"] != "validate" or result["state"] != "QUEUED" or result["validation_id"] in self.tasks:
            return
        identifier = result["validation_id"]
        task = asyncio.create_task(self._validate(identifier), name=identifier)
        self.tasks[identifier] = task
        task.add_done_callback(lambda finished: self._finished(identifier, finished))

    def _finished(self, identifier, task):
        self.tasks.pop(identifier)
        if not task.cancelled():
            error = task.exception()
            if error is not None:
                with self.store.connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    record = optional(db, "model_connection_validation", identifier)
                    require(record is not None, "验证记录不存在")
                    status = record.get("http_status")
                    record.update(state="FAILED", at=now(), error="连接验证终止：" + type(error).__name__ + (" · HTTP " + str(status) if status is not None else ""))
                    self._save_validation(db, record)

    def provider(self, values, identifier, observer=None):
        return RecordedProvider({**values, "base_url": PROVIDERS[values["provider"]]["base_url"], "thinking": "disabled"},
                                self.store.path.parent / "model-transport" / (identifier + ".json"),
                                redact_payload=True, transport_observer=observer)

    async def _validate(self, identifier):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            from boss_v7_configuration import check_technical_access
            check_technical_access(db, "models", "WRITE")
            record = optional(db, "model_connection_validation", identifier)
            if record["state"] != "QUEUED":
                return
            record.update(state="RUNNING", at=now())
            self._save_validation(db, record)
        values = record["values"]
        require(record["credential_sha256"] == checksum(os.environ[values["credential_reference"]]), "验证前服务端凭据已经变化")
        observed_usage = {}
        def observe(event):
            if event["type"] == "request":
                record["external_request_count"] += 1
            if event.get("usage") is not None:
                observed_usage[event["model_request_id"]] = event["usage"]
                record["usage"] = encode(list(observed_usage.values()))
            if event["type"] == "response":
                record["http_status"] = event["status"]
            record["at"] = now()
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                self._save_validation(db, record)
            return {}
        provider = self.provider(values, identifier, observe)
        terminal = "INTERRUPTED"
        try:
            async with asyncio.timeout(values["timeout_seconds"]):
                capabilities = set(values["capabilities"])
                messages = [{"role": "user", "content": "请读取连接诊断工具提供的当前服务时间，并用一句中文复述，完整保留server_time原文。" if "TOOL_CALLING" in capabilities else "请用一句中文说明连接诊断请求已经收到。"}]
                if "TOOL_CALLING" in capabilities:
                    definition = {"type": "function", "function": {"name": "boss_connection_probe", "description": "读取当前连接诊断服务的实际时间", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}}
                    response = await provider.chat(messages, tools=[definition], model=values["model_id"], max_tokens=512,
                                                   tool_choice={"type": "function", "function": {"name": "boss_connection_probe"}})
                    require(response.finish_reason != "error" and len(response.tool_calls) == 1, "模型没有完成工具调用")
                    call = response.tool_calls[0]
                    require(call.name == "boss_connection_probe" and call.arguments == {}, "模型调用的工具或参数不符")
                    server_time = now()
                    messages += [{"role": "assistant", "content": response.content or "", "tool_calls": [call.to_openai_tool_call()]},
                                 {"role": "tool", "tool_call_id": call.id, "content": encode({"server_time": server_time, "provider": values["provider"], "model_id": values["model_id"]})}]
                deltas = []
                async def observed_delta(content):
                    if content:
                        deltas.append(len(content))
                if "STREAMING" in capabilities:
                    response = await provider.chat_stream(messages, model=values["model_id"], max_tokens=512, on_content_delta=observed_delta)
                    require(bool(deltas), "模型没有产生流式文本")
                else:
                    response = await provider.chat(messages, model=values["model_id"], max_tokens=512)
                require(response.finish_reason == "stop" and bool(response.content) and not response.tool_calls, "模型没有完成文本回答")
                if "TOOL_CALLING" in capabilities:
                    require(server_time in response.content, "回答没有保留实际工具返回的服务时间")
                record["capabilities"] = sorted(capabilities)
                terminal = "PASSED"
        finally:
            try:
                if provider._client is not None:
                    await provider._client.close()
            finally:
                record.update(state=terminal, at=now(),
                              error=None if terminal == "PASSED" else "连接验证中断；已观察请求保留")
                with self.store.connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    self._save_validation(db, record)
