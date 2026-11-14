# Bug register — exhaustive scan 2026-07-10

Four-agent review of the full codebase (core pipeline, analytics/export engines,
UI backend, frontend). Every finding was traced through actual code paths;
three were confirmed empirically with synthetic fixtures. Severity reflects
impact on **correctness of numbers** first, stability second.

**Re-verified 2026-11-12** against `main` at `6c3b484`: every entry was traced in the
current code (line references in the Where column are from July and have drifted;
search by identifier). The Status column below is the result. Of 61 entries, 8 had
already been fixed without the register being updated; the entries marked
`fixed 2026-11` were fixed on branch `patch/robuustheid-2026-11`. The loader, engine and state fixes
each have a unit test; the front-end ones rely on the browser suite plus three new
browser tests (log, Ctrl+Z, file types).
Entries marked *needs a decision* change planning numbers on a valid workbook and
fall under change-protocol rule 4: they are listed again at the end.

Status legend: `open` (not fixed), `question` (formula/domain semantics — needs
client/VBA confirmation before touching, per docs/ontwikkelhandleiding.md, change-protocol rule 4).

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
| H1 | `modules/planning_engine.py:59` | `months_actuals` is stored but never read — the CLI flag and UI field do nothing; Line 01 anchoring always uses the workbook Config value. The comment at :96-108 claims the override is applied; it isn't. | open, needs a decision. Narrower than described: since `forecast_align_to_month` defaults to true, Line 01 values are keyed by calendar month and the actuals count only drives AUX1. The calculate-form field and the CLI flag are still inert |
| H2 | `modules/data_loader.py:324,744` + `planning_engine.py:111-148` | Machine availability and purchase actuals are filtered against the pre-override period window at load; `run()` then regenerates periods. Months outside the Config window get carried-forward availability and zero PO actuals even when the sheet had real data → wrong L04/06/07/09/10/12 whenever planning_month/forecast horizon differs from the Config sheet. | open, needs a decision (changes numbers whenever planning month or horizon differs from the Config sheet) |
| H3 | `modules/planning_engine.py:504` | `previous_cycle_df` is accepted and never used: the cross-cycle MoM pipeline (CycleManager save/load, workflow pre-run snapshots, export wiring) is a dead end. The exported "MoM Comparison" sheet is actually the within-run `calculate_sequential` view; console messages claim otherwise. | open, product decision (the cross-cycle MoM pipeline is still a dead end; M11, L8 only matter once it is wired) |
| H4 | `modules/capacity_engine.py:93-152` | NLI1 PML18 site exception runs after group aggregation: machine L7 is corrected but group L7 and L12 FTE keep the pre-exception (overstated) values. Confirmed empirically (group 222 vs correct 160; FTE 1.786 vs 1.287). | open, needs a decision (NLI1 only: group L7, L12 and the FTE cost) |
| H5 | `modules/planning_engine.py:711-721` + `chart_renderer.py:184` | Export crashes (`ValueError: shape mismatch` in `roce_bar`) when consolidation rows are empty (missing/incomplete Valuation-parameters sheet, which the loader deliberately tolerates). `/api/export` → 500 after a successful run. | fixed (`chart_renderer.roce_bar` returns a placeholder on empty or mismatched data; charts wrapped in try/except) |
| H6 | `ui/session_store.py:39-61` + `ui/engine_rebuild.py:46-48` | Per-session `purchased_and_produced` is never persisted; cold rebuilds (restart, warmup) inherit the last-active session's PAP from `_global_config`. Sync points 2 & 6 broken for this field (valuation_params has the fallback; PAP doesn't). | fixed (session PAP is persisted and read session-first on rebuild); follow-on gaps under N1 |
| H7 | `ui/routes/scenarios.py:125-169` | Scenario load replaces `pending_edits` but leaves `capacity_overrides`/`inventory_overrides` stale → the next recalc resurrects edits the scenario doesn't contain; live ≠ replay. Load must clear both stores and re-derive (mirror `replay.py:44-45`). | fixed (`derive_override_stores` on scenario load) |
| H8 | `ui/routes/config.py:109` | Master-file upload writes `upload_dir / file.filename` unsanitized — same path-traversal class fixed in workflow.py, missed in this route. | fixed (`secure_filename` in `ui/routes/config.py`) |
| H9 | `ui/templates/index.html:5284,2701` + `sop_planning.js:1637` | Plan/VP cell commits use `parseFloat` without comma normalization: Dutch `2,5` silently commits `2`. Machine-edit and paste paths DO normalize — cell paths were missed. | fixed (`parseLocaleNumber` on plan cells, value cells and paste) |
| H10 | `ui/templates/index.html:5305-5361` | No in-flight guard on plan-cell edits: overlapping `/api/update_volume` cascades mutate `engine.results` concurrently server-side and last-response-wins clobbers client state. (Machine edits have `_machineOpInFlight`; plan edits have nothing.) | fixed for plan cells (`_planEditQueue`). Residual: undo/redo, bulk, value-aux and machine routes are not serialised against that queue |
| H11 | `ui/templates/index.html:5337-5350` | Session switch during an in-flight edit: late response repaints the old session's results AND persists the edit key into the NEW session's `pending_edits` (permanent cross-instance contamination via `/api/sessions/edits/persist` reading `state.activeSessionId` after the await). | partial: plan cells capture the session id. Value-aux edits, inline machine edits, machine undo/redo/reset, the utilisation drag and plan undo/redo still do not |
| H12 | `index.html:5011,2542,3087,7622,7708` + `sop_planning.js:768,879` | Stored XSS: workbook-derived strings (material names, aux columns) rendered via innerHTML unescaped in table cells, heatmap title attributes, tooltips. `esc()` exists and is used for data-attributes only. | fixed 2026-11: the log is text-only; workbook and user strings are escaped in every sink found (incl. the UoM banner and its buttons, scenario compare, PAP, MoM scatter, session list, master filename); every inline-handler argument goes through `_jsArg` (JS string and HTML attribute). Not done: server error strings rendered in the scenario-compare modal |

## MEDIUM

| ID | Where | Defect | Status |
|---|---|---|---|
| M1 | `modules/data_loader.py:261,518+` | Numeric SKU column with one blank cell → float64 → all keys become `"...0"`; forecast sheet (header=None) yields int-keys → joins silently miss on every material. | partial: only the forecast sheet goes through `_norm_material`; material master, BOM, routing, stock, safety stock, purchase and cost sheets still use raw `str()`. Must be changed for all sheets in one step |
| M2 | `modules/data_loader.py:179-182` | Config-sheet failure fallback never sets `forecast_actuals_months` → later AttributeError; the graceful-degradation path can't work for the xlsm route. | fixed 2026-11: an unreadable Config sheet is a clear `ValueError` instead of defaults followed by an AttributeError |
| M3 | `modules/data_loader.py:348` | Blank OEE cell → NaN (no `pd.notna` guard, unlike neighbors) → NaN spreads through L09/10/12 and export with no error. | fixed 2026-11: a blank OEE loads as 1.0 (the value every formula already used) with a load warning; no NaN in the machines JSON |
| M4 | `modules/bom_engine.py:44-50,105-109` | Duplicate (parent,component) BOM rows: values last-row-wins, aux display first-row-wins, never summed across production versions. | open, needs a decision (sum versus production-version selection) |
| M5 | `modules/planning_engine.py:330-334` + `capacity_engine.py:640` | `all_line_data` keeps one row per material; truck SUMIFS over multi-row line types (L02/L08) only sees the last row → truck hours understated. | open, needs a decision (only when a truck row points at a multi-row line type) |
| M6 | `modules/data_loader.py:789-806` | BOM cycles neither detected nor reported — cascade silently drops demand; dense diamond BOMs cause exponential re-traversal. | partial: the cycle warning now reaches the UI (load warnings, fixed 2026-11); exponential re-traversal on dense diamond BOMs is still open |
| M7 | `modules/data_loader.py:650-671,458-479` | Forecast rows keyed by material with plain overwrite, no plant/site filter — multi-row extracts keep an arbitrary last row. | open, needs a decision (sum versus site filter) |
| M8 | `modules/data_loader.py:268-270` | NaN material name / product family becomes literal `'nan'` string → grouping/MoM-join identifier pollution. | open (`'nan'` strings for blank name / product family; consumers work around it) |
| M9 | `modules/capacity_engine.py:205-241` | Group-level L7 override redistribution assumes SUM semantics: wrong for mill groups (MAX) and double-counts compound production-line rows (confirmed empirically: 3x group edit leaves machine rows unchanged). | open, needs a decision (edit path only) |
| M10 | `modules/capacity_engine.py:841-887` | L7 overrides on truck/control-room rows don't flow into their L12 FTE (regenerated from caches/lookups, not overridden L7). | open, needs a decision (edit path only) |
| M11 | `modules/mom_comparison_engine.py:164-172` | Cross-cycle join on number+name+type with inner merge: renamed/retyped materials silently vanish (moot until H3 is fixed; will bite then). | open (dead until H3) |
| M12 | `main.py:118` | `--export-db` without `--db-path` drops the output directory (`Path.stem`) — DB export lands in CWD. | fixed 2026-11: the DB export lands next to the planning workbook |
| M13 | `ui/app.py:117` | Scenarios live only in a module-level dict — all saved scenarios silently lost on restart. | fixed (scenarios are persisted atomically and loaded at startup) |
| M14 | `ui/routes/sessions.py:194-199` + warmup | Switching to a warming session never syncs `_global_config` (and warmup completion doesn't either) → config UI shows previous session's VP/PAP; scenarios saved in that window capture wrong VP. Same gap on active-session delete (:233-242). | partial, fixed 2026-11: scenario save takes VP/PAP from the engine it snapshots, and deleting the active instance syncs the promoted one. The mirror is still stale after upload+calculate and after warmup completes (N2) |
| M15 | `ui/routes/config.py:190-231` | Settings POST combining structural change + new PAP/VP: rebuild prefers the OLD engine's values; new PAP/VP silently discarded until manual recalc. | fixed (new PAP/VP are applied before the structural rebuild) |
| M16 | `ui/routes/config.py:46-71` | Changing the sessions folder orphans the existing store (nothing migrates/saves) and the next auto-save can clobber a store already at the new location. | open (changing the sessions folder neither migrates nor guards an existing store) |
| M17 | `ui/routes/sessions.py:105-108` | Duplicate instance drops live VP edits (reads `sess['valuation_params']`/baseline instead of `engine.data.valuation_params`). | fixed (duplicate reads the live engine's VP and PAP) |
| M18 | `ui/volume_change.py:654` + cascade | `inventory_overrides` is persisted but consumed by nothing at recalc time: an L4 starting-stock edit is silently reverted when the material is rebuilt as a child of another edit, while the UI still shows the edited marker. | fixed 2026-11: an edited starting stock survives every later recalculation of that material (own edit, parent plan, PAP change); live and replay agree |
| M19 | `ui/app.py:396-450` + `sessions.py:200-215` | Autorun and switch-session can rebuild the same session concurrently (autorun doesn't register warmup events) → two threads replaying into one session dict. | partial: the background install is guarded, but autorun and switch-session still take different locks |
| M20 | `ui/state_snapshot.py:95-107` + `scenarios.py:169` | `all_purch_raw_needs` not snapshotted/rebuilt on scenario load or restore-based reset → stale MOQ warnings. | open (`all_purch_raw_needs` not snapshotted; stale MOQ badges after Reset or scenario load) |
| M21 | `ui/routes/edits.py:172-196` | `/api/undo` pops the stack before applying; a 403/404 consumes the entry and pushes it to redo → stacks desync from engine state. | fixed 2026-11: each undo/redo step is snapshotted before it leaves its stack; 403/404 entries are dropped, any other failure or exception restores the engine, the session's edit stores and both stacks |
| M22 | `index.html:7501-7565,5544` | Machine edits pass `skipDashboard: true` and nothing ever sets `dashboardDirty` → dashboard/capacity charts show pre-edit numbers ("graphs disagree with the table"). | fixed 2026-11: the dashboard is marked dirty after every edit, machine edits included |
| M23 | `index.html:8585-8607` | Switching to an uncalculated/warming instance leaves the previous instance's tables/charts on screen under the new instance's name. | fixed 2026-11: both tables are replaced by a placeholder; charts follow on their next render |
| M24 | `index.html:2463-2481` | `/api/value_results` error path keeps previous session's value data → VP tab mixes instances. | fixed 2026-11: value state, table, consolidation, financial chart and value KPI tiles are cleared when the instance has no value results |
| M25 | `index.html:6295-6310` | Global Ctrl+Z/Ctrl+Y ignores focus: while typing in search/session-name/cell, native undo is hijacked into a server-side volume-edit undo. | fixed 2026-11: Ctrl+Z / Ctrl+Y are left to the field while typing |
| M26 | `index.html:5904-5926` | Delta-summary cascade detection ignores aux_column for multi-row line types → spurious cascade tags. | open (delta summary ignores aux_column for multi-row line types) |

## LOW

| ID | Where | Defect | Status |
|---|---|---|---|
| L1 | `modules/planning_engine.py:141-159` | `months_forecast=0` clobbers config before the fallback reads it → empty run, no error; Config `ForecastMonths` dead for CLI. | fixed 2026-11 for the zero horizon (keeps the Config value). The CLI default of 12 still overrides Config `ForecastMonths`: behaviour decision |
| L2 | `modules/planning_engine.py:255-289` | Forecast-only materials (no BOM/safety-stock row) get L01 only; first UI edit then synthesizes L03-07 → baseline vs edited structure disagree. | open, needs a decision |
| L3 | `modules/inventory_engine.py:196,222-249` | Stale `purch_raw_need` when a PO actual replaces the first flexible month → phantom MOQ warning. | fixed 2026-11: raw needs are rebuilt by the re-run after PO actuals |
| L4 | `modules/data_loader.py:138,226,699,726` | Broad excepts degrade lead times/MOQ/FTE config to defaults with only a console line — silent numeric drift. | fixed 2026-11: every fallback is recorded as a load warning and shown above the planning table; the defaults themselves are unchanged |
| L5 | `modules/data_loader.py:356-362` | Duplicate machine rows: machine overwritten but appended twice to group → doubled L11 name list, skewed shift-hour averages. | detected, fixed 2026-11: a duplicate machine row raises a load warning. Grouping is deliberately unchanged (counting the row once would change numbers): decision |
| L6 | `modules/value_planning_engine.py:280-287` | Aux override checked after zero-cost/rate guards → override silently dropped if cost data degrades. | open (aux override dropped when cost data is missing) |
| L7 | `modules/cycle_manager.py:47-64` | Parquet+meta written non-atomically, read outside locks; concurrent read during write silently reports "no previous cycle". | fixed 2026-11: snapshot and metadata are each written to a unique temporary file and swapped in; the metadata carries the snapshot's sha256 and is ignored when it belongs to another snapshot. Two separate reads (snapshot, then metadata) can still straddle a write: there is no paired read |
| L8 | `modules/mom_comparison_engine.py:174-178` | `Delta % = np.inf` when previous is 0 → JSON/openpyxl hazard once H3 is fixed. | open (dead until H3) |
| L9 | `main.py:241` | Crash handler `input()` hangs in non-interactive contexts; `--web` flag parsed but ignored. | fixed 2026-11: the crash handler only waits for Enter on an interactive console. `--web` is still a parsed no-op |
| L10 | `modules/capacity_engine.py:243-263` | L9 aux display overwritten with group L11 average, clobbering per-machine shift-hour override display (display only). | open (display only) |
| L11 | `ui/routes/sessions.py:216-226` | Dirty-baseline refresh on switch installs a clean baseline without replay → wipes override stores while pending_edits still carry them (rare precondition). | open, latent (no reachable trigger found) |
| L12 | `ui/engine_rebuild.py:82-85` | `install_clean_engine_baseline` clears `machine_undo` but not `machine_redo` → stale machine redo after calculate/reset. | fixed 2026-11: `machine_redo` is cleared together with `machine_undo` |
| L13 | `ui/routes/pap.py:60-63`, `config.py:190-199` | PAP fraction unvalidated: negative, >1, NaN accepted; NaN cascades through the whole plan. | fixed 2026-11: `/api/pap` and the settings route refuse a share outside 0..1 or non-finite |
| L14 | `ui/routes/edit_state.py:29-53`, `config.py:180`, `edits.py:64` | Unvalidated numeric coercion → 500 instead of 400; sync stores raw keys while persist canonicalizes (possible duplicate pending entries). | fixed 2026-11: malformed or non-finite numbers return 400; sync keys are canonical and the store is replaced all-or-nothing |
| L15 | `ui/routes/config.py:199-201` | PAP mutated before `ensure_reset_baseline` (opposite order of pap.py) — baseline can capture post-edit PAP. | open, latent (baseline captured after the PAP mutation in the settings route) |
| L16 | `index.html:5317,5361` | Error rollback writes raw fraction into percent cells; edit indicators not restored. | open (rollback writes a raw fraction into percent cells) |
| L17 | `volume_change.py:691` + `index.html:5395` | MOQ badges stale after volume edits (response omits `moq_raw_needs`, client never recomputes). | open (edit responses carry no `moq_raw_needs`; client never recomputes the badges) |
| L18 | `index.html:7519-7534` | Machine-undo "nothing to undo" is 200 + success:false; client records phantom undo event. | fixed 2026-11: a `success:false` undo/redo updates the depths and records no step |
| L19 | `index.html:3747-3829` | localStorage UI prefs (filters/search/sort) global across instances → "empty table" confusion after switch. | partial: the planning table explains an empty filter result; preferences are still global across instances |
| L20 | `index.html:2364-2370` | `runCalc` wipes client edit badges before the request; on failure UI shows 0 edits while server holds them. | fixed 2026-11: client edit state is restored when the server reports an error and when the request or its response fails |
| L21 | `index.html:8299-8324` | Drop zone accepts `.xls` that upload later rejects with a confusing error. | fixed 2026-11: `.xls` is no longer offered |
| L22 | `index.html:1845-1857` | UTC parse/local format of period banner → month off-by-one in UTC-negative timezones. | fixed 2026-11: the horizon banner builds local dates |
| L23 | `sop_planning.js:1592-1752` | Dead duplicate of the VP edit path (never invoked, already diverged) — maintenance trap. | fixed 2026-11: the dead copy is removed from `sop_planning.js` |

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
| Q8 | `capacity_engine.py` `_calculate_utilization_rate` | At 0 % availability Line 10 reports utilization 0 (`used / available if available > 0 else 0.0`), so a machine with planned hours but no capacity looks idle. Since 2026-11 the scenario comparison counts these months separately ("Geplande uren zonder capaciteit"). VBA parity? Should it show the planned hours as overload instead? |

## New findings from the 2026-11-12 re-verification

| ID | Where | Defect | Status |
|---|---|---|---|
| N1 | `ui/state_snapshot.py`, `ui/routes/scenarios.py`, `ui/session_store.py` | The session PAP field is the authority for rebuilds but is not kept up to date: Reset and scenario load set engine and mirror but not `sess['purchased_and_produced']`, so the next rebuild brings back the PAP from before. Saving persists the live PAP as the session field for every session, after which master-store PAP changes no longer reach existing sessions. | open |
| N2 | `ui/routes/workflow.py`, `ui/app.py` | M14 is wider than registered: the global mirror is also stale after upload+calculate and after a warmup completes, until the next switch or page load. The Config tab can then show, and save into this instance, another instance's forecast defaults. | open |
| N3 | `ui/replay.py` | Replay iterated the live `pending_edits` dict while `apply_volume_change` pops a reverted key from it: `RuntimeError: dictionary changed size during iteration`, a 500 on switch/calculate or a failed warmup. | fixed 2026-11 |
| N4 | `ui/templates/index.html`, `ui/routes/edit_state.py` | After every undo/redo the client rebuilds its edit list from the results and replaces the server's `pending_edits` wholesale: replay order becomes results order instead of edit order. | open |
| N5 | `ui/routes/config.py` | In master-store mode the settings route still accepts `valuation_params` and applies them to the live engine, although every rebuild takes them from the store. API-only today. | open |
| N6 | `ui/templates/index.html` (werkbank) | 'Komende 3/6 maanden' counts from the calendar month; near the end of the horizon the tile averaged over fewer months while still saying 3 or 6. Its test depended on the test date and failed in October and November 2026. | fixed 2026-11 (label states the real window; tests freeze the browser clock) |
| N7 | `tests/browser/test_pw_machine_inzet.py` | A test still expected the combination status line that the inspector replaced with the 'Combineren' button on 2026-09-14; it had been failing since. | fixed 2026-11 (test follows the current design) |
| N8 | `main.py` | `python main.py --test` printed 'Test file not found' and exited 0: a self-test that could not run looked like one that passed. | fixed 2026-11 (exit code 2) |
| N9 | `ui/routes/edit_state.py` | `/api/sessions/edits/sync` accepted an empty key, and two client keys for one cell silently overwrote each other. | fixed 2026-11 (both refused with 400; the store is only replaced when every entry is valid) |
| N10 | `ui/app.py` | The PAP recalculation took the active session's edited starting stocks when the engine's own session could not be found. | fixed 2026-11 (only the owning session; a detached engine recalculates without edited stocks) |


## Missing client data: assumptions (Maastricht only)

Changeover times can be filled with tool-generated assumptions until the client
delivers them (`modules/placeholder_data.py`, machine-inzet tab). See
`docs/aannames-klantdata.md`. Staffing norms, labour rates, throughput overrides
and MES/PEER benchmarks are deliberately not generated.

## Decisions needed before these can be fixed

Each of these changes computed numbers on a valid workbook, or what an export contains.
Rule 4 applies: describe, decide with the client where the VBA is the reference, then fix.

| ID | The decision |
|---|---|
| H1 | Remove the inert 'months of actuals' field and flag, or wire them (changes Line 01 AUX1). |
| H2 | Re-read availability and PO actuals for the final window when the planning month or horizon differs from the Config sheet. |
| H3 | Cross-cycle MoM: wire it (and define 'previous cycle'), or remove the dead parameter and the messages that claim it works. |
| H4 | NLI1/PML18: apply the exception before group aggregation so group L7, L12 and FTE cost follow. |
| M4 | Duplicate (parent, component) BOM rows: sum across production versions, or select one. |
| M5 | Truck hours over multi-row line types: sum per material. |
| M7 | Several forecast rows for one material: sum, or filter by plant. |
| M9 | Group-level L7 override on mill (MAX) and compound groups: scale by the pre-override aggregate. |
| M10 | L7 overrides on truck and control-room rows should flow into their L12 FTE. |
| L2 | Forecast-only materials: give them L03-07 in the baseline, or stop the edit path creating them. |
| L5 | A machine listed twice: count it once in its group, or keep following the sheet. |
| L1 | CLI: let Config `ForecastMonths` apply when `--months-forecast` is not given. |
