#!/usr/bin/env python3
"""B8 / C8 CI check: the customer definition lives in exactly one place.

The literal 'CUSTOMER' and the code 100000000 may appear only in the seed and the is_customer macro.
Scans dbt/models, dbt/macros, dbt/tests, dbt/seeds and the other scripts. Exit code 1 on a violation.
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ALLOWED = {
    REPO / "dbt" / "seeds" / "map_customer_type.csv",
    REPO / "dbt" / "macros" / "is_customer.sql",
    REPO / "dbt" / "seeds" / "seeds.yml",           # documents the seed
    Path(__file__).resolve(),
}
SCAN = [REPO / "dbt" / d for d in ("models", "macros", "tests", "seeds")] + [REPO / "scripts", REPO / "orchestration"]
PATTERN = re.compile(r"'CUSTOMER'|\"CUSTOMER\"|\b100000000\b")
SUFFIXES = {".sql", ".yml", ".yaml", ".csv", ".py"}


def main() -> int:
    bad = []
    for base in SCAN:
        for p in base.rglob("*"):
            if p.suffix not in SUFFIXES or not p.is_file() or p in ALLOWED:
                continue
            for n, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if PATTERN.search(line):
                    bad.append(f"{p.relative_to(REPO)}:{n}: {line.strip()}")
    for b in bad:
        print("FAIL", b)
    print(f"single-definition check: {len(bad)} problems")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
