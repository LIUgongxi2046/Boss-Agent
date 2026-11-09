import argparse
import hashlib
import importlib.metadata as metadata
import sys
import tomllib
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


parser = argparse.ArgumentParser()
parser.add_argument("source", type=Path)
arguments = parser.parse_args()
source = arguments.source.resolve(strict=True)
project = tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8"))["project"]
distributions = list(metadata.distributions(path=[str(source)]))
if len(distributions) != 1 or canonicalize_name(distributions[0].metadata["Name"]) != "hermes-agent":
    raise ValueError("源码目录发行元数据不可核查")
distribution = distributions[0]
if distribution.version != project["version"]:
    raise ValueError("源码版本与发行元数据不一致")

environment = default_environment()
environment.update({"sys_platform": "linux", "platform_system": "Linux", "os_name": "posix",
                    "platform_machine": "x86_64", "python_version": "3.14", "python_full_version": "3.14.9"})
extras = ("all", "documents", "documents-pdf")


def identity(specification):
    requirement = Requirement(specification)
    return (canonicalize_name(requirement.name), tuple(sorted(requirement.extras)),
            str(requirement.specifier), requirement.url)


def applies(specification, extra):
    requirement = Requirement(specification)
    return requirement.marker is None or requirement.marker.evaluate({**environment, "extra": extra})


declared = {identity(item) for item in project["dependencies"] if applies(item, "")}
for extra in extras:
    declared.update(identity(item) for item in project["optional-dependencies"][extra] if applies(item, extra))
selected = {identity(item) for item in distribution.requires or []
            if any(applies(item, extra) for extra in ("", *extras))}
missing = declared - selected
unexpected = selected - declared
print("PYTHON", sys.version.split()[0])
print("METADATA_PATH", distribution._path)
print("METADATA_SHA256", hashlib.sha256((distribution._path / "PKG-INFO").read_bytes()).hexdigest())
print("PROJECT_DIRECT_REQUIREMENTS", len(declared))
print("METADATA_DIRECT_REQUIREMENTS", len(selected))
print("MISSING_REQUIREMENTS", len(missing))
print("UNEXPECTED_REQUIREMENTS", len(unexpected))
for item in sorted(missing):
    print("MISSING", item)
for item in sorted(unexpected):
    print("UNEXPECTED", item)
if missing or unexpected:
    raise SystemExit(1)
