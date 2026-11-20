#!/usr/bin/env python3
"""E1 rule check: environments differ only in *.tfvars and *.backend.hcl.

Two checks, run from the repository root:

1. Under terraform/, any file or directory named after an environment (dev.*, *.int.*, ...)
   must be a <env>.tfvars or <env>.backend.hcl file. No copy-pasted per-environment Terraform.
2. Each environment's tfvars (and backend.hcl) define the same set of keys, so a variable
   can't be set for dev and forgotten for int.

Environments without files yet are reported and skipped (int arrives with E9).
Exit code 0 = pass, 1 = violations.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ENVS = ("dev", "int")
ENV_DIR = Path("terraform/env")
ALLOWED_SUFFIXES = (".tfvars", ".backend.hcl")
KEY_RE = re.compile(r"^\s*([A-Za-z_][\w-]*)\s*=", re.MULTILINE)


def env_named_paths(root: Path, envs=ENVS):
    """Paths under root whose name carries an environment token like dev.x or x.int.y."""
    token = re.compile(r"(^|[._-])(%s)([._-]|$)" % "|".join(envs))
    for p in sorted(root.rglob("*")):
        if ".terraform" in p.parts:
            continue
        if token.search(p.name):
            yield p


def keys_of(path: Path) -> set[str]:
    return set(KEY_RE.findall(re.sub(r"#.*|//.*", "", path.read_text(encoding="utf-8"))))


def check(repo: Path = Path("."), envs=ENVS) -> tuple[list[str], list[str]]:
    errors, notes = [], []
    tf = repo / "terraform"
    for p in env_named_paths(tf, envs):
        if not p.name.endswith(ALLOWED_SUFFIXES):
            errors.append(
                f"{p.relative_to(repo).as_posix()}: environment-specific file that is not "
                f"*.tfvars or *.backend.hcl"
            )

    env_dir = repo / ENV_DIR
    for suffix in ALLOWED_SUFFIXES:
        present = {e: env_dir / f"{e}{suffix}" for e in envs if (env_dir / f"{e}{suffix}").exists()}
        for e in envs:
            if e not in present:
                notes.append(f"{ENV_DIR.as_posix()}/{e}{suffix} not present, skipped")
        if len(present) < 2:
            continue
        ref_env, ref_path = next(iter(present.items()))
        ref = keys_of(ref_path)
        for e, path in present.items():
            diff = keys_of(path) ^ ref
            if diff:
                errors.append(
                    f"{path.relative_to(repo).as_posix()}: keys differ from {ref_env}{suffix}: "
                    f"{sorted(diff)}"
                )
    return errors, notes


def main() -> int:
    errors, notes = check()
    for n in notes:
        print(f"note: {n}")
    for e in errors:
        print(f"ERROR: {e}")
    if errors:
        return 1
    print("check_env_diff: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
