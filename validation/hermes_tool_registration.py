import json
import hashlib
import os
import stat
import threading
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from tools.registry import registry

from hermes_transport_client import HermesTransportClient
from agent_artifact_hermes import FORMAT_TOOL_NAME, FORMAT_TOOL_SCHEMA, TOOL_NAME, TOOL_SCHEMA, TOOLSET


_workspace_file_lock = threading.RLock()


def workspace_file_path(workspace, value, *, writing):
    workspace = Path(workspace)
    if not workspace.is_absolute() or workspace.resolve(strict=True) != workspace or not workspace.is_dir():
        raise ValueError('文件工具工作区不可核查')
    if not isinstance(value, str) or not value or '\x00' in value or value.startswith('~'):
        raise ValueError('文件工具路径无效')
    path = Path(value)
    if path.is_absolute():
        if not path.is_relative_to(workspace):
            raise ValueError('文件工具路径超出工作区')
        path = path.relative_to(workspace)
    if not path.parts or any(part in {'.', '..'} for part in path.parts):
        raise ValueError('文件工具路径无效')
    current = workspace
    for index, part in enumerate(path.parts):
        current = current / part
        if not os.path.lexists(current):
            if not writing:
                raise ValueError('文件工具目录或文件不存在')
            continue
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValueError('文件工具路径不能包含符号链接')
        if index < len(path.parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise ValueError('文件工具父目录无效')
        if index == len(path.parts) - 1 and not stat.S_ISREG(info.st_mode):
            raise ValueError('文件工具目标必须是普通文件')
    return current


@contextmanager
def registered_workspace_file_tools(client):
    if not isinstance(client, HermesTransportClient):
        raise ValueError('文件工具需要运行通信客户端')
    names = ('workspace_read_file', 'workspace_write_file')
    if any(registry.get_entry(name) is not None for name in names):
        raise ValueError('文件工具已经注册')

    def execute(arguments, *, writing, **kwargs):
        from tools.file_tools import read_file_tool, write_file_tool
        fields = {'path', 'content'} if writing else {'path', 'offset', 'limit'}
        required = {'path', 'content'} if writing else {'path'}
        if not isinstance(arguments, dict) or not required <= set(arguments) or set(arguments) - fields:
            raise ValueError('文件工具参数无效')
        if writing and not isinstance(arguments['content'], str):
            raise ValueError('文件工具内容无效')
        if not writing and (type(arguments.get('offset', 1)) is not int or type(arguments.get('limit', 2000)) is not int or arguments.get('offset', 1) < 1 or not 1 <= arguments.get('limit', 2000) <= 2000):
            raise ValueError('文件工具读取范围无效')
        name = names[1] if writing else names[0]
        call_id = str(uuid4())
        digest = hashlib.sha256(json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
        with _workspace_file_lock:
            path = workspace_file_path(Path('/mnt'), arguments['path'], writing=writing)
            client.reserve_workspace_file_tool(name, call_id, digest)
            if writing:
                result = write_file_tool(path=str(path), content=arguments['content'], task_id=client.run_id)
            else:
                result = read_file_tool(path=str(path), offset=arguments.get('offset', 1), limit=arguments.get('limit', 2000), task_id=client.run_id)
            parsed = json.loads(result)
            if not isinstance(parsed, dict):
                raise ValueError('文件工具结果无效')
            client.finish_workspace_file_tool(name, call_id, 'FAILED' if parsed.get('error') or parsed.get('success') is False else 'RETURNED')
            return result

    schemas = (
        {'name': names[0], 'description': '读取当前运行工作区内的文件', 'parameters': {'type': 'object', 'additionalProperties': False, 'required': ['path'], 'properties': {'path': {'type': 'string', 'minLength': 1}, 'offset': {'type': 'integer', 'minimum': 1}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 2000}}}},
        {'name': names[1], 'description': '在当前运行工作区内创建或更新文件', 'parameters': {'type': 'object', 'additionalProperties': False, 'required': ['path', 'content'], 'properties': {'path': {'type': 'string', 'minLength': 1}, 'content': {'type': 'string'}}}},
    )
    registered = []
    try:
        for index, schema in enumerate(schemas):
            def handler(arguments, *, _writing=bool(index), **kwargs):
                return execute(arguments, writing=_writing, **kwargs)
            registry.register(name=names[index], toolset='boss_domain', schema=schema, handler=handler)
            registered.append(names[index])
        yield
    finally:
        for name in registered:
            registry.deregister(name)


def register_document_tool(client):
    if not isinstance(client, HermesTransportClient):
        raise ValueError("工具注册需要运行通信客户端")
    if registry.get_entry("read_bound_documents") is not None:
        raise ValueError("业务资料工具已经注册")

    def read_documents(arguments, **kwargs):
        if arguments != {}:
            raise ValueError("来源读取不接受模型参数")
        return json.dumps(client.read_documents(str(uuid4())), ensure_ascii=False, allow_nan=False)

    registry.register(name="read_bound_documents", toolset="boss_domain",
        schema={"name": "read_bound_documents", "description": "读取当前运行已选择且仍有效的业务资料",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
        handler=read_documents)


@contextmanager
def registered_bi_tools(client, definitions):
    if not isinstance(client, HermesTransportClient) or not isinstance(definitions, list):
        raise ValueError("经营工具需要运行通信客户端")
    names = {"query_metrics", "read_evidence"}
    if len(definitions) != 2 or any(not isinstance(item, dict) or set(item) != {"name", "description", "parameters"} or not isinstance(item["description"], str) or not isinstance(item["parameters"], dict) for item in definitions) or {item["name"] for item in definitions} != names:
        raise ValueError("经营工具定义不可核查")
    if any(registry.get_entry(name) is not None for name in names):
        raise ValueError("经营工具已经注册")
    registered = []
    try:
        for definition in definitions:
            name = definition["name"]
            def execute(arguments, *, _name=name, **kwargs):
                return json.dumps(client.call_bi_tool(_name, arguments, str(uuid4())), ensure_ascii=False, allow_nan=False)
            registry.register(name=name, toolset="boss_domain", schema=definition, handler=execute)
            registered.append(name)
        yield
    finally:
        for name in registered:
            registry.deregister(name)


@contextmanager
def registered_document_tool(client):
    register_document_tool(client)
    try:
        yield
    finally:
        registry.deregister("read_bound_documents")


@contextmanager
def registered_evidence_tool(client):
    if not isinstance(client, HermesTransportClient) or registry.get_entry("bossEvidenceRead") is not None:
        raise ValueError("来源工具客户端无效或工具已经注册")
    def read(arguments, **kwargs):
        if not isinstance(arguments, dict) or set(arguments) != {"source"}:
            raise ValueError("来源工具参数无效")
        return json.dumps(client.read_evidence(arguments["source"], str(uuid4())), ensure_ascii=False, allow_nan=False)
    registry.register(name="bossEvidenceRead", toolset="boss_domain", schema={"name": "bossEvidenceRead", "description": "读取当前运行已选择且仍有效的来源原文和版本", "parameters": {"type": "object", "properties": {"source": {"type": "string", "minLength": 1, "maxLength": 100}}, "required": ["source"], "additionalProperties": False}}, handler=read)
    try:
        yield
    finally:
        registry.deregister("bossEvidenceRead")


@contextmanager
def registered_meeting_read_tools(client):
    if not isinstance(client, HermesTransportClient):
        raise ValueError("会议工具需要运行通信客户端")
    names = {"bossMeetingsRead": "catalog", "meetingArrangementRead": "arrangement"}
    if any(registry.get_entry(name) is not None for name in names):
        raise ValueError("会议工具已经注册")
    registered = []
    try:
        for name, kind in names.items():
            def read(arguments, *, _kind=kind, **kwargs):
                if arguments != {}:
                    raise ValueError("会议读取不接受模型参数")
                return json.dumps(client.read_meeting_projection(_kind, str(uuid4())), ensure_ascii=False, allow_nan=False)
            registry.register(name=name, toolset="boss_domain", schema={"name": name, "description": "读取当前会议和本次运行选中来源范围内的会议资料", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}, handler=read)
            registered.append(name)
        yield
    finally:
        for name in registered:
            registry.deregister(name)


@contextmanager
def registered_input_request_tool(client):
    name = "request_additional_input"
    if not isinstance(client, HermesTransportClient) or registry.get_entry(name) is not None:
        raise ValueError("补充事项工具客户端无效或工具已经注册")
    def ask(arguments, **kwargs):
        if not isinstance(arguments, dict) or set(arguments) != {"question"}:
            raise ValueError("补充事项参数无效")
        context = client.input_context()
        return json.dumps(client.request_additional_input(arguments["question"], context["goal_revision"], str(uuid4())), ensure_ascii=False, allow_nan=False)
    registry.register(name=name, toolset="boss_domain", schema={"name": name, "description": "需要本人提供具体缺少信息时，提交当前问题并等待本人补充", "parameters": {"type": "object", "properties": {"question": {"type": "string", "minLength": 1, "maxLength": 2000}}, "required": ["question"], "additionalProperties": False}}, handler=ask)
    try:
        yield
    finally:
        registry.deregister(name)


@contextmanager
def registered_context_tools(client):
    if not isinstance(client, HermesTransportClient):
        raise ValueError("工具注册需要运行通信客户端")
    names = {"read_product_memory": "memory", "read_enabled_method": "method"}
    if any(registry.get_entry(name) is not None for name in names):
        raise ValueError("运行上下文工具已经注册")
    registered = []
    try:
        for name, kind in names.items():
            def read(arguments, *, _kind=kind, **kwargs):
                if arguments != {}:
                    raise ValueError("上下文读取不接受模型参数")
                return json.dumps(client.read_context(_kind, str(uuid4())), ensure_ascii=False, allow_nan=False)
            registry.register(name=name, toolset="boss_domain", schema={"name": name, "description": "读取当前运行获准的记忆或方法", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}, handler=read)
            registered.append(name)
        yield
    finally:
        for name in registered:
            registry.deregister(name)


@contextmanager
def registered_artifact_tools(client):
    if not isinstance(client, HermesTransportClient):
        raise ValueError("成果工具需要运行通信客户端")
    from hermes_domain_schema import RUNTIME_BRIEF_SCHEMA
    runtime_name = "boss_runtime_meeting_brief"
    names = (TOOL_NAME, FORMAT_TOOL_NAME, runtime_name)
    if any(registry.get_entry(name) is not None for name in names):
        raise ValueError("成果工具已经注册")
    registered = []
    try:
        for name, schema in ((TOOL_NAME, TOOL_SCHEMA), (FORMAT_TOOL_NAME, FORMAT_TOOL_SCHEMA)):
            def create(arguments, **kwargs):
                return json.dumps(client.create_meeting_brief(arguments), ensure_ascii=False, allow_nan=False)
            registry.register(name=name, toolset=TOOLSET, schema=schema, handler=create, check_fn=lambda: False, is_async=False)
            registered.append(name)
        def create_runtime(arguments, **kwargs):
            return json.dumps(client.create_runtime_meeting_brief(arguments), ensure_ascii=False, allow_nan=False)
        registry.register(name=runtime_name, toolset=TOOLSET, schema={"name": runtime_name, "description": "使用实际整理内容和当前运行引用生成会议简报", "parameters": RUNTIME_BRIEF_SCHEMA}, handler=create_runtime, check_fn=lambda: False, is_async=False)
        registered.append(runtime_name)
        yield
    finally:
        for name in registered:
            registry.deregister(name)


@contextmanager
def registered_managed_child_tools(client):
    if not isinstance(client, HermesTransportClient):
        raise ValueError("委派工具需要运行通信客户端")
    names = ("create_managed_child", "dispatch_managed_child", "read_managed_child_result")
    if any(registry.get_entry(name) is not None for name in names):
        raise ValueError("委派工具已经注册")
    key = {"type": "string", "minLength": 1, "maxLength": 128}
    child = {"type": "string", "format": "uuid"}
    definitions = (
        (names[0], "创建受管子任务，返回运行编号", {"request_key": key, "description": {"type": "string", "minLength": 1, "maxLength": 2000}}, client.create_child),
        (names[1], "派发已获准的子任务，返回真实派发状态", {"child_id": child, "request_key": key}, client.dispatch_child),
        (names[2], "读取已登记的子任务结果及运行状态", {"child_id": child, "request_key": key}, client.child_result),
    )
    registered = []
    try:
        for name, description, properties, operation in definitions:
            def invoke(arguments, *, _operation=operation, _properties=properties, **kwargs):
                if not isinstance(arguments, dict) or set(arguments) != set(_properties):
                    raise ValueError("委派工具参数无效")
                return json.dumps(_operation(**arguments), ensure_ascii=False, allow_nan=False)
            schema = {"name": name, "description": description, "parameters": {"type": "object", "additionalProperties": False, "required": list(properties), "properties": properties}}
            registry.register(name=name, toolset="boss_domain", schema=schema, handler=invoke)
            registered.append(name)
        yield
    finally:
        for name in registered:
            registry.deregister(name)


@contextmanager
def registered_product_tools(client, *, bi_definitions):
    from hermes_domain_schema import FIELDS, MEETING_DRAFT_SCHEMA, MEETING_DRAFT_FIELDS, MEETING_DRAFT_PROPERTIES, MINUTES_DRAFT_SCHEMA
    name = "prepare_domain_intent"
    read_name = "read_meeting_context"
    receipt_name = "read_decision_receipt"
    draft_name = "save_meeting_draft"
    formal_draft_name = "meetingDraftSave"
    formal_confirm_name = "meetingConfirm"
    brief_prepare_name = "boss.meeting.brief.prepare"
    finish_tools = {"meetingCancel": "boss.meeting.cancel", "meetingHeld": "boss.meeting.held"}
    minutes_read_name = "read_minutes_context"
    minutes_draft_name = "save_minutes_draft"
    if any(registry.get_entry(item) is not None for item in (name, read_name, receipt_name, draft_name, formal_draft_name, formal_confirm_name, brief_prepare_name, minutes_read_name, minutes_draft_name, *finish_tools)):
        raise ValueError("业务意图工具已经注册")
    def prepare(arguments, **kwargs):
        if not isinstance(arguments, dict) or set(arguments) != {"action", "params", "request_key"}:
            raise ValueError("业务意图工具参数无效")
        return json.dumps(client.prepare_domain_intent(arguments["action"], arguments["params"], arguments["request_key"]), ensure_ascii=False, allow_nan=False)
    arrays = {"evidence_requirements", "related_event_ids", "source_refs"}
    schemas = []
    for action, fields in FIELDS.items():
        properties = {field: ({"type": "array", "items": {"type": "string"}} if field in arrays else {"type": "string", "minLength": 1}) for field in fields}
        schemas.append({"type": "object", "additionalProperties": False, "required": ["action", "params", "request_key"], "properties": {"action": {"const": action}, "params": {"type": "object", "additionalProperties": False, "required": sorted(fields), "properties": properties}, "request_key": {"type": "string", "pattern": "^[A-Za-z0-9_.-]{8,128}$"}}})
    schema = {"name": name, "description": "准备会议、纪要或交办的本人确认意图，返回待确认状态", "parameters": {"oneOf": schemas}}
    def read_meeting(arguments, **kwargs):
        if arguments != {}:
            raise ValueError("会议读取不接受模型参数")
        return json.dumps(client.read_meeting_context(str(uuid4())), ensure_ascii=False, allow_nan=False)
    def read_receipt(arguments, **kwargs):
        if not isinstance(arguments, dict) or set(arguments) != {"intent_id"}:
            raise ValueError("本人决定回执参数无效")
        return json.dumps(client.read_decision_receipt(arguments["intent_id"], str(uuid4())), ensure_ascii=False, allow_nan=False)
    def save_draft(arguments, **kwargs):
        if not isinstance(arguments, dict) or set(arguments) != {"request_key", "params"}:
            raise ValueError("会议草稿工具参数无效")
        return json.dumps(client.save_meeting_draft(arguments["params"], arguments["request_key"]), ensure_ascii=False, allow_nan=False)
    draft_schema = {"name": draft_name, "description": "保存待本人审阅的会议草稿，不确认会议或发送邀请", "parameters": {"type": "object", "additionalProperties": False, "required": ["request_key", "params"], "properties": {"request_key": {"type": "string", "pattern": "^[A-Za-z0-9_.-]{8,128}$"}, "params": MEETING_DRAFT_SCHEMA}}}
    def save_formal_draft(arguments, **kwargs):
        if not isinstance(arguments, dict) or set(arguments) != MEETING_DRAFT_FIELDS | {"client_request_id"}:
            raise ValueError("会议草稿工具参数无效")
        return json.dumps(client.save_formal_meeting_draft({key: arguments[key] for key in MEETING_DRAFT_FIELDS}, arguments["client_request_id"]), ensure_ascii=False, allow_nan=False)
    formal_draft_schema = {"name": formal_draft_name, "description": "保存当前会议的待审阅草稿，返回领域回执", "parameters": {"type": "object", "additionalProperties": False, "required": sorted(MEETING_DRAFT_FIELDS | {"client_request_id"}), "properties": {**MEETING_DRAFT_PROPERTIES, "client_request_id": {"type": "string", "pattern": "^[A-Za-z0-9_.-]{8,128}$"}}}}
    confirm_fields = FIELDS["boss.meeting.confirm"]
    def prepare_formal_confirm(arguments, **kwargs):
        if not isinstance(arguments, dict) or set(arguments) != confirm_fields | {"request_key"}:
            raise ValueError("会议确认意图参数无效")
        return json.dumps(client.prepare_domain_intent("boss.meeting.confirm", {key: arguments[key] for key in confirm_fields}, arguments["request_key"], tool_name=formal_confirm_name), ensure_ascii=False, allow_nan=False)
    formal_confirm_schema = {"name": formal_confirm_name, "description": "准备会议确认意图，等待本人明确决定；不会直接确认会议", "parameters": {"type": "object", "additionalProperties": False, "required": sorted(confirm_fields | {"request_key"}), "properties": {**{field: {"type": "string", "minLength": 1} for field in confirm_fields}, "request_key": {"type": "string", "pattern": "^[A-Za-z0-9_.-]{8,128}$"}}}}
    brief_fields = {"meeting_id", "meeting_version", "expected_version"}
    def prepare_brief(arguments, **kwargs):
        if not isinstance(arguments, dict) or set(arguments) != brief_fields | {"request_key"}:
            raise ValueError("会议简报参数无效")
        return json.dumps(client.prepare_meeting_brief({key: arguments[key] for key in brief_fields}, arguments["request_key"]), ensure_ascii=False, allow_nan=False)
    brief_schema = {"name": brief_prepare_name, "description": "使用本人明确选择的会议范围准备会前简报", "parameters": {"type": "object", "additionalProperties": False, "required": sorted(brief_fields | {"request_key"}), "properties": {**{field: {"type": "string", "minLength": 1} for field in brief_fields}, "request_key": {"type": "string", "pattern": "^[A-Za-z0-9_.-]{8,128}$"}}}}
    def finish_handler(name, action):
        fields = FIELDS[action]
        def prepare_finish(arguments, **kwargs):
            if not isinstance(arguments, dict) or set(arguments) != fields | {"request_key"}:
                raise ValueError("会议决定意图参数无效")
            return json.dumps(client.prepare_domain_intent(action, {key: arguments[key] for key in fields}, arguments["request_key"], tool_name=name), ensure_ascii=False, allow_nan=False)
        return prepare_finish
    def read_minutes(arguments, **kwargs):
        if arguments != {}:
            raise ValueError("纪要读取不接受模型参数")
        return json.dumps(client.minutes_tool(None, str(uuid4())), ensure_ascii=False, allow_nan=False)
    def save_minutes(arguments, **kwargs):
        if not isinstance(arguments, dict) or set(arguments) != {"request_key", "params"}:
            raise ValueError("纪要草稿工具参数无效")
        return json.dumps(client.minutes_tool(arguments["params"], arguments["request_key"]), ensure_ascii=False, allow_nan=False)
    minutes_schema = {"name": minutes_draft_name, "description": "保存带原文位置的纪要草稿，供本人审阅", "parameters": {"type": "object", "additionalProperties": False, "required": ["request_key", "params"], "properties": {"request_key": {"type": "string", "pattern": "^[A-Za-z0-9_.-]{8,128}$"}, "params": MINUTES_DRAFT_SCHEMA}}}
    with registered_document_tool(client), registered_evidence_tool(client), registered_meeting_read_tools(client), registered_input_request_tool(client), registered_context_tools(client), registered_artifact_tools(client), registered_workspace_file_tools(client), registered_bi_tools(client, bi_definitions), registered_managed_child_tools(client):
        registry.register(name=name, toolset="boss_domain", schema=schema, handler=prepare)
        try:
            registry.register(name=receipt_name, toolset="boss_domain", schema={"name": receipt_name, "description": "根据已准备的意图编号读取当前运行中已有的本人决定回执", "parameters": {"type": "object", "additionalProperties": False, "required": ["intent_id"], "properties": {"intent_id": {"type": "string", "minLength": 1, "maxLength": 128}}}}, handler=read_receipt)
            registry.register(name=read_name, toolset="boss_domain", schema={"name": read_name, "description": "读取当前获准会议草稿及本人确认所需参数", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}, handler=read_meeting)
            registry.register(name=draft_name, toolset="boss_domain", schema=draft_schema, handler=save_draft)
            registry.register(name=formal_draft_name, toolset="boss_domain", schema=formal_draft_schema, handler=save_formal_draft)
            registry.register(name=formal_confirm_name, toolset="boss_domain", schema=formal_confirm_schema, handler=prepare_formal_confirm)
            registry.register(name=brief_prepare_name, toolset="boss_domain", schema=brief_schema, handler=prepare_brief)
            for finish_name, finish_action in finish_tools.items():
                fields = FIELDS[finish_action]
                finish_schema = {"name": finish_name, "description": "准备会议本人决定意图，等待本人确认", "parameters": {"type": "object", "additionalProperties": False, "required": sorted(fields | {"request_key"}), "properties": {**{field: {"type": "string", "minLength": 1} for field in fields}, "request_key": {"type": "string", "pattern": "^[A-Za-z0-9_.-]{8,128}$"}}}}
                registry.register(name=finish_name, toolset="boss_domain", schema=finish_schema, handler=finish_handler(finish_name, finish_action))
            registry.register(name=minutes_read_name, toolset="boss_domain", schema={"name": minutes_read_name, "description": "读取当前会议纪要及本人确认参数", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}, handler=read_minutes)
            registry.register(name=minutes_draft_name, toolset="boss_domain", schema=minutes_schema, handler=save_minutes)
            yield
        finally:
            registry.deregister(receipt_name)
            registry.deregister(minutes_draft_name)
            registry.deregister(minutes_read_name)
            for finish_name in finish_tools:
                registry.deregister(finish_name)
            registry.deregister(formal_confirm_name)
            registry.deregister(brief_prepare_name)
            registry.deregister(formal_draft_name)
            registry.deregister(draft_name)
            registry.deregister(read_name)
            registry.deregister(name)
