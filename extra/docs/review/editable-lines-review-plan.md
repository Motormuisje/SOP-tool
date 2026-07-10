# Editable Lines Review Plan

## Review goal

Review the editable-lines work for correctness, efficiency, and bug risk.
Primary invariant:

> A live edit sequence must produce the same final engine, table, value, and
> chart state as a clean rebuild followed by replaying `pending_edits`.

## Golden fixture

Use:

```powershell
$env:SOP_GOLDEN_FIXTURE = "C:\Users\stijn\Desktop\SOP_GOLDEN_FIXTURE.xlsm"
```

This workbook is the source of truth for golden/browser review. Do not add
Python-side expectations that are not present in the workbook.

## PAP guardrail

PAP (`purchased_and_produced`) products are not present in the golden Excel.
During this review:

- Do not copy PAP products into Python baselines or fixtures.
- Treat PAP as a UI/config/session override only.
- Golden pipeline tests should assert the workbook-derived state, not a
  manually injected PAP state.
- PAP-specific tests may use small synthetic fixtures, but must be clearly
  separated from golden workbook expectations.
- If a chart or value difference only appears after manually setting PAP,
  label that finding as a PAP override scenario, not a golden regression.

## Review matrix

| Line | Editable surface | Storage | Expected cascade | Key risk |
|---|---|---|---|---|
| L4 Inventory | `starting_stock` only | `pending_edits`, `inventory_overrides` | inventory subtree, capacity, values | period cells accidentally editable; replay drift |
| L7 Capacity utilization | machine-group period cells only | `pending_edits`, `capacity_overrides` | L10, values | material/machine rows editable but ignored |
| L9 Available capacity | machine period cells | `pending_edits`, `capacity_overrides` | L10, values | percent display vs raw fractional value |
| L10 Utilization rate | not editable | none | derived from L7/L9 | inverse edit ambiguity |
| L11 Shift availability | shift-system period cells | `pending_edits`, `capacity_overrides` | L9, L10, values; not L12 | accidental L12 cascade |
| L12 FTE requirements | group period cells | `pending_edits`, `capacity_overrides` | values only | full capacity recalc may be too broad |

## Correctness pass

Review in this order:

1. `ui/volume_change.py`
2. `modules/inventory_engine.py`
3. `modules/capacity_engine.py`
4. `ui/replay.py`
5. `ui/session_store.py`
6. `ui/engine_rebuild.py`
7. `ui/templates/index.html`

For every editable line, verify:

- row lookup uses the correct material/group/machine/shift identity
- edit writes the canonical pending edit key
- override store is populated and cleared at the right moments
- undo, redo, reset, session switch, and restart are deterministic
- value results and downstream charts refresh from the recalculated data

## Efficiency pass

Check whether any edit path recalculates more than necessary:

- L12 currently routes through capacity + values for consistency; decide if
  value-only recalc is safe enough as a later optimization.
- Frontend table refresh should avoid O(rows x cells) lookups where practical.
- Chart refresh should not redraw unrelated heavy views after leaf edits unless
  those views consume the changed data.

## Chart regression plan

Use Playwright with the golden fixture for robust chart smoke tests:

- open app, upload/calculate golden fixture
- assert no browser console errors
- visit dashboard, capacity, inventory, value-planning views
- assert chart containers are visible and non-empty
- for canvas charts, sample pixels to ensure the canvas is not blank
- assert expected period labels are visible
- perform one edit per editable line and verify dependent chart data changes
  only where expected

For visual regression:

- capture screenshots of known-good dashboard/capacity/inventory/value views
- compare future screenshots with a small pixel tolerance
- keep screenshot baselines separate from golden numeric baselines because
  fonts and browser rendering can vary

## Test commands

```powershell
$env:SOP_GOLDEN_FIXTURE = "C:\Users\stijn\Desktop\SOP_GOLDEN_FIXTURE.xlsm"
python main.py --test
pytest -v
```

Targeted review commands:

```powershell
pytest -v tests/test_edit_l4_starting_stock.py
pytest -v tests/test_capacity_engine_overrides.py tests/test_inventory_engine_overrides.py
pytest -v tests/browser
```

## Deliverables

- Findings ordered by severity, with file/line references.
- A test-gap list split into correctness, replay/session, and browser/chart.
- Small follow-up commits per accepted finding; do not batch unrelated fixes.
