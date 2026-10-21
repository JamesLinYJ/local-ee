#!/usr/bin/env python3
"""Generate a privacy-safe, pinned Earth Engine API compatibility inventory.

Normal generation reads the pinned public SDK metadata, local source
declarations, and a checked-in sanitized evidence snapshot. The opt-in refresh
mode reads only allowlisted fields from local audit records to regenerate that
snapshot. This tool never imports application modules, executes user code,
starts services, or accesses a network. SDK signatures and local compiler
declarations are reported as separate evidence layers."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Direct CLI execution and importlib callers use the same package entry points.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ee_inventory.catalogue import CLIENT_ALIAS_LOWERINGS, KNOWN_PARTIAL_LIMITS
from scripts.ee_inventory.declarations import _expand_handler_expression, read_declared_handlers
from scripts.ee_inventory.audit_extract import (
    _safe_numerical_evidence,
    _safe_probe_snapshot,
    _safe_workflows,
)
from scripts.ee_inventory.evidence import (
    build_local_evidence_snapshot,
    refresh_local_evidence_snapshot,
)
from scripts.ee_inventory.inventory import _canonical_name, build_inventory
from scripts.ee_inventory.shared import ROOT, SCHEMA_VERSION, _snapshot_path, read_json, render_json, sha256
from scripts.ee_inventory.validation import _validate_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository root (defaults to this checkout)")
    parser.add_argument("--output", type=Path, default=Path("reports/gee-api-inventory.json"), help="Output path relative to --root unless absolute")
    parser.add_argument(
        "--refresh-local-evidence",
        action="store_true",
        help="Explicitly read allowlisted local audit fields and write the sanitized reports/gee-evidence-snapshot.json before generating the report",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    if args.refresh_local_evidence:
        snapshot = refresh_local_evidence_snapshot(root)
        print(f"Wrote {snapshot.relative_to(root) if snapshot.is_relative_to(root) else snapshot.name}")
    output = args.output if args.output.is_absolute() else root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_json(build_inventory(root)), encoding="utf-8")
    print(f"Wrote {output.relative_to(root) if output.is_relative_to(root) else output.name}")
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
