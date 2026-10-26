from boss_agent_read_tools import BossResearchSourcesTool
from runtime_assignment_source_tool import BossAssignmentSourcesReadTool
from runtime_owner_read_tools import BossTodayReadTool, BossOwnerPlansReadTool
from runtime_page_read_tools import BossDashboardReadTool, BossMeetingsReadTool, BossEvidenceReadTool
from runtime_sop_read_tools import BossTasksReadTool, BossCalendarConflictReadTool, BossCalendarSharePreviewTool
from runtime_sector_read import BossSectorReadTool


def product_read_tools(store, pages, observation_sink=None):
    return [BossResearchSourcesTool(store, "BOSS", observation_sink=observation_sink),
        BossTodayReadTool(store, "BOSS"), BossOwnerPlansReadTool(store, "BOSS"), BossAssignmentSourcesReadTool(store, "BOSS"),
        BossDashboardReadTool(pages, "BOSS"), BossMeetingsReadTool(pages, "BOSS"), BossEvidenceReadTool(pages, "BOSS"),
        BossTasksReadTool(pages, "BOSS"), BossCalendarConflictReadTool(pages, "BOSS"), BossCalendarSharePreviewTool(pages, "BOSS"),
        BossSectorReadTool(store, "BOSS")]
