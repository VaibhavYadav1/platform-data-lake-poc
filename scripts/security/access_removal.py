"""D6 access-removal test (AT-25): rows disappear within one cycle (20 minutes) after `simulator revoke`,
and come back after `simulator grant`.

    python scripts/security/access_removal.py [--principal EMAIL] [--account ACC00001] [--timeout-minutes 20]

Needs: the micro-batch running (E4), the simulator's G2 connection settings in the environment, and the runner
holding token creator on sa-tenant-a-user. Exit 0 when both steps pass, 1 otherwise.
"""
from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from security_lib import REPO, BigQueryRunner, Config, Result, log, new_run_id, write_results  # noqa: E402


def count_sql(cfg: Config) -> str:
    # wh facts require a partition filter; the wide range still counts every row.
    return f"SELECT COUNT(*) AS n FROM {cfg.table('wh', 'fct_alert')} WHERE alert_date >= '1970-01-01'"


def simulator(action: str, principal: str, account: str) -> None:
    cmd = [sys.executable, "-m", "simulator", action, "--principal", principal, "--account", account]
    log("SIMULATOR", command=" ".join(cmd[1:]))
    subprocess.run(cmd, cwd=REPO, check=True)


def poll(count, done, timeout_s: float, every_s: float = 60, sleep=time.sleep, clock=time.monotonic):
    """Call count() every `every_s` until done(n). Returns (seconds taken or None on timeout, last n)."""
    start = clock()
    while True:
        n = count()
        elapsed = clock() - start
        log("POLL", rows=n, seconds=round(elapsed))
        if done(n):
            return elapsed, n
        if elapsed + every_s > timeout_s:
            return None, n
        sleep(every_s)


def run_test(cfg: Config, count, revoke, grant, principal: str, timeout_s: float = 1200, every_s: float = 60,
             sleep=time.sleep, clock=time.monotonic) -> list[Result]:
    before = count()
    if before == 0:
        return [Result(8, "access_removal", principal, "wh.fct_alert", "rows before revoke", "0 rows", False,
                       detail="the tenant sees nothing before the revoke, so the test proves nothing")]
    revoke()
    took, n = poll(count, lambda x: x == 0, timeout_s, every_s, sleep, clock)
    removed = Result(8, "access_removal", principal, "wh.fct_alert", f"0 rows within {timeout_s / 60:.0f} min",
                     f"0 rows after {took:.0f} s" if took is not None else f"{n} rows after timeout",
                     took is not None, detail=f"rows before revoke: {before}")
    grant()
    took2, n2 = poll(count, lambda x: x > 0, timeout_s, every_s, sleep, clock)
    restored = Result(8, "access_restore", principal, "wh.fct_alert", "rows back after grant",
                      f"{n2} rows after {took2:.0f} s" if took2 is not None else "0 rows after timeout",
                      took2 is not None)
    return [removed, restored]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--principal", help="default: sa-tenant-a-user of the project")
    ap.add_argument("--account", help="default: tenant A (TENANT_A, ACC00001)")
    ap.add_argument("--timeout-minutes", type=float, default=20)
    ap.add_argument("--every-seconds", type=float, default=60)
    args = ap.parse_args(argv)
    cfg = Config.from_env()
    principal = args.principal or cfg.sa("sa-tenant-a-user")
    account = args.account or cfg.tenants["A"]
    run_id, run_at = new_run_id(), dt.datetime.now(dt.timezone.utc)
    runner = BigQueryRunner(cfg, run_id)
    results = run_test(
        cfg,
        count=lambda: runner.query(count_sql(cfg), identity=principal)[0]["n"],
        revoke=lambda: simulator("revoke", principal, account),
        grant=lambda: simulator("grant", principal, account),
        principal=principal, timeout_s=args.timeout_minutes * 60, every_s=args.every_seconds,
    )
    write_results(runner, cfg, run_id, run_at, results)
    for r in results:
        log("RESULT", case=r.case_name, passed=r.passed, actual=r.actual)
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
