"""Make CRM export folders for testing the loader without the simulator (stand-in for task B2).

Writes <out>/export_ts=<ts>/{account,store,work_order}.csv and manifest.json (written last). All data is made up.

  python make_test_exports.py --out DIR --ts 20261120T080000Z                       first export, 20 accounts
  python make_test_exports.py --out DIR --ts 20261120T090000Z --change 0.10         10% of accounts change vs. the base
  python make_test_exports.py --out DIR --ts 20261120T100000Z --change 0.60         60% change (trips DQ42)
  python make_test_exports.py --out DIR --ts 20261120T110000Z --bad-work-order      account/store load, work_order fails
  python make_test_exports.py --out DIR --ts 20261120T120000Z --bad-md5             manifest checksum is wrong
  python make_test_exports.py --out DIR --ts 20261120T140000Z --bad-header          store.csv has a wrong header
  python make_test_exports.py --out DIR --ts 20261120T150000Z --wrong-row-ts        a row carries another export's export_ts
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

N_ACCOUNTS = 20
BASE = datetime(2026, 11, 1, tzinfo=timezone.utc)
FILES = ("account.csv", "store.csv", "work_order.csv")


def iso(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else ""


def build(ts: datetime, change: float, bad_work_order: bool, bad_header: bool = False, wrong_row_ts: bool = False) -> dict[str, list[list[str]]]:
    n_changed = round(N_ACCOUNTS * change)
    export = iso(ts)
    accounts = [["account_id", "account_name", "customer_type_code", "status", "parent_account_id",
                 "primary_contact_name", "primary_contact_email", "updated_at", "export_ts"]]
    stores = [["crm_store_id", "account_id", "g2_store_id", "status", "updated_at", "export_ts"]]
    orders = [["work_order_id", "account_id", "crm_store_id", "g2_device_id", "work_type", "status",
               "opened_at", "closed_at", "updated_at", "export_ts"]]
    for i in range(1, N_ACCOUNTS + 1):
        acc = f"ACC{i:05d}"
        # the first n_changed accounts get a new updated_at in this export; the rest keep the base time
        updated = ts if i <= n_changed else BASE + timedelta(minutes=i)
        parent = "ACC00001" if i in (2, 3) else ""
        code = "100000000" if i % 4 else "100000001"
        accounts.append([acc, f"Test Company {i}", code, "Active", parent, f"Contact {i}",
                         f"contact{i}@example.test", iso(updated), export])
        stores.append([f"CST{i:05d}", acc, f"G2-{i:05d}", "Active", iso(BASE + timedelta(minutes=i)), export])
        opened = BASE + timedelta(hours=i)
        orders.append([f"WO{i:06d}", acc, f"CST{i:05d}", f"DEV{i:04d}", "INSTALL", "CLOSED",
                       iso(opened), iso(opened + timedelta(hours=3)), iso(opened + timedelta(hours=3)), export])
    if bad_work_order:
        orders.append(["WO999999", "ACC00001", "CST00001", "", "REPAIR", "OPEN", "not-a-timestamp", "", iso(ts), export])
    if bad_header:
        stores[0][1] = "acct_id"
    if wrong_row_ts:
        stores[1][-1] = iso(ts - timedelta(hours=1))
    return {"account.csv": accounts, "store.csv": stores, "work_order.csv": orders}


def write_folder(out: Path, ts_name: str, tables: dict[str, list[list[str]]], bad_md5: bool) -> Path:
    folder = out / f"export_ts={ts_name}"
    folder.mkdir(parents=True, exist_ok=True)
    entries = []
    for name, rows in tables.items():
        path = folder / name
        with path.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f, lineterminator="\n").writerows(rows)
        md5 = hashlib.md5(path.read_bytes()).hexdigest()
        entries.append({"name": name, "size": path.stat().st_size, "md5": "0" * 32 if bad_md5 and name == "store.csv" else md5})
    (folder / "manifest.json").write_text(json.dumps({"export_ts": ts_name, "files": entries}, indent=2), encoding="utf-8")
    return folder


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--ts", required=True, help="YYYYMMDDTHHMMSSZ")
    ap.add_argument("--change", type=float, default=0.0, help="share of accounts whose updated_at changes")
    ap.add_argument("--bad-work-order", action="store_true")
    ap.add_argument("--bad-md5", action="store_true")
    ap.add_argument("--bad-header", action="store_true")
    ap.add_argument("--wrong-row-ts", action="store_true")
    args = ap.parse_args()
    ts = datetime.strptime(args.ts, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    print(write_folder(args.out, args.ts, build(ts, args.change, args.bad_work_order, args.bad_header, args.wrong_row_ts), args.bad_md5))


if __name__ == "__main__":
    main()
