from pathlib import Path
import os
import shutil
import sys
import tempfile

from setuptools import find_namespace_packages, find_packages, setup
from setuptools.command.build import build
from setuptools.command.build_py import build_py
from setuptools.command.egg_info import egg_info


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from desktop_manifest import validate_desktop_manifest

VALIDATION = ROOT / "validation"
PACKAGE = "boss_agent_runtime"
BUILD_PARENT = Path(os.environ.get("BOSS_PRODUCT_BUILD_ROOT", str(ROOT / ".work" / "upgrade2" / "u2-01"))).resolve()
BUILD_PARENT.mkdir(parents=True, exist_ok=True)
BUILD_ROOT = Path(tempfile.mkdtemp(prefix="product-alt-build-", dir=BUILD_PARENT))
EGG_ROOT = Path(tempfile.mkdtemp(prefix="product-alt-egg-info-", dir=BUILD_PARENT))
RESOURCE_JSON = (
    "agent_schedule_history_schema.json",
    "agent_artifact_schema.json",
    "agent_artifact_source_history_schema.json",
    "agent_run_recovery_schema.json",
    "agent_run_resume_schema.json",
    "agent_source_history_schema.json",
)
ENGINE_MANIFEST = ROOT / "hermes-engine-resources.txt"
if ENGINE_MANIFEST.is_symlink():
    raise RuntimeError("引擎资源清单不能是符号链接")
ENGINE_FILES = tuple(line.strip() for line in ENGINE_MANIFEST.read_text(encoding="utf-8").splitlines() if line.strip())
SPEC_MANIFEST = ROOT / "specs-resources.txt"
if SPEC_MANIFEST.is_symlink():
    raise RuntimeError("规格清单不能是符号链接")
SPEC_FILES = tuple(
    line.strip()
    for line in SPEC_MANIFEST.read_text(encoding="utf-8").splitlines()
    if line.strip()
)
SOURCE_MANIFEST = ROOT / "source-python-resources.txt"
if SOURCE_MANIFEST.is_symlink():
    raise RuntimeError("源码清单不能是符号链接")
SOURCE_FILES = tuple(
    line.strip()
    for line in SOURCE_MANIFEST.read_text(encoding="utf-8").splitlines()
    if line.strip()
)
AGENT_SKILLS_MANIFEST = ROOT / "agent-skills-resources.txt"
if AGENT_SKILLS_MANIFEST.is_symlink():
    raise RuntimeError("方法资源清单不能是符号链接")
AGENT_SKILLS_FILES = tuple(
    line.strip()
    for line in AGENT_SKILLS_MANIFEST.read_text(encoding="utf-8").splitlines()
    if line.strip()
)
DESKTOP_MANIFEST = ROOT / "desktop-resources.txt"
if DESKTOP_MANIFEST.is_symlink():
    raise RuntimeError("桌面资源清单不能是符号链接")
DESKTOP_FILES = tuple(
    line.strip()
    for line in DESKTOP_MANIFEST.read_text(encoding="utf-8").splitlines()
    if line.strip()
)
FRONTEND_SCHEMA_PAIRS = {
    "app/webui/agent_artifact_source_history_schema.local.json": "validation/agent_artifact_source_history_schema.json",
    "app/webui/agent_run_resume_schema.local.json": "validation/agent_run_resume_schema.json",
    "app/webui/agent_source_history_schema.local.json": "validation/agent_source_history_schema.json",
}
PREFIX_PACKAGES = find_packages(where=str(VALIDATION)) + find_namespace_packages(
    where=str(VALIDATION), include=["sop_write_tools", "sop_write_tools.*"]
)
DEV_ONLY_MODULES = (
    "bind_saved_checks.py",
    "capture_reuse.py",
    "capture_validation.py",
    "check_historical_receipts.py",
    "fc03_candidate_inventory.py",
)


def assert_controlled_resources():
    validate_desktop_manifest(DESKTOP_FILES)
    if len(ENGINE_FILES) != len(set(ENGINE_FILES)):
        raise RuntimeError("引擎资源清单包含重复项")
    for name in ENGINE_FILES:
        source = ROOT / name
        if source.is_symlink() or not source.is_file():
            raise RuntimeError("引擎资源必须是受控普通文件")
        if name not in SOURCE_FILES and name not in {f"validation/{item}" for item in RESOURCE_JSON}:
            raise RuntimeError("引擎资源未列入产品源码或资源清单")
    specs = ROOT / "specs"
    actual_specs = {source.name for source in specs.iterdir()} if specs.is_dir() else set()
    if actual_specs != set(SPEC_FILES) or len(SPEC_FILES) != len(set(SPEC_FILES)):
        raise RuntimeError("规格目录与受控清单不一致")
    for name in SPEC_FILES:
        if (specs / name).is_symlink():
            raise RuntimeError("规格文件不能是符号链接")
    actual_sources = set()
    for source in VALIDATION.rglob("*.py"):
        relative = source.relative_to(VALIDATION)
        if any(part in {".work", ".venv", "__pycache__"} for part in relative.parts):
            continue
        if source.is_symlink():
            raise RuntimeError("源码清单包含符号链接")
        actual_sources.add((Path("validation") / relative).as_posix())
    if actual_sources != set(SOURCE_FILES) or len(SOURCE_FILES) != len(set(SOURCE_FILES)):
        raise RuntimeError("源码目录与受控清单不一致")
    for local_name, validation_name in FRONTEND_SCHEMA_PAIRS.items():
        local_schema = ROOT / local_name
        validation_schema = ROOT / validation_name
        if local_schema.is_symlink() or validation_schema.is_symlink():
            raise RuntimeError("前端 Schema 副本不能是符号链接")
        if local_schema.read_bytes() != validation_schema.read_bytes():
            raise RuntimeError("前端 Schema 与 validation 副本不一致")
    actual_skills = set()
    for source in (ROOT / "agent" / "skills").rglob("*"):
        relative = source.relative_to(ROOT).as_posix()
        if source.is_symlink():
            raise RuntimeError("方法资源不能是符号链接")
        if source.is_file():
            actual_skills.add(relative)
    if actual_skills != set(AGENT_SKILLS_FILES) or len(AGENT_SKILLS_FILES) != len(set(AGENT_SKILLS_FILES)):
        raise RuntimeError("方法资源目录与受控清单不一致")
    for name in DESKTOP_FILES:
        source = ROOT / name
        if source.is_symlink() or not source.is_file():
            raise RuntimeError("桌面清单文件必须是受控普通文件")
    simulation = ROOT / "data" / "simulation"
    allowed = {simulation / "supply-quality-v1.yaml"}
    if not simulation.is_dir() or {source for source in simulation.iterdir()} != allowed:
        raise RuntimeError("模拟资料目录与受控清单不一致")
    page = ROOT / "Boss-Agent-Desktop-Complete-v7" / "meta" / "页面配置.json"
    if page.is_symlink() or not page.is_file():
        raise RuntimeError("页面配置缺失或不是普通文件")


class ProductBuild(build):
    def initialize_options(self):
        super().initialize_options()
        self.build_base = str(BUILD_ROOT)


class ProductEggInfo(egg_info):
    def initialize_options(self):
        super().initialize_options()
        self.egg_base = str(EGG_ROOT)


class ProductBuildPy(build_py):
    def run(self):
        assert_controlled_resources()
        super().run()
        build_lib = Path(self.build_lib)
        self._copy_specs(build_lib)
        self._copy_page(build_lib)
        self._copy_simulation(build_lib)
        self._copy_agent_skills(build_lib)
        self._copy_desktop(build_lib)
        self._copy_frontend(build_lib)
        self._copy_licenses(build_lib)
        for name in DEV_ONLY_MODULES:
            path = build_lib / PACKAGE / name
            if path.is_symlink() or not path.is_file():
                raise RuntimeError("开发检查文件缺失或不是普通文件")
            path.unlink()

    def _copy_specs(self, build_lib):
        specs = ROOT / "specs"
        if not specs.is_dir():
            raise RuntimeError("规格目录不存在")
        actual = {source.name for source in specs.iterdir()}
        if actual != set(SPEC_FILES) or len(SPEC_FILES) != len(set(SPEC_FILES)):
            raise RuntimeError("规格目录与受控清单不一致")
        for name in SPEC_FILES:
            source = specs / name
            if source.is_symlink() or not source.is_file():
                raise RuntimeError("规格文件必须是受控普通文件")
            self._copy(source, build_lib / "specs" / name)

    def _copy_page(self, build_lib):
        page = ROOT / "Boss-Agent-Desktop-Complete-v7" / "meta" / "页面配置.json"
        if page.is_symlink() or not page.is_file():
            raise RuntimeError("页面配置不存在或不是普通文件")
        self._copy(page, build_lib / "Boss-Agent-Desktop-Complete-v7" / "meta" / page.name)

    def _copy_simulation(self, build_lib):
        simulation = ROOT / "data" / "simulation"
        allowed = {simulation / "supply-quality-v1.yaml"}
        for source in simulation.iterdir():
            if source not in allowed or source.is_symlink() or not source.is_file():
                raise RuntimeError("模拟资料目录包含未允许的内容")
        for source in allowed:
            if source.is_symlink() or not source.is_file():
                raise RuntimeError("模拟定义不存在或不是普通文件")
            self._copy(source, build_lib / "data" / "simulation" / source.name)

    def _copy_frontend(self, build_lib):
        if os.environ.get("BOSS_PRODUCT_FRONTEND_DIST") is not None or os.environ.get("BOSS_PRODUCT_FRONTEND_MANIFEST") is not None:
            raise RuntimeError("前端正式使用关闭：没有由实际构建产生且对应当前源码与未提交内容的前端来源清单")

    def _copy_agent_skills(self, build_lib):
        root = ROOT / "agent" / "skills"
        for name in AGENT_SKILLS_FILES:
            source = ROOT / name
            if source.is_symlink() or not source.is_file():
                raise RuntimeError("方法资源必须是受控普通文件")
            self._copy(source, build_lib / "agent" / "skills" / source.relative_to(root))

    def _copy_desktop(self, build_lib):
        for name in DESKTOP_FILES:
            source = ROOT / name
            if source.is_symlink() or not source.is_file():
                raise RuntimeError("桌面资源必须是受控普通文件")
            self._copy(source, build_lib / PACKAGE / "desktop" / source.relative_to(ROOT / "validation" / "desktop"))

    def _copy_licenses(self, build_lib):
        for name in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md", "COMMERCIAL_LICENSE.md", "TRADEMARKS.md", "evidence/T02/inventory/LICENSE", "evidence/T02/inventory/THIRD_PARTY_NOTICES.md"):
            source = ROOT / name
            if source.is_symlink() or not source.is_file():
                raise RuntimeError("许可文件必须是受控普通文件")
            self._copy(source, build_lib / PACKAGE / "licenses" / name)

    @staticmethod
    def _copy(source, destination):
        if source.is_symlink():
            raise RuntimeError("构建资源不能是符号链接")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)


setup(
    name="boss-agent-product-runtime",
    package_dir={PACKAGE: str(VALIDATION)},
    packages=[PACKAGE] + [PACKAGE + "." + name for name in PREFIX_PACKAGES],
    package_data={PACKAGE: ["migrations/*.sql", *RESOURCE_JSON]},
    cmdclass={"build": ProductBuild, "build_py": ProductBuildPy, "egg_info": ProductEggInfo},
)
