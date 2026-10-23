import hashlib
import inspect
import json
import os
from pathlib import Path

from aiohttp import web
from nanobot.config.loader import load_config, resolve_config_env_vars
from nanobot.providers.factory import ProviderSnapshot
from nanobot.webui.settings_services import WebUISettingsConfig
from pydantic import BaseModel, ConfigDict, Field

from business import checksum, now, require
from boss_prompt_config import obj
from boss_runtime_records import ATTRIBUTE, RuntimeBinding


NS = "ui-check"
ACTIONS = {"boss.runtime.save", "boss.runtime.validate", "boss.runtime.activate", "boss.runtime.deactivate"}


class RuntimeValues(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    max_tool_rounds: int = Field(ge=1, le=12)
    max_output_tokens: int = Field(ge=128, le=8192)
    tool_scope: list[str] = Field(min_length=1, max_length=9)


class ProductRuntime:
    def __init__(self, store, config_path, loop, registry, available_tools, provider):
        self.store, self.loop, self.registry, self.provider = store, loop, registry, provider
        self.config = WebUISettingsConfig(config_path)
        self.available = {tool.name: tool for tool in available_tools}
        self.skill_readiness = None
        self.skill_pending = None
        require(len(self.available) == len(available_tools), "工具目录包含重复标识")
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for item in db.execute("SELECT id,body FROM objects WHERE namespace=? AND kind='runtime_run'", (NS,)).fetchall():
                row = json.loads(item[1])
                if row["status"] in {"QUEUED", "RUNNING", "WAITING_INPUT"} and row["finished_at"] is None:
                    row.update(status="FAILED", stop_reason="service_restarted", finished_at=now(),
                               model_completion_observed=False)
                    if row["model_requests"]:
                        row["usage_coverage"] = "PARTIAL_OBSERVED_REQUESTS"
                    store.put(db, NS, "runtime_run", item[0], row)
            current = store.get(db, NS, "configuration", "current")
        self.config.run_serialized(lambda path: self._apply(self._native(), current["tool_scope"]))

    def _native(self):
        source_sha = self._native_sha()
        config = resolve_config_env_vars(load_config(self.config.path), config_path=self.config.path)
        preset = config.resolve_preset()
        require(config.get_provider_name(preset.model, preset=preset) == "deepseek"
                and preset.model == "deepseek-flash", "模型配置超出当前获准服务", web.HTTPForbidden)
        require(config.providers.deepseek.api_base == "https://api.deepseek.com"
                and config.providers.deepseek.api_key == os.environ["DEEPSEEK_API_KEY"],
                "模型连接与当前获准配置不一致", web.HTTPForbidden)
        require(config.agents.defaults.dream.enabled is False, "当前产品不允许后台模型任务", web.HTTPForbidden)
        require(source_sha == self._native_sha(), "读取期间原生配置发生变化")
        return config

    def _native_sha(self):
        return hashlib.sha256(self.config.path.read_bytes()).hexdigest()

    def _scope(self, scope):
        require(isinstance(scope, list) and scope and len(set(scope)) == len(scope)
                and all(isinstance(name, str) and name in self.available for name in scope),
                "工具范围包含未获准标识", web.HTTPBadRequest)
        return sorted(scope)

    def _catalog_sha(self):
        records = []
        for name, tool in sorted(self.available.items()):
            source = inspect.getsourcefile(type(tool))
            require(source is not None, "工具实现缺少可核查来源")
            records.append({"name": name, "schema": tool.to_schema(),
                            "implementation_sha256": hashlib.sha256(Path(source).read_bytes()).hexdigest()})
        return checksum(records)

    def _apply(self, config, scope):
        scope = self._scope(scope)
        preset = config.resolve_preset()
        generation = preset.to_generation_settings()
        native_sha = self._native_sha()
        self.provider.generation = generation
        self.loop.runtime_resolver.adopt_snapshot(ProviderSnapshot(
            provider=self.provider, model=preset.model, context_window_tokens=preset.context_window_tokens,
            signature=("boss-product", native_sha), generation=generation,
        ))
        self.loop.max_iterations = config.agents.defaults.max_tool_iterations
        for name in list(self.registry.tool_names):
            self.registry.unregister(name)
        for name in scope:
            self.registry.register(self.available[name])
        self.effective = {
            "provider": "deepseek", "model_id": preset.model, "api_type": "chat_completions",
            "max_tool_rounds": self.loop.max_iterations, "max_output_tokens": generation.max_tokens,
            "timeout": 120, "config_sha256": native_sha,
        }
        self.native_configuration = config.model_dump(mode="json")

    def snapshot(self):
        require(self._native_sha() == self.effective["config_sha256"],
                "已保存配置尚未启用到当前Runtime")
        return dict(self.effective)

    def native_refresh_requested(self):
        # 原生配置保存后，由本人技术维护操作完成当前版本校验及启用。
        return self.loop.llm_runtime()

    async def context(self, request):
        existing = request.attributes.get(ATTRIBUTE)
        if existing is not None:
            require(isinstance(existing, RuntimeBinding) and existing.recorder.store is self.store
                    and existing.recorder.namespace == NS and existing.session_id == request.session_key,
                    "进行中请求的运行归属不一致")
            return None
        if self.skill_readiness is not None:
            self.skill_readiness()
        effective = self.snapshot()
        with self.store.connect() as db:
            db.execute("BEGIN")
            self.store.active(db, NS)
            current = self.store.get(db, NS, "configuration", "current")
            require(current["enabled"] is True, "当前模型配置已停用")
            require(all(current[key] == effective[key] for key in
                        ("provider", "model_id", "api_type", "max_tool_rounds", "timeout")),
                    "当前配置尚未被Runtime采用")
            require(set(current["tool_scope"]) == set(self.registry.tool_names), "当前工具与启用范围不一致")
            require("max_output_tokens" not in current or current["max_output_tokens"] == effective["max_output_tokens"],
                    "输出限制尚未被Runtime采用")
        require(request.runtime is not None and request.runtime.provider is self.provider
                and request.runtime.model == effective["model_id"]
                and request.runtime.generation.max_tokens == effective["max_output_tokens"],
                "请求采用的模型快照与当前启用版本不一致")
        return None

    def read(self):
        with self.store.connect() as db:
            db.execute("BEGIN")
            self.store.active(db, NS)
            current = self.store.get(db, NS, "configuration", "current")
            draft = obj(db, "configuration_draft", "current")
            active_runs = sum(json.loads(item[0])["status"] in {"QUEUED", "RUNNING", "WAITING_INPUT"}
                              for item in db.execute("SELECT body FROM objects WHERE namespace=? AND kind='runtime_run'", (NS,)))
            skill_pending = bool(self.skill_pending(db)) if self.skill_pending is not None else False
        fields = ("config_id", "version", "provider", "model_id", "api_type", "tool_scope", "max_tool_rounds", "timeout", "enabled")
        ready = (current["enabled"] and not skill_pending and self._native_sha() == self.effective["config_sha256"]
                 and set(current["tool_scope"]) == set(self.registry.tool_names)
                 and all(current[key] == self.effective[key] for key in
                         ("provider", "model_id", "api_type", "max_tool_rounds", "timeout")))
        return {"projection": "runtime-configuration", "current": {key: current[key] for key in fields},
                "draft": draft, "effective": dict(self.effective), "available_tools": sorted(self.available),
                "native_config_sha256": self._native_sha(), "admission_ready": bool(ready),
                "active_run_count": active_runs, "private_body_available_here": False,
                "business_authority_granted": False, "model_validation_performed": False}

    def execute(self, api, action, payload):
        def operation(path):
            return self._execute_locked(api, action, payload)
        return self.config.run_serialized(operation)

    def _execute_locked(self, api, action, payload):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.store.active(db, NS)
            key, digest, previous = api._check_existing(db, action, payload)
            if previous is not None:
                return previous
            if action == "boss.runtime.activate" and self.skill_readiness is not None:
                self.skill_readiness()
            current = self.store.get(db, NS, "configuration", "current")
            draft = obj(db, "configuration_draft", "current")
            if action == "boss.runtime.save":
                api._exact(payload, {"client_request_id", "expected_version", "values"})
                require(payload["expected_version"] == (draft["version"] if draft else "0"), "当前配置草稿已变化")
                values = RuntimeValues.model_validate(payload["values"]).model_dump()
                values["tool_scope"] = self._scope(values["tool_scope"])
                self._native()
                document = {"version": str(int(draft["version"]) + 1) if draft else "1",
                            "values": values, "native_config_sha256": self._native_sha(),
                            "tool_catalog_sha256": self._catalog_sha(),
                            "validation_status": "DRAFT_UNVALIDATED", "updated_at": now()}
                document["content_sha256"] = checksum({"values": values, "native": document["native_config_sha256"],
                                                       "tools": document["tool_catalog_sha256"]})
                self.store.put(db, NS, "configuration_draft", "current", document)
                result = document
            elif action in {"boss.runtime.validate", "boss.runtime.activate"}:
                fields = {"client_request_id", "expected_version", "expected_content_sha256"}
                if action == "boss.runtime.activate":
                    fields.add("expected_active_version")
                api._exact(payload, fields)
                require(draft is not None and draft["version"] == payload["expected_version"]
                        and draft["content_sha256"] == payload["expected_content_sha256"], "配置草稿版本或内容已变化")
                require(self._native_sha() == draft["native_config_sha256"], "原生配置已变化，请重新保存并校验")
                require(self._catalog_sha() == draft["tool_catalog_sha256"], "工具定义或实现已变化，请重新保存并校验")
                self._scope(draft["values"]["tool_scope"])
                self._native()
                if action == "boss.runtime.validate":
                    require(draft["validation_status"] == "DRAFT_UNVALIDATED", "当前草稿已经校验")
                    draft.update(version=str(int(draft["version"]) + 1), validation_status="VALIDATED_STATIC_ONLY", validated_at=now())
                    self.store.put(db, NS, "configuration_draft", "current", draft)
                    result = draft
                else:
                    require(current["version"] == payload["expected_active_version"], "当前启用版本已变化")
                    require(draft["validation_status"] == "VALIDATED_STATIC_ONLY", "必须校验当前配置草稿")
                    active = [json.loads(item[0]) for item in db.execute(
                        "SELECT body FROM objects WHERE namespace=? AND kind='runtime_run'", (NS,))]
                    require(not any(row["status"] in {"QUEUED", "RUNNING", "WAITING_INPUT"} for row in active),
                            "当前存在运行任务，请等待结束后启用配置")
                    values = RuntimeValues.model_validate(draft["values"])
                    def update(config):
                        require(self._native_sha() == draft["native_config_sha256"], "配置文件在启用期间发生变化")
                        config.agents.defaults.max_tool_iterations = values.max_tool_rounds
                        config.agents.defaults.max_tokens = values.max_output_tokens
                    def apply_config(path):
                        self.config.update(update)
                        self._apply(self._native(), values.tool_scope)
                    self.config.run_serialized(apply_config)
                    activated = {**current, **values.model_dump(), "version": str(int(current["version"]) + 1),
                                 "enabled": True, "native_config_sha256": self.effective["config_sha256"],
                                 "draft_version": draft["version"], "activated_at": now()}
                    self.store.put(db, NS, "configuration_revision", current["version"], current)
                    self.store.put(db, NS, "configuration", "current", activated)
                    draft.update(validation_status="ACTIVATED", active_version=activated["version"],
                                 activated_at=activated["activated_at"])
                    self.store.put(db, NS, "configuration_draft", "current", draft)
                    result = {"config_id": activated["config_id"], "version": activated["version"],
                              "enabled": True, "runtime_applied": True, "tool_scope": sorted(values.tool_scope),
                              "native_config_sha256": self.effective["config_sha256"]}
            else:
                require(action == "boss.runtime.deactivate", "未知配置动作", web.HTTPNotFound)
                api._exact(payload, {"client_request_id", "expected_active_version"})
                require(current["version"] == payload["expected_active_version"], "当前启用版本已变化")
                updated = {**current, "enabled": False, "version": str(int(current["version"]) + 1)}
                self.store.put(db, NS, "configuration_revision", current["version"], current)
                self.store.put(db, NS, "configuration", "current", updated)
                result = {"config_id": updated["config_id"], "version": updated["version"], "enabled": False}
            api._record(db, action, payload, key, digest, result)
            return result
