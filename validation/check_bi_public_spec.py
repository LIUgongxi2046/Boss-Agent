from pathlib import Path

from openapi_spec_validator import validate
from ruamel.yaml import YAML

path = Path(__file__).resolve().parents[1] / "specs/product-bi.openapi.yaml"
loader = YAML(typ="safe")
loader.allow_duplicate_keys = False
validate(loader.load(path), base_uri=path.as_uri())
print("PASS product-bi.openapi.yaml")
