# Phase 0 — Scope Verification Report

Verified the editable-lines proposal (L4 starting stock, L7, L9, L11, L12 — L10 explicitly out of scope) against the codebase. Findings below drive Phase 1+ scope.

## 1. Per-line verification

### L4 — Starting stock — PASS (with caveats)
- `InventoryEngine.calculate_for_material` ([inventory_engine.py:47-58](modules/inventory_engine.py#L47)) accepts `override_target_stock` / `override_target_stock_values` but **no `override_initial_stock`**.
- Initial stock is hard-coded at [inventory_engine.py:154](modules/inventory_engine.py#L154): `initial_stock = self.data.stock_levels.get(mat_num, 0.0)`.
- **Decision**: `override_initial_stock` should be a **scalar** (one value per material), not a dict. `starting_stock` is per-material, not per-period.
- Cascade via `_recalc_material_subtree` (ui/app.py:941, currently in ui/volume_change.py) rebuilds Lines 03/04/05/06/07 correctly — same path used by MIN_TARGET_STOCK edit.
- **No dedicated tests** for `override_initial_stock` exist yet.

### L7 — Hours per (machine_group, period) — PARTIAL
- `_calculate_capacity_utilization` ([capacity_engine.py:162](modules/capacity_engine.py#L162)) builds material → machine → group hours via SUMIFS (packaging) / MAXIFS (mill).
- **No central injection point** between calculation and aggregation.
- **Recommended override point**: at group level (after line 400, before `self.rows_07_cap.append`). Or alternatively per-material (line 204) before machine aggregation.
- **Site exceptions** ([capacity_engine.py:75](modules/capacity_engine.py#L75)) apply post-calculation corrections to PML18.
- **Cascade**: L10 reads `machine_hours_oee_adjusted` (line 571); L12 reads `group_hours_aggregated` (line 605). Both need recalc after L7 edit.

### L9 — Available capacity per (machine, period) — PASS
- Calculated per individual machine in `_calculate_available_capacity` ([capacity_engine.py:533](modules/capacity_engine.py#L533)).
- Reads `machine.get_availability(period)` ([models.py:147-148](modules/models.py#L147)).
- **Cascade**: L10 only. **L12 NOT affected** by L9 (L12 reads L7 hours, not L9 availability).

### L11 — Shift hours per (shift_system, period) — PASS
- `_calculate_shift_availability` ([capacity_engine.py:493](modules/capacity_engine.py#L493)) reads `self.data.shift_hours` dict (keys: `'2-shift system'`, `'3-shift system'`, `'24/7 production'`).
- **Cascade chain**: L11 → L9 (via `_get_shift_hours_for_machine` line 547) → L10.
- **Important correction to original plan**: **L11 does NOT cascade to L12 directly.** L12 FTE formula ([capacity_engine.py:603](modules/capacity_engine.py#L603)) uses `fte_hours_per_year / 12` (constant), NOT shift_hours.
- **Updated cascade for L11 edit**: L11 → L9 → L10 only.

### L12 — FTE per (group, period) — PASS (LEAF confirmed)
- FTE formula at [capacity_engine.py:595-626](modules/capacity_engine.py#L595): `hours[p] * fte_coeff / fte_monthly_hours`.
- **Only consumer**: `ValuePlanningEngine._convert_fte_requirements` ([value_planning_engine.py:321](modules/value_planning_engine.py#L321)).
- L12 edit triggers value/cost recalc only — no further planning cascade.

## 2. Override-injection points

| Function | Add parameter | Location | Notes |
|---|---|---|---|
| `InventoryEngine.calculate_for_material` | `override_initial_stock: Optional[float] = None` | inventory_engine.py:47 | Scalar; replaces line 154 lookup |
| `CapacityEngine.__init__` | `overrides: Optional[Dict[str, Dict[str, Dict[str, float]]]] = None` | capacity_engine.py:22 | Nested: `overrides[line_type][group][period]` |
| `_calculate_capacity_utilization` | (apply overrides) | capacity_engine.py:162 | After site exceptions, before L10 |
| `_calculate_available_capacity` | (apply overrides) | capacity_engine.py:533 | Per-machine override |
| `_calculate_shift_availability` | (apply overrides) | capacity_engine.py:493 | Per shift_system |
| `_calculate_fte_requirements` | (apply overrides) | capacity_engine.py:595 | Per group |

## 3. Downstream consumers per line

| Edit | Triggers |
|---|---|
| L4 starting stock | `recalc_material_subtree` (full L02-L07 + BOM children) → capacity recalc → value recalc |
| L7 hours | L10 + L12 recalc → value recalc |
| L9 availability | L10 recalc only |
| L11 shift hours | L9 + L10 recalc (NOT L12) |
| L12 FTE | value recalc only |

## 4. Risks and open questions

1. **Site exceptions vs user overrides — POLICY DECISION**: Current `_apply_site_exceptions` (capacity_engine.py:75) overwrites period values for PML18. **Decision: user overrides win** — apply user overrides AFTER site exceptions in the call chain. Document in code.
2. **L4 starting stock semantics**: scalar per material, sentinel period key `'starting_stock'` for `pending_edits` storage.
3. **L11 → L12 gap**: Original plan was wrong. L11 affects only L9/L10. Document this so UI doesn't show fake L12 "out-of-date" state after L11 edit.
4. **Truck / control-room special paths**: Out of scope for this iteration. EDITABLE_LINE_TYPES check via `material_number` will naturally exclude truck/control-room rows since they have ZZZZ-prefixed material numbers, not regular machine groups.
5. **Coproduct cascade**: BOMItem.is_coproduct is handled by existing `_recalc_material_subtree` — no change needed for L4 starting stock edits.
6. **Replay determinism**: `pending_edits` is a dict; Python 3.7+ preserves insertion order. Combined edits replay in correct order.

## 5. Code review observations

### 1. Truck capacity hours recomputed twice
- **Severity**: low
- **Location**: capacity_engine.py:463 and 631
- **Observation**: `_compute_truck_hours` cached in `_truck_hours_cache` for cap-util but recomputed in `_calculate_truck_fte`.
- **Suggestion**: `@lru_cache` on `_compute_truck_hours` or share via single private method.
- **Action**: fix-now (trivial)

### 2. Site exceptions silently mutate L7 post-calculation
- **Severity**: med
- **Location**: capacity_engine.py:75-117
- **Observation**: Exceptions overwrite period values without logging or marking the row. Hard to debug if user expects raw calc.
- **Suggestion**: Log "site exception applied" line per affected row.
- **Action**: defer (ticket)

### 3. OEE division silent fallback
- **Severity**: med
- **Location**: capacity_engine.py:280, 299
- **Observation**: `h / oee if oee > 0 and h > 0 else h` returns raw hours when oee=0; semantically assumes oee=1.
- **Suggestion**: Validate oee > 0 in DataLoader, emit warning if oee=0.
- **Action**: defer (data quality)

### 4. PlanningRow.values contract not enforced
- **Severity**: low
- **Location**: models.py:59 vs docs/ontwikkelhandleiding.md
- **Observation**: docs/ontwikkelhandleiding.md says `values` is "never None" but no `__post_init__` validation.
- **Suggestion**: Add `field(default_factory=dict)` or post-init guard.
- **Action**: defer

### 5. Magic threshold: 6-month coverage warning
- **Severity**: low
- **Location**: inventory_engine.py:113
- **Observation**: Hard-coded `> 6` for warning marker, no comment.
- **Suggestion**: Constant + comment referencing VBA light-red threshold.
- **Action**: defer

### 6. ZZ-prefix machine group detection is fragile
- **Severity**: med
- **Location**: capacity_engine.py:49
- **Observation**: `if mn.startswith('ZZ')` is the only test for machine-group rows.
- **Suggestion**: Use explicit `data.machine_groups` registry.
- **Action**: defer (ticket — broader refactor)

### 7. ceiling_multiple silently returns 0 on bad input
- **Severity**: med
- **Location**: inventory_engine.py:29
- **Observation**: Cannot distinguish failure from legitimate zero result.
- **Suggestion**: Document or raise on invalid multiple.
- **Action**: defer

### 8. UNLIMITED shift system fallback unbounded
- **Severity**: low
- **Location**: capacity_engine.py:136-147
- **Observation**: `ShiftSystem.UNLIMITED` not in `SHIFT_HOURS` dict; falls back to 347.0 silently.
- **Suggestion**: Explicit entry or warning.
- **Action**: defer

### 9. Mutable dicts in machine aggregation
- **Severity**: low
- **Location**: capacity_engine.py:351, 380
- **Observation**: Dicts assigned by reference; risk if downstream mutates.
- **Suggestion**: Defensive copy or comprehension.
- **Action**: defer

### 10. InventoryEngine stateless but data-coupled
- **Severity**: low
- **Location**: inventory_engine.py:40-45
- **Observation**: Reads mutable `data.stock_levels` etc.; if data mutates mid-session, results diverge.
- **Suggestion**: Snapshot at `__init__`.
- **Action**: defer

## Summary

Scope is **viable**. Two policy adjustments to original plan:

1. **L11 cascade is shorter than expected**: L11 → L9 → L10 only, NOT L12.
2. **Site exceptions vs user overrides**: user overrides apply AFTER exceptions (user wins).

Phase 1 can proceed with engine override parameters as listed in section 2.
