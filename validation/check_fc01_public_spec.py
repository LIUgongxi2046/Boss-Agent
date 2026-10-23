from pathlib import Path

from openapi_spec_validator import validate
from ruamel.yaml import YAML

root = Path(__file__).resolve().parents[1]
loader = YAML(typ="safe")
loader.allow_duplicate_keys = False
for name in ("product-fc01.openapi.yaml", "product-runtime.openapi.yaml", "product-auth.openapi.yaml", "product-skills.openapi.yaml"):
    path = root / "specs" / name
    validate(loader.load(path), base_uri=path.as_uri())
    print("PASS " + name)
