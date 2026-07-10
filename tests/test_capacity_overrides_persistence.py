"""Phase 3 regression tests: persist/restore + replay clear of the new
override stores (`inventory_overrides`, `capacity_overrides`)."""

import json
from types import SimpleNamespace

import pytest

import ui.replay as replay
from ui.session_store import load_sessions_from_disk, save_sessions_to_disk


pytestmark = pytest.mark.no_fixture


def test_capacity_override_survives_save_load(tmp_path):
    store_path = tmp_path / "sessions_store.json"
    sessions = {
        "s1": {
            "id": "s1",
            "file_path": "C:/fixtures/golden.xlsm",
            "filename": "golden.xlsm",
            "engine": None,
            "pending_edits": {
                "04. Inventory||MAT-1||||starting_stock": {
                    "original": 100.0, "new_value": 250.0,
                },
                "07. Capacity utilization||MAT-2||||2025-12": {
                    "original": 0.0, "new_value": 480.0,
                },
            },
            "inventory_overrides": {"MAT-1": 250.0},
            "capacity_overrides": {
                "07. Capacity utilization": {
                    "MAT-2": {"2025-12": 480.0},
                },
                "12. FTE requirements": {
                    "MAT-3": {"2025-12": 5.5, "2026-01": 6.0},
                },
            },
        }
    }

    save_sessions_to_disk(sessions, "s1", store_path, lambda sess, engine: {})

    raw = json.loads(store_path.read_text(encoding="utf-8"))
    saved = raw["sessions"]["s1"]
    assert saved["inventory_overrides"] == {"MAT-1": 250.0}
    assert saved["capacity_overrides"] == sessions["s1"]["capacity_overrides"]

    loaded, active = load_sessions_from_disk(store_path)
    assert active == "s1"
    assert loaded["s1"]["pending_edits"] == sessions["s1"]["pending_edits"]
    assert loaded["s1"]["inventory_overrides"] == {"MAT-1": 250.0}
    assert loaded["s1"]["capacity_overrides"] == sessions["s1"]["capacity_overrides"]


def test_load_old_session_without_override_fields(tmp_path):
    """Sessions written before Phase 3 don't have the override fields.
    Default-handling must produce empty dicts (never None)."""
    store_path = tmp_path / "sessions_store.json"
    legacy_payload = {
        "active_session_id": "s1",
        "sessions": {
            "s1": {
                "id": "s1",
                "filename": "legacy.xlsm",
                "pending_edits": {
                    "01. Demand forecast||MAT-1||||2025-12": {
                        "original": 10.0, "new_value": 12.0,
                    },
                },
                # No inventory_overrides, no capacity_overrides keys
            },
        },
    }
    store_path.write_text(json.dumps(legacy_payload), encoding="utf-8")

    loaded, active = load_sessions_from_disk(store_path)

    assert active == "s1"
    assert loaded["s1"]["inventory_overrides"] == {}
    assert loaded["s1"]["capacity_overrides"] == {}
    # Existing fields remain untouched.
    assert loaded["s1"]["pending_edits"] == legacy_payload["sessions"]["s1"]["pending_edits"]


def test_replay_clears_override_stores_first():
    """Stale override entries from disk must be cleared at the start of
    replay; otherwise replaying a now-empty pending_edits would still leave
    them populated and double-applied next round."""
    sess = {
        "pending_edits": {},
        "inventory_overrides": {"M1": 999.0},
        "capacity_overrides": {
            "07. Capacity utilization": {"M2": {"2025-12": 480.0}},
        },
        "machine_overrides": {},
    }
    engine = SimpleNamespace()

    replay.replay_pending_edits(
        sess,
        engine,
        lambda *args, **kwargs: pytest.fail("no pending edits to replay"),
        lambda e, overrides: False,
        lambda e, s: None,
    )

    assert sess["inventory_overrides"] == {}
    assert sess["capacity_overrides"] == {}
