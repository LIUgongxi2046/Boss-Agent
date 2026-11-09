import importlib.metadata as metadata
import json

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


inventory = {}
for distribution in metadata.distributions():
    name = canonicalize_name(distribution.metadata["Name"])
    if name in inventory:
        raise ValueError("发行包重复：" + name)
    inventory[name] = distribution

pending = [("hermes-agent", ("all", "documents", "documents-pdf"))]
visited = set()
missing = []
while pending:
    name, extras = pending.pop()
    key = (name, extras)
    if key in visited:
        continue
    visited.add(key)
    distribution = inventory.get(name)
    if distribution is None:
        missing.append(name)
        continue
    for specification in distribution.requires or []:
        requirement = Requirement(specification)
        if requirement.marker and not any(requirement.marker.evaluate({"extra": extra}) for extra in ("", *extras)):
            continue
        dependency = canonicalize_name(requirement.name)
        installed = inventory.get(dependency)
        if installed is None or not requirement.specifier.contains(installed.version, prereleases=True):
            missing.append(specification)
            continue
        pending.append((dependency, tuple(sorted(requirement.extras))))

result = {"packages": len({name for name, _ in visited}), "missing_or_incompatible": sorted(set(missing))}
print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
if missing:
    raise ValueError("Hermes 依赖检查未通过")
