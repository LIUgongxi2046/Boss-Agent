import hashlib
import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator
from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {
    "functions": ("FR-", 32, ["id", "acceptance_ids", "given", "when", "then", "specific_error"]),
    "common_errors": ("E", 6, ["id", "given", "when", "then"]),
    "administration": ("AD", 16, ["id", "actions", "consumer"]),
    "nonfunctional": ("NFR-", 12, ["id", "assertion"]),
}


def check():
    source = ROOT / "docs/PRD.md"
    inventory_path = ROOT / "specs/acceptance-cases.json"
    inventory = json.loads(inventory_path.read_text())
    schema = {
        "type": "object", "required": [*REQUIRED, "expansion", "execution_status", "evidence_required"],
        "properties": {
            name: {"type": "array", "items": {
                "type": "object", "required": fields,
                "properties": {field: {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}}
                               if field in {"acceptance_ids", "then", "actions"} else {"type": "string", "minLength": 1}
                               for field in fields},
            }} for name, (_, _, fields) in REQUIRED.items()
        },
    }
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(inventory)
    texts = [token.content for token in MarkdownIt().parse(source.read_text()) if token.type == "inline"]
    for name, (prefix, count, _) in REQUIRED.items():
        expected = {prefix + str(index).zfill(2) for index in range(1, count + 1)}
        identifiers = [item["id"] for item in inventory[name]]
        assert len(identifiers) == len(set(identifiers)) == count, name
        assert set(identifiers) == expected, name
        observed = {match for text in texts for match in re.findall(r"\b" + re.escape(prefix) + r"\d{2}\b", text)}
        assert expected <= observed, name
    acceptance_ids = [identifier for item in inventory["functions"] for identifier in item["acceptance_ids"]]
    expected_acceptance = {"AC-" + str(index).zfill(2) + "-" + state for index in range(1, 33) for state in ("S", "E")}
    assert len(acceptance_ids) == len(set(acceptance_ids)) == 64
    assert set(acceptance_ids) == expected_acceptance
    observed_acceptance = {match for text in texts for match in re.findall(r"\bAC-\d{2}-[SE]\b", text)}
    assert expected_acceptance == observed_acceptance
    for item in inventory["functions"]:
        assert set(item["acceptance_ids"]) == {"AC-" + item["id"][3:] + "-" + state for state in ("S", "E")}
    assert inventory["expansion"]["per_function"] == ["success", "specific_error", "E01", "E02", "E03", "E04", "E05", "E06"]
    assert inventory["expansion"]["per_administration"] == ["legitimate", "failure", "inactive", "unauthorized"]
    assert inventory["execution_status"] == "NOT_RUN"
    assert len(inventory["evidence_required"]) == len(set(inventory["evidence_required"]))
    return {
        "status": "PASS_INVENTORY_ONLY", "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "inventory_sha256": hashlib.sha256(inventory_path.read_bytes()).hexdigest(),
        "functions": 32, "acceptance_ids": 64, "inherited_error_scenarios": 192,
        "administration": 16, "administration_states": 64, "nonfunctional": 12,
        "planned_scenarios": 332, "business_execution": "NOT_RUN", "semantic_review": "PENDING",
        "full_A09_accepted": False,
    }


if __name__ == "__main__":
    result = check()
    output = ROOT / "evidence/T09/w3-20261023/inventory.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))
