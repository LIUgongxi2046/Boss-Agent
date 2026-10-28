import argparse
import json
import re
from decimal import Decimal
from pathlib import Path

import jsonlines


def verify(directory, reports, output):
    results = []
    cases = {}
    for path in reports:
        report = json.loads(path.read_text())
        for row in report.get("results", report.get("records", [])):
            cases[row["case"]] = row
    excluded = "".join(chr(value) for value in (28023, 22823, 38598, 22242))
    requirements = {
        "sector-F14": ["3360", "3210", "3320"], "sector-F15": ["49500"],
        "sector-F18": ["50100", "14.6"], "sector-F22": ["18000"],
        "public-baseline": ["2024", "2025"],
        "business-EGG": ["产蛋", "枚"], "business-MILK": ["产奶", "公斤"], "business-BEEF": ["生长", "公斤"],
        "morning-question": ["林知远", "12000", "8600", "26000", "48000"],
        "business-EGG-question": ["产蛋", "枚"], "business-MILK-question": ["产奶", "公斤"],
        "business-BEEF-question": ["生长", "公斤"], "document-discussion": ["2024", "2025"],
    }
    for name, row in cases.items():
        path = directory / "webui" / ("websocket_" + row["chat_id"] + ".jsonl")
        with jsonlines.open(path) as events:
            answers = [event["text"] for event in events if event.get("event") == "stream_end" and event.get("text")]
        if not answers:
            raise ValueError(name + " 尚无已保存的完整回答")
        answer = answers[-1]
        if excluded in answer:
            raise ValueError(name + " 回答没有采用仿真企业名称")
        normalized = answer.replace(",", "").replace("，", "").replace(" ", "")
        normalized = re.sub(r"([0-9]+(?:\.[0-9]+)?)万", lambda match: format(Decimal(match[1]) * 10000, "f"), normalized)
        for term in requirements.get(name, []):
            if term not in normalized:
                raise ValueError(name + " 回答尚未包含核查内容：" + term)
        results.append({"case": name, "run_id": row["run_id"], "chat_id": row["chat_id"],
                        "answer_characters": len(answer), "company_name_check": "PASSED", "business_assertions": requirements.get(name, [])})
    output.write_text(json.dumps({"results": results, "count": len(results)}, ensure_ascii=False, indent=2))
    print(json.dumps({"verified_answers": len(results), "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="核查已保存回答中的企业名称、业务数值与用途单位")
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--report", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verify(args.directory, args.report, args.output)
