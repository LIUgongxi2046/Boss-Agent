import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DESIGN = ROOT / "Boss-Agent-Desktop-Complete-v6"
PROMPTS = ROOT / "design/T03/prompts-desktop"


def check():
    pages = json.loads((DESIGN / "meta/页面配置.json").read_text())
    states = json.loads((DESIGN / "meta/v6-状态关联.json").read_text())
    architecture = json.loads((ROOT / "specs/hld-72-page-map.json").read_text())
    services = json.loads((ROOT / "specs/page-service-map.json").read_text())
    assert len(pages) == 72
    assert set(pages) == {row["page_id"] for row in architecture["pages"]}
    assert set(pages) == {row["page_id"] for row in services["pages"]}
    assert len(states) == 561
    assert len({(row["page_id"], row["state_id"]) for row in states}) == 561
    assert len({row["page_id"] for row in states}) == 51
    for page_id, page in pages.items():
        assert (DESIGN / "pages" / f"{page_id}-{page['title']}.html").is_file(), page_id
    for row in states:
        assert row["page_id"] in pages
        assert (DESIGN / row["design_entry"].split("?", 1)[0]).is_file(), row["design_entry"]
        assert (PROMPTS / row["source"]).is_file(), row["source"]
    with (DESIGN / "meta/v6-完整素材清单.csv").open(encoding="utf-8-sig", newline="") as handle:
        assets = list(csv.DictReader(handle))
    assert assets
    for row in assets:
        asset = (DESIGN / row["path"]).resolve(strict=True)
        assert asset.is_relative_to(DESIGN.resolve()), row["path"]
        assert asset.stat().st_size == int(row["bytes"]), row["path"]
        assert hashlib.sha256(asset.read_bytes()).hexdigest() == row["sha256"], row["path"]
        assert row["license"].strip(), row["path"]
    return {
        "page_count": len(pages), "state_count": len(states),
        "asset_count": len(assets), "asset_hashes": "PASS",
        "visual_acceptance": "NOT_RUN", "business_acceptance": "NOT_RUN",
        "license_review": "NOT_RUN",
    }


if __name__ == "__main__":
    print(json.dumps(check(), ensure_ascii=False, indent=2))
