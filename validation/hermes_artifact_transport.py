from aiohttp import web

from agent_artifact_api import HermesMeetingBriefTool
from agent_artifacts import ArtifactPreparation
from role_channel import RoleChannel


class HermesArtifactTransport:
    def __init__(self, preparation, request, channel):
        if not isinstance(preparation, ArtifactPreparation) or not isinstance(request, web.Request) or not isinstance(channel, RoleChannel):
            raise ValueError("成果通信需要运行服务与实际产品请求")
        if channel.boss_commands is None or channel.boss_commands.store.path.resolve() != preparation.store.path.resolve() or channel.gateway.session_manager is not preparation.scope_service.sources.sessions:
            raise ValueError("成果身份与运行服务不属于同一环境")
        self.preparation, self.request, self.channel = preparation, request, channel
        self.tool = HermesMeetingBriefTool(preparation)

    def authorize(self):
        self.channel.require_run_api_role(self.request)
        with self.preparation.store.connect() as db:
            db.execute("BEGIN")
            row = db.execute("SELECT conversation_id FROM agent_runs WHERE run_id=?", (self.preparation.run_gate.config.run_id,)).fetchone()
            if row is None or not isinstance(row[0], str) or not row[0]:
                raise ValueError("成果运行会话不可核查")
            self.channel.require_run_subscription(self.request, row[0])

    def require_ready(self):
        raise web.HTTPServiceUnavailable(text="成果工作区隔离及本人授权保护尚未完成")

    def execute(self, payload):
        return self.tool.execute_authenticated(self.request, self.channel, payload)

    def execute_runtime_brief(self, payload, skill):
        from agent_artifact_meeting_brief import RuntimeMeetingBriefPreparation
        self.authorize()
        self.require_ready()
        service = RuntimeMeetingBriefPreparation(self.preparation, skill)
        result = service.create(self.preparation.run_gate.config.run_id, payload["source_ids"],
            request_key=payload["request_key"], format_name=payload["format_name"],
            expected_goal_revision=payload["expected_goal_revision"], meeting_id=payload["meeting_id"],
            meeting_version=payload["meeting_version"], sections=payload["sections"],
            previous_artifact_id=payload.get("previous_artifact_id"), expected_version=payload.get("expected_version"))
        self.authorize()
        self.require_ready()
        return {key: value for key, value in result.items() if key != "storage_key"}
