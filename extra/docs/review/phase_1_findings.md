# Phase 1 — Engine Override Layer Review

Code review of changes to `modules/inventory_engine.py` and
`modules/capacity_engine.py` after adding `override_initial_stock` (L4) and
the L7/L9/L11/L12 override mechanism. Up to 10 findings, scoped to the
touched files.

### 1. L7 override scope is silently group-only
- **Severity**: med
- **Location**: modules/capacity_engine.py:175-182 (in `_apply_user_overrides`)
- **Observation**: For L7 we filter to `product_type == 'Machine Group'`. Material- and machine-level rows for the same period stay at the original computed value, so the L7 group total in the UI no longer equals the sum of its machine rows after a group override.
- **Suggestion**: Document the asymmetry in the docstring and surface it in the UI (e.g. show overridden cell in a colour) — or keep machine totals consistent by also rebuilding them.
- **Action**: defer (UI/policy decision; out-of-scope for engine layer).

### 2. L10 utilization rate `aux_column` recomputed even when no L7/L9 overrides applied
- **Severity**: low
- **Location**: modules/capacity_engine.py:225-227
- **Observation**: `_recalculate_utilization_rate` always runs in `calculate()`, so it recomputes L10 row values + average aux even when `self.overrides` is empty. Net effect should be identical to the first pass, but it's wasted work and re-derives `avg_rate` formatting independently.
- **Suggestion**: Skip the call when `self.overrides` does not contain L7 or L9 entries.
- **Action**: fix-now (trivial guard).

### 3. L10 average uses raw float instead of original formatting path
- **Severity**: low
- **Location**: modules/capacity_engine.py:223-224
- **Observation**: `aux_column = str(avg)` — `_calculate_utilization_rate` originally also writes `str(avg_rate)`, so behaviour matches, but if that formatting ever gets a `round` or `f"{avg:.4f}"` the recalc path will diverge silently.
- **Suggestion**: Extract the avg-formatting into a helper used by both passes.
- **Action**: defer.

### 4. `_apply_override` helper is unused
- **Severity**: low
- **Location**: modules/capacity_engine.py:148-156
- **Observation**: Helper added per spec, but `_apply_user_overrides` walks `self.overrides` directly with `.get()` chains and never calls it. Dead code attracts confusion.
- **Suggestion**: Either use it inside `_apply_user_overrides` per cell, or remove it.
- **Action**: fix-now (remove or wire in).

### 5. `override_initial_stock` not propagated to engine result dict
- **Severity**: low
- **Location**: modules/inventory_engine.py:154-157, 327-336
- **Observation**: The chosen `initial_stock` is used internally and surfaces as `starting_stock` on the L4 row, but the returned dict does not expose it. Callers wanting to verify which value won (override vs. data lookup) must read it off the L4 row.
- **Suggestion**: Add `'starting_stock': initial_stock` to the result dict.
- **Action**: defer.

### 6. Override structure has no schema/validation
- **Severity**: med
- **Location**: modules/capacity_engine.py:25-31
- **Observation**: `overrides` is `Dict[str, Dict[str, Dict[str, float]]]`. Misspelled line-type keys, integer values, or wrong period keys all silently no-op. A typo in the UI layer becomes invisible.
- **Suggestion**: Validate in `__init__` — known line-type keys, numeric leaves, period keys in `data.periods`. Raise on unknown line type; warn on unknown code/period.
- **Action**: defer (ticket — the UI plumbing is out of scope for this phase).

### 7. L10 recalc skips UNLIMITED machines unconditionally
- **Severity**: low
- **Location**: modules/capacity_engine.py:204-205
- **Observation**: Mirrors the original `_calculate_utilization_rate` path (rate=1.0 for UNLIMITED). Correct, but if the user overrides L9 for an UNLIMITED machine the override on L9 sticks while L10 stays 1.0 — an inconsistency between L9 and L10 the user can produce.
- **Suggestion**: Either reject L9 overrides for UNLIMITED machines or recompute L10 from the override.
- **Action**: defer (edge case; needs product policy).

### 8. Site-exception/override interaction is correct but undocumented
- **Severity**: low
- **Location**: modules/capacity_engine.py:60-69 (`calculate` flow)
- **Observation**: Order is: base calc → site exceptions → L9/L10/L11/L12 → user overrides → L10 recalc. User wins, which is the intended policy from phase 0. Not stated in the engine docstring.
- **Suggestion**: Add a short comment block at the top of `calculate()` explaining the precedence.
- **Action**: fix-now (documentation, trivial).

### 9. `_recalculate_utilization_rate` reads only machine-level L7 rows
- **Severity**: med
- **Location**: modules/capacity_engine.py:184-189
- **Observation**: We rebuild L10 from `rows_07_cap` rows where `product_type == 'Machine'`. But L7 user overrides only touch `'Machine Group'` rows (finding 1). Therefore an L7 group override does NOT propagate into L10 at all — a hidden invariant.
- **Suggestion**: Either explicitly document "L10 recalc reflects L9 overrides only; L7 overrides at group level do not affect L10" or push group-level L7 overrides down to constituent machine rows before L10 recalc.
- **Action**: defer (needs a clear product decision; tests confirm the L9-only L10 path works).

### 10. Magic string `'Machine Group'` repeated
- **Severity**: low
- **Location**: modules/capacity_engine.py: multiple (incl. new `_apply_user_overrides`)
- **Observation**: Pre-existing in the file; the new code adds another instance (line 178). The IDE flagged it (8 occurrences total).
- **Suggestion**: Extract a module-level constant `MACHINE_GROUP_PRODUCT_TYPE = 'Machine Group'`.
- **Action**: defer (ticket — broader cleanup, out of scope).

## Summary

Engine-layer override path is functional and covered by 10 unit tests
(3 inventory, 7 capacity). Two findings worth fixing now (low-risk
trivial: guard L10 recalc when overrides empty; remove or use
`_apply_override`; add comment to `calculate()`); the rest are deferred
policy/UX questions or pre-existing code-style issues out of scope for
this phase.
