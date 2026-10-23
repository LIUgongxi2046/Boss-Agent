import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "validation"))

from business import initial_materials
from boss_metrics import aggregate_metrics


def test_approved_details_independently_recompute_comparison():
    rows = initial_materials()["details"]
    base, current = [aggregate_metrics([r for r in rows if r["period"] == p])["metrics"] for p in ("BASE", "CURRENT")]
    assert (current["sales_quantity"][0] / base["sales_quantity"][0] - 1) * 100 == Decimal("20")
    assert (current["revenue"][0] / base["revenue"][0] - 1) * 100 == Decimal("20")
    assert (current["gross_profit"][0] / base["gross_profit"][0] - 1) * 100 == Decimal("-4")
    assert current["gross_margin"][0] - base["gross_margin"][0] == Decimal("-2")
    assert (current["gross_profit_per_tonne"][0] / base["gross_profit_per_tonne"][0] - 1) * 100 == Decimal("-20")
    assert aggregate_metrics([])["metrics"]["revenue"][0] is None
    assert aggregate_metrics([])["missing_fields"] == ["records"]
