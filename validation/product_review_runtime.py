from boss_command_api import BossCommandAPI
from boss_execution_scope import NAMESPACE
from runtime_sop_read_tools import SOP_WORKSPACE_PROJECTIONS


def configure_review_runtime(runtime):
    if NAMESPACE != "ui-check":
        raise ValueError("验收配置仅适用于本机模拟资料")
    state = runtime.read()
    if state["current"]["version"] != "1" or state["draft"] is not None:
        return
    api = BossCommandAPI(runtime.store, runtime)

    def execute(action, **payload):
        status, result = api.execute("MAINTAINER", "boss.runtime." + action,
            {"client_request_id": "user-review-runtime-" + action, **payload})
        if status != 200:
            raise RuntimeError(f"验收运行配置{action}失败：{status}")
        return result

    draft = execute("save", expected_version="0", values={
        "max_tool_rounds": 12, "max_output_tokens": 4096,
        "tool_scope": sorted(runtime.available),
        "workspace_read_mode": "WORKSPACE_PROJECTIONS",
        "workspace_projections": sorted(SOP_WORKSPACE_PROJECTIONS),
    })
    checked = execute("validate", expected_version=draft["version"], expected_content_sha256=draft["content_sha256"])
    execute("activate", expected_version=checked["version"], expected_content_sha256=checked["content_sha256"],
            expected_active_version=state["current"]["version"])
