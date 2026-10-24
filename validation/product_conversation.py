from aiohttp import web
from nanobot.command.builtin import builtin_command_starts_agent_turn

from business import require
from conversation_agent import ConversationReadTool
from conversation_agent.native import NativeConversationAgent
from conversation_agent.queries import ConversationQueryTool
from fc02_agent import Fc02Tool
from runtime_sop_read_tools import BossWorkspaceReadTool


class ProductConversation(NativeConversationAgent):
    def registry_tool(self, name, ordinary):
        require(ordinary is not None and ordinary.name == name, "当前配置没有启用所需会话工具", web.HTTPConflict)
        if name == "query_metrics":
            protected = ConversationQueryTool(Fc02Tool(self.store, self.query_context, name), self.scope)
            require(isinstance(protected, ConversationReadTool) and protected.scope is self.scope
                    and protected.delegate.store.path.resolve() == self.store.path.resolve(),
                    "当前查询缺少同库会话范围保护", web.HTTPForbidden)
            return protected
        if name == "bossWorkspaceRead":
            require(isinstance(ordinary, BossWorkspaceReadTool), "一般会话需要启用正式工作投影模式", web.HTTPConflict)
            delegate = ordinary
        else:
            delegate = next(tool for tool in self.delegates if tool.name == name)
        return ConversationReadTool(delegate, self.scope)

    async def native_context(self, request):
        if not builtin_command_starts_agent_turn(request.original_user_text or ""):
            return None
        return await super().native_context(request)
