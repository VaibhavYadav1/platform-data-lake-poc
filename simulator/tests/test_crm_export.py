"""Tests for CRM export generation (task B2)."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from simulator.crm_export import CRMState, generate_export, write_export_folder


def test_crm_state_initialization():
    """Test that CRM state initializes with correct structure."""
    state = CRMState.initialize(n_accounts=10, n_stores=20, seed=42)
    
    assert len(state.accounts) == 10
    assert len(state.stores) == 20
    assert len(state.work_orders) > 0
    
    # Check account structure
    acc = state.accounts["ACC00001"]
    assert "account_id" in acc
    assert "customer_type_code" in acc
    assert "status" in acc
    
    # Check store structure
    store = state.stores["CST00001"]
    assert "crm_store_id" in store
    assert "account_id" in store
    assert "g2_store_id" in store


def test_customer_type_distribution():
    """Test that customer types are distributed correctly."""
    state = CRMState.initialize(n_accounts=50, seed=42)
    
    types = [acc["customer_type_code"] for acc in state.accounts.values()]
    customers = [t for t in types if t == "100000000"]  # CUSTOMER
    vendors = [t for t in types if t == "100000001"]     # VENDOR
    
    # At least 50% should be customers
    assert len(customers) >= len(state.accounts) * 0.5
    # Should have some vendors
    assert len(vendors) > 0


def test_account_hierarchy():
    """Test that account hierarchies are created."""
    state = CRMState.initialize(n_accounts=20, seed=42)
    
    # Check for child accounts
    children = [acc for acc in state.accounts.values() if acc["parent_account_id"]]
    assert len(children) > 0
    
    # Verify parent exists
    for child in children:
        assert child["parent_account_id"] in state.accounts


def test_store_account_linking():
    """Test that stores are properly linked to accounts."""
    state = CRMState.initialize(n_accounts=10, n_stores=20, seed=42)
    
    for store in state.stores.values():
        # Every store should have an account
        assert store["account_id"] in state.accounts
        # Should have g2_store_id
        assert store["g2_store_id"].startswith("S")


def test_work_order_references():
    """Test that work orders reference valid accounts and stores."""
    state = CRMState.initialize(n_accounts=10, n_stores=20, seed=42)
    
    for wo in state.work_orders.values():
        # Work order should reference existing account
        assert wo["account_id"] in state.accounts
        # Should reference existing store
        assert wo["crm_store_id"] in state.stores
        # Store's account should match work order's account
        store = state.stores[wo["crm_store_id"]]
        assert store["account_id"] == wo["account_id"]


def test_evolve_changes_data():
    """Test that evolve() modifies state."""
    state = CRMState.initialize(n_accounts=20, seed=42)
    export_time = datetime(2026, 11, 2, 0, 0, 0, tzinfo=timezone.utc)
    
    # Record original update times
    original_times = {acc_id: acc["updated_at"] for acc_id, acc in state.accounts.items()}
    
    # Evolve with 30% change rate
    state.evolve(change_rate=0.3, export_time=export_time)
    
    # Check that some accounts changed
    changed = sum(1 for acc_id, acc in state.accounts.items() 
                  if acc["updated_at"] != original_times.get(acc_id))
    
    assert changed >= len(state.accounts) * 0.2  # At least 20% changed
    assert changed <= len(state.accounts) * 0.4  # At most 40% changed


def test_big_change_exceeds_threshold():
    """Test that big_change forces >50% change."""
    state = CRMState.initialize(n_accounts=20, seed=42)
    export_time = datetime(2026, 11, 2, 0, 0, 0, tzinfo=timezone.utc)
    
    original_times = {acc_id: acc["updated_at"] for acc_id, acc in state.accounts.items()}
    
    # Evolve with big change
    state.evolve(change_rate=0.1, export_time=export_time, big_change=True)
    
    # Count changes
    changed = sum(1 for acc_id, acc in state.accounts.items() 
                  if acc["updated_at"] != original_times.get(acc_id))
    
    # Should exceed 50%
    assert changed / len(state.accounts) > 0.5


def test_generate_export_creates_csvs():
    """Test that generate_export creates all required CSV files."""
    state = CRMState.initialize(n_accounts=10, n_stores=20, seed=42)
    export_time = datetime(2026, 11, 20, 8, 0, 0, tzinfo=timezone.utc)
    
    csv_files = generate_export(state, export_time)
    
    # Should have all three files
    assert "account.csv" in csv_files
    assert "store.csv" in csv_files
    assert "work_order.csv" in csv_files
    
    # Each should have headers
    for name, content in csv_files.items():
        assert content.count('\n') > 1  # Header + at least one row


def test_csv_has_correct_columns():
    """Test that CSV files have required columns."""
    state = CRMState.initialize(n_accounts=5, seed=42)
    export_time = datetime(2026, 11, 20, 8, 0, 0, tzinfo=timezone.utc)
    
    csv_files = generate_export(state, export_time)
    
    # Check account columns
    account_header = csv_files["account.csv"].split('\n')[0]
    assert "account_id" in account_header
    assert "customer_type_code" in account_header
    assert "primary_contact_email" in account_header
    assert "export_ts" in account_header
    
    # Check store columns
    store_header = csv_files["store.csv"].split('\n')[0]
    assert "crm_store_id" in store_header
    assert "g2_store_id" in store_header
    assert "account_id" in store_header
    
    # Check work_order columns
    wo_header = csv_files["work_order.csv"].split('\n')[0]
    assert "work_order_id" in wo_header
    assert "g2_device_id" in wo_header
    assert "opened_at" in wo_header


def test_export_ts_in_all_rows():
    """Test that export_ts appears in all CSV rows."""
    state = CRMState.initialize(n_accounts=5, seed=42)
    export_time = datetime(2026, 11, 20, 8, 0, 0, tzinfo=timezone.utc)
    expected_ts = "2026-11-20T08:00:00Z"
    
    csv_files = generate_export(state, export_time)
    
    # Check that every row has the export timestamp
    for name, content in csv_files.items():
        lines = content.strip().split('\n')
        for line in lines[1:]:  # Skip header
            assert expected_ts in line, f"{name} missing export_ts in row"


def test_plant_issues_adds_unknown_type():
    """Test that plant_issues adds test data quality issues."""
    state = CRMState.initialize(n_accounts=10, seed=42)
    export_time = datetime(2026, 11, 20, 8, 0, 0, tzinfo=timezone.utc)
    
    # Generate without issues
    csv_without = generate_export(state, export_time, plant_issues=False)
    state_copy = CRMState.initialize(n_accounts=10, seed=42)
    
    # Generate with issues
    csv_with = generate_export(state_copy, export_time, plant_issues=True)
    
    # With issues should have ACC99999 with unknown type
    assert "ACC99999" in csv_with["account.csv"]
    assert "999999999" in csv_with["account.csv"]  # Unknown customer_type_code


def test_write_export_folder_creates_manifest(tmp_path):
    """Test that write_export_folder creates manifest.json."""
    state = CRMState.initialize(n_accounts=5, seed=42)
    export_time = datetime(2026, 11, 20, 8, 0, 0, tzinfo=timezone.utc)
    
    csv_files = generate_export(state, export_time)
    folder = write_export_folder(tmp_path, export_time, csv_files)
    
    # Check folder exists
    assert folder.exists()
    assert folder.name == "export_ts=20261120T080000Z"
    
    # Check manifest exists and is valid JSON
    manifest_path = folder / "manifest.json"
    assert manifest_path.exists()
    
    manifest = json.loads(manifest_path.read_text())
    assert "export_ts" in manifest
    assert "files" in manifest
    assert len(manifest["files"]) == 3


def test_manifest_has_correct_metadata(tmp_path):
    """Test that manifest contains correct file metadata."""
    state = CRMState.initialize(n_accounts=5, seed=42)
    export_time = datetime(2026, 11, 20, 8, 0, 0, tzinfo=timezone.utc)
    
    csv_files = generate_export(state, export_time)
    folder = write_export_folder(tmp_path, export_time, csv_files)
    
    manifest = json.loads((folder / "manifest.json").read_text())
    
    # Check each file entry
    for file_entry in manifest["files"]:
        assert "name" in file_entry
        assert "size" in file_entry
        assert "md5" in file_entry
        
        # Verify file actually exists
        file_path = folder / file_entry["name"]
        assert file_path.exists()
        
        # Verify size matches
        assert file_path.stat().st_size == file_entry["size"]


def test_csv_format_no_quotes_in_simple_fields():
    """Test that CSV is properly formatted."""
    state = CRMState.initialize(n_accounts=5, seed=42)
    export_time = datetime(2026, 11, 20, 8, 0, 0, tzinfo=timezone.utc)
    
    csv_files = generate_export(state, export_time)
    
    # Check line terminator
    assert csv_files["account.csv"].count('\r\n') == 0  # Should use \n, not \r\n
    
    # Should have proper CSV structure
    lines = csv_files["account.csv"].strip().split('\n')
    assert len(lines) > 1
    
    # Each line should have the same number of commas
    comma_counts = [line.count(',') for line in lines]
    assert len(set(comma_counts)) == 1, "Inconsistent column counts"


def test_reproducibility_with_same_seed():
    """Test that same seed produces same output."""
    export_time = datetime(2026, 11, 20, 8, 0, 0, tzinfo=timezone.utc)
    
    state1 = CRMState.initialize(n_accounts=10, seed=42)
    csv1 = generate_export(state1, export_time, change_rate=0.2)
    
    state2 = CRMState.initialize(n_accounts=10, seed=42)
    csv2 = generate_export(state2, export_time, change_rate=0.2)
    
    # Should produce identical output
    assert csv1["account.csv"] == csv2["account.csv"]
    assert csv1["store.csv"] == csv2["store.csv"]
    assert csv1["work_order.csv"] == csv2["work_order.csv"]


def test_different_seeds_produce_different_output():
    """Test that different seeds produce different data."""
    export_time = datetime(2026, 11, 20, 8, 0, 0, tzinfo=timezone.utc)
    
    state1 = CRMState.initialize(n_accounts=10, seed=42)
    csv1 = generate_export(state1, export_time)
    
    state2 = CRMState.initialize(n_accounts=10, seed=99)
    csv2 = generate_export(state2, export_time)
    
    # Should produce different output
    assert csv1["account.csv"] != csv2["account.csv"]
