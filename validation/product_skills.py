import json
import shutil
from pathlib import Path

from aiohttp import web
from nanobot.agent.skills import SkillsLoader
from nanobot.runtime_context import RuntimeContextBlock

from boss_native_skills import BossSkillCatalog
from business import encode, require


ROOT = Path(__file__).resolve().parents[1]


class ProductSkills:
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
        self.catalog.technical_status("MAINTAINER")

    def read(self, role):
        result = self.catalog.technical_status(role)
        return {**result, "native_configuration_sha256": self.runtime._native_sha(),
                "runtime_admission_ready": self.runtime.read()["admission_ready"]}

    def update(self, role, payload):
        require(role is not None, "需要认证身份", web.HTTPUnauthorized)
        require(role == "MAINTAINER", "仅技术维护身份可以修改方法", web.HTTPForbidden)
        require(isinstance(payload, dict) and set(payload) == {"name", "enabled", "expected_content_sha256"},
                "方法状态输入字段无效", web.HTTPBadRequest)
        name = payload["name"]
        require(isinstance(name, str) and name in self.identifiers, "方法不属于获准目录", web.HTTPBadRequest)

        def operation(config_path):
            self.runtime.snapshot()
            before = self.runtime._native().model_dump(mode="json")
            before["agents"]["defaults"].pop("disabled_skills")
            with self.runtime.store.connect() as db:
                current = self.runtime.store.get(db, "ui-check", "configuration", "current")
            result = self.catalog.set_enabled(role, self.identifiers[name], enabled=payload["enabled"],
                expected_content_sha256=payload["expected_content_sha256"], config_path=config_path)
            config = self.runtime._native()
            after = config.model_dump(mode="json")
            after["agents"]["defaults"].pop("disabled_skills")
            require(after == before, "方法状态保存改变了其他运行配置")
            self.runtime._apply(config, current["tool_scope"])
            return result

        return self.runtime.config.run_serialized(operation)

    async def context(self, request):
        require(request.sender_id == "boss-1", "方法上下文仅限本人任务", web.HTTPForbidden)
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
