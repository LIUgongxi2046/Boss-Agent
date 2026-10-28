import argparse
import hashlib
import json
from io import BytesIO
from pathlib import Path

import httpx
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]


def verify(output):
    baseline = json.loads((ROOT / "specs/public-business-baseline.json").read_text())
    response = httpx.get(baseline["source_url"], timeout=90, follow_redirects=True)
    response.raise_for_status()
    reader = PdfReader(BytesIO(response.content))
    normalized = "".join(reader.pages[baseline["financial_page"]].extract_text().split()).replace(",", "")
    values = [value for group in [baseline["consolidated"], *baseline["products"]]
              for year in ("2024", "2025") for value in group[year].values()]
    for value in values:
        if value not in normalized:
            raise ValueError("公开报告金额核查失败：" + value)
    volume_pages = {key: baseline["volume_page"] for key in ("total", "internal", "external", "poultry", "pig", "aquatic", "ruminant_and_other")}
    volume_pages["overseas_external"] = 17
    volume_texts = {index: "".join(reader.pages[index].extract_text().split()).replace(",", "") for index in set(volume_pages.values())}
    for key, index in volume_pages.items():
        if baseline["feed_sales_2025"][key] not in volume_texts[index]:
            raise ValueError("公开报告销量核查失败：" + key)
    result = {"source_url": baseline["source_url"], "sha256": hashlib.sha256(response.content).hexdigest(),
              "pages": len(reader.pages), "financial_page": baseline["financial_page"],
              "page_index_base": 0, "volume_pages": volume_pages,
              "verified_amounts": len(values), "verified_volumes": len(volume_pages),
              "baseline_sha256": hashlib.sha256((ROOT / "specs/public-business-baseline.json").read_bytes()).hexdigest()}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="抓取公开报告并核查匿名经营基准")
    parser.add_argument("--output", type=Path, default=ROOT / ".work/simulation-20261028/public-source.json")
    verify(parser.parse_args().output)
