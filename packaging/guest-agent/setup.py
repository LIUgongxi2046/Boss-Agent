from pathlib import Path
import os
import tempfile

from setuptools import setup
from setuptools.command.build import build
from setuptools.command.egg_info import egg_info


root = Path(__file__).resolve().parents[2]
build_parent = Path(os.environ.get("BOSS_GUEST_BUILD_ROOT", str(root / ".work" / "upgrade2" / "u2-03"))).resolve()
build_parent.mkdir(parents=True, exist_ok=True)
build_root = Path(tempfile.mkdtemp(prefix="guest-build-", dir=build_parent))
egg_root = Path(tempfile.mkdtemp(prefix="guest-egg-", dir=build_parent))


class GuestBuild(build):
    def initialize_options(self):
        super().initialize_options()
        self.build_base = str(build_root)


class GuestEggInfo(egg_info):
    def initialize_options(self):
        super().initialize_options()
        self.egg_base = str(egg_root)


setup(
    name="boss-agent-guest-runtime",
    version="0.2.59",
    package_dir={"": str(root / "validation")},
    py_modules=[
        "hermes_guest_agent",
        "hermes_guest_control",
        "hermes_guest_cpu_guard",
        "hermes_guest_identity",
        "hermes_guest_proxy",
        "hermes_guest_slice",
        "hermes_guest_systemd",
        "hermes_guest_unit_reference",
        "hermes_guest_workspace_directory",
        "hermes_guest_workspace_guard",
        "hermes_guest_workspace_service",
        "hermes_vm_channel",
        "hermes_vm_credentials",
    ],
    python_requires=">=3.14,<3.15",
    install_requires=["aiohttp==3.14.5", "cryptography==50.0.2", "dbus-next==0.2.3"],
    cmdclass={"build": GuestBuild, "egg_info": GuestEggInfo},
)
