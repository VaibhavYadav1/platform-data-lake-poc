"""CRM export generator (task B2): generates hourly CRM snapshots with accounts, stores, and work orders.

Writes to GCS: <bucket>/<prefix>/export_ts=<YYYYMMDDTHHMMSSZ>/{account,store,work_order}.csv + manifest.json
Manifest is written last to signal completion.

Usage:
  python -m simulator crm-export --bucket my-bucket --prefix crm --count 3
  python -m simulator crm-export --bucket my-bucket --prefix crm --count 1 --big-change
  python -m simulator crm-export --bucket my-bucket --local-dir ./test_exports --count 2

The generator creates realistic CRM data:
- Accounts with hierarchies (parent_account_id)
- Customer types: CUSTOMER, VENDOR, PARTNER, PROSPECT
- Stores linked to accounts via g2_store_id
- Work orders linked to accounts, stores, and devices
- Incremental changes over time
"""
from __future__ import annotations

import csv
import hashlib
import json
import random
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Customer type codes from the CRM (option-set values)
CUSTOMER_TYPES = {
    "100000000": "CUSTOMER",
    "100000001": "VENDOR",
    "100000002": "PARTNER",
    "100000003": "PROSPECT",
}

WORK_TYPES = ["INSTALL", "REPAIR", "MAINTENANCE", "INSPECTION", "UPGRADE"]
WO_STATUSES = ["OPEN", "IN_PROGRESS", "CLOSED", "CANCELLED"]
ACCOUNT_STATUSES = ["Active", "Inactive"]
STORE_STATUSES = ["Active", "Inactive"]


@dataclass
class CRMState:
    """State that evolves across exports: accounts, stores, work orders, and their update times."""
    accounts: dict[str, dict[str, Any]]
    stores: dict[str, dict[str, Any]]
    work_orders: dict[str, dict[str, Any]]
    next_account_num: int
    next_store_num: int
    next_wo_num: int
    base_time: datetime
    rng: random.Random

    @classmethod
    def initialize(cls, n_accounts: int = 50, n_stores: int = 100, seed: int = 42) -> CRMState:
        """Create initial CRM state with accounts, stores, and some work orders."""
        rng = random.Random(seed)
        base_time = datetime(2026, 11, 1, tzinfo=timezone.utc)
        
        accounts = {}
        # Create top-level accounts first
        for i in range(1, n_accounts + 1):
            acc_id = f"ACC{i:05d}"
            # First 60% are customers, rest are mixed
            if i <= int(n_accounts * 0.6):
                type_code = "100000000"  # CUSTOMER
            elif i <= int(n_accounts * 0.75):
                type_code = "100000001"  # VENDOR
            elif i <= int(n_accounts * 0.9):
                type_code = "100000002"  # PARTNER
            else:
                type_code = "100000003"  # PROSPECT
            
            accounts[acc_id] = {
                "account_id": acc_id,
                "account_name": f"Company {i}",
                "customer_type_code": type_code,
                "status": "Active",
                "parent_account_id": "",
                "primary_contact_name": f"Contact Person {i}",
                "primary_contact_email": f"contact{i}@company{i}.example",
                "updated_at": base_time + timedelta(minutes=i),
            }
        
        # Add some hierarchies (10% of accounts have parents)
        for i in range(1, min(5, n_accounts // 10)):
            child_id = f"ACC{i + 1:05d}"
            accounts[child_id]["parent_account_id"] = "ACC00001"
        
        # Create stores linked to accounts via g2_store_id
        stores = {}
        for i in range(1, n_stores + 1):
            store_id = f"CST{i:05d}"
            # Link stores to accounts (multiple stores per account possible)
            account_num = ((i - 1) % n_accounts) + 1
            account_id = f"ACC{account_num:05d}"
            
            stores[store_id] = {
                "crm_store_id": store_id,
                "account_id": account_id,
                "g2_store_id": f"S{i:04d}",  # G2 store format
                "status": "Active" if rng.random() > 0.05 else "Inactive",
                "updated_at": base_time + timedelta(minutes=i * 2),
            }
        
        # Create initial work orders
        work_orders = {}
        n_work_orders = min(50, n_stores)
        for i in range(1, n_work_orders + 1):
            wo_id = f"WO{i:06d}"
            store_num = ((i - 1) % n_stores) + 1
            store_id = f"CST{store_num:05d}"
            account_id = stores[store_id]["account_id"]
            
            opened_at = base_time + timedelta(hours=i)
            is_closed = rng.random() > 0.3
            
            work_orders[wo_id] = {
                "work_order_id": wo_id,
                "account_id": account_id,
                "crm_store_id": store_id,
                "g2_device_id": f"D{i:04d}",  # G2 device format
                "work_type": rng.choice(WORK_TYPES),
                "status": "CLOSED" if is_closed else rng.choice(["OPEN", "IN_PROGRESS"]),
                "opened_at": opened_at,
                "closed_at": opened_at + timedelta(hours=rng.randint(1, 48)) if is_closed else None,
                "updated_at": opened_at + timedelta(hours=rng.randint(0, 72)),
            }
        
        return cls(
            accounts=accounts,
            stores=stores,
            work_orders=work_orders,
            next_account_num=n_accounts + 1,
            next_store_num=n_stores + 1,
            next_wo_num=n_work_orders + 1,
            base_time=base_time,
            rng=rng,
        )

    def evolve(self, change_rate: float, export_time: datetime, big_change: bool = False) -> None:
        """Apply changes to simulate CRM evolution between exports."""
        if big_change:
            change_rate = max(0.6, change_rate)  # Force >50% change for guard testing
        
        n_accounts_to_change = int(len(self.accounts) * change_rate)
        n_stores_to_change = int(len(self.stores) * change_rate * 0.5)
        n_wo_to_change = int(len(self.work_orders) * change_rate * 0.3)
        
        # Change existing accounts
        account_ids = sorted(self.accounts.keys())
        for acc_id in self.rng.sample(account_ids, min(n_accounts_to_change, len(account_ids))):
            self.accounts[acc_id]["updated_at"] = export_time
            # Occasionally change status or type
            if self.rng.random() < 0.1:
                self.accounts[acc_id]["status"] = self.rng.choice(ACCOUNT_STATUSES)
        
        # Add a few new accounts
        if self.rng.random() < 0.3:
            for _ in range(self.rng.randint(1, 3)):
                acc_id = f"ACC{self.next_account_num:05d}"
                self.accounts[acc_id] = {
                    "account_id": acc_id,
                    "account_name": f"New Company {self.next_account_num}",
                    "customer_type_code": self.rng.choice(list(CUSTOMER_TYPES.keys())),
                    "status": "Active",
                    "parent_account_id": "",
                    "primary_contact_name": f"New Contact {self.next_account_num}",
                    "primary_contact_email": f"newcontact{self.next_account_num}@example.test",
                    "updated_at": export_time,
                }
                self.next_account_num += 1
        
        # Change existing stores
        store_ids = sorted(self.stores.keys())
        for store_id in self.rng.sample(store_ids, min(n_stores_to_change, len(store_ids))):
            self.stores[store_id]["updated_at"] = export_time
            if self.rng.random() < 0.05:
                self.stores[store_id]["status"] = self.rng.choice(STORE_STATUSES)
        
        # Update work orders (close open ones, create new ones)
        wo_ids = sorted(self.work_orders.keys())
        for wo_id in self.rng.sample(wo_ids, min(n_wo_to_change, len(wo_ids))):
            wo = self.work_orders[wo_id]
            if wo["status"] in ["OPEN", "IN_PROGRESS"] and self.rng.random() < 0.4:
                wo["status"] = "CLOSED"
                wo["closed_at"] = export_time
            wo["updated_at"] = export_time
        
        # Add new work orders
        if self.rng.random() < 0.5:
            for _ in range(self.rng.randint(1, 5)):
                wo_id = f"WO{self.next_wo_num:06d}"
                store_id = self.rng.choice(list(self.stores.keys()))
                account_id = self.stores[store_id]["account_id"]
                
                self.work_orders[wo_id] = {
                    "work_order_id": wo_id,
                    "account_id": account_id,
                    "crm_store_id": store_id,
                    "g2_device_id": f"D{self.rng.randint(1, 200):04d}",
                    "work_type": self.rng.choice(WORK_TYPES),
                    "status": "OPEN",
                    "opened_at": export_time,
                    "closed_at": None,
                    "updated_at": export_time,
                }
                self.next_wo_num += 1

    def plant_issues(self, export_time: datetime) -> None:
        """Plant data quality issues for testing (DQ36, DQ33, etc.)."""
        # DQ36: Unknown customer type
        if "ACC99999" not in self.accounts and self.rng.random() < 0.3:
            self.accounts["ACC99999"] = {
                "account_id": "ACC99999",
                "account_name": "Unknown Type Company",
                "customer_type_code": "999999999",  # Unknown code
                "status": "Active",
                "parent_account_id": "",
                "primary_contact_name": "Unknown Contact",
                "primary_contact_email": "unknown@example.test",
                "updated_at": export_time,
            }


def iso_timestamp(dt: datetime | None) -> str:
    """Format datetime as ISO string, empty if None."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else ""


def write_csv(rows: list[dict], columns: list[str]) -> str:
    """Write rows to CSV string with given column order."""
    import io
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue()


def generate_export(
    state: CRMState,
    export_time: datetime,
    change_rate: float = 0.1,
    big_change: bool = False,
    plant_issues: bool = False,
) -> dict[str, str]:
    """Generate one CRM export as CSV strings."""
    # Evolve the state
    state.evolve(change_rate, export_time, big_change)
    
    # Optionally plant test issues
    if plant_issues:
        state.plant_issues(export_time)
    
    export_ts = iso_timestamp(export_time)
    
    # Generate account CSV
    account_rows = []
    for acc in sorted(state.accounts.values(), key=lambda x: x["account_id"]):
        account_rows.append({
            "account_id": acc["account_id"],
            "account_name": acc["account_name"],
            "customer_type_code": acc["customer_type_code"],
            "status": acc["status"],
            "parent_account_id": acc["parent_account_id"],
            "primary_contact_name": acc["primary_contact_name"],
            "primary_contact_email": acc["primary_contact_email"],
            "updated_at": iso_timestamp(acc["updated_at"]),
            "export_ts": export_ts,
        })
    
    account_csv = write_csv(account_rows, [
        "account_id", "account_name", "customer_type_code", "status", "parent_account_id",
        "primary_contact_name", "primary_contact_email", "updated_at", "export_ts"
    ])
    
    # Generate store CSV
    store_rows = []
    for store in sorted(state.stores.values(), key=lambda x: x["crm_store_id"]):
        store_rows.append({
            "crm_store_id": store["crm_store_id"],
            "account_id": store["account_id"],
            "g2_store_id": store["g2_store_id"],
            "status": store["status"],
            "updated_at": iso_timestamp(store["updated_at"]),
            "export_ts": export_ts,
        })
    
    store_csv = write_csv(store_rows, [
        "crm_store_id", "account_id", "g2_store_id", "status", "updated_at", "export_ts"
    ])
    
    # Generate work_order CSV
    wo_rows = []
    for wo in sorted(state.work_orders.values(), key=lambda x: x["work_order_id"]):
        wo_rows.append({
            "work_order_id": wo["work_order_id"],
            "account_id": wo["account_id"],
            "crm_store_id": wo["crm_store_id"],
            "g2_device_id": wo["g2_device_id"],
            "work_type": wo["work_type"],
            "status": wo["status"],
            "opened_at": iso_timestamp(wo["opened_at"]),
            "closed_at": iso_timestamp(wo["closed_at"]),
            "updated_at": iso_timestamp(wo["updated_at"]),
            "export_ts": export_ts,
        })
    
    work_order_csv = write_csv(wo_rows, [
        "work_order_id", "account_id", "crm_store_id", "g2_device_id", "work_type", "status",
        "opened_at", "closed_at", "updated_at", "export_ts"
    ])
    
    return {
        "account.csv": account_csv,
        "store.csv": store_csv,
        "work_order.csv": work_order_csv,
    }


def write_export_folder(
    folder: Path,
    export_time: datetime,
    csv_files: dict[str, str],
) -> Path:
    """Write CSV files and manifest to a folder."""
    ts_name = export_time.strftime("%Y%m%dT%H%M%SZ")
    export_folder = folder / f"export_ts={ts_name}"
    export_folder.mkdir(parents=True, exist_ok=True)
    
    # Write CSV files and collect metadata
    manifest_entries = []
    for filename, content in csv_files.items():
        file_path = export_folder / filename
        file_path.write_text(content, encoding="utf-8")
        
        file_bytes = content.encode("utf-8")
        md5 = hashlib.md5(file_bytes).hexdigest()
        
        manifest_entries.append({
            "name": filename,
            "size": len(file_bytes),
            "md5": md5,
        })
    
    # Write manifest last (signals completion)
    manifest = {
        "export_ts": ts_name,
        "files": manifest_entries,
    }
    manifest_path = export_folder / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    
    return export_folder


def upload_to_gcs(bucket_name: str, prefix: str, export_time: datetime, csv_files: dict[str, str]) -> str:
    """Upload export to GCS and return the folder path."""
    from google.cloud import storage
    
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    
    ts_name = export_time.strftime("%Y%m%dT%H%M%SZ")
    folder_path = f"{prefix}/export_ts={ts_name}"
    
    # Upload CSV files
    manifest_entries = []
    for filename, content in csv_files.items():
        blob_path = f"{folder_path}/{filename}"
        blob = bucket.blob(blob_path)
        blob.upload_from_string(content, content_type="text/csv")
        
        file_bytes = content.encode("utf-8")
        md5 = hashlib.md5(file_bytes).hexdigest()
        
        manifest_entries.append({
            "name": filename,
            "size": len(file_bytes),
            "md5": md5,
        })
    
    # Upload manifest last
    manifest = {
        "export_ts": ts_name,
        "files": manifest_entries,
    }
    manifest_blob = bucket.blob(f"{folder_path}/manifest.json")
    manifest_blob.upload_from_string(json.dumps(manifest, indent=2), content_type="application/json")
    
    return f"gs://{bucket_name}/{folder_path}"


def export_exists(bucket_name: str, prefix: str, export_time: datetime) -> bool:
    """True when this hour's export is complete: its manifest.json (written last) is in the bucket."""
    from google.cloud import storage

    ts_name = export_time.strftime("%Y%m%dT%H%M%SZ")
    return storage.Client().bucket(bucket_name).blob(f"{prefix}/export_ts={ts_name}/manifest.json").exists()


class CRMExportError(Exception):
    pass
