#!/usr/bin/env python3
"""C1 CI check: every `build` model needs unique + not_null on a key and a description on every column.

Key rule: either one column with both `unique` and `not_null`, or (composite keys) a model-level
`dbt_utils.unique_combination_of_columns` test.
Scope: models under dbt/models/marts, rollups and security (the `build` layer).
Exit code 1 on any violation, so a pull request that breaks the rule fails.
"""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2] / "dbt" / "models"
BUILD_DIRS = ("marts", "rollups", "security")


def test_names(tests) -> set[str]:
    names = set()
    for t in tests or []:
        names.add(t if isinstance(t, str) else next(iter(t)))
    return names


def col_tests(col: dict) -> set[str]:
    return test_names(col.get("data_tests")) | test_names(col.get("tests"))


def check_file(path: Path) -> list[str]:
    errors = []
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for model in doc.get("models", []):
        name = model["name"]
        if not model.get("description"):
            errors.append(f"{path}: model {name} has no description")
        cols = model.get("columns") or []
        if not cols:
            errors.append(f"{path}: model {name} declares no columns")
        for col in cols:
            if not col.get("description"):
                errors.append(f"{path}: {name}.{col['name']} has no description")
        single_key = any({"unique", "not_null"} <= col_tests(c) for c in cols)
        model_tests = test_names(model.get("data_tests")) | test_names(model.get("tests"))
        composite_key = "dbt_utils.unique_combination_of_columns" in model_tests
        if not (single_key or composite_key):
            errors.append(f"{path}: model {name} has no key tests (unique + not_null, or unique_combination_of_columns)")
        if not (path.parent / f"{name}.sql").exists():
            errors.append(f"{path}: no {name}.sql next to it (one .sql and one .yml per model)")
    return errors


def main() -> int:
    errors: list[str] = []
    sql_models = {p.stem for d in BUILD_DIRS for p in (ROOT / d).rglob("*.sql")}
    documented: set[str] = set()
    for d in BUILD_DIRS:
        for yml in (ROOT / d).rglob("*.yml"):
            errors += check_file(yml)
            documented |= {m["name"] for m in (yaml.safe_load(yml.read_text(encoding="utf-8")) or {}).get("models", [])}
    for missing in sorted(sql_models - documented):
        errors.append(f"model {missing} has no schema yml")
    for e in errors:
        print("FAIL", e)
    print(f"{len(sql_models)} build models checked, {len(errors)} problems")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
