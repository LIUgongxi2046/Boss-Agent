import argparse
import hashlib
import zipfile
from pathlib import Path


FILES = (
    "agent_artifact_hermes.py", "agent_artifact_schema.json", "hermes_domain_schema.py",
    "hermes_engine_entry.py", "hermes_meeting_brief_public.py", "hermes_parent_guard.py",
    "hermes_process_anchor.py", "hermes_resource_exec.py", "hermes_start_gate.py",
    "hermes_tool_names.py", "hermes_tool_registration.py", "hermes_transport_client.py",
)
parser = argparse.ArgumentParser()
parser.add_argument("wheel", type=Path)
parser.add_argument("directory", type=Path)
arguments = parser.parse_args()
with zipfile.ZipFile(arguments.wheel) as archive:
    for name in FILES:
        if archive.read(name) != (arguments.directory / name).read_bytes():
            raise ValueError("引擎适配文件不一致：" + name)
with arguments.wheel.open("rb") as stream:
    digest = hashlib.file_digest(stream, "sha256").hexdigest()
print("HERMES_ADAPTER_FILES_MATCH", len(FILES), digest, flush=True)
