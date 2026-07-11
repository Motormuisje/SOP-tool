"""Fase 3 — added_products through the state-sync points (mirrors the
forecast_defaults pattern in tests/test_forecast_defaults.py)."""

from types import SimpleNamespace

import pytest

from ui.config_store import sync_global_config_from_engine
from ui.engine_rebuild import get_config_overrides, get_session_config_overrides
from ui.session_store import load_sessions_from_disk, save_sessions_to_disk

pytestmark = pytest.mark.no_fixture

PRODUCT = {"material_number": "900000001", "name": "Test", "product_type": "bulk",
           "flat_volume": 100.0}


def _engine(added=None):
    return SimpleNamespace(
        data=SimpleNamespace(purchased_and_produced=None, valuation_params=None),
        config_overrides={"added_products": added} if added is not None else {},
    )


# ---------------------------------------------------- get_config_overrides

def test_global_config_feeds_calculate_overrides():
    ov = get_config_overrides({"added_products": [PRODUCT]})
    assert ov["added_products"] == [PRODUCT]
    assert "added_products" not in get_config_overrides({"added_products": []})
    assert "added_products" not in get_config_overrides({})


# -------------------------------------------- get_session_config_overrides

def test_session_products_do_not_leak_from_global_on_rebuild():
    global_config = {"added_products": [PRODUCT]}
    # Cold session without products: [] on load, no engine.
    sess = {"id": "a", "engine": None, "added_products": []}
    assert "added_products" not in get_session_config_overrides(sess, global_config)


def test_session_products_win_over_global():
    other = dict(PRODUCT, material_number="900000002")
    global_config = {"added_products": [PRODUCT]}
    sess = {"id": "b", "engine": None, "added_products": [other]}
    ov = get_session_config_overrides(sess, global_config)
    assert ov["added_products"] == [other]


def test_live_engine_is_fallback_when_session_field_missing():
    sess = {"id": "c", "engine": _engine([PRODUCT])}
    ov = get_session_config_overrides(sess, {})
    assert ov["added_products"] == [PRODUCT]


# ----------------------------------------------------- session persistence

def test_round_trip_engine_authoritative(tmp_path):
    sessions = {"s1": {"id": "s1", "engine": _engine([PRODUCT]),
                       "added_products": [],  # stale session field: engine wins
                       "parameters": {"planning_month": "2025-12"}}}
    store = tmp_path / "sessions_store.json"
    save_sessions_to_disk(sessions, "s1", store, lambda s, e: {})
    loaded, _ = load_sessions_from_disk(store)
    assert loaded["s1"]["added_products"] == [PRODUCT]


def test_round_trip_without_engine_uses_session_field(tmp_path):
    sessions = {"s1": {"id": "s1", "engine": None, "added_products": [PRODUCT],
                       "parameters": {"planning_month": "2025-12"}}}
    store = tmp_path / "sessions_store.json"
    save_sessions_to_disk(sessions, "s1", store, lambda s, e: {})
    loaded, _ = load_sessions_from_disk(store)
    assert loaded["s1"]["added_products"] == [PRODUCT]


def test_old_store_files_default_to_empty_list(tmp_path):
    sessions = {"s1": {"id": "s1", "engine": None,
                       "parameters": {"planning_month": "2025-12"}}}
    store = tmp_path / "sessions_store.json"
    save_sessions_to_disk(sessions, "s1", store, lambda s, e: {})
    # Simulate a pre-Fase-3 store: drop the field entirely.
    import json
    payload = json.loads(store.read_text(encoding="utf-8"))
    payload["sessions"]["s1"].pop("added_products", None)
    store.write_text(json.dumps(payload), encoding="utf-8")
    loaded, _ = load_sessions_from_disk(store)
    assert loaded["s1"]["added_products"] == []


# ------------------------------------------------------------ global mirror

def test_sync_global_mirrors_active_session_and_clears_stale():
    global_config = {"added_products": [dict(PRODUCT, material_number="STALE")]}
    sync_global_config_from_engine(_engine([PRODUCT]), global_config, lambda pap: "")
    assert global_config["added_products"] == [PRODUCT]

    # Active session without products must clear the stale global list.
    sync_global_config_from_engine(_engine(), global_config, lambda pap: "")
    assert global_config["added_products"] == []
