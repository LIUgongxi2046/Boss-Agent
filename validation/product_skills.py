import json
import shutil
import yaml
from copy import deepcopy
from pathlib import Path

from aiohttp import web
from nanobot.agent.skills import SkillsLoader
from nanobot.runtime_context import RuntimeContextBlock
from jsonschema import Draft202012Validator

from boss_native_skills import BossSkillCatalog
from boss_skill_drafts import BossSkillDrafts
from business import checksum, encode, require


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ACTIONS = {"save", "validate", "activate", "enable", "disable", "restore", "recover", "cancel"}
NATIVE_ACTIONS = {"activate", "enable", "disable", "recover", "cancel"}
SCHEMA = yaml.safe_load((ROOT / "specs/product-skills.openapi.yaml").read_text())
VALIDATORS = {action: Draft202012Validator({**SCHEMA, "$ref": "#/components/schemas/" + action.capitalize()}) for action in PUBLIC_ACTIONS}
QUERY_VALIDATORS = {path: Draft202012Validator({**SCHEMA, "type": "object", "additionalProperties": False,
    "required": [item["name"] for item in definition["get"]["parameters"] if item.get("required")],
    "properties": {item["name"]: item["schema"] for item in definition["get"]["parameters"]}})
    for path, definition in SCHEMA["paths"].items() if definition["get"].get("parameters")}


class ProductSkills:
    @staticmethod
    def validate_query(path, values):
        require(not list(QUERY_VALIDATORS[path].iter_errors(values)), "方法查询不符合当前Schema", web.HTTPBadRequest)

    def __init__(self, runtime):
        self.runtime = runtime
        workspace = runtime.loop.context.skills.workspace.resolve()
        require(workspace.is_relative_to(runtime.config.path.parent.resolve()), "方法目录必须属于当前独立应用")
        workspace.mkdir(parents=True, exist_ok=True)
        assets = json.loads((ROOT / "specs/agent-assets.json").read_text())
        self.identifiers = {"boss-" + item["sop_id"].lower(): item["sop_id"] for item in assets["sops"]}
        directory = workspace / "skills"
        require(not directory.is_symlink(), "方法目录不能使用符号链接")
        directory.mkdir(exist_ok=True)
        for name in self.identifiers:
            target = directory / name
            require(not target.is_symlink(), "方法文件不能引用其他目录")
            if target.exists():
                require((target / "SKILL.md").is_file() and not (target / "SKILL.md").is_symlink(), "当前方法文件缺少或引用其他位置")
            else:
                shutil.copytree(ROOT / "agent/skills" / name, target)
        self.catalog = BossSkillCatalog(runtime.loop.context.skills, runtime.registry)
        self.drafts = BossSkillDrafts(runtime.store, self.catalog, runtime.config.path)
        runtime.skill_readiness = self.drafts.require_ready
        runtime.skill_pending = self.drafts._pending
        self.catalog.technical_status("MAINTAINER")

    def read(self, role):
        def operation(path):
            result = self.catalog.technical_status(role)
            with self.runtime.store.connect() as db:
                self.runtime.store.active(db, self.drafts.namespace)
                pending = [{key: item[key] for key in ("client_request_id", "sop_id", "draft_version", "state", "prepared_at")}
                           for item in self.drafts._pending(db)]
            return {**result, "items": [{**item, "context_eligible": item["context_eligible"] and not pending} for item in result["items"]],
                    "pending_activations": pending, "native_configuration_sha256": self.runtime._native_sha(),
                    "runtime_admission_ready": self.runtime.read()["admission_ready"]}
        return self.runtime.config.run_serialized(operation)

    def update(self, role, payload):
        require(role is not None, "需要认证身份", web.HTTPUnauthorized)
        require(role == "MAINTAINER", "仅技术维护身份可以修改方法", web.HTTPForbidden)
        require(isinstance(payload, dict) and set(payload) == {"name", "enabled", "expected_content_sha256"},
                "方法状态输入字段无效", web.HTTPBadRequest)
        name = payload["name"]
        require(isinstance(name, str) and name in self.identifiers, "方法不属于获准目录", web.HTTPBadRequest)

        return self.runtime.config.run_serialized(lambda config_path: self._native_operation(lambda: self.catalog.set_enabled(
            role, self.identifiers[name], enabled=payload["enabled"],
            expected_content_sha256=payload["expected_content_sha256"], config_path=config_path)))

    @staticmethod
    def _without_skills(configuration):
        value = deepcopy(configuration)
        value["agents"]["defaults"].pop("disabled_skills")
        return value

    def _native_operation(self, operation, recovery=False):
        if not recovery:
            self.runtime.snapshot()
        before = self.runtime._native().model_dump(mode="json")
        require(self._without_skills(before) == self._without_skills(self.runtime.native_configuration),
                "其他原生运行配置尚未被当前Runtime采用")
        with self.runtime.store.connect() as db:
            current = self.runtime.store.get(db, "ui-check", "configuration", "current")
        result = operation()
        config = self.runtime._native()
        require(self._without_skills(config.model_dump(mode="json")) == self._without_skills(before),
                "方法操作改变了其他运行配置")
        self.runtime._apply(config, current["tool_scope"])
        return result

    def execute(self, role, action, payload):
        require(role is not None, "需要认证身份", web.HTTPUnauthorized)
        require(role == "MAINTAINER", "仅技术维护身份可以修改方法", web.HTTPForbidden)
        require(isinstance(action, str) and action in PUBLIC_ACTIONS, "方法动作没有公开", web.HTTPBadRequest)
        require(not list(VALIDATORS[action].iter_errors(payload)), "方法输入不符合当前Schema", web.HTTPBadRequest)

        def operation(path):
            with self.runtime.store.connect() as db:
                self.runtime.store.active(db, self.drafts.namespace)
                previous = self.drafts._receipt(db, action, payload)
                if previous is not None:
                    return previous
            if action == "activate":
                require(isinstance(payload, dict) and isinstance(payload.get("sop_id"), str), "方法输入无效", web.HTTPBadRequest)
                view = self.drafts.read(role, payload["sop_id"])
                require(view["draft"] is not None and view["draft"].get("tool_config_sha256") == checksum(self.runtime.registry.get_definitions()),
                        "当前工具定义已变化，请重新校验方法草稿")
            execute = lambda: self.drafts.execute(role, action, payload)
            if action in NATIVE_ACTIONS:
                return self._native_operation(execute, recovery=action in {"recover", "cancel"})
            before = self.runtime._native_sha()
            result = execute()
            require(self.runtime._native_sha() == before, "草稿操作改变了原生运行配置")
            return result

        return self.runtime.config.run_serialized(operation)

    async def context(self, request):
        require(request.sender_id == "boss-1", "方法上下文仅限本人任务", web.HTTPForbidden)
        self.drafts.require_ready()
        loader = self.catalog.loader
        raw = SkillsLoader(loader.workspace, builtin_skills_dir=loader.builtin_skills)
        names = raw.get_explicitly_invoked_skills(request.original_user_text or "")
        selected = [self.identifiers[name] for name in names if name in self.identifiers]
        if not selected:
            return None
        block, references = self.catalog.context("BOSS", selected)
        request.attributes["boss_sop_reference"] = references
        return [block, RuntimeContextBlock(source="boss-sop-versions", content=encode({"sops": references,
            "business_authorization_granted": False, "model_adoption_verified": False}))]
