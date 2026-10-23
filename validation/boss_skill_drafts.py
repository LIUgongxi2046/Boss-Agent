import fcntl
import hashlib
import json
import re
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlparse

import yaml
from aiohttp import web
from markdown_it import MarkdownIt
from nanobot.agent.skills import parse_skill_metadata, valid_skill_metadata
from nanobot.config.loader import load_config
from nanobot.utils.helpers import _write_text_atomic
from nanobot.webui.skills_api import set_webui_skill_enabled
from packaging.version import VERSION_PATTERN, Version

from boss_native_skills import HUMAN_ONLY_OPERATIONS, _require_role
from business import checksum, now
from boss_knowledge_ingestion import POTENTIAL_SECRET


VERSION_RE = re.compile(VERSION_PATTERN, re.VERBOSE | re.IGNORECASE)
OPERATIONS = {"save", "validate", "activate", "prepare", "recover", "cancel", "disable", "enable", "restore"}


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class BossSkillDrafts:
    def __init__(self, store, catalog, config_path, namespace="ui-check"):
        self.store, self.catalog = store, catalog
        self.config_path = Path(config_path)
        self.namespace = namespace
        self.catalog.drafts = self

    @contextmanager
    def _locked(self):
        with (self.catalog.loader.workspace / ".boss-sop.lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield

    def _get(self, db, kind, identifier):
        row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind=? AND id=?",
                         (self.namespace, kind, identifier)).fetchone()
        return json.loads(row[0]) if row else None

    def _put(self, db, kind, identifier, value):
        self.store.put(db, self.namespace, kind, identifier, value)

    def _configuration(self):
        if not self.config_path.is_file():
            raise web.HTTPConflict(text="当前原生运行配置缺少")
        config = load_config(self.config_path)
        if Path(config.agents.defaults.workspace).expanduser().resolve() != self.catalog.loader.workspace.resolve():
            raise web.HTTPConflict(text="原生配置与方法workspace不符")
        return config

    def _method(self, sop_id):
        assets = json.loads(self.catalog.assets_path.read_text())
        sop = next((item for item in assets["sops"] if item["sop_id"] == sop_id), None)
        if sop is None:
            raise web.HTTPNotFound(text="当前方法不存在")
        name = "boss-" + sop_id.lower()
        workspace = self.catalog.loader.workspace.resolve()
        path = workspace / "skills" / name / "SKILL.md"
        if not path.resolve().is_relative_to(workspace) or not path.is_file():
            raise web.HTTPForbidden(text="方法必须来自当前workspace的原生目录")
        content = path.read_text()
        metadata = parse_skill_metadata(content)
        if metadata is None or not valid_skill_metadata(metadata, name):
            raise web.HTTPConflict(text="当前方法身份无效")
        if metadata.get("metadata", {}).get("boss", {}).get("sop_id") != sop_id:
            raise web.HTTPConflict(text="当前方法编号不符")
        binding = next(item for item in assets["sop_backend_bindings"] if item["sop_id"] == sop_id)
        return path, content, metadata, binding

    def _pending(self, db, sop_id=None):
        rows = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='sop_activation' ORDER BY id",
                          (self.namespace,)).fetchall()
        return [item for row in rows if (item := json.loads(row[0]))["state"] == "PREPARED"
                and (sop_id is None or item["sop_id"] == sop_id)]

    def require_ready(self):
        with self.store.connect() as db:
            self.store.active(db, self.namespace)
            if self._pending(db):
                raise web.HTTPConflict(text="方法启用尚未完成，需要维护查询并恢复原操作")

    def _assessment(self, content, binding):
        tokens = MarkdownIt().parse(content)
        references = {urlparse(child.attrGet("href")).path for token in tokens for child in token.children or []
                      if child.type == "link_open" and urlparse(child.attrGet("href")).scheme == "tool"}
        expected = set(binding["read_operations"] + binding["command_operations"])
        headings = [tokens[index + 1].content for index, token in enumerate(tokens[:-1]) if token.type == "heading_open"]
        errors = []
        if references != expected:
            errors.append({"code": "TOOL_REFERENCES_CHANGED", "missing": sorted(expected - references), "unknown": sorted(references - expected)})
        absent = [label for label in ("触发", "输入", "步骤", "授权", "输出", "结束条件") if not any(label in heading for heading in headings)]
        if absent:
            errors.append({"code": "REQUIRED_SECTIONS_MISSING", "sections": absent})
        missing = sorted(expected - HUMAN_ONLY_OPERATIONS - set(self.catalog.registry.tool_names))
        return {"validation_status": "INVALID" if errors else "VALIDATED_STATIC_ONLY", "errors": errors,
                "missing_tools": missing, "tool_config_sha256": checksum(self.catalog.registry.get_definitions()),
                "model_adoption_verified": False}

    def _sections(self, body):
        tokens = MarkdownIt().parse(body)
        headings = [(index, token) for index, token in enumerate(tokens) if token.type == "heading_open"]
        lines = body.splitlines()
        return [{"heading": tokens[index + 1].content,
                 "body": "\n".join(lines[token.map[1]:headings[position + 1][1].map[0] if position + 1 < len(headings) else len(lines)]).strip()}
                for position, (index, token) in enumerate(headings)]

    def _historical(self, db, sop_id, content, label):
        identifier = sop_id + ":" + digest(content)
        if self._get(db, "sop_history", identifier) is None:
            metadata = parse_skill_metadata(content)
            self._put(db, "sop_history", identifier, {
                "history_id": identifier, "sop_id": sop_id, "method_version": metadata["metadata"]["boss"]["version"],
                "content_sha256": digest(content), "raw_markdown": content, "recorded_at": now(), "origin": label,
            })
        return identifier

    def _receipt(self, db, action, payload):
        row = db.execute("SELECT digest,result FROM idempotency WHERE namespace=? AND operation=? AND key=?",
                         (self.namespace, "boss.sop." + action, payload["client_request_id"])).fetchone()
        if row is not None:
            if row[0] != checksum(payload):
                raise web.HTTPConflict(text="同一操作编号的内容不符")
            return json.loads(row[1])
        return None

    def _record(self, db, action, payload, result):
        operation = "boss.sop." + action
        db.execute("INSERT INTO idempotency(namespace,operation,key,digest,result) VALUES(?,?,?,?,?)",
                   (self.namespace, operation, payload["client_request_id"], checksum(payload), json.dumps(result, ensure_ascii=False)))
        db.execute("INSERT INTO audit(namespace,operation,input,output,created_at) VALUES(?,?,?,?,?)",
                   (self.namespace, operation, json.dumps({"sop_id": payload["sop_id"], "client_request_id": payload["client_request_id"]}),
                    json.dumps(result, ensure_ascii=False), now()))
        return result

    def operation_status(self, role, action, client_request_id):
        _require_role(role, {"MAINTAINER"})
        if not isinstance(action, str) or action not in OPERATIONS or not isinstance(client_request_id, str) or not client_request_id or len(client_request_id) > 128:
            raise web.HTTPBadRequest(text="操作编号无效")
        with self.store.connect() as db:
            self.store.active(db, self.namespace)
            row = db.execute("SELECT result FROM idempotency WHERE namespace=? AND operation=? AND key=?",
                             (self.namespace, "boss.sop." + action, client_request_id)).fetchone()
            pending = self._get(db, "sop_activation", client_request_id)
            return {"action": action, "client_request_id": client_request_id,
                    "outcome": "RECORDED" if row else "PREPARED" if pending and pending["state"] == "PREPARED" else "NOT_FOUND_IN_CURRENT_STORE",
                    "result": json.loads(row[0]) if row else None}

    def read(self, role, sop_id):
        _require_role(role, {"MAINTAINER"})
        configuration = self._configuration()
        with self._locked(), self.store.connect() as db:
            db.execute("BEGIN")
            self.store.active(db, self.namespace)
            _, content, metadata, binding = self._method(sop_id)
            active = {"name": metadata["name"], "version": metadata["metadata"]["boss"]["version"],
                      "description": metadata["description"], "content_sha256": digest(content),
                      "body": self.catalog.loader._strip_frontmatter(content),
                      "enabled": metadata["name"] not in set(configuration.agents.defaults.disabled_skills)}
            rows = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='sop_history' ORDER BY id",
                              (self.namespace,)).fetchall()
            history = [{key: item[key] for key in ("history_id", "method_version", "content_sha256", "recorded_at", "origin")}
                       for row in rows if (item := json.loads(row[0]))["sop_id"] == sop_id]
            pending = [{key: item[key] for key in ("client_request_id", "sop_id", "draft_version", "state", "prepared_at")}
                       for item in self._pending(db, sop_id)]
            draft = self._get(db, "sop_draft", sop_id)
            return {"projection": "sop-method-editor", "source_type": "RUNTIME_RECORD", "external_api_mode": "SIMULATED",
                    "namespace": self.namespace, "sop_id": sop_id, "active": active, "draft": draft, "history": history,
                    "pending_activations": pending, "read_operations": binding["read_operations"], "command_operations": binding["command_operations"],
                    "sections": self._sections(draft["body"] if draft else active["body"]),
                    "active_assessment": self._assessment(content, binding), "model_adoption_verified": False,
                    "business_authorization_granted": False}

    def read_history(self, role, sop_id, history_id):
        _require_role(role, {"MAINTAINER"})
        if not isinstance(history_id, str) or not history_id or len(history_id) > 256:
            raise web.HTTPBadRequest(text="历史方法编号无效")
        with self.store.connect() as db:
            self.store.active(db, self.namespace)
            item = self._get(db, "sop_history", history_id)
            if item is None or item["sop_id"] != sop_id:
                raise web.HTTPNotFound(text="历史方法版本不存在")
            if digest(item["raw_markdown"]) != item["content_sha256"]:
                raise web.HTTPConflict(text="历史方法摘要不符")
            metadata = parse_skill_metadata(item["raw_markdown"])
            return {key: item[key] for key in ("history_id", "sop_id", "method_version", "content_sha256", "recorded_at", "origin")} | {
                "description": metadata["description"], "body": self.catalog.loader._strip_frontmatter(item["raw_markdown"]),
                "source_type": "RUNTIME_RECORD", "external_api_mode": "SIMULATED",
            }

    def _save(self, db, payload, restored=None):
        sop_id = payload["sop_id"]
        _, active, metadata, _ = self._method(sop_id)
        current = self._get(db, "sop_draft", sop_id)
        if payload["expected_draft_version"] != (current["draft_version"] if current else "0"):
            raise web.HTTPConflict(text="草稿版本已经变化，需要重新读取")
        if payload["expected_active_sha256"] != digest(active):
            raise web.HTTPConflict(text="当前生效正文已经变化，需要重新读取")
        version = payload["method_version"]
        if not isinstance(version, str) or len(version) > 64 or VERSION_RE.fullmatch(version) is None:
            raise web.HTTPBadRequest(text="方法版本格式无效")
        if Version(version) <= Version(metadata["metadata"]["boss"]["version"]):
            raise web.HTTPConflict(text="新方法版本需要高于当前生效版本")
        for field, limit in (("description", 1024), ("body", 32000), ("change_note", 360)):
            value = payload[field]
            if not isinstance(value, str) or not value.strip() or len(value) > limit or POTENTIAL_SECRET.search(value):
                raise web.HTTPBadRequest(text="方法字段无效或包含疑似凭据：" + field)
        document_metadata = deepcopy(metadata)
        document_metadata["description"] = payload["description"].strip()
        document_metadata["metadata"]["boss"]["version"] = version
        content = "---\n" + yaml.safe_dump(document_metadata, allow_unicode=True, sort_keys=False) + "---\n\n" + payload["body"].strip() + "\n"
        self._historical(db, sop_id, active, "NATIVE_CURRENT")
        if current is not None:
            identifier = "draft:" + sop_id + ":" + current["draft_version"]
            self._put(db, "sop_history", identifier, {**current, "history_id": identifier,
                      "origin": "DRAFT_REVISION", "recorded_at": current["saved_at"]})
        draft = {"sop_id": sop_id, "draft_version": str(int(current["draft_version"]) + 1 if current else 1),
                 "method_version": version, "description": document_metadata["description"], "body": payload["body"].strip(),
                 "raw_markdown": content, "content_sha256": digest(content), "base_active_sha256": digest(active),
                 "change_note": payload["change_note"].strip(), "state": "DRAFT", "validation_status": "NOT_RUN",
                 "restored_from": restored, "saved_at": now()}
        self._put(db, "sop_draft", sop_id, draft)
        return {key: draft[key] for key in ("sop_id", "draft_version", "method_version", "content_sha256", "state", "validation_status", "restored_from")}

    def _draft(self, db, payload):
        draft = self._get(db, "sop_draft", payload["sop_id"])
        if draft is None:
            raise web.HTTPNotFound(text="当前方法没有保存草稿")
        if draft["draft_version"] != payload["expected_draft_version"] or draft["content_sha256"] != payload["expected_content_sha256"]:
            raise web.HTTPConflict(text="草稿版本或内容摘要已经变化")
        return draft

    def _prepare(self, db, payload):
        draft = self._draft(db, payload)
        _, active, metadata, binding = self._method(payload["sop_id"])
        if digest(active) != payload["expected_active_sha256"] or digest(active) != draft["base_active_sha256"]:
            raise web.HTTPConflict(text="当前生效方法与草稿来源不一致")
        assessment = self._assessment(draft["raw_markdown"], binding)
        if draft["validation_status"] != "VALIDATED_STATIC_ONLY" or assessment["errors"] or assessment["missing_tools"]:
            raise web.HTTPConflict(text="草稿尚未校验或当前工具引用不可用")
        if self._pending(db):
            raise web.HTTPConflict(text="存在尚未完成的方法启用操作")
        journal = {"client_request_id": payload["client_request_id"], "sop_id": payload["sop_id"], "draft_version": draft["draft_version"],
                   "state": "PREPARED", "prepared_at": now(), "payload": payload,
                   "before_markdown": active, "target_markdown": draft["raw_markdown"],
                   "was_enabled": metadata["name"] not in set(load_config(self.config_path).agents.defaults.disabled_skills)}
        self._put(db, "sop_activation", payload["client_request_id"], journal)
        return journal

    def _complete(self, journal, *, cancel=False, recovery_action=None, recovery_payload=None):
        payload = journal["payload"]
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.store.active(db, self.namespace)
            self._configuration()
            current = self._get(db, "sop_activation", journal["client_request_id"])
            if current["state"] != "PREPARED":
                raise web.HTTPConflict(text="启用操作状态已经变化")
            path, active, metadata, binding = self._method(journal["sop_id"])
            if digest(active) not in {digest(journal["before_markdown"]), digest(journal["target_markdown"])}:
                raise web.HTTPConflict(text="当前方法已被其他操作修改，需要人工核查")
            target = journal["before_markdown"] if cancel else journal["target_markdown"]
            assessment = self._assessment(target, binding)
            if not cancel and (assessment["errors"] or assessment["missing_tools"]):
                raise web.HTTPConflict(text="当前方法依赖已经变化，不能继续启用")
            # 已提交的准备记录跨文件操作保留，当前空间在整个完成事务中保持有效。
            disabled = self.catalog.loader.disabled_skills
            set_webui_skill_enabled(self.catalog.loader.workspace, metadata["name"], enabled=False, disabled_skills=disabled, config_path=self.config_path)
            _write_text_atomic(path, target)
            set_webui_skill_enabled(self.catalog.loader.workspace, metadata["name"], enabled=journal["was_enabled"] if cancel else True,
                                    disabled_skills=disabled, config_path=self.config_path)
            self._historical(db, journal["sop_id"], journal["before_markdown"], "NATIVE_CURRENT")
            if not cancel:
                self._historical(db, journal["sop_id"], target, "ACTIVATED_DRAFT")
            draft = self._get(db, "sop_draft", journal["sop_id"])
            if not cancel:
                draft["state"] = "ACTIVE"
                self._put(db, "sop_draft", journal["sop_id"], draft)
            journal = {**journal, "state": "CANCELED" if cancel else "COMPLETED", "finished_at": now()}
            self._put(db, "sop_activation", journal["client_request_id"], journal)
            result = {"sop_id": journal["sop_id"], "draft_version": journal["draft_version"], "state": "CANCELED" if cancel else "ACTIVE",
                      "method_version": parse_skill_metadata(target)["metadata"]["boss"]["version"], "content_sha256": digest(target),
                      "model_adoption_verified": False, "business_authorization_granted": False}
            self._record(db, "activate", payload, result)
            if recovery_action is not None:
                self._record(db, recovery_action, recovery_payload, result)
            return result

    def execute(self, role, action, payload):
        _require_role(role, {"MAINTAINER"})
        if not isinstance(action, str) or action not in OPERATIONS or not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="方法操作无效")
        fields = {"client_request_id", "sop_id"}
        extra = {
            "save": {"expected_draft_version", "expected_active_sha256", "method_version", "description", "body", "change_note"},
            "restore": {"expected_draft_version", "expected_active_sha256", "method_version", "history_id", "change_note"},
            "validate": {"expected_draft_version", "expected_content_sha256"},
            "activate": {"expected_draft_version", "expected_content_sha256", "expected_active_sha256"},
            "prepare": {"expected_draft_version", "expected_content_sha256", "expected_active_sha256"},
            "disable": {"expected_active_sha256"}, "enable": {"expected_active_sha256"}, "recover": {"activation_request_id"}, "cancel": {"activation_request_id"},
        }[action]
        if set(payload) != fields | extra or any(not isinstance(value, str) for value in payload.values()) or any(not payload[key] or len(payload[key]) > 128 for key in fields):
            raise web.HTTPBadRequest(text="方法操作字段或编号无效")
        self._configuration()
        with self._locked():
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                self.store.active(db, self.namespace)
                existing = self._receipt(db, action, payload)
                if existing is not None:
                    return existing
                self._method(payload["sop_id"])
                if action not in {"recover", "cancel"} and self._pending(db):
                    raise web.HTTPConflict(text="存在待恢复的方法启用操作")
                if action in {"recover", "cancel"}:
                    journal = self._get(db, "sop_activation", payload["activation_request_id"])
                    if journal is None or journal["sop_id"] != payload["sop_id"] or journal["state"] != "PREPARED":
                        raise web.HTTPConflict(text="待恢复操作不存在或已经处理")
                elif action in {"activate", "prepare"}:
                    journal = self._prepare(db, payload)
                    if action == "prepare":
                        return self._record(db, action, payload, {key: journal[key] for key in ("client_request_id", "sop_id", "draft_version", "state")})
                else:
                    if action == "save":
                        result = self._save(db, payload)
                    elif action == "restore":
                        history = self._get(db, "sop_history", payload["history_id"])
                        if history is None or history["sop_id"] != payload["sop_id"]:
                            raise web.HTTPNotFound(text="历史方法版本不存在")
                        metadata = parse_skill_metadata(history["raw_markdown"])
                        restored = {key: value for key, value in payload.items() if key != "history_id"}
                        restored.update(description=metadata["description"], body=self.catalog.loader._strip_frontmatter(history["raw_markdown"]))
                        result = self._save(db, restored, history["history_id"])
                    elif action == "validate":
                        draft = self._draft(db, payload)
                        _, _, _, binding = self._method(payload["sop_id"])
                        assessment = self._assessment(draft["raw_markdown"], binding)
                        draft.update(assessment, validated_at=now())
                        self._put(db, "sop_draft", payload["sop_id"], draft)
                        result = {"sop_id": payload["sop_id"], "draft_version": draft["draft_version"], **assessment}
                    else:
                        result = self.catalog.set_enabled(role, payload["sop_id"], enabled=action == "enable",
                                                          expected_content_sha256=payload["expected_active_sha256"], config_path=self.config_path)
                    return self._record(db, action, payload, result)
            recovery = action in {"recover", "cancel"}
            return self._complete(journal, cancel=action == "cancel", recovery_action=action if recovery else None,
                                  recovery_payload=payload if recovery else None)
