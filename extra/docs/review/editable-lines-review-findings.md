# Editable Lines Review Findings

Review date: 2026-05-05

Golden fixture used:

```powershell
C:\Users\stijn\Desktop\SOP_GOLDEN_FIXTURE.xlsm
```

PAP guardrail: the golden fixture run did not load `PurchasedAndProduced`
entries. Do not add PAP entries to golden Python expectations; keep PAP as a
separate UI/config/session override scenario.

## Findings

### High — L7 and L11 overrides do not cascade to the derived capacity lines promised by the feature

Files:

- `modules/capacity_engine.py:157`
- `modules/capacity_engine.py:178`
- `modules/capacity_engine.py:188`
- `modules/capacity_engine.py:199`
- `modules/capacity_engine.py:585`
- `modules/capacity_engine.py:625`
- `modules/capacity_engine.py:687`

`CapacityEngine.calculate()` computes L11, L9, L10, and L12 before applying
user overrides. `_apply_user_overrides()` then mutates group-level L7 rows and
L11 rows, and only `_recalculate_utilization_rate()` is run afterward.

That recomputation reads machine-level L7 rows, not group-level L7 rows:

- L7 overrides are explicitly limited to `product_type == 'Machine Group'`.
- L10 recomputation builds `machine_hours` only from `product_type == 'Machine'`.
- L12 is calculated from `group_hours_aggregated` before L7 overrides are
  applied and is not recomputed afterward.
- L11 overrides are applied after L9/L10 have already been calculated, and
  `_get_shift_hours_for_machine()` reads static shift-hour lookup/config, not
  overridden L11 rows.

Runtime probe on the existing capacity test fixture:

```text
base_l10 0.21367521367521367
l7_group 999.0
l7_l10 0.21367521367521367
base_l12 0.8042895442359249
l7_l12 0.8042895442359249
base_l9 0.9
l11_row 999.0
l11_l9 0.9
l11_l10 0.21367521367521367
```

Impact:

- Editing L7 changes the displayed L7 group row but does not change L10 or L12.
- Editing L11 changes the displayed L11 row but does not change L9 or L10.
- Dashboard/capacity/value views can look refreshed while still showing derived
  values from the pre-edit capacity model.

Suggested next step:

Decide the intended math contract first. If L7 group edits are user-facing
aggregate edits, propagate them into the source used by L10/L12 or recompute
derived group/machine views from override-aware structures. If L11 is intended
to drive L9/L10, apply it before L9/L10 or make those calculations read the
override-aware shift availability.

### Medium — Capacity override edits lose `manual_edits` markers after recalc

Files:

- `ui/volume_change.py:397`
- `ui/volume_change.py:592`
- `ui/volume_change.py:601`
- `modules/capacity_engine.py:157`
- `ui/routes/edits.py:218`
- `ui/routes/edits.py:226`

`apply_volume_change()` writes `target_row.manual_edits` before calling
`recalculate_capacity_and_values()`. That function rebuilds the capacity rows
from `CapacityEngine.calculate()`. `_apply_user_overrides()` mutates `row.values`
but does not restore or create `manual_edits` entries on the new capacity rows.

Runtime probe on the golden fixture after an L9 edit:

```text
pending_keys ['09. Available capacity||Z_MACH01||||2025-12']
override 1.01
manual_edits {}
```

Impact:

- UI edit indicators for L7/L9/L11/L12 are missing after the recalc.
- `/api/edits/export` scans `current_engine.results` for `row.manual_edits`, so
  capacity edits may be absent from exported edits even though they survive in
  `pending_edits`.
- Scenario snapshots that derive pending edits from result-row `manual_edits`
  risk dropping these capacity edits.

Suggested next step:

Populate `manual_edits` for capacity override rows during
`_apply_user_overrides()` or immediately after capacity rebuild using
`sess['pending_edits']`. Keep the canonical key format
`line_type||material_number||aux_column||period`.

### Medium — Test suite covers L9-to-L10 but not the claimed L7/L11 derived cascades

Files:

- `tests/test_capacity_engine_overrides.py:117`
- `tests/test_capacity_engine_overrides.py:165`
- `tests/test_capacity_engine_overrides.py:186`
- `tests/test_capacity_engine_overrides.py:207`

The current tests prove target cells change, and they prove L9 affects L10.
They do not assert:

- L7 affects L10.
- L7 affects L12.
- L11 affects L9.
- L11 affects L10.
- L11 does not affect L12.
- L12 does not affect upstream capacity rows.

This is why the high-severity cascade issue is currently green in CI.

Suggested next step:

Add focused unit tests before changing code. Mark the current behavior with
failing expectations that encode the feature contract, then fix the engine.

### Medium — Browser tests do not verify chart correctness or nonblank rendering

Files:

- `tests/browser/test_load.py:43`
- `ui/templates/index.html:844`
- `ui/templates/index.html:914`
- `ui/templates/index.html:921`
- `ui/templates/index.html:2719`
- `ui/templates/index.html:2806`
- `ui/templates/index.html:2850`

The browser suite checks page load, planning-table rendering, basic demand
edits, machine edits, and sessions. It does not check that dashboard/capacity
charts render nonblank canvases or update after the new editable-line edits.

The run with the supplied golden fixture passed, but the terminal summary still
reported transient resource-load console entries:

```text
BROWSER_CONSOLE_ERRORS=Failed to load resource: net::ERR_NETWORK_CHANGED |
Failed to load resource: net::ERR_NETWORK_CHANGED |
Failed to load resource: net::ERR_INTERNET_DISCONNECTED
```

These are ignored by `page.js_errors`, but they show why chart tests should be
robust and should inspect the rendered canvases directly.

Suggested next step:

Add a browser chart smoke test that:

- opens dashboard and capacity tabs
- asserts `financialChart`, `utilChart`, `fteChart`, and inventory-quality
  charts are visible
- samples canvas pixels to assert nonblank rendering
- edits L9 and verifies utilization chart data/pixels change
- edits L12 and verifies FTE/value chart data/pixels change without requiring
  unrelated planning-row changes

### Low — L12 uses full capacity recalculation for a leaf edit

Files:

- `ui/volume_change.py:595`
- `ui/volume_change.py:602`

The code intentionally sends L12 through `recalculate_capacity_and_values()` for
consistency. This is safe but broader than necessary if L12 remains a leaf that
only value planning consumes.

Suggested next step:

Defer until correctness is fixed. Later, consider a value-only path for L12 if
tests prove it does not need upstream capacity recalculation.

## Verification Run

Commands run:

```powershell
$env:SOP_TEST_FILE='C:\Users\stijn\Desktop\SOP_GOLDEN_FIXTURE.xlsm'
python main.py --test

$env:SOP_GOLDEN_FIXTURE='C:\Users\stijn\Desktop\SOP_GOLDEN_FIXTURE.xlsm'
pytest -v tests/browser
```

Results:

- `python main.py --test`: passed; 1973 total rows; 15 line types; no
  `PurchasedAndProduced` entries loaded from the fixture.
- `pytest -v tests/browser`: 17 passed in 209.69s.

Earlier full-suite status after license removal and UI review fixes:

- `pytest -v`: 464 passed, 1 skipped.

## Recommended Fix Order

1. Add failing tests for L7/L11 derived cascades.
2. Fix `CapacityEngine` override ordering/data flow.
3. Restore `manual_edits` markers for capacity override rows.
4. Add export/scenario tests proving capacity edits are not dropped.
5. Add browser nonblank chart smoke tests with the supplied golden fixture.

## Fix Pass Notes

Applied after this review:

- Added L7/L11 cascade tests in `tests/test_capacity_engine_overrides.py`.
- Changed `CapacityEngine` so driver overrides are applied before derived
  recomputation:
  - L7 group overrides update group hours for L12.
  - L7 group overrides are distributed across machines in that group for L10.
  - L11 overrides are used as period-specific shift hours for L10.
  - L12 leaf overrides are applied after regenerated L12 rows.
- Added `restore_manual_edits_from_pending()` in `ui/volume_change.py` so rows
  rebuilt during recalc regain their canonical edit markers from
  `pending_edits`.
- Added `tests/test_edit_capacity_overrides.py` covering L9 and L4 manual edit
  marker restoration after recalc.

Remaining review items:

- Add export/scenario tests proving L7/L9/L11/L12 edits are not dropped.
- Add browser nonblank chart smoke tests for dashboard/capacity/value charts.
- Decide later whether L12 can use a value-only recalc path for performance.

Verification after fix pass:

```powershell
python -m py_compile modules/capacity_engine.py ui/volume_change.py tests/test_capacity_engine_overrides.py tests/test_edit_capacity_overrides.py
$env:SOP_TEST_FILE='C:\Users\stijn\Desktop\SOP_GOLDEN_FIXTURE.xlsm'; python main.py --test
pytest -v tests/test_capacity_engine_overrides.py tests/test_edit_capacity_overrides.py
```

All passed.

Full-suite note:

```powershell
$env:SOP_GOLDEN_FIXTURE='C:\Users\stijn\Desktop\SOP_GOLDEN_FIXTURE.xlsm'; pytest -v
```

Result: 464 passed, 4 skipped, 1 failed. The failure was
`tests/test_golden_pipeline.py::test_baseline_exists` because
`C:\Users\stijn\Desktop\golden_baseline.json` does not exist. No baseline was
generated automatically.
