# Bug register — exhaustive scan 2026-07-10

Four-agent review of the full codebase (core pipeline, analytics/export engines,
UI backend, frontend). Every finding was traced through actual code paths;
three were confirmed empirically with synthetic fixtures. Severity reflects
impact on **correctness of numbers** first, stability second.

Status legend: `open` (not fixed), `question` (formula/domain semantics — needs
client/VBA confirmation before touching, per docs/ontwikkelhandleiding.md rule 4).

Previously fixed (2026-07-10, commits `5ac412e`..`3562ffa`): reset not restoring
shift_hours_override; revert pinning capacity/inventory overrides; error tuples
from apply_volume_change; stdout swap races; upload path traversal (workflow
routes); sessions dict thread safety; non-atomic global_config writes.

Known accepted limitations (not bugs): single global `active_session_id` (no
multi-user isolation); export files accumulate; `redirect_stdout` is process-global.

---

## HIGH — wrong numbers or data loss

| ID | Where | Defect | Status |
|---|---|---|---|
| H1 | `modules/planning_engine.py:59` | `months_actuals` is stored but never read — the CLI flag and UI field do nothing; Line 01 anchoring always uses the workbook Config value. The comment at :96-108 claims the override is applied; it isn't. | open |
| H2 | `modules/data_loader.py:324,744` + `planning_engine.py:111-148` | Machine availability and purchase actuals are filtered against the pre-override period window at load; `run()` then regenerates periods. Months outside the Config window get carried-forward availability and zero PO actuals even when the sheet had real data → wrong L04/06/07/09/10/12 whenever planning_month/forecast horizon differs from the Config sheet. | open |
| H3 | `modules/planning_engine.py:504` | `previous_cycle_df` is accepted and never used: the cross-cycle MoM pipeline (CycleManager save/load, workflow pre-run snapshots, export wiring) is a dead end. The exported "MoM Comparison" sheet is actually the within-run `calculate_sequential` view; console messages claim otherwise. | open |
| H4 | `modules/capacity_engine.py:93-152` | NLI1 PML18 site exception runs after group aggregation: machine L7 is corrected but group L7 and L12 FTE keep the pre-exception (overstated) values. Confirmed empirically (group 222 vs correct 160; FTE 1.786 vs 1.287). | open |
| H5 | `modules/planning_engine.py:711-721` + `chart_renderer.py:184` | Export crashes (`ValueError: shape mismatch` in `roce_bar`) when consolidation rows are empty (missing/incomplete Valuation-parameters sheet, which the loader deliberately tolerates). `/api/export` → 500 after a successful run. | open |
| H6 | `ui/session_store.py:39-61` + `ui/engine_rebuild.py:46-48` | Per-session `purchased_and_produced` is never persisted; cold rebuilds (restart, warmup) inherit the last-active session's PAP from `_global_config`. Sync points 2 & 6 broken for this field (valuation_params has the fallback; PAP doesn't). | open |
| H7 | `ui/routes/scenarios.py:125-169` | Scenario load replaces `pending_edits` but leaves `capacity_overrides`/`inventory_overrides` stale → the next recalc resurrects edits the scenario doesn't contain; live ≠ replay. Load must clear both stores and re-derive (mirror `replay.py:44-45`). | open |
| H8 | `ui/routes/config.py:109` | Master-file upload writes `upload_dir / file.filename` unsanitized — same path-traversal class fixed in workflow.py, missed in this route. | open |
| H9 | `ui/templates/index.html:5284,2701` + `sop_planning.js:1637` | Plan/VP cell commits use `parseFloat` without comma normalization: Dutch `2,5` silently commits `2`. Machine-edit and paste paths DO normalize — cell paths were missed. | open |
| H10 | `ui/templates/index.html:5305-5361` | No in-flight guard on plan-cell edits: overlapping `/api/update_volume` cascades mutate `engine.results` concurrently server-side and last-response-wins clobbers client state. (Machine edits have `_machineOpInFlight`; plan edits have nothing.) | open |
| H11 | `ui/templates/index.html:5337-5350` | Session switch during an in-flight edit: late response repaints the old session's results AND persists the edit key into the NEW session's `pending_edits` (permanent cross-instance contamination via `/api/sessions/edits/persist` reading `state.activeSessionId` after the await). | open |
| H12 | `index.html:5011,2542,3087,7622,7708` + `sop_planning.js:768,879` | Stored XSS: workbook-derived strings (material names, aux columns) rendered via innerHTML unescaped in table cells, heatmap title attributes, tooltips. `esc()` exists and is used for data-attributes only. | open |

## MEDIUM

| ID | Where | Defect | Status |
|---|---|---|---|
| M1 | `modules/data_loader.py:261,518+` | Numeric SKU column with one blank cell → float64 → all keys become `"...0"`; forecast sheet (header=None) yields int-keys → joins silently miss on every material. | deels (fase-3): `normalize_material_number` (`modules/product_overlay.py`) normaliseert gebruikersinvoer via UI/routes; de loader-leespunten zelf zijn nog open |
| M2 | `modules/data_loader.py:179-182` | Config-sheet failure fallback never sets `forecast_actuals_months` → later AttributeError; the graceful-degradation path can't work for the xlsm route. | open |
| M3 | `modules/data_loader.py:348` | Blank OEE cell → NaN (no `pd.notna` guard, unlike neighbors) → NaN spreads through L09/10/12 and export with no error. | open |
| M4 | `modules/bom_engine.py:44-50,105-109` | Duplicate (parent,component) BOM rows: values last-row-wins, aux display first-row-wins, never summed across production versions. | open |
| M5 | `modules/planning_engine.py:330-334` + `capacity_engine.py:640` | `all_line_data` keeps one row per material; truck SUMIFS over multi-row line types (L02/L08) only sees the last row → truck hours understated. | open |
| M6 | `modules/data_loader.py:789-806` | BOM cycles neither detected nor reported — cascade silently drops demand; dense diamond BOMs cause exponential re-traversal. | deels (fase-3): detectie + luide warning (`DataLoader.bom_cycle_warnings`); overlay-cycli zijn harde fouten (`modules/product_overlay.py`). Cascade-getallen bij bestaande werkboek-cycli bewust ongewijzigd; exponentiële re-traversal nog open |
| M7 | `modules/data_loader.py:650-671,458-479` | Forecast rows keyed by material with plain overwrite, no plant/site filter — multi-row extracts keep an arbitrary last row. | open |
| M8 | `modules/data_loader.py:268-270` | NaN material name / product family becomes literal `'nan'` string → grouping/MoM-join identifier pollution. | open |
| M9 | `modules/capacity_engine.py:205-241` | Group-level L7 override redistribution assumes SUM semantics: wrong for mill groups (MAX) and double-counts compound production-line rows (confirmed empirically: 3x group edit leaves machine rows unchanged). | open |
| M10 | `modules/capacity_engine.py:841-887` | L7 overrides on truck/control-room rows don't flow into their L12 FTE (regenerated from caches/lookups, not overridden L7). | open |
| M11 | `modules/mom_comparison_engine.py:164-172` | Cross-cycle join on number+name+type with inner merge: renamed/retyped materials silently vanish (moot until H3 is fixed; will bite then). | open |
| M12 | `main.py:118` | `--export-db` without `--db-path` drops the output directory (`Path.stem`) — DB export lands in CWD. | open |
| M13 | `ui/app.py:117` | Scenarios live only in a module-level dict — all saved scenarios silently lost on restart. | open |
| M14 | `ui/routes/sessions.py:194-199` + warmup | Switching to a warming session never syncs `_global_config` (and warmup completion doesn't either) → config UI shows previous session's VP/PAP; scenarios saved in that window capture wrong VP. Same gap on active-session delete (:233-242). | open |
| M15 | `ui/routes/config.py:190-231` | Settings POST combining structural change + new PAP/VP: rebuild prefers the OLD engine's values; new PAP/VP silently discarded until manual recalc. | open |
| M16 | `ui/routes/config.py:46-71` | Changing the sessions folder orphans the existing store (nothing migrates/saves) and the next auto-save can clobber a store already at the new location. | open |
| M17 | `ui/routes/sessions.py:105-108` | Duplicate instance drops live VP edits (reads `sess['valuation_params']`/baseline instead of `engine.data.valuation_params`). | open |
| M18 | `ui/volume_change.py:654` + cascade | `inventory_overrides` is persisted but consumed by nothing at recalc time: an L4 starting-stock edit is silently reverted when the material is rebuilt as a child of another edit, while the UI still shows the edited marker. | open |
| M19 | `ui/app.py:396-450` + `sessions.py:200-215` | Autorun and switch-session can rebuild the same session concurrently (autorun doesn't register warmup events) → two threads replaying into one session dict. | open |
| M20 | `ui/state_snapshot.py:95-107` + `scenarios.py:169` | `all_purch_raw_needs` not snapshotted/rebuilt on scenario load or restore-based reset → stale MOQ warnings. | open |
| M21 | `ui/routes/edits.py:172-196` | `/api/undo` pops the stack before applying; a 403/404 consumes the entry and pushes it to redo → stacks desync from engine state. | open |
| M22 | `index.html:7501-7565,5544` | Machine edits pass `skipDashboard: true` and nothing ever sets `dashboardDirty` → dashboard/capacity charts show pre-edit numbers ("graphs disagree with the table"). | open |
| M23 | `index.html:8585-8607` | Switching to an uncalculated/warming instance leaves the previous instance's tables/charts on screen under the new instance's name. | open |
| M24 | `index.html:2463-2481` | `/api/value_results` error path keeps previous session's value data → VP tab mixes instances. | open |
| M25 | `index.html:6295-6310` | Global Ctrl+Z/Ctrl+Y ignores focus: while typing in search/session-name/cell, native undo is hijacked into a server-side volume-edit undo. | open |
| M26 | `index.html:5904-5926` | Delta-summary cascade detection ignores aux_column for multi-row line types → spurious cascade tags. | open |

## LOW

| ID | Where | Defect | Status |
|---|---|---|---|
| L1 | `modules/planning_engine.py:141-159` | `months_forecast=0` clobbers config before the fallback reads it → empty run, no error; Config `ForecastMonths` dead for CLI. | open |
| L2 | `modules/planning_engine.py:255-289` | Forecast-only materials (no BOM/safety-stock row) get L01 only; first UI edit then synthesizes L03-07 → baseline vs edited structure disagree. | open |
| L3 | `modules/inventory_engine.py:196,222-249` | Stale `purch_raw_need` when a PO actual replaces the first flexible month → phantom MOQ warning. | open |
| L4 | `modules/data_loader.py:138,226,699,726` | Broad excepts degrade lead times/MOQ/FTE config to defaults with only a console line — silent numeric drift. | open |
| L5 | `modules/data_loader.py:356-362` | Duplicate machine rows: machine overwritten but appended twice to group → doubled L11 name list, skewed shift-hour averages. | open |
| L6 | `modules/value_planning_engine.py:280-287` | Aux override checked after zero-cost/rate guards → override silently dropped if cost data degrades. | open |
| L7 | `modules/cycle_manager.py:47-64` | Parquet+meta written non-atomically, read outside locks; concurrent read during write silently reports "no previous cycle". | open |
| L8 | `modules/mom_comparison_engine.py:174-178` | `Delta % = np.inf` when previous is 0 → JSON/openpyxl hazard once H3 is fixed. | open |
| L9 | `main.py:241` | Crash handler `input()` hangs in non-interactive contexts; `--web` flag parsed but ignored. | open |
| L10 | `modules/capacity_engine.py:243-263` | L9 aux display overwritten with group L11 average, clobbering per-machine shift-hour override display (display only). | open |
| L11 | `ui/routes/sessions.py:216-226` | Dirty-baseline refresh on switch installs a clean baseline without replay → wipes override stores while pending_edits still carry them (rare precondition). | open |
| L12 | `ui/engine_rebuild.py:82-85` | `install_clean_engine_baseline` clears `machine_undo` but not `machine_redo` → stale machine redo after calculate/reset. | open |
| L13 | `ui/routes/pap.py:60-63`, `config.py:190-199` | PAP fraction unvalidated: negative, >1, NaN accepted; NaN cascades through the whole plan. | open |
| L14 | `ui/routes/edit_state.py:29-53`, `config.py:180`, `edits.py:64` | Unvalidated numeric coercion → 500 instead of 400; sync stores raw keys while persist canonicalizes (possible duplicate pending entries). | open |
| L15 | `ui/routes/config.py:199-201` | PAP mutated before `ensure_reset_baseline` (opposite order of pap.py) — baseline can capture post-edit PAP. | open |
| L16 | `index.html:5317,5361` | Error rollback writes raw fraction into percent cells; edit indicators not restored. | open |
| L17 | `volume_change.py:691` + `index.html:5395` | MOQ badges stale after volume edits (response omits `moq_raw_needs`, client never recomputes). | open |
| L18 | `index.html:7519-7534` | Machine-undo "nothing to undo" is 200 + success:false; client records phantom undo event. | open |
| L19 | `index.html:3747-3829` | localStorage UI prefs (filters/search/sort) global across instances → "empty table" confusion after switch. | open |
| L20 | `index.html:2364-2370` | `runCalc` wipes client edit badges before the request; on failure UI shows 0 edits while server holds them. | open |
| L21 | `index.html:8299-8324` | Drop zone accepts `.xls` that upload later rejects with a confusing error. | open |
| L22 | `index.html:1845-1857` | UTC parse/local format of period banner → month off-by-one in UTC-negative timezones. | open |
| L23 | `sop_planning.js:1592-1752` | Dead duplicate of the VP edit path (never invoked, already diverged) — maintenance trap. | open |

## Formula questions — need domain/VBA confirmation before any change

| ID | Where | Question |
|---|---|---|
| Q1 | `planning_engine.py:294-323` | NLI1 Exception 2 reduces B15's plan AFTER its L08 explosion — children keep demand from the unadjusted plan. VBA parity? |
| Q2 | `bom_engine.py:22` vs `data_loader.py:307` | Comment says coproducts carry negative qty_per; loader keeps positive qty for `Co-product == 'X'` rows → adds demand instead of crediting supply. Does the SAP export always store them negative? |
| Q3 | `data_loader.py:337` | Availability heuristic `raw <= 2.0` kept as-is else /100: 1.5 → 150%, 150 → 1.5. Ambiguous band (1,2]. |
| Q4 | `capacity_engine.py:477,496` | `oee == 0` falls back to RAW hours instead of 0/error — missing data inflates capacity vs any oee<1 machine. |
| Q5 | `capacity_engine.py:121,386` | PML18 exception recompute uses different zero-std-time fallback than base calc and ignores DeleteDoubleProcessRows removals. |
| Q6 | `capacity_engine.py:334,344` | Shift-hour fallbacks inconsistent: 347 for missing machine vs 520 for unknown shift system. |
| Q7 | `forecast_engine.py:106` | `months_actuals + 1` anchor leaves one month in neither AUX1 nor planning values — documented as verified VBA math; noted for completeness. |
