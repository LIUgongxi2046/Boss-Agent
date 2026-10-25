import importlib.util
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
DOMAIN = Path(os.environ["CONVERSATION_DOMAIN_ROOT"])
sys.path.insert(0, str(DOMAIN / "validation"))
spec = importlib.util.spec_from_file_location("conversation_agent", ROOT / "validation/conversation_agent/__init__.py",
    submodule_search_locations=[str(ROOT / "validation/conversation_agent")])
module = importlib.util.module_from_spec(spec)
sys.modules["conversation_agent"] = module
spec.loader.exec_module(module)

native_spec = importlib.util.spec_from_file_location("fc03_agent.native", ROOT / "validation/fc03_agent/native.py")
native_module = importlib.util.module_from_spec(native_spec)
sys.modules["fc03_agent.native"] = native_module
native_spec.loader.exec_module(native_module)


def prohibit_network(event, args):
    if event == "socket.connect":
        raise PermissionError("会话实际SDK检查禁止外部连接")


sys.addaudithook(prohibit_network)
