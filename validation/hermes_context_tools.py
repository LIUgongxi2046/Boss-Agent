from contextlib import contextmanager
from copy import deepcopy
import json

from aiohttp import web

from business import checksum
from hermes_memory_adapter import HermesMemoryAdapter
from hermes_skill_adapter import HermesSkillAdapter
from hermes_tool_names import METHOD_DEPENDENCY_TOOL_NAMES


class HermesContextTools:
    @staticmethod
    def require_selected_method_in_transaction(db, run_id, method):
        from agent_run_method_selection import AgentRunMethodSelection
        selected = AgentRunMethodSelection.read_in_transaction(db, run_id)
        initial = AgentRunMethodSelection.read_in_transaction(db, run_id, 1) if AgentRunMethodSelection.schema_state(db) else None
        if selected is None:
            if initial is not None or method["sop_id"] == "SOP04":
                raise web.HTTPConflict(text="当前目标缺少明确方法选择")
        elif {key: selected[key] for key in ("sop_id", "name", "version", "content_sha256")} != method:
            raise web.HTTPConflict(text="当前方法与运行选择不一致")

    @staticmethod
    def require_runtime_dependencies(skill):
        if not isinstance(skill, HermesSkillAdapter):
            raise ValueError("需要当前运行的方法服务")
        items, _ = skill.catalog._snapshot()
        matches = [item for item in items if item["sop_id"] == skill.sop_id]
        if len(matches) != 1:
            raise web.HTTPConflict(text="当前方法定义不可核查")
        required = set(matches[0]["read_operations"] + matches[0]["command_operations"])
        missing = sorted(required - METHOD_DEPENDENCY_TOOL_NAMES)
        if missing:
            raise web.HTTPConflict(text="Hermes 运行工具缺少：" + ", ".join(missing))

    @classmethod
    def assemble(cls, memory, skill):
        if not isinstance(memory, HermesMemoryAdapter) or not isinstance(skill, HermesSkillAdapter):
            raise ValueError("运行上下文需要记忆和方法服务")
        if memory.run_gate.config != skill.run_gate.config or memory.run_gate.lease_owner != skill.run_gate.lease_owner or memory.store.path.resolve() != skill.store.path.resolve():
            raise ValueError("记忆和方法不属于同一运行")
        cls.require_runtime_dependencies(skill)
        method_reference = skill.read()["reference"]
        memory_reference = memory.read()["reference"]
        return cls(memory, memory_reference, skill, method_reference)

    def __init__(self, memory, memory_reference, skill, skill_reference):
        if not isinstance(memory, HermesMemoryAdapter) or not isinstance(skill, HermesSkillAdapter):
            raise ValueError("运行上下文需要记忆和方法服务")
        if memory.run_gate.config != skill.run_gate.config or memory.run_gate.lease_owner != skill.run_gate.lease_owner or memory.store.path.resolve() != skill.store.path.resolve():
            raise ValueError("记忆和方法不属于同一运行")
        if not isinstance(memory_reference, dict) or not isinstance(skill_reference, dict):
            raise ValueError("运行上下文引用无效")
        self.memory, self.memory_reference = memory, deepcopy(memory_reference)
        self.skill, self.skill_reference = skill, deepcopy(skill_reference)
        self.require_current()

    def require_current(self):
        self.memory.require_current(self.memory_reference)
        self.skill.require_current(self.skill_reference)

    def read(self, name):
        self.require_current()
        if name == "read_product_memory":
            result = self.memory.read()
            expected = self.memory_reference
        elif name == "read_enabled_method":
            result = self.skill.read()
            expected = self.skill_reference
        else:
            raise ValueError("运行上下文工具无效")
        if result["reference"] != expected:
            raise ValueError("运行上下文引用已经变化")
        self.require_current()
        return result

    def request_digest(self, name):
        return checksum({"tool": name, "memory": self.memory_reference, "method": self.skill_reference})

    def require_method_read_in_transaction(self, db, goal_revision):
        gate = self.skill.run_gate
        if not db.in_transaction or type(goal_revision) is not int or goal_revision < 1:
            raise ValueError("方法读取核查需要当前运行事务")
        method = self.skill_reference["method"]
        digest = checksum({"context_digest": self.request_digest("read_enabled_method"), "goal_revision": goal_revision})
        events = db.execute("SELECT event_id,seq,payload FROM agent_run_events WHERE run_id=? AND lease_epoch=? AND type='TOOL_FINISHED' ORDER BY seq", (gate.config.run_id, gate.config.lease_epoch)).fetchall()
        applied = db.execute("SELECT max(e.seq) FROM agent_run_inputs i JOIN agent_run_events e ON e.run_id=i.run_id AND e.event_id=i.applied_event_id WHERE i.run_id=? AND i.goal_revision<=?", (gate.config.run_id, goal_revision)).fetchone()[0] or 0
        for event_id, seq, raw in events:
            payload = json.loads(raw)
            if payload.get("tool_id") != "read_enabled_method" or payload.get("goal_revision") != goal_revision or payload.get("method_ref") != method or payload.get("outcome") != "RETURNED" or seq <= applied:
                continue
            call_id = payload.get("call_id")
            reservation = db.execute("SELECT request_digest,tool_name,lease_epoch FROM agent_tool_reservations WHERE run_id=? AND request_key=?", (gate.config.run_id, call_id)).fetchone()
            started = db.execute("SELECT seq,payload,lease_epoch FROM agent_run_events WHERE run_id=? AND origin_event_id=? AND type='TOOL_STARTED'", (gate.config.run_id, "context-start:" + call_id)).fetchone()
            if reservation == (digest, "read_enabled_method", gate.config.lease_epoch) and started is not None and applied < started[0] < seq and started[2] == gate.config.lease_epoch and json.loads(started[1]) == {"tool_id": "read_enabled_method", "call_id": call_id}:
                return event_id
        raise web.HTTPConflict(text="当前目标缺少可核查的方法读取事件")

    @contextmanager
    def guarded_read(self, name, *, gate_check=None):
        with self.skill.drafts._locked():
            with self.memory.run_gate.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if gate_check is not None:
                    gate_check(db)
                if self.skill.drafts._pending(db):
                    raise web.HTTPConflict(text="方法配置正在变化")
                current_goal = db.execute("SELECT goal FROM agent_runs WHERE run_id=?", (self.memory.run_gate.config.run_id,)).fetchone()
                if current_goal is None or not isinstance(current_goal[0], str) or not current_goal[0].strip():
                    raise web.HTTPConflict(text="运行目标不可用")
                marker, eligible, parent = self.memory._read(db)
                run_id = self.memory.run_gate.config.run_id
                for identifier in (run_id,) if parent is None else (run_id, parent):
                    invalid = db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind='hermes_memory_invalidation' AND id=?", (marker["namespace"], identifier)).fetchone()
                    if invalid is not None or self.memory._saved(db, marker["namespace"], identifier) != marker:
                        raise web.HTTPConflict(text="运行记忆引用已经失效")
                if marker != self.memory_reference:
                    raise web.HTTPConflict(text="运行记忆引用已经变化")
                scope = self.skill._guard(db)
                configuration = self.skill.drafts._configuration()
                if set(configuration.agents.defaults.disabled_skills) != set(self.skill.catalog.loader.disabled_skills):
                    raise web.HTTPConflict(text="方法运行配置已经变化")
                path, _, _, _ = self.skill.drafts._method(self.skill.sop_id)
                if path.is_symlink() or path.parent.is_symlink() or path.parent.parent.is_symlink():
                    raise web.HTTPConflict(text="方法文件引用不可用")
                block, method = self.skill._current_method()
                expected = {**scope, "method": method}
                saved = self.skill.drafts._get(db, "hermes_skill_adoption", run_id + ":" + self.skill.sop_id)
                if saved != expected or expected != self.skill_reference:
                    raise web.HTTPConflict(text="运行方法引用已经变化")
                self.require_selected_method_in_transaction(db, run_id, method)
                if name == "read_product_memory":
                    data = {key: eligible[key] for key in ("memory_id", "version", "confirmation_state", "text")} if eligible is not None else None
                    result = {"reference": marker, "memory": data}
                elif name == "read_enabled_method":
                    result = {"content": block.content, "reference": expected, "business_authorization_granted": False}
                elif name == "record_result":
                    result = None
                else:
                    raise ValueError("运行上下文工具无效")
                yield db, result

    @contextmanager
    def guarded_result(self, *, gate_check):
        with self.guarded_read("record_result", gate_check=gate_check) as (db, _):
            yield db

