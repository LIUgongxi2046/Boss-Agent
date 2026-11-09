import argparse
import hashlib
import importlib.util
import zipfile
from pathlib import Path


parser = argparse.ArgumentParser()
parser.add_argument("wheel", type=Path)
wheel = parser.parse_args().wheel
modules = ("hermes_guest_agent", "hermes_guest_control", "hermes_guest_cpu_guard", "hermes_guest_identity", "hermes_guest_proxy",
           "hermes_guest_systemd", "hermes_vm_channel", "hermes_vm_credentials")
with zipfile.ZipFile(wheel) as archive:
    if len(archive.namelist()) != len(set(archive.namelist())):
        raise ValueError("客体制品包含重复文件")
    for name in modules:
        spec = importlib.util.find_spec(name)
        if spec is None or spec.origin is None:
            raise ValueError("客体安装模块不存在")
        installed = Path(spec.origin)
        if installed.is_symlink() or installed.read_bytes() != archive.read(name + ".py"):
            raise ValueError("客体安装模块与制品不一致")
print("GUEST_MODULES_MATCH", len(modules), flush=True)
print("GUEST_WHEEL_SHA256", hashlib.sha256(wheel.read_bytes()).hexdigest(), flush=True)
