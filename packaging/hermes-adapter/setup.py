from pathlib import Path
import os
import shutil
import tempfile

from setuptools import setup
from setuptools.command.build import build
from setuptools.command.build_py import build_py
from setuptools.command.egg_info import egg_info


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "validation"
MANIFEST = ROOT / "hermes-engine-resources.txt"
EXPECTED = {
    "hermes_engine_entry.py", "hermes_transport_client.py", "hermes_tool_names.py",
    "hermes_tool_registration.py", "hermes_domain_schema.py", "hermes_meeting_brief_public.py",
    "agent_artifact_hermes.py", "agent_artifact_schema.json", "hermes_process_anchor.py",
    "hermes_start_gate.py", "hermes_parent_guard.py", "hermes_resource_exec.py",
}
if MANIFEST.is_symlink() or not MANIFEST.is_file():
    raise RuntimeError("引擎资源清单必须是普通文件")
entries = [line.strip() for line in MANIFEST.read_text(encoding="utf-8").splitlines() if line.strip()]
if len(entries) != len(set(entries)) or set(entries) != {f"validation/{name}" for name in EXPECTED}:
    raise RuntimeError("引擎资源清单不完整或包含重复项")
for name in EXPECTED:
    source = SOURCE / name
    if source.is_symlink() or not source.is_file():
        raise RuntimeError(f"引擎资源必须是普通文件：{name}")

BUILD_PARENT = Path(os.environ.get("BOSS_HERMES_ADAPTER_BUILD_ROOT", str(ROOT / ".work" / "upgrade2" / "u2-01"))).resolve()
BUILD_PARENT.mkdir(parents=True, exist_ok=True)
BUILD_ROOT = Path(tempfile.mkdtemp(prefix="hermes-adapter-build-", dir=BUILD_PARENT))
EGG_ROOT = Path(tempfile.mkdtemp(prefix="hermes-adapter-egg-", dir=BUILD_PARENT))


class AdapterBuild(build):
    def initialize_options(self):
        super().initialize_options()
        self.build_base = str(BUILD_ROOT)


class AdapterEggInfo(egg_info):
    def initialize_options(self):
        super().initialize_options()
        self.egg_base = str(EGG_ROOT)


class AdapterBuildPy(build_py):
    def run(self):
        super().run()
        source = SOURCE / "agent_artifact_schema.json"
        if source.is_symlink() or not source.is_file():
            raise RuntimeError("成果 Schema 必须是普通文件")
        shutil.copyfile(source, Path(self.build_lib) / source.name)
        for name in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md", "COMMERCIAL_LICENSE.md", "TRADEMARKS.md", "evidence/T02/inventory/LICENSE", "evidence/T02/inventory/THIRD_PARTY_NOTICES.md"):
            license_file = ROOT / name
            if license_file.is_symlink() or not license_file.is_file():
                raise RuntimeError("许可文件必须是普通文件")
            destination = Path(self.build_lib) / "boss_agent_hermes_adapter_licenses" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(license_file, destination)


setup(
    py_modules=sorted(Path(name).stem for name in EXPECTED if name.endswith(".py")),
    package_dir={"": str(SOURCE)},
    cmdclass={"build": AdapterBuild, "build_py": AdapterBuildPy, "egg_info": AdapterEggInfo},
)
