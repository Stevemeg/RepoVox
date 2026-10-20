"""Offline $10 worksheet. Not a quote, budget grant or AWS client."""

import json
import math
from pathlib import Path

from tools.phase2_cloud_retention_model import require


def assess(plan):
    require(plan["version"] == "aws-synthetic-test-budget-1.0", "budget_version")
    require(
        plan["ceiling_usd"] == 10 and plan["active_hours"] == 4 and plan["planning_hours"] == 6,
        "owner_budget_boundary",
    )
    known, unknown = {}, []
    require(len({r["name"] for r in plan["charges"]}) == len(plan["charges"]), "duplicate_cost")
    for row in plan["charges"]:
        quantity, price = row["quantity"], row["reference_usd_per_unit"]
        if quantity is None or price is None:
            unknown.append(row["name"])
            continue
        require(
            all(type(v) in {int, float} and math.isfinite(v) and v >= 0 for v in [quantity, price]),
            "cost_number",
        )
        known[row["name"]] = quantity * price
    subtotal = sum(known.values())
    proven = (
        not unknown
        and plan["regional_quote_verified"] is True
        and plan["failure_liability_capped"] is True
        and subtotal + plan["contingency_usd"] <= plan["ceiling_usd"]
    )
    return dict(
        status="BUDGET PROVEN" if proven else "BUDGET NOT PROVEN",
        reference_subtotal_usd=subtotal,
        reference_items_usd=known,
        contingency_usd=plan["contingency_usd"],
        unknown_charges=unknown,
        total_usd=None if not proven else subtotal + plan["contingency_usd"],
        deployment_authorized=False,
        spending_authorized=False,
    )


if __name__ == "__main__":
    path = Path(__file__).resolve().parents[1] / "docs/operations/aws-synthetic-test-budget.json"
    print(json.dumps(assess(json.loads(path.read_bytes())), indent=2))
