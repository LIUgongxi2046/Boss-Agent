import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "app/tests"))
from test_boss_material_cost_reports import reports_input

print(json.dumps(reports_input(), ensure_ascii=False))
