import json
import time
from dataclasses import asdict
from datetime import datetime, timezone
from uuid import uuid4

from aiohttp import web
from nanobot.agent.skills import parse_skill_metadata, valid_skill_metadata
from nanobot.webui.http_utils import bearer_token
from packaging.version import Version

from agent_run_scope import RunScopeService
from boss_execution_transition import pending_transition
from boss_knowledge_ingestion import POTENTIAL_SECRET
from boss_native_skills import BossSkillCatalog
from boss_skill_drafts import BossSkillDrafts, VERSION_RE, digest
from boss_simulation_api import _context
from business import checksum, now
from hermes_bridge import EngineEventSink
from product_skills import ProductSkills
from role_channel import RoleChannel


class HermesSkillAdapter:
    def __init__(self, store, scope_service, catalog, drafts, *, run_gate, sop_id):
        if not isinstance(scope_service, RunScopeService) or not isinstance(catalog, BossSkillCatalog) or not isinstance(drafts, BossSkillDrafts) or not isinstance(run_gate, EngineEventSink):
            raise ValueError("需要实际运行、会话范围及方法服务")
        if drafts.catalog is not catalog or store.path.resolve() != drafts.store.path.resolve() or store.path.resolve() != scope_service.store.path.resolve() or store.path.resolve() != run_gate.store.path.resolve() or drafts.namespace != scope_service.namespace:
            raise ValueError("方法、运行和会话必须属于同一数据库及执行空间")
        if not isinstance(sop_id, str) or not sop_id:
            raise ValueError("需要服务端确定的方法编号")
        self.store, self.scope_service, self.catalog, self.drafts, self.run_gate, self.sop_id = store, scope_service, catalog, drafts, run_gate, sop_id

    def _guard(self, db):
        gate = self.run_gate
        gate.store._require_lease(db, gate.config.run_id, gate.lease_owner, gate.config.lease_epoch)
        gate.store.require_active_lineage(db, gate.config.run_id)
        row = db.execute("SELECT actor_id,space_id,conversation_id,selected_refs,scope_proof,status,cancel_requested_at,goal FROM agent_runs WHERE run_id=?", (gate.config.run_id,)).fetchone()
        if row is None or row[5] != "RUNNING" or row[6] is not None or row[3] is None or row[4] is None or not isinstance(row[7], str) or not row[7].strip():
            raise ValueError("运行状态、任务或会话范围无效")
        context = _context(db)
        if row[:2] != (context["owner_id"], context["namespace"]) or context["namespace"] != self.scope_service.namespace or pending_transition(db, context["namespace"]) is not None or self.drafts._pending(db):
            raise ValueError("运行身份、执行空间或方法配置无效")
        proof = self.scope_service.prove_in_transaction(db, row[2], json.loads(row[3]))
        if json.loads(json.dumps(asdict(proof))) != json.loads(row[4]):
            raise ValueError("运行会话或来源范围已经变化")
        return {"run_id": gate.config.run_id, "owner_id": context["owner_id"], "namespace": context["namespace"],
                "conversation_id": row[2], "goal_sha256": checksum(row[7]), "scope_sha256": checksum(asdict(proof))}

    def _current_method(self):
        configuration = self.drafts._configuration()
        if set(configuration.agents.defaults.disabled_skills) != set(self.catalog.loader.disabled_skills):
            raise ValueError("方法运行配置已经变化")
        path, _, _, _ = self.drafts._method(self.sop_id)
        if path.is_symlink() or path.parent.is_symlink() or path.parent.parent.is_symlink():
            raise ValueError("方法文件不能引用其他位置")
        block, refs = self.catalog.context("BOSS", [self.sop_id])
        return block, refs[0]

    def read(self):
        with self.drafts._locked():
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                scope = self._guard(db)
            block, reference = self._current_method()
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if self._guard(db) != scope:
                    raise ValueError("方法读取期间运行范围已经变化")
                key = scope["run_id"] + ":" + self.sop_id
                record = {**scope, "method": reference}
                existing = self.drafts._get(db, "hermes_skill_adoption", key)
                if existing is not None and existing != record:
                    raise ValueError("当前运行的方法版本已经变化")
                if existing is None:
                    self.store.put(db, scope["namespace"], "hermes_skill_adoption", key, record)
            return {"content": block.content, "reference": record, "business_authorization_granted": False}

    def require_current(self, reference):
        if not isinstance(reference, dict):
            raise ValueError("方法引用无效")
        with self.drafts._locked():
            _, method = self._current_method()
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                scope = self._guard(db)
                expected = {**scope, "method": method}
                saved = self.drafts._get(db, "hermes_skill_adoption", scope["run_id"] + ":" + self.sop_id)
                if saved != expected or reference != expected:
                    raise ValueError("方法引用缺少或已经变化")

    def save_candidate(self, content):
        if not isinstance(content, str) or not content.strip() or len(content) > 32000 or POTENTIAL_SECRET.search(content):
            raise ValueError("方法候选内容无效")
        with self.drafts._locked():
            _, method = self._current_method()
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                scope = self._guard(db)
                saved = self.drafts._get(db, "hermes_skill_adoption", scope["run_id"] + ":" + self.sop_id)
                if saved != {**scope, "method": method}:
                    raise ValueError("当前运行没有有效方法采用记录")
                candidate_id = str(uuid4())
                candidate = {"candidate_id": candidate_id, "run_id": scope["run_id"], "sop_id": self.sop_id,
                             "base_method": method, "content": content, "content_sha256": checksum(content),
                             "state": "DRAFT", "enabled": False, "validation_status": "NOT_RUN", "created_at": now()}
                self.store.put(db, scope["namespace"], "hermes_skill_candidate", candidate_id, candidate)
                return {key: candidate[key] for key in ("candidate_id", "run_id", "sop_id", "content_sha256", "state", "enabled", "validation_status")}

    def inspect_candidate(self, candidate_id, expected_content_sha256):
        with self.drafts._locked():
            _, method = self._current_method()
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                scope = self._guard(db)
                candidate = self.drafts._get(db, "hermes_skill_candidate", candidate_id)
                if candidate is None or candidate["run_id"] != scope["run_id"] or candidate["sop_id"] != self.sop_id:
                    raise ValueError("方法候选不存在或不属于当前运行")
                if candidate["state"] != "DRAFT" or candidate["enabled"] is not False or candidate["validation_status"] != "NOT_RUN" or candidate["content_sha256"] != expected_content_sha256 or checksum(candidate["content"]) != candidate["content_sha256"] or candidate["base_method"] != method:
                    raise ValueError("方法候选或基础版本已经变化")
                if self.drafts._get(db, "hermes_skill_adoption", scope["run_id"] + ":" + self.sop_id) != {**scope, "method": method}:
                    raise ValueError("当前运行没有有效方法采用记录")
                metadata = parse_skill_metadata(candidate["content"])
                if metadata is None or not valid_skill_metadata(metadata, method["name"]) or metadata.get("metadata", {}).get("boss", {}).get("sop_id") != self.sop_id:
                    raise ValueError("方法候选身份无效")
                version = metadata.get("metadata", {}).get("boss", {}).get("version")
                if not isinstance(version, str) or len(version) > 64 or VERSION_RE.fullmatch(version) is None or Version(version) <= Version(method["version"]):
                    raise ValueError("候选版本必须高于当前方法版本")
                _, _, _, binding = self.drafts._method(self.sop_id)
                assessment = self.drafts._assessment(candidate["content"], binding)
                return {"candidate_id": candidate_id, "content_sha256": candidate["content_sha256"],
                        "method_version": version, "assessment": assessment, "state": "DRAFT", "enabled": False}


class HermesSkillMaintenance:
    def __init__(self, channel, store):
        if not isinstance(channel, RoleChannel) or channel.boss_commands is None or channel.boss_commands.store.path.resolve() != store.path.resolve():
            raise ValueError("需要同一环境的实际身份和方法服务")
        self.channel, self.store = channel, store

    def _authorize(self, request, role="MAINTAINER"):
        if not isinstance(request, web.Request):
            raise web.HTTPUnauthorized(text="需要实际维护身份请求")
        token = bearer_token(request.headers)
        if not token or not self.channel.gateway.tokens.check_api_token(request) or self.channel.token_roles.get(token) not in {"BOSS", "MAINTAINER"} or time.monotonic() >= self.channel.token_expirations.get(token, 0):
            raise web.HTTPUnauthorized(text="维护身份未认证")
        if role is not None and self.channel.token_roles[token] != role:
            raise web.HTTPForbidden(text="当前身份无权执行此方法操作")
        if not self.channel.execution_space_active():
            raise web.HTTPConflict(text="执行空间已经变化")

    def publish(self, request, candidate_id, payload=None):
        self._authorize(request)
        skills = self._skills()
        fields = {"client_request_id", "expected_content_sha256", "expected_base_sha256", "expected_draft_version", "authorization_id", "change_note"}
        if not isinstance(candidate_id, str) or not candidate_id or not isinstance(payload, dict) or set(payload) != fields or any(not isinstance(payload[key], str) or not payload[key].strip() or len(payload[key]) > (360 if key == "change_note" else 128) for key in fields):
            raise web.HTTPBadRequest(text="候选发布字段无效")

        def operation(config_path):
            with self.store.connect() as db:
                recovery = skills.drafts._get(db, "hermes_skill_publication", payload["client_request_id"]) is not None
            def activate():
                drafts = skills.drafts
                with drafts._locked():
                    with self.store.connect() as db:
                        db.execute("BEGIN IMMEDIATE")
                        namespace = drafts.namespace
                        self.store.active(db, namespace)
                        if pending_transition(db, namespace) is not None:
                            raise web.HTTPConflict(text="执行空间正在变化")
                        publication = drafts._get(db, "hermes_skill_publication", payload["client_request_id"])
                        bound = {"candidate_id": candidate_id, **payload}
                        if publication is not None:
                            if publication["request_sha256"] != checksum(bound):
                                raise web.HTTPConflict(text="同一操作编号的内容不符")
                            journal = drafts._get(db, "sop_activation", payload["client_request_id"])
                            if journal is None:
                                raise web.HTTPConflict(text="候选启用准备记录缺少")
                            if journal["state"] != "PREPARED":
                                result = drafts._receipt(db, "activate", journal["payload"])
                                if result is None:
                                    raise web.HTTPConflict(text="候选启用结果缺少")
                                return result
                        else:
                            if drafts._get(db, "sop_activation", payload["client_request_id"]) is not None or db.execute("SELECT 1 FROM idempotency WHERE namespace=? AND operation IN (?,?) AND key=?", (namespace, "boss.sop.save", "boss.sop.activate", payload["client_request_id"])).fetchone() is not None:
                                raise web.HTTPConflict(text="操作编号已经用于其他方法操作")
                            candidate = drafts._get(db, "hermes_skill_candidate", candidate_id)
                            if candidate is None:
                                raise web.HTTPNotFound(text="方法候选不存在")
                            if candidate["content_sha256"] != payload["expected_content_sha256"] or candidate["base_method"]["content_sha256"] != payload["expected_base_sha256"]:
                                raise web.HTTPConflict(text="候选或来源摘要已经变化")
                            drafts.require_candidate_authorization(db, candidate, payload["authorization_id"], candidate["content"])
                            configuration = drafts._configuration()
                            if set(configuration.agents.defaults.disabled_skills) != set(skills.catalog.loader.disabled_skills):
                                raise web.HTTPConflict(text="方法运行配置已经变化")
                            items, _ = skills.catalog._snapshot()
                            item = next(item for item in items if item["sop_id"] == candidate["sop_id"])
                            method = {key: item[key] for key in ("sop_id", "name", "version", "content_sha256")}
                            adoption = drafts._get(db, "hermes_skill_adoption", candidate["run_id"] + ":" + candidate["sop_id"])
                            if not item["context_eligible"] or method != candidate["base_method"] or adoption is None or adoption.get("method") != method or adoption.get("run_id") != candidate["run_id"]:
                                raise web.HTTPConflict(text="来源方法或依赖已经变化")
                            metadata = parse_skill_metadata(candidate["content"])
                            if metadata is None or not valid_skill_metadata(metadata, method["name"]) or metadata.get("metadata", {}).get("boss", {}).get("sop_id") != candidate["sop_id"]:
                                raise web.HTTPConflict(text="方法候选身份无效")
                            save = {"client_request_id": payload["client_request_id"], "sop_id": candidate["sop_id"],
                                    "expected_draft_version": payload["expected_draft_version"], "expected_active_sha256": payload["expected_base_sha256"],
                                    "method_version": metadata["metadata"]["boss"]["version"], "description": metadata["description"],
                                    "body": skills.catalog.loader._strip_frontmatter(candidate["content"]), "change_note": payload["change_note"]}
                            if drafts._pending(db):
                                raise web.HTTPConflict(text="存在尚未完成的方法启用操作")
                            self._authorize(request)
                            saved = drafts._save(db, save)
                            draft = drafts._get(db, "sop_draft", candidate["sop_id"])
                            _, _, _, binding = drafts._method(candidate["sop_id"])
                            assessment = drafts._assessment(candidate["content"], binding)
                            if assessment["errors"] or assessment["missing_tools"] or assessment["tool_config_sha256"] != candidate["tool_config_sha256"]:
                                raise web.HTTPConflict(text="候选静态校验或工具配置已经变化")
                            draft.update(assessment, raw_markdown=candidate["content"], content_sha256=digest(candidate["content"]),
                                         validated_at=now(), hermes_candidate_id=candidate_id, hermes_authorization_id=payload["authorization_id"])
                            drafts._put(db, "sop_draft", candidate["sop_id"], draft)
                            saved.update(content_sha256=draft["content_sha256"], validation_status=draft["validation_status"])
                            drafts._record(db, "save", save, saved)
                            activation = {"client_request_id": payload["client_request_id"], "sop_id": candidate["sop_id"],
                                          "expected_draft_version": draft["draft_version"], "expected_content_sha256": draft["content_sha256"],
                                          "expected_active_sha256": payload["expected_base_sha256"]}
                            journal = drafts._prepare(db, activation)
                            drafts._put(db, "hermes_skill_publication", payload["client_request_id"], {"request_sha256": checksum(bound), "candidate_id": candidate_id})
                    self._authorize(request)
                    return drafts._complete(journal)
            return skills._native_operation(activate, recovery=recovery)

        return skills.runtime.config.run_serialized(operation)

    def publication_status(self, request, candidate_id, client_request_id):
        self._authorize(request)
        skills = self._skills()
        if not isinstance(candidate_id, str) or not candidate_id or not isinstance(client_request_id, str) or not client_request_id or len(client_request_id) > 128:
            raise web.HTTPBadRequest(text="候选或操作编号无效")
        with self.store.connect() as db:
            db.execute("BEGIN")
            self.store.active(db, skills.drafts.namespace)
            publication = skills.drafts._get(db, "hermes_skill_publication", client_request_id)
            if publication is None:
                return {"candidate_id": candidate_id, "client_request_id": client_request_id, "state": "NOT_FOUND"}
            if publication["candidate_id"] != candidate_id:
                raise web.HTTPConflict(text="操作编号与候选不符")
            journal = skills.drafts._get(db, "sop_activation", client_request_id)
            if journal is None:
                raise web.HTTPConflict(text="候选启用准备记录缺少")
            return {"candidate_id": candidate_id, "client_request_id": client_request_id,
                    "sop_id": journal["sop_id"], "state": journal["state"],
                    "result": skills.drafts._receipt(db, "activate", journal["payload"])}

    def decision_status(self, request, candidate_id, client_request_id):
        self._authorize(request, "BOSS")
        skills = self._skills()
        if not isinstance(candidate_id, str) or not candidate_id or len(candidate_id) > 128 or not isinstance(client_request_id, str) or not client_request_id or len(client_request_id) > 128:
            raise web.HTTPBadRequest(text="候选或操作编号无效")
        with self.store.connect() as db:
            db.execute("BEGIN")
            namespace = skills.drafts.namespace
            self.store.active(db, namespace)
            context = _context(db)
            if context["namespace"] != namespace or pending_transition(db, namespace) is not None:
                raise web.HTTPConflict(text="执行空间正在变化")
            row = db.execute("SELECT result FROM idempotency WHERE namespace=? AND operation=? AND key=?", (namespace, "hermes.skill.decision", client_request_id)).fetchone()
            if row is None:
                return {"candidate_id": candidate_id, "client_request_id": client_request_id, "state": "NOT_FOUND", "result": None}
            result = json.loads(row[0])
            if result.get("candidate_id") != candidate_id:
                raise web.HTTPConflict(text="操作编号与候选不符")
            authorization = skills.drafts._get(db, "authorization", result["authorization_id"])
            if authorization is None or authorization.get("owner_id") != context["owner_id"] or authorization.get("issuer") != context["owner_id"] or authorization.get("issuer_identity") != "BOSS" or authorization.get("scope") != namespace or authorization.get("action") != "hermes.skill.decision" or authorization.get("content_version") != result.get("content_sha256") or authorization.get("target_id") != candidate_id or authorization.get("payload") != {key: value for key, value in result.items() if key != "authorization_id"}:
                raise web.HTTPConflict(text="本人决定与授权记录不一致")
            self._authorize(request, "BOSS")
            return {"candidate_id": candidate_id, "client_request_id": client_request_id, "state": "RECORDED", "result": result}

    def _skills(self):
        skills = self.channel.skills
        if not isinstance(skills, ProductSkills) or skills.runtime.store.path.resolve() != self.store.path.resolve():
            raise web.HTTPServiceUnavailable(text="方法维护服务尚未装配")
        return skills

    def list_candidates(self, request, *, after="", limit=50):
        self._authorize(request, None)
        skills = self._skills()
        if not isinstance(after, str) or len(after) > 128 or type(limit) is not int or not 1 <= limit <= 100:
            raise web.HTTPBadRequest(text="候选分页参数无效")
        with self.store.connect() as db:
            db.execute("BEGIN")
            namespace = skills.drafts.namespace
            self.store.active(db, namespace)
            context = _context(db)
            if context["namespace"] != namespace or pending_transition(db, namespace) is not None:
                raise web.HTTPConflict(text="执行空间正在变化")
            rows = db.execute("SELECT id,body FROM objects WHERE namespace=? AND kind='hermes_skill_candidate' AND id>? ORDER BY id LIMIT ?", (namespace, after, limit + 1)).fetchall()
            items = []
            for identifier, body in rows[:limit]:
                candidate = json.loads(body)
                adoption = skills.drafts._get(db, "hermes_skill_adoption", candidate["run_id"] + ":" + candidate["sop_id"])
                if candidate.get("candidate_id") != identifier or adoption is None or adoption.get("owner_id") != context["owner_id"] or adoption.get("namespace") != namespace or adoption.get("method") != candidate.get("base_method") or checksum(candidate.get("content")) != candidate.get("content_sha256"):
                    raise web.HTTPConflict(text="候选来源或内容记录不一致")
                items.append({key: candidate[key] for key in ("candidate_id", "run_id", "sop_id", "content_sha256", "state", "enabled", "validation_status", "created_at")})
            self._authorize(request, None)
            return {"items": items, "next_after": items[-1]["candidate_id"] if len(rows) > limit else None}

    def maintenance_detail(self, request, candidate_id):
        self._authorize(request)
        skills = self._skills()
        if not isinstance(candidate_id, str) or not candidate_id or len(candidate_id) > 128:
            raise web.HTTPBadRequest(text="候选编号无效")

        def operation(config_path):
            drafts = skills.drafts
            with drafts._locked(), self.store.connect() as db:
                db.execute("BEGIN")
                namespace = drafts.namespace
                self.store.active(db, namespace)
                context = _context(db)
                if context["namespace"] != namespace or pending_transition(db, namespace) is not None:
                    raise web.HTTPConflict(text="执行空间正在变化")
                candidate = drafts._get(db, "hermes_skill_candidate", candidate_id)
                if candidate is None:
                    raise web.HTTPNotFound(text="方法候选不存在")
                adoption = drafts._get(db, "hermes_skill_adoption", candidate["run_id"] + ":" + candidate["sop_id"])
                if candidate.get("candidate_id") != candidate_id or adoption is None or adoption.get("owner_id") != context["owner_id"] or adoption.get("namespace") != namespace or adoption.get("method") != candidate.get("base_method") or checksum(candidate.get("content")) != candidate.get("content_sha256"):
                    raise web.HTTPConflict(text="候选来源或内容记录不一致")
                _, current, _, _ = drafts._method(candidate["sop_id"])
                draft = drafts._get(db, "sop_draft", candidate["sop_id"])
                rows = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='hermes_skill_decision'", (namespace,)).fetchall()
                decisions = []
                for row in rows:
                    decision = json.loads(row[0])
                    if decision.get("candidate_id") != candidate_id:
                        continue
                    auth = drafts._get(db, "authorization", decision["authorization_id"])
                    if auth is None:
                        raise web.HTTPConflict(text="本人决定的授权记录缺少")
                    if auth.get("authorization_id") != decision["authorization_id"] or auth.get("owner_id") != context["owner_id"] or auth.get("issuer") != context["owner_id"] or auth.get("issuer_identity") != "BOSS" or auth.get("scope") != namespace or auth.get("action") != "hermes.skill.decision" or auth.get("target_id") != candidate_id or auth.get("content_version") != decision.get("content_sha256") or type(auth.get("revoked")) is not bool or auth.get("payload") != {key: value for key, value in decision.items() if key != "authorization_id"}:
                        raise web.HTTPConflict(text="本人决定与授权记录不一致")
                    start = datetime.fromisoformat(auth["valid_from"])
                    end = datetime.fromisoformat(auth["valid_until"])
                    if start.tzinfo is None or end.tzinfo is None:
                        raise web.HTTPConflict(text="本人授权有效期无效")
                    decisions.append({"authorization_id": decision["authorization_id"], "decision": decision["decision"],
                                      "valid_from": auth["valid_from"], "valid_until": auth["valid_until"],
                                      "revoked": auth["revoked"], "expired": datetime.now(timezone.utc) >= end,
                                      "content_sha256": decision["content_sha256"], "base_sha256": decision["base_sha256"],
                                      "tool_config_sha256": decision["tool_config_sha256"]})
                decisions.sort(key=lambda item: (item["valid_from"], item["authorization_id"]), reverse=True)
                self._authorize(request)
                return {**{key: candidate[key] for key in ("candidate_id", "run_id", "sop_id", "content_sha256", "base_method", "state", "enabled", "validation_status", "created_at")},
                        "errors": candidate.get("errors", []), "missing_tools": candidate.get("missing_tools", []),
                        "tool_config_sha256": candidate.get("tool_config_sha256"), "current_active_sha256": digest(current),
                        "draft_version": draft["draft_version"] if draft else "0", "decisions": decisions}

        return skills.runtime.config.run_serialized(operation)

    def preview(self, request, candidate_id):
        self._authorize(request, "BOSS")
        skills = self._skills()

        def operation(config_path):
            with skills.drafts._locked(), self.store.connect() as db:
                db.execute("BEGIN")
                self.store.active(db, skills.drafts.namespace)
                if pending_transition(db, skills.drafts.namespace) is not None or skills.drafts._pending(db):
                    raise web.HTTPConflict(text="执行空间或方法启用状态正在变化")
                candidate = skills.drafts._get(db, "hermes_skill_candidate", candidate_id)
                if candidate is None:
                    raise web.HTTPNotFound(text="方法候选不存在")
                if candidate.get("state") != "DRAFT" or checksum(candidate.get("content")) != candidate.get("content_sha256"):
                    raise web.HTTPConflict(text="方法候选状态或内容已经变化")
                _, current, _, _ = skills.drafts._method(candidate["sop_id"])
                if digest(current) != candidate["base_method"]["content_sha256"]:
                    raise web.HTTPConflict(text="来源方法已经变化")
                rows = db.execute("SELECT key,result FROM idempotency WHERE namespace=? AND operation=? AND json_extract(result,'$.candidate_id')=? ORDER BY key", (skills.drafts.namespace, "hermes.skill.decision", candidate_id)).fetchall()
                receipts = [{"client_request_id": key, **json.loads(result)} for key, result in rows]
                self._authorize(request, "BOSS")
                return {"candidate_id": candidate_id, "sop_id": candidate["sop_id"],
                        "content": candidate["content"], "content_sha256": candidate["content_sha256"],
                        "base_content": current, "base_method": candidate["base_method"],
                        "validation_status": candidate["validation_status"], "decision_receipts": receipts}

        return skills.runtime.config.run_serialized(operation)

    def decide(self, request, candidate_id, payload):
        self._authorize(request, "BOSS")
        skills = self._skills()
        fields = {"client_request_id", "expected_content_sha256", "expected_base_sha256", "decision"}
        if not isinstance(payload, dict) or set(payload) != fields or any(not isinstance(payload[field], str) or not payload[field] or len(payload[field]) > 128 for field in fields) or payload["decision"] not in {"APPROVE", "REJECT"}:
            raise web.HTTPBadRequest(text="本人决定字段无效")

        def operation(config_path):
            with skills.drafts._locked(), self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                namespace = skills.drafts.namespace
                self.store.active(db, namespace)
                if pending_transition(db, namespace) is not None or skills.drafts._pending(db):
                    raise web.HTTPConflict(text="执行空间或方法启用状态正在变化")
                bound = {"candidate_id": candidate_id, **payload}
                operation_name = "hermes.skill.decision"
                row = db.execute("SELECT digest,result FROM idempotency WHERE namespace=? AND operation=? AND key=?", (namespace, operation_name, payload["client_request_id"])).fetchone()
                if row is not None:
                    if row[0] != checksum(bound):
                        raise web.HTTPConflict(text="同一操作编号的内容不符")
                    return json.loads(row[1])
                candidate = skills.drafts._get(db, "hermes_skill_candidate", candidate_id)
                if candidate is None:
                    raise web.HTTPNotFound(text="方法候选不存在")
                if candidate.get("state") != "DRAFT" or candidate.get("enabled") is not False or candidate.get("content_sha256") != payload["expected_content_sha256"] or checksum(candidate.get("content")) != payload["expected_content_sha256"]:
                    raise web.HTTPConflict(text="方法候选或内容摘要已经变化")
                _, current, _, _ = skills.drafts._method(candidate["sop_id"])
                if digest(current) != payload["expected_base_sha256"] or candidate["base_method"]["content_sha256"] != payload["expected_base_sha256"]:
                    raise web.HTTPConflict(text="来源方法已经变化")
                configuration = skills.drafts._configuration()
                if set(configuration.agents.defaults.disabled_skills) != set(skills.catalog.loader.disabled_skills):
                    raise web.HTTPConflict(text="方法运行配置已经变化")
                items, _ = skills.catalog._snapshot()
                item = next(item for item in items if item["sop_id"] == candidate["sop_id"])
                if not item["context_eligible"]:
                    raise web.HTTPConflict(text="来源方法已停用或依赖不可用")
                if candidate.get("validation_status") != "VALIDATED_STATIC_ONLY" or candidate.get("errors") or candidate.get("missing_tools") or candidate.get("tool_config_sha256") != checksum(skills.catalog.registry.get_definitions()):
                    raise web.HTTPConflict(text="候选尚未通过当前静态校验")
                self._authorize(request, "BOSS")
                decision = {"candidate_id": candidate_id, "sop_id": candidate["sop_id"],
                            "content_sha256": candidate["content_sha256"], "base_sha256": payload["expected_base_sha256"],
                            "tool_config_sha256": candidate["tool_config_sha256"], "decision": payload["decision"]}
                authorization_id = self.channel.boss_commands._authorize(db, "hermes.skill.decision", decision, candidate_id, candidate["content_sha256"])
                result = {**decision, "authorization_id": authorization_id}
                self.store.put(db, namespace, "hermes_skill_decision", authorization_id, result)
                db.execute("INSERT INTO idempotency(namespace,operation,key,digest,result) VALUES(?,?,?,?,?)", (namespace, operation_name, payload["client_request_id"], checksum(bound), json.dumps(result, ensure_ascii=False)))
                db.execute("INSERT INTO audit(namespace,operation,input,output,created_at) VALUES(?,?,?,?,?)", (namespace, operation_name, json.dumps({"candidate_id": candidate_id, "client_request_id": payload["client_request_id"]}), json.dumps(result, ensure_ascii=False), now()))
                return result

        return skills.runtime.config.run_serialized(operation)

    def validate(self, request, candidate_id, expected_content_sha256):
        self._authorize(request)
        skills = self._skills()
        if not isinstance(candidate_id, str) or not candidate_id or not isinstance(expected_content_sha256, str) or len(expected_content_sha256) != 64:
            raise web.HTTPBadRequest(text="候选编号或内容摘要无效")

        def operation(config_path):
            drafts, catalog = skills.drafts, skills.catalog
            with drafts._locked(), self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                self.store.active(db, drafts.namespace)
                if pending_transition(db, drafts.namespace) is not None or drafts._pending(db):
                    raise web.HTTPConflict(text="执行空间或方法启用状态正在变化")
                candidate = drafts._get(db, "hermes_skill_candidate", candidate_id)
                if candidate is None:
                    raise web.HTTPNotFound(text="方法候选不存在")
                if candidate.get("state") != "DRAFT" or candidate.get("enabled") is not False or candidate.get("content_sha256") != expected_content_sha256 or checksum(candidate.get("content")) != expected_content_sha256:
                    raise web.HTTPConflict(text="方法候选或内容摘要已经变化")
                sop_id = candidate["sop_id"]
                configuration = drafts._configuration()
                if set(configuration.agents.defaults.disabled_skills) != set(catalog.loader.disabled_skills):
                    raise web.HTTPConflict(text="方法运行配置已经变化")
                path, _, active_metadata, binding = drafts._method(sop_id)
                if path.is_symlink() or path.parent.is_symlink() or path.parent.parent.is_symlink():
                    raise web.HTTPConflict(text="方法文件不能引用其他位置")
                items, _ = catalog._snapshot()
                item = next(item for item in items if item["sop_id"] == sop_id)
                method = {key: item[key] for key in ("sop_id", "name", "version", "content_sha256")}
                adoption = drafts._get(db, "hermes_skill_adoption", candidate["run_id"] + ":" + sop_id)
                if not item["context_eligible"] or candidate["base_method"] != method or adoption is None or adoption.get("method") != method or adoption.get("run_id") != candidate["run_id"]:
                    raise web.HTTPConflict(text="候选来源方法或采用记录已经变化")
                metadata = parse_skill_metadata(candidate["content"])
                if metadata is None or not valid_skill_metadata(metadata, method["name"]) or metadata.get("metadata", {}).get("boss", {}).get("sop_id") != sop_id or metadata.get("metadata", {}).get("boss", {}).get("requirement_id") != active_metadata["metadata"]["boss"]["requirement_id"]:
                    raise web.HTTPConflict(text="方法候选身份或需求引用无效")
                version = metadata.get("metadata", {}).get("boss", {}).get("version")
                if not isinstance(version, str) or len(version) > 64 or VERSION_RE.fullmatch(version) is None or Version(version) <= Version(method["version"]):
                    raise web.HTTPConflict(text="候选版本必须高于当前方法版本")
                assessment = drafts._assessment(candidate["content"], binding)
                self._authorize(request)
                candidate.update(assessment, validated_at=now())
                self.store.put(db, drafts.namespace, "hermes_skill_candidate", candidate_id, candidate)
                return {"candidate_id": candidate_id, "content_sha256": expected_content_sha256,
                        "method_version": version, "state": "DRAFT", "enabled": False, **assessment}

        return skills.runtime.config.run_serialized(operation)

    def disable(self, request, payload):
        self._authorize(request)
        if not isinstance(self.channel.skills, ProductSkills) or self.channel.skills.runtime.store.path.resolve() != self.store.path.resolve():
            raise web.HTTPServiceUnavailable(text="方法维护服务尚未装配")
        return self.channel.skills.execute("MAINTAINER", "disable", payload)
