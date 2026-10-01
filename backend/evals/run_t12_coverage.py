"""Audit reviewed catalog coverage without credentials, publishing or model calls."""

import argparse
import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from whisky.modules.catalog.coverage import audit_catalog
from whisky.modules.catalog.publication import load_reviewed_release


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--as-of", type=date.fromisoformat, required=True)
    budgets = parser.add_mutually_exclusive_group(required=True)
    budgets.add_argument("--budget", type=Decimal)
    budgets.add_argument("--no-budget", action="store_true")
    args = parser.parse_args()
    if args.budget is not None and (not args.budget.is_finite() or args.budget <= 0):
        parser.error("budget must be a positive finite TWD amount")
    payload = args.manifest.read_bytes()
    try:
        release = load_reviewed_release(payload.decode())
    except ValueError as error:
        report: dict[str, object] = dict(publication_error=str(error), paths=[])
    else:
        report = audit_catalog(release, args.as_of, args.budget)
    report.update(
        manifest=args.manifest.name,
        manifest_sha256=hashlib.sha256(payload).hexdigest(),
        acceptance_status="not_reviewed",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return int(report["publication_error"] is not None)


if __name__ == "__main__":
    raise SystemExit(main())
