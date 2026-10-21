"""Write the complete pinned Python API/signature inventory without networking.

Run as ``.venv/bin/python -m scripts.ee_python_inventory`` in the checkout.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.ee_python_api.inventory import ROOT, build_inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "reports/gee-python-api-inventory.json")
    args = parser.parse_args()
    report = build_inventory()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    counts = report["summary"]
    print(f"Wrote {counts['algorithm_signature_count']} pinned signatures, "
          f"{counts['python_class_count']} Python classes and "
          f"{counts['python_callable_count']} callable signatures; "
          "these counts do not measure backend compatibility")


if __name__ == "__main__":
    main()
