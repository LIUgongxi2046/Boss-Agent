from pathlib import Path

from openapi_spec_validator import validate
from ruamel.yaml import YAML

ROOT = Path(__file__).resolve().parents[2]
path = ROOT / "specs/openapi.yaml"
loader = YAML(typ="safe")
loader.allow_duplicate_keys = False
document = loader.load(path)
validate(document, base_uri=path.as_uri())
print("PASS: OpenAPI3.1标准规范与YAML重复字段检查")
