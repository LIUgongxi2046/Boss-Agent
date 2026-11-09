import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "validation"))
sys.path.insert(0, sys.argv[1])

from tools.registry import registry
from hermes_tool_registration import registered_context_tools
from hermes_transport_client import HermesTransportClient


configuration = json.load(sys.stdin)
client = HermesTransportClient(configuration["endpoint"], configuration["capability"], configuration["run_id"])
try:
    with registered_context_tools(client):
        memory = json.loads(registry.get_entry("read_product_memory").handler({}))
        method = json.loads(registry.get_entry("read_enabled_method").handler({}))
        if memory["memory"] is None or method["reference"]["method"]["sop_id"] != "SOP03" or method["goal_revision"] != 1 or not method["content"]:
            raise ValueError("上下文读取结果无效")
    if registry.get_entry("read_product_memory") is not None or registry.get_entry("read_enabled_method") is not None:
        raise ValueError("上下文工具未注销")
finally:
    client.close()
