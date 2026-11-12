"""Small core fixes from the 2026-11 re-check of the bug register.

Each test names the register entry it pins. None of these changes a planning
number on a valid workbook; the golden pipeline tests guard that separately.
"""

import pandas as pd
import pytest

from modules.cycle_manager import CycleManager
from modules.models import LineType, ProductType
from tests.test_inventory_engine import _engine, _make_data


pytestmark = pytest.mark.no_fixture


def _frame(value):
    return pd.DataFrame({"Material number": ["MAT-1"], "2025-01": [value]})


def test_failed_snapshot_write_keeps_the_previous_cycle(tmp_path, monkeypatch):
    """BUGS.md L7. The snapshot is written beside the target and swapped in,
    so a write that fails halfway leaves the previous cycle readable and no
    temporary file behind."""
    manager = CycleManager(str(tmp_path))
    manager.save_current_as_previous(_frame(1.0), planning_month="2025-01")

    def _disk_full(self, path, *args, **kwargs):
        with open(path, "wb") as handle:
            handle.write(b"half a parquet")
        raise OSError("No space left on device")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", _disk_full)
    with pytest.raises(OSError):
        manager.save_current_as_previous(_frame(2.0), planning_month="2025-02")
    monkeypatch.undo()

    assert manager.load_previous_cycle()["2025-01"].tolist() == [1.0]
    assert manager.load_metadata() == {"planning_month": "2025-01"}
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        CycleManager.META_FILENAME, CycleManager.DEFAULT_FILENAME]


def test_successful_snapshot_write_replaces_both_files(tmp_path):
    manager = CycleManager(str(tmp_path))
    manager.save_current_as_previous(_frame(1.0), planning_month="2025-01")
    manager.save_current_as_previous(_frame(2.0), planning_month="2025-02")

    assert manager.load_previous_cycle()["2025-01"].tolist() == [2.0]
    assert manager.load_metadata() == {"planning_month": "2025-02"}
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        CycleManager.META_FILENAME, CycleManager.DEFAULT_FILENAME]


def _purchase_result(purchase_actuals):
    data = _make_data(
        product_type=ProductType.RAW_MATERIAL,
        is_bom_parent=False,
        has_routing=False,
        in_purchase_sheet=True,
        safety_stock=100.0,
        initial_stock=0.0,
        lead_time=1,
        purchase_moq=1.0,
        purchase_actuals=purchase_actuals,
    )
    forecast = {"2025-01": 0.0, "2025-02": 50.0, "2025-03": 50.0}
    return _engine(data).calculate_for_material("MAT-1", forecast, {}, {})


def test_raw_need_of_a_month_locked_by_a_po_actual_is_not_reported():
    """BUGS.md L3. The first pass records a raw need for the first flexible
    month; a PO actual then locks that month. The stale need used to stay and
    showed a MOQ warning on a receipt the heuristic no longer decides."""
    locked = _purchase_result({"MAT-1": {"2025-02": 500.0}})

    receipt = next(r for r in locked["rows"] if r.line_type == LineType.PURCHASE_RECEIPT.value)
    assert receipt.values["2025-02"] == pytest.approx(500.0)
    assert "2025-02" not in locked["purch_raw_need"]
    # 500 received covers the later months: their need disappeared as well.
    assert locked["purch_raw_need"] == {}


def test_raw_need_is_still_recorded_for_months_the_heuristic_decides():
    """The clear must not swallow needs the re-run really computes: with an
    actuals row that locks nothing, every flexible month keeps its need."""
    free = _purchase_result({"MAT-1": {"2025-01": 0.0}})

    assert set(free["purch_raw_need"]) == {"2025-02", "2025-03"}
    assert all(need > 0 for need in free["purch_raw_need"].values())
