#!/usr/bin/env python
"""Basic verification script for CRM export functionality (no external dependencies)."""

import sys
from datetime import datetime, timezone
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from simulator.crm_export import CRMState, generate_export, write_export_folder


def test_basic_functionality():
    """Test basic CRM export generation."""
    print("Testing CRM Export Simulator...")
    print("=" * 60)
    
    # Test 1: Initialize state
    print("\n✓ Test 1: Initialize CRM state")
    state = CRMState.initialize(n_accounts=10, n_stores=20, seed=42)
    assert len(state.accounts) == 10, f"Expected 10 accounts, got {len(state.accounts)}"
    assert len(state.stores) == 20, f"Expected 20 stores, got {len(state.stores)}"
    print(f"  Created {len(state.accounts)} accounts, {len(state.stores)} stores, {len(state.work_orders)} work orders")
    
    # Test 2: Check customer types
    print("\n✓ Test 2: Verify customer type distribution")
    types = {}
    for acc in state.accounts.values():
        code = acc["customer_type_code"]
        types[code] = types.get(code, 0) + 1
    print(f"  Customer types: {types}")
    assert "100000000" in types, "Missing CUSTOMER type"
    
    # Test 3: Check hierarchies
    print("\n✓ Test 3: Verify account hierarchies")
    children = [acc for acc in state.accounts.values() if acc["parent_account_id"]]
    print(f"  Found {len(children)} child accounts")
    for child in children:
        parent_id = child["parent_account_id"]
        assert parent_id in state.accounts, f"Parent {parent_id} not found"
    
    # Test 4: Check store-account links
    print("\n✓ Test 4: Verify store-account linking")
    for store in state.stores.values():
        assert store["account_id"] in state.accounts, f"Store {store['crm_store_id']} references missing account"
        assert store["g2_store_id"].startswith("S"), f"Invalid g2_store_id format: {store['g2_store_id']}"
    print(f"  All {len(state.stores)} stores properly linked to accounts")
    
    # Test 5: Generate export
    print("\n✓ Test 5: Generate CSV export")
    export_time = datetime(2026, 11, 20, 8, 0, 0, tzinfo=timezone.utc)
    csv_files = generate_export(state, export_time)
    
    assert "account.csv" in csv_files
    assert "store.csv" in csv_files
    assert "work_order.csv" in csv_files
    print(f"  Generated 3 CSV files")
    
    # Test 6: Check CSV format
    print("\n✓ Test 6: Verify CSV format")
    for name, content in csv_files.items():
        lines = content.strip().split('\n')
        assert len(lines) > 1, f"{name} has no data rows"
        
        # Check header
        header = lines[0]
        assert "export_ts" in header, f"{name} missing export_ts column"
        
        # Check data rows
        for i, line in enumerate(lines[1:4], 1):  # Check first 3 data rows
            assert "2026-11-20T08:00:00Z" in line, f"{name} row {i} missing correct export_ts"
        
        rows = len(lines) - 1
        print(f"  {name}: {rows} rows")
    
    # Test 7: Evolve state
    print("\n✓ Test 7: Test state evolution")
    original_times = {acc_id: acc["updated_at"] for acc_id, acc in state.accounts.items()}
    
    export_time2 = datetime(2026, 11, 20, 9, 0, 0, tzinfo=timezone.utc)
    state.evolve(change_rate=0.3, export_time=export_time2)
    
    changed = sum(1 for acc_id, acc in state.accounts.items() 
                  if acc["updated_at"] != original_times.get(acc_id))
    change_pct = (changed / len(state.accounts)) * 100
    print(f"  {changed}/{len(state.accounts)} accounts changed ({change_pct:.1f}%)")
    assert changed >= 2, "Expected at least some accounts to change"
    
    # Test 8: Big change mode
    print("\n✓ Test 8: Test big change mode (>50%)")
    state2 = CRMState.initialize(n_accounts=20, seed=99)
    original_times2 = {acc_id: acc["updated_at"] for acc_id, acc in state2.accounts.items()}
    
    export_time3 = datetime(2026, 11, 20, 10, 0, 0, tzinfo=timezone.utc)
    state2.evolve(change_rate=0.1, export_time=export_time3, big_change=True)
    
    changed2 = sum(1 for acc_id, acc in state2.accounts.items() 
                   if acc["updated_at"] != original_times2.get(acc_id))
    change_pct2 = (changed2 / len(state2.accounts)) * 100
    print(f"  {changed2}/{len(state2.accounts)} accounts changed ({change_pct2:.1f}%)")
    assert change_pct2 > 50, f"Big change should exceed 50%, got {change_pct2:.1f}%"
    
    # Test 9: Write to filesystem
    print("\n✓ Test 9: Write export folder")
    test_dir = Path(__file__).parent / "test_output"
    test_dir.mkdir(exist_ok=True)
    
    folder = write_export_folder(test_dir, export_time, csv_files)
    assert folder.exists(), "Export folder not created"
    assert (folder / "manifest.json").exists(), "Manifest not created"
    assert (folder / "account.csv").exists(), "account.csv not created"
    assert (folder / "store.csv").exists(), "store.csv not created"
    assert (folder / "work_order.csv").exists(), "work_order.csv not created"
    
    print(f"  Created: {folder}")
    
    # Test 10: Reproducibility
    print("\n✓ Test 10: Test reproducibility")
    state_a = CRMState.initialize(n_accounts=5, seed=42)
    csv_a = generate_export(state_a, export_time)
    
    state_b = CRMState.initialize(n_accounts=5, seed=42)
    csv_b = generate_export(state_b, export_time)
    
    assert csv_a["account.csv"] == csv_b["account.csv"], "Same seed should produce same output"
    print(f"  ✓ Same seed produces identical output")
    
    print("\n" + "=" * 60)
    print("✅ All tests passed!")
    print("\nCRM Export Simulator is working correctly.")
    print(f"\nTest output written to: {test_dir}")
    
    return 0


if __name__ == "__main__":
    try:
        sys.exit(test_basic_functionality())
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
