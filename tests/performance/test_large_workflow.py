import time
from types import SimpleNamespace

import pytest

from modules.models import LineType, PlanningRow
from modules.planning_engine import PlanningEngine
from ui.pending_edits import pending_edit_key
from ui.replay import replay_pending_edits


pytestmark = pytest.mark.performance


def _row(material, line_type, periods):
    return PlanningRow(
        material_number=material,
        material_name=f"Material {material}",
        product_type="Bulk Product",
        product_family="Family",
        spc_product="SPC",
        product_cluster="Cluster",
        product_name="Product",
        line_type=line_type,
        aux_column="",
        aux_2_column="",
        starting_stock=0.0,
        values={period: 1.0 for period in periods},
    )


def test_replay_pending_edits_large_batch_stays_linear():
    periods = [f"2026-{month:02d}" for month in range(1, 13)]
    pending = {}
    for material_idx in range(100):
        material = f"MAT-{material_idx:03d}"
        for period in periods:
            key = pending_edit_key(
                LineType.DEMAND_FORECAST.value,
                material,
                "",
                period,
            )
            pending[key] = {"original": 1.0, "new_value": 2.0}

    calls = []

    def apply_volume_change(*args, **kwargs):
        calls.append((args[2], args[3], args[4], args[5], kwargs.get("push_undo")))
        return SimpleNamespace(get_json=lambda silent=True: {"success": True})

    started = time.perf_counter()
    replay_pending_edits(
        {"pending_edits": pending},
        object(),
        apply_volume_change,
        lambda engine, overrides: False,
        lambda engine, sess: None,
    )
    elapsed = time.perf_counter() - started

    assert len(calls) == len(pending)
    assert all(call[-1] is False for call in calls)
    assert elapsed < 5.0


def test_compile_summary_dataframe_large_synthetic_result_set():
    periods = [f"2026-{month:02d}" for month in range(1, 13)]
    line_types = [
        LineType.DEMAND_FORECAST.value,
        LineType.TOTAL_DEMAND.value,
        LineType.PRODUCTION_PLAN.value,
        LineType.INVENTORY.value,
        LineType.PURCHASE_RECEIPT.value,
        LineType.DEPENDENT_DEMAND.value,
    ]
    engine = PlanningEngine()
    engine.data = SimpleNamespace(
        periods=periods,
        materials={f"MAT-{material_idx:03d}": object() for material_idx in range(200)},
        bom=[],
        machines={},
        machine_groups={},
    )
    for line_type in line_types:
        engine.results[line_type] = [
            _row(f"MAT-{material_idx:03d}", line_type, periods)
            for material_idx in range(200)
        ]

    started = time.perf_counter()
    engine._compile_all_rows()
    engine._generate_summary()
    frame = engine.to_dataframe()
    elapsed = time.perf_counter() - started

    assert len(engine.all_rows) == 1200
    assert engine.summary["total_rows"] == 1200
    assert len(frame) == 1200
    assert elapsed < 5.0
