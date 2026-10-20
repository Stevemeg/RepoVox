"""Offline arithmetic only; no SDK, quote request, credential or deployment API."""

import argparse
import json
import math
from pathlib import Path


def estimate(inputs, hours):
    if type(hours) not in {int, float} or not math.isfinite(hours) or not 0 < hours <= 730:
        raise ValueError("hours must be finite and within one 730-hour planning month")
    if inputs["mode"] != "REFERENCE_SUBTOTAL_NOT_BUDGET_AUTHORIZATION":
        raise ValueError("reference input boundary")
    factor = hours / 730
    rows, unknown = {}, []
    names = [row["name"] for row in inputs["items"]]
    if len(names) != len(set(names)):
        raise ValueError("duplicate cost item")
    for row in inputs["items"]:
        rate, quantity = row["usd_per_unit"], row["monthly_units"]
        if rate is None:
            unknown.append(row["name"])
            continue
        if not all(
            type(n) in {int, float} and math.isfinite(n) and n >= 0 for n in [rate, quantity]
        ):
            raise ValueError("invalid price/quantity")
        rows[row["name"]] = rate * quantity * factor
    return dict(
        hours=hours,
        items_usd=rows,
        reference_subtotal_usd=sum(rows.values()),
        unknown_costs=unknown,
        complete_budget=False,
        free_tier_assumed=False,
        provisioning_authorized=False,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=730)
    args = parser.parse_args()
    path = Path(__file__).resolve().parents[1] / "docs/operations/cloud-retention-costs.json"
    print(json.dumps(estimate(json.loads(path.read_bytes()), args.hours), indent=2))
