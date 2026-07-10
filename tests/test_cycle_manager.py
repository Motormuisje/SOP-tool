from pathlib import Path

import pandas as pd
import pytest

from modules.cycle_manager import CycleManager


pytestmark = pytest.mark.no_fixture


def test_cycle_manager_missing_snapshot_returns_empty_frame(tmp_path):
    manager = CycleManager(str(tmp_path))

    assert manager.has_previous_cycle() is False
    assert manager.load_previous_cycle().empty
    assert manager.load_metadata() == {}


def test_cycle_manager_load_previous_cycle_returns_empty_when_corrupt(tmp_path, monkeypatch):
    manager = CycleManager(str(tmp_path))
    manager._path.write_bytes(b"not parquet")

    def _raise_read(path):
        raise RuntimeError(f"bad parquet: {path}")

    monkeypatch.setattr(pd, "read_parquet", _raise_read)

    loaded = manager.load_previous_cycle()

    assert loaded.empty


def test_cycle_manager_save_current_as_previous_writes_snapshot_and_metadata(
    tmp_path,
    monkeypatch,
):
    manager = CycleManager(str(tmp_path))
    captured = {}

    def _fake_to_parquet(self, path, index=False):
        captured["path"] = Path(path)
        captured["index"] = index
        captured["df"] = self.copy()
        Path(path).write_bytes(b"parquet")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", _fake_to_parquet)
    df = pd.DataFrame(
        {
            "material": ["MAT-1", None],
            "value": [10.0, 20.0],
            "mixed": [{"a": 1}, "text"],
        }
    )

    manager.save_current_as_previous(df, planning_month="2025-12")

    assert captured["path"] == manager._path
    assert captured["index"] is False
    assert manager.has_previous_cycle() is True
    assert manager.load_metadata() == {"planning_month": "2025-12"}
    assert captured["df"]["material"].iloc[0] == "MAT-1"
    assert pd.isna(captured["df"]["material"].iloc[1])
    assert captured["df"]["mixed"].tolist() == ["{'a': 1}", "text"]


def test_cycle_manager_load_metadata_returns_empty_for_corrupt_json(tmp_path):
    manager = CycleManager(str(tmp_path))
    manager._meta_path.write_text("{bad json", encoding="utf-8")

    assert manager.load_metadata() == {}


def test_cycle_manager_clear_removes_snapshot_and_metadata(tmp_path):
    manager = CycleManager(str(tmp_path))
    manager._path.write_bytes(b"parquet")
    manager._meta_path.write_text('{"planning_month": "2025-12"}', encoding="utf-8")

    manager.clear()

    assert manager.has_previous_cycle() is False
    assert not manager._meta_path.exists()
