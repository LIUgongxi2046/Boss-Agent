import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

from aiohttp import web
from markdown_it import MarkdownIt
from nanobot.agent.skills import SkillsLoader, parse_skill_metadata, valid_skill_metadata
from nanobot.webui.skills_api import set_webui_skill_enabled
from packaging.version import Version


ASSETS_PATH = Path(__file__).resolve().parents[1] / "specs/agent-assets.json"
HUMAN_ONLY_OPERATIONS = frozenset({"assignmentSourcesConfirm"})


def _require_role(role, allowed):
    if role is None:
        raise web.HTTPUnauthorized(text="需要认证身份")
    if role not in allowed:
        raise web.HTTPForbidden(text="当前身份无权读取方法")


class BossSkillCatalog:
    def __init__(self, loader, registry, assets_path=ASSETS_PATH):
        self.loader = loader
        self.registry = registry
        self.assets_path = assets_path

    def _snapshot(self):
        assets = json.loads(self.assets_path.read_text(encoding="utf-8"))
        bindings = {item["sop_id"]: item for item in assets["sop_backend_bindings"]}
        raw_loader = SkillsLoader(self.loader.workspace, builtin_skills_dir=self.loader.builtin_skills)
        available = {item["name"] for item in self.loader.list_skills()}
        registered = set(self.registry.tool_names)
        documents, items = {}, []
        for sop in assets["sops"]:
            sop_id = sop["sop_id"]
            name = "boss-" + sop_id.lower()
            content = raw_loader.load_skill(name)
            if content is None:
                raise web.HTTPConflict(text="当前方法文件缺少：" + name)
            metadata = parse_skill_metadata(content)
            if metadata is None or not valid_skill_metadata(metadata, name):
                raise web.HTTPConflict(text="当前方法身份无效：" + name)
            extension = metadata.get("metadata")
            if not isinstance(extension, dict) or not isinstance(extension.get("boss"), dict):
                raise web.HTTPConflict(text="当前方法扩展信息无效：" + name)
            boss = extension["boss"]
            if boss.get("sop_id") != sop_id or boss.get("requirement_id") != sop["requirement_id"]:
                raise web.HTTPConflict(text="当前方法需求引用无效：" + name)
            version = boss.get("version")
            if not isinstance(version, str):
                raise web.HTTPConflict(text="当前方法版本缺少：" + name)
            Version(version)
            binding = bindings[sop_id]
            operations = set(binding["read_operations"] + binding["command_operations"])
            references = {
                urlparse(child.attrGet("href")).path
                for token in MarkdownIt().parse(content) for child in token.children or []
                if child.type == "link_open" and urlparse(child.attrGet("href")).scheme == "tool"
            }
            if references != operations:
                raise web.HTTPConflict(text="方法正文的工具引用与当前定义不一致：" + name)
            missing = sorted(operations - HUMAN_ONLY_OPERATIONS - registered)
            enabled = name not in self.loader.disabled_skills
            items.append({
                "sop_id": sop_id, "name": name, "requirement_id": sop["requirement_id"],
                "version": version, "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
                "enabled": enabled, "native_available": name in available,
                "read_operations": binding["read_operations"], "command_operations": binding["command_operations"],
                "human_only_operations": sorted(operations & HUMAN_ONLY_OPERATIONS),
                "missing_tools": missing, "tool_references_resolved": not missing,
                "context_eligible": enabled and name in available and not missing,
                "business_authorization_granted": False, "model_adoption_verified": False,
            })
            documents[name] = content
        return items, documents

    def technical_status(self, role):
        _require_role(role, {"MAINTAINER"})
        items, _ = self._snapshot()
        return {
            "projection": "sop-technical-status", "items": items,
            "configuration_source": "NATIVE_SKILL_FILES_AND_DISABLED_SKILLS",
            "configuration_mutation_performed": False, "private_body_available_here": False,
            "business_authorization_granted": False, "model_adoption_verified": False,
        }

    def set_enabled(self, role, sop_id, *, enabled, expected_content_sha256, config_path):
        _require_role(role, {"MAINTAINER"})
        if type(enabled) is not bool or not isinstance(sop_id, str):
            raise web.HTTPBadRequest(text="方法编号或启停状态无效")
        if not isinstance(expected_content_sha256, str) or len(expected_content_sha256) != 64:
            raise web.HTTPBadRequest(text="需要当前方法内容摘要")
        items, _ = self._snapshot()
        item = next((item for item in items if item["sop_id"] == sop_id), None)
        if item is None:
            raise web.HTTPNotFound(text="当前方法不存在")
        if item["content_sha256"] != expected_content_sha256:
            raise web.HTTPConflict(text="方法内容已经变化，需要重新核查")
        if enabled and item["missing_tools"]:
            raise web.HTTPConflict(text="方法工具引用尚未全部注册")
        if not config_path.is_file():
            raise web.HTTPConflict(text="当前原生运行配置文件缺少")
        result = set_webui_skill_enabled(
            self.loader.workspace, item["name"], enabled=enabled,
            disabled_skills=self.loader.disabled_skills, config_path=config_path,
        )
        return {**result, "sop_id": sop_id, "version": item["version"],
                "content_sha256": item["content_sha256"], "activation_policy": "NEXT_CONTEXT_LOAD",
                "business_authorization_granted": False, "model_adoption_verified": False}

    def context(self, role, sop_ids):
        _require_role(role, {"BOSS"})
        if not isinstance(sop_ids, list) or not sop_ids or any(not isinstance(item, str) for item in sop_ids):
            raise web.HTTPBadRequest(text="需要明确的SOP编号列表")
        if len(set(sop_ids)) != len(sop_ids):
            raise web.HTTPBadRequest(text="SOP编号不能重复")
        items, documents = self._snapshot()
        indexed = {item["sop_id"]: item for item in items}
        if any(sop_id not in indexed for sop_id in sop_ids):
            raise web.HTTPBadRequest(text="SOP编号不在当前方法范围")
        chosen = [indexed[sop_id] for sop_id in sop_ids]
        for item in chosen:
            if not item["context_eligible"]:
                raise web.HTTPConflict(text="当前方法停用、依赖不可用或工具引用缺少：" + item["name"])
        # 正文读取沿用原生机制，输出前再次核查本次版本及工具引用。
        block = self.loader.build_explicit_skill_runtime_context(" ".join("$" + item["name"] for item in chosen))
        current, latest_documents = self._snapshot()
        latest = {item["sop_id"]: item for item in current}
        if block is None or any(latest[item["sop_id"]] != item or latest_documents[item["name"]] != documents[item["name"]] for item in chosen):
            raise web.HTTPConflict(text="方法读取期间配置或内容发生变化")
        references = [{key: item[key] for key in ("sop_id", "name", "version", "content_sha256")} for item in chosen]
        return block, references
