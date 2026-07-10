# Phase 2 — UI Wiring Review (`ui/volume_change.py`)

Code review of Phase 2 changes to `ui/volume_change.py`, where the new
`override_initial_stock` (L4) and `capacity_overrides` (L7/L9/L11/L12) edit
paths get wired into `apply_volume_change` and the cascade helpers. Up to
10 findings, scoped to this file.

### 1. `apply_volume_change` cognitive complexity is now untenable
- **Severity**: med
- **Location**: ui/volume_change.py — `apply_volume_change` body
  (~280 lines, ~95 cognitive complexity per linter).
- **Observation**: Each new line-type branch piles onto an already-deep
  function. SonarLint reports cognitive complexity ~97 (limit 15). The L06
  block alone is ~120 lines; the new L4/L7/L9/L11/L12 branches add another
  ~35. Future edits (e.g. L08 dependent requirements direct edit, if ever
  added) will be unsafe to merge here.
- **Suggestion**: Extract per-line-type handlers
  (`_handle_min_target_stock_edit`, `_handle_l06_edit`, …,
  `_handle_inventory_edit`, `_handle_capacity_edit`) so `apply_volume_change`
  becomes a thin dispatcher. Keep the prelude (validation, manual_edits,
  pending_edits, undo) shared. Pure refactor — no behavioural change.
- **Action**: defer (own ticket, ideally in Phase 3 cleanup).

### 2. L7/L9/L11 and L12 branches are textually identical
- **Severity**: low
- **Location**: ui/volume_change.py:573-589 (new branches).
- **Observation**: Both branches do the same three statements
  (`setdefault('capacity_overrides', {})`, nested setdefault store, then
  `recalculate_capacity_and_values`). SonarLint S1871 flags the duplication.
  They are kept separate for documentation clarity (the L12 branch carries a
  comment explaining why we still do a full capacity recalc).
- **Suggestion**: Merge into a single branch
  `line_type in (CAPACITY_UTILIZATION, AVAILABLE_CAPACITY,
  SHIFT_AVAILABILITY, FTE_REQUIREMENTS)` and put the L12 explanation in a
  block comment above the branch. Drops the duplication without losing
  intent.
- **Action**: fix-now (trivial; left as-is per spec, flagged for follow-up).

### 3. `manual_edits` tracking is asymmetric across line types
- **Severity**: med
- **Location**: ui/volume_change.py:386-394 (shared prelude) vs. new
  branches.
- **Observation**: The prelude unconditionally writes `target_row.manual_edits`
  for every editable line type, including the new L4/L7/L9/L11/L12 cells. For
  L01/L05/L06 the cascade then preserves those markers explicitly
  (see `prior_prod_edits`, `prior_purch_edits`, `l05_saved_edits`). For
  L7/L9/L11/L12 the rebuild via `recalculate_capacity_and_values` discards
  rows entirely and re-creates them — the just-set `manual_edits` is lost.
  For L4 starting_stock, `manual_edits[period='starting_stock']` is set on a
  row that gets rebuilt by `recalc_one_material`, so it is also lost.
- **Suggestion**: Either (a) skip the manual_edits write in the new branches
  and rely on `pending_edits` + override stores as the source of truth; or
  (b) re-attach manual_edits markers post-rebuild. Phase 3 should pick a
  policy — current behaviour means the UI cannot show "edited" indicators
  on L4/L7/L9/L11/L12 cells across a recalc.
- **Action**: defer (Phase 3 decision; document in PR).

### 4. `pending_edits` for L4 stores period sentinel `'starting_stock'`
- **Severity**: low
- **Location**: ui/volume_change.py:400-408 (shared prelude) +
  ui/volume_change.py:558-571 (L4 branch).
- **Observation**: `pending_edit_key(line_type, mat, aux, 'starting_stock')`
  is well-defined and replays cleanly through `apply_volume_change`, which
  re-checks the sentinel in the L4 branch. But replay reads the value from
  `pending_edits`, not from `inventory_overrides`. If Phase 3 only persists
  one of the two, the other becomes stale.
- **Suggestion**: Phase 3 should treat `pending_edits` as the canonical
  store and rebuild `inventory_overrides` from it on load (or vice-versa).
  Avoid double sources of truth.
- **Action**: defer (Phase 3).

### 5. `recalc_material_subtree` no longer documents which params are
"root-only"
- **Severity**: low
- **Location**: ui/volume_change.py:259-280.
- **Observation**: Docstring now mentions `override_initial_stock` is
  root-only, but `root_override_target_stock(_values)` and
  `override_root_forecast` already had the same property and weren't
  documented. The new param uses a different naming convention
  (`override_initial_stock` vs. `root_override_…`).
- **Suggestion**: Either rename to `root_override_initial_stock` for
  consistency, or rename the others on a future cleanup pass. Mention all
  root-only params in the docstring.
- **Action**: defer (naming only).

### 6. `is_l4_starting_stock` flag duplicates the line-type check
- **Severity**: low
- **Location**: ui/volume_change.py:375-385 and 558-571.
- **Observation**: We check `line_type == LineType.INVENTORY.value and
  period == 'starting_stock'` twice — once in the prelude (to swap the
  attribute read), once in the cascade branch. Drift risk if one site is
  updated.
- **Suggestion**: Compute once at top of function and store on `sess` or a
  local, reused below.
- **Action**: fix-now if dispatcher refactor (#1) lands; otherwise defer.

### 7. L4 cascade does not validate `material_number` actually exists in BOM
- **Severity**: low
- **Location**: ui/volume_change.py:558-571.
- **Observation**: We pass `material_number` straight into
  `recalc_material_subtree`. If the L4 row is for a synthetic material
  (e.g. truck/control-room ZZZZ entries) the subtree walker may produce
  unexpected results because those materials aren't part of the BOM.
- **Suggestion**: Guard with `if material_number in
  current_engine.data.materials` and short-circuit to a value-only recalc
  otherwise.
- **Action**: defer (the broader truck/control-room edit policy is
  Phase 0 finding #4 territory).

### 8. `recalculate_capacity_and_values` now silently mutates engine state
   based on a session field
- **Severity**: low
- **Location**: ui/volume_change.py:312-329.
- **Observation**: The function previously read only engine state. Now it
  reads `sess.get('capacity_overrides', {})`. Callers passing
  `sess=None` (legacy paths, e.g. some test scaffolding) get the same
  behaviour as before via the `if sess else {}` guard, but any code that
  passes a stale dict copy will see drift between override store and
  engine output.
- **Suggestion**: Document the new dependency in the docstring; consider
  taking `capacity_overrides` as an explicit kwarg with `sess` extraction
  at the call site, to make the dependency injection explicit.
- **Action**: defer.

### 9. No bounds / sanity check on numeric edit values for new branches
- **Severity**: low
- **Location**: ui/volume_change.py:564, 579, 588.
- **Observation**: We do `float(new_value)` and store. Negative starting
  stock, negative capacity hours, or absurdly large FTE values are accepted
  silently. L06 had a ceiling rounding for lot multiples; nothing analogous
  for the new line types.
- **Suggestion**: Reject negatives for L4 starting_stock and L11 shift
  hours. Optionally cap L7 at L9 (utilization-rate sanity) — but that's a
  policy decision.
- **Action**: defer (validation is a UI policy concern).

### 10. Existing recalc paths are not trivially understandable
- **Severity**: med
- **Location**: ui/volume_change.py — `recalc_one_material` (~150 lines)
  and the L06 block in `apply_volume_change` (~120 lines).
- **Observation**: Both contain near-duplicate logic for inventory rebuild
  + manual_edits preservation + BOM cascade. Maintainers must understand
  both to safely add a new edit path. The Phase 2 work didn't introduce
  this, but adding L4/L7/L9/L11/L12 makes the duplication more glaring —
  e.g. if a future bug requires preserving `starting_stock` markers, both
  copies need updating.
- **Suggestion**: Consolidate into a single
  `_rebuild_inventory_for_material(...)` helper used by both call sites.
  Out-of-scope for Phase 2 but a strong candidate for the Phase 3 cleanup
  branch.
- **Action**: defer.

## Summary

Phase 2 wires up the override stores correctly and tests pass, but
`apply_volume_change` is now ~280 lines and 97 cognitive complexity. The
strongest follow-up is finding #1 (dispatcher refactor) — it would also
absorb #2, #6, and partially #10. Findings #3 and #4 require a Phase 3
policy decision on which session store is canonical for which line types.
