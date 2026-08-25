# Coverage Completion Plan

Date: 2026-05-06

This plan describes how to expand the remaining automated coverage and
validation for the Apex Rainier Planning Tool. It builds on the gaps identified
in `customer-test-validation-summary.md` and on the current coverage data from
`htmlcov/status.json`.

## Goal

The goal is not to chase 100% coverage for its own sake. The goal is to:

- protect the most important customer workflows automatically
- expose error paths and edge cases before users encounter them
- strengthen automated validation for charts and heatmaps
- add measurable guardrails for large workbooks and performance
- increase coverage with tests that can catch real regressions

Current baseline:

| Scope | Executable lines | Covered automatically | Coverage |
|---|---:|---:|---:|
| Total `modules/` + `ui` | 5,577 statements + 2,138 branches | full non-browser suite | 81% |
| Fixture-free CI slice | 5,577 statements + 2,138 branches | `pytest -m no_fixture --cov=ui --cov=modules` | 62% |
| Browser tests | subprocess/server code excluded | 19 Playwright validations passed | not counted |

Target milestones:

| Milestone | Target |
|---|---|
| After sprints 1-2 | 70%+ total coverage, with stronger route and state-edge coverage - achieved |
| After sprints 3-5 | 75%+ total coverage, including error paths and engine edge cases - achieved |
| After sprints 6-8 | 80%+ total coverage, plus automated visual checks - achieved |
| After that | Add coverage only where risk or maintainability clearly justifies it |

## Current Hotspots

Largest remaining coverage gaps from the branch-enabled full non-browser run:

| File | Coverage | Missing lines | Why it matters |
|---|---:|---:|---|
| `modules/planning_engine.py` | 56% | 336 | Main orchestration, export, high-level pipeline |
| `ui/app.py` | 56% | 79 | App wiring, blueprint registration, session glue |
| `modules/data_loader.py` | 71% | 180 | Workbook parsing and input failure behavior |
| `ui/paths.py` | 74% | 3 | Runtime path selection |
| `modules/capacity_engine.py` | 77% | 90 | Capacity edge cases and machine behavior |
| `modules/inventory_engine.py` | 82% | 28 | Inventory edge cases |
| `ui/routes/machines.py` | 84% | 35 | High-use capacity and machine-edit routes |
| `ui/routes/sessions.py` | 86% | 15 | Session switch/delete/snapshot edge cases |
| `ui/state_snapshot.py` | 87% | 19 | Reset, restore, and session baseline behavior |
| `ui/volume_change.py` | 87% | 28 | Live edit cascade behavior |

Completion status on 2026-05-06:

- Sprint 0: branch coverage and CI coverage artifacts are configured.
- Sprint 1: high-value scenario/session/workflow/config route edges were added.
- Sprint 3: dashboard, values, and machine chart canvas nonblank checks were added.
- Sprint 4: data-loader parsing/config edge cases were added without customer data.
- Sprint 5: planning-engine synthetic orchestration/export helper tests were added.
- Sprint 6: cycle-manager and export/MoM coverage is above the target range.
- Sprint 7: performance guardrails were added for pending-edit replay and large result compilation.
- Sprint 8: parked because license files are deleted in the current working tree.
- Sprint 9: CI now reports coverage artifacts, but hard coverage gates remain intentionally off.

## Working Rules

- Prefer test-only changes. Production code should change only when a real
  testability problem cannot be solved otherwise.
- Do not change calculation formulas during coverage sprints.
- If a new test exposes a bug, report it first. Do not silently fix production
  code in the same change.
- Keep each PR or commit focused on one sprint area.
- Report coverage movement after every sprint: total coverage and per-file
  deltas.
- Do not include local user paths in customer-facing documentation or fixture
  descriptions.
- The golden fixture must remain configured through environment or managed test
  infrastructure, never through a hardcoded local path.
- Before starting each sprint, mark already-covered scenarios against the
  current test suite so new work closes real gaps instead of duplicating tests.
- If a feature has been removed, regenerate coverage and drop or park its
  sprint target before assigning work against stale files.

## Sprint 0 - Measurement Baseline And Coverage Infrastructure

Objective: make every later sprint measurable and repeatable.

Work:

- Add the current baseline to `docs/tasks/qa-coverage-baseline.md`.
- Generate `coverage.xml` in addition to the HTML report so CI and external
  tools can consume the result.
- Enable report-only branch coverage early. Do not gate on branch coverage
  until the suite has settled.
- Decide whether browser-test server subprocesses should be included in
  Python coverage. Today they validate product behavior, but subprocess code
  usually does not count in `pytest-cov`.
- Explicitly document the measurement model:
  - route/API tests count toward code coverage
  - browser tests count toward product validation
  - browser subprocess coverage is optional and should be added only if stable

Concrete tasks:

- Update `.coveragerc` only if subprocess coverage is intentionally added.
- Add a short section to `tests/README.md` with:
  - quick test command
  - full coverage command
  - browser validation command
  - golden fixture setup without local paths
- Add pytest markers for `browser`, `golden`, and `performance`.
- Add CI artifact publishing for `coverage.xml` and the HTML coverage report.

Acceptance criteria:

- `pytest --cov=ui --cov=modules --cov-report=term-missing --cov-report=html`
  runs successfully.
- Baseline is recorded with date, total percentage, and top 10 lowest-coverage
  files.
- No production code is changed.

Current suite audit before Sprint 1:

| Area | Existing coverage to avoid duplicating | Remaining emphasis |
|---|---|---|
| Workflow routes | Upload missing-file, empty filename, loader failure, multi-file master errors, calculate errors, and successful calculate already have tests. | Engine `run()` failure, invalid extension behavior if it is meant to be enforced, and output-folder isolation. |
| Session routes | List/switch/delete/rename/snapshot and warm snapshot paths already have tests. | Delete-last-session safety and hard failure paths around snapshot/rebuild. |
| Scenario routes | List/save/load/delete/compare/export happy paths and missing-id errors already have tests. | Cross-session rejection, missing comparison selection, empty-diff export, and no-active/no-engine save/load edges. |
| Browser validation | Page load, planning table, edit heatmap class, undo, sessions, and machine-edit DOM behavior already have tests. | Canvas nonblank checks and edit-to-chart pixel/data changes. |

Stale target note: `modules/license_manager.py`, `ui/routes/license.py`, and
`tests/test_routes_license.py` are deleted in the current working tree. Sprint 8
should remain parked unless the license feature is restored.

## Sprint 1 - High-Value Route Edge Cases

Objective: strengthen Flask API contracts, especially where users change state,
work with scenarios, or run exports.

### 1A. Workflow Routes

Files:

- `ui/routes/workflow.py`
- `tests/test_routes_workflow.py`

Scenarios to test:

- upload without file
- upload with empty filename
- upload with non-Excel extension
- corrupt workbook or loader exception
- multi-file upload without configured master file
- multi-file upload with wrong master-keyword match
- calculate without active session
- calculate without workbook path
- calculate when engine construction fails
- calculate when `PlanningEngine.run()` raises
- successful multi-file session creation with correct metadata

Acceptance criteria:

- Response status codes and JSON shapes remain stable.
- Error messages are specific enough for the UI.
- Runtime files are not written into the repository.
- `ui/routes/workflow.py` moves toward 70%+ coverage.

### 1B. Session Routes

Files:

- `ui/routes/sessions.py`
- `tests/test_routes_sessions.py`

Scenarios to test:

- snapshot without active session
- snapshot with engine deepcopy failure
- switch to unknown session
- switch restores `_global_config` from the target session
- deleting the active session promotes a predictable next active session
- deleting the last session leaves the app in a safe empty state
- rename with empty name
- rename unknown session
- session list contains pending edit count, calculated flag, and metadata

Acceptance criteria:

- No cross-session state leakage.
- Snapshot failure is not presented as a successful calculated snapshot.
- `ui/routes/sessions.py` moves toward 75%+ coverage.

### 1C. Scenario Routes

Files:

- `ui/routes/scenarios.py`
- `tests/test_routes_scenarios.py`

Scenarios to test:

- save without active session or engine
- save with duplicate or empty name
- load unknown scenario
- load restores `results`, `value_results`, `pending_edits`, and overrides
- compare with fewer than two scenarios
- compare scenarios from another session
- compare/export without selected comparison
- compare/export with empty diff
- delete scenario from active session
- delete scenario from another session is rejected or ignored according to the
  current contract

Acceptance criteria:

- Scenario load remains consistent across dashboard, planning, and values.
- Compare/export uses only scenarios from the active session.
- `ui/routes/scenarios.py` moves toward 75%+ coverage.

## Sprint 2 - State Snapshot, Replay, And Rebuild Edge Cases

Objective: protect reset, replay, and rebuild behavior. These are the areas
where subtle session bugs usually appear.

Files:

- `ui/state_snapshot.py`
- `ui/replay.py`
- `ui/engine_rebuild.py`
- `ui/config_store.py`
- `tests/test_state_snapshot.py`
- `tests/test_replay.py`
- `tests/test_engine_rebuild.py`

Scenarios to test:

- snapshot preserves `results`, `value_results`, machine overrides, value aux
  overrides, and valuation params
- restore accepts missing optional fields from older session stores
- restore does not overwrite live session fields that do not belong to the
  snapshot
- replay preserves pending edit order
- replay of Line 01 followed by Line 06 matches the live edit result
- replay of Line 07, Line 09, Line 11, and Line 12 uses the correct override
  stores
- rebuild applies session config overrides before pending edits replay
- rebuild fails clearly when workbook path is missing
- reset baseline remains isolated from live engine mutations

Acceptance criteria:

- The six state-sync points from the development guide are named for each new state test.
- `ui/state_snapshot.py` moves toward 80%+ coverage.
- `ui/replay.py` and `ui/engine_rebuild.py` move toward 85%+ coverage.

## Sprint 3 - Automated Chart And Heatmap Validation

Objective: automate the visual checks currently covered mostly by human
validation.

Files:

- `tests/browser/test_charts.py`
- `tests/browser/test_visual_regression.py` or a smaller smoke-test file
- optional helpers in `tests/browser/conftest.py`

Scenarios to test:

- dashboard charts are visible and nonblank
- capacity charts are visible and nonblank
- values charts are visible and nonblank
- heatmap contains multiple color categories
- after a Line 09 edit, utilization chart data or pixels change
- after a Line 12 edit, FTE or value chart data or pixels change
- after machine OEE/availability edit, the relevant chart and heatmap change
- after undo, chart/heatmap returns to previous state
- no JavaScript console errors during chart refresh

Technical approach:

- Use Playwright to sample canvas pixels.
- Assert more than "canvas exists":
  - width and height exceed a minimum
  - colored pixel count is above a threshold
  - canvas is not fully white, black, or transparent
- For data-change tests:
  - capture pixel or data snapshot before edit
  - perform edit
  - wait for API response and chart redraw
  - compare pixel hash or chart dataset

Acceptance criteria:

- At least one nonblank test per chart area.
- At least three edit-to-chart-change tests.
- TEST F evidence is converted into automated checks where practical.
- Browser tests improve product validation even if they do not directly
  increase `pytest-cov`.

## Sprint 4 - Upload, Data Loader, And Workbook Error Paths

Objective: handle bad input and realistic workbook problems clearly and safely.

Files:

- `modules/data_loader.py`
- `ui/errors.py`
- `ui/routes/workflow.py`
- `tests/test_data_loader_errors.py`
- `tests/test_routes_workflow.py`

Scenarios to test:

- missing required sheets
- sheet exists but required columns are missing
- empty workbook
- workbook with zero materials
- workbook with one planning period
- workbook with invalid date or period columns
- non-numeric values in numeric fields
- duplicate material rows
- duplicate routing rows
- missing purchase actuals
- missing valuation parameters
- permission error while reading
- simulated file lock / open-in-Excel behavior
- `MemoryError` or large-file guard

Acceptance criteria:

- User-facing error classification remains understandable.
- Loader exceptions are not shown as generic 500s without context.
- No tests use customer data or hardcoded local paths.
- `modules/data_loader.py` moves toward 80%+ coverage.

## Sprint 5 - Engine Edge Cases And Synthetic Fixtures

Objective: cover calculation behavior outside the normal happy path without
changing formulas.

Files:

- `modules/planning_engine.py`
- `modules/capacity_engine.py`
- `modules/inventory_engine.py`
- `modules/inventory_quality_engine.py`
- `modules/mom_comparison_engine.py`
- focused test files per engine

Scenarios to test:

- empty material set
- single-material planning
- single-period planning
- materials without BOM children
- materials with multiple BOM levels
- circular BOM detection or current fallback behavior explicitly documented
- machine without routing
- routing to unknown machine
- missing shift system
- capacity with zero available hours
- capacity with extreme utilization
- inventory with negative starting stock
- missing target stock
- value planning without valuation params
- MoM without overlapping periods
- MoM with new and removed materials

Approach:

- Use small synthetic fixtures built from dataclasses.
- Keep one engine focus per test file.
- For `PlanningEngine`, focus on orchestration:
  - constructor config
  - `run()` calls engines in the expected order
  - `results` and `value_results` are set
  - export helpers receive the expected data

Acceptance criteria:

- `modules/capacity_engine.py` moves toward 85%+ coverage.
- `modules/inventory_engine.py` moves toward 85%+ coverage.
- `modules/mom_comparison_engine.py` moves toward 80%+ coverage.
- `modules/planning_engine.py` improves on meaningful orchestration paths; do
  not force fragile tests for every export-formatting branch.

## Sprint 6 - Export, MoM, And Cycle Manager

Objective: protect reporting output and cycle snapshot behavior.

Files:

- `modules/database_exporter.py`
- `modules/cycle_manager.py`
- `modules/mom_comparison_engine.py`
- `ui/routes/exports.py`
- `tests/test_database_exporter.py`
- `tests/test_cycle_manager.py`
- `tests/test_mom_comparison_engine.py`
- `tests/test_routes_exports.py`

Scenarios to test:

- export without engine
- export with previous-cycle snapshot
- export when previous-cycle snapshot is corrupt or empty
- export DB with empty rows
- export DB with valid rows and sanitized filename
- cycle snapshot save/load metadata
- cycle snapshot list sorting
- cycle snapshot clear/delete
- corrupt metadata is handled safely
- MoM compare with missing columns
- MoM scatter data with empty input

Acceptance criteria:

- Runtime output goes to the app-data/export folder, not into the repository.
- Export route HTTP contracts remain stable.
- `modules/cycle_manager.py` moves toward 80%+ coverage.
- `modules/mom_comparison_engine.py` moves toward 80%+ coverage.

## Sprint 7 - Performance And Large-Workbook Validation

Objective: make large customer-style workbooks measurable and catch runtime or
memory regressions.

Files:

- `tests/performance/test_large_workbook.py`
- `tests/performance/test_large_session_replay.py`
- optional `scripts/generate_synthetic_workbook.py`

Scenarios to test:

- 1,000+ materials
- 36 planning periods
- deep BOM with multiple levels
- many machine routings
- many pending edits replayed
- export of large result set
- scenario comparison with large snapshots

Approach:

- Use synthetic data, not customer data.
- Mark performance tests separately, for example `@pytest.mark.performance`.
- Do not run them in every quick unit-test pass.
- Use broad guardrail thresholds:
  - maximum smoke runtime
  - maximum replay runtime
  - maximum export runtime
  - memory must not grow without bound

Acceptance criteria:

- Performance tests are reproducible.
- They run on demand or in nightly CI, not in every small PR.
- When a threshold fails, the slow step is clear.

## Sprint 8 - License And Security Edge Cases

Objective: explicitly test license and security-sensitive branches if this
feature remains in the selected build.

Files:

- `modules/license_manager.py`
- `ui/routes/license.py`
- `tests/test_license_manager.py`
- `tests/test_routes_license.py`

Scenarios to test:

- valid activation
- expired trial
- expired full license
- tampered license record
- missing license file
- corrupt license file
- system-clock edge cases
- activation with missing fields
- protected API without activation
- protected API with valid activation

Acceptance criteria:

- License failure modes are predictable.
- No real secrets or customer data are used in tests.
- `modules/license_manager.py` moves toward 80%+ if the license feature remains
  active.

## Sprint 9 - CI, Reporting, And Regression Gates

Objective: make coverage improvements durable, not just local.

Work:

- Add stable test commands to CI:
  - fast unit/route tests
  - full coverage run
  - browser smoke run
  - optional performance/nightly run
- Store coverage HTML as a CI artifact.
- Publish `coverage.xml`.
- Add a minimum total coverage threshold after the suite is stable.
- Consider per-package thresholds:
  - `ui` minimum
  - `modules` minimum
  - no hard threshold for files where low coverage is consciously accepted

Suggested thresholds:

| Phase | Threshold |
|---|---:|
| Now | no hard gate, report only |
| After sprint 2 | total >= 70% |
| After sprint 5 | total >= 75% |
| After sprint 8 | total >= 80% |

Acceptance criteria:

- Coverage drops are visible in PRs.
- Browser regressions are reported separately from code coverage.
- Performance regressions block nightly/release only, not every small PR.

## Recommended Order

1. Sprint 0: record measurement baseline and test commands.
2. Sprint 1B and 1C: sessions/scenarios edge routes, because state bugs damage
   user trust quickly.
3. Sprint 3: chart/heatmap automation, because this is currently mostly
   manual.
4. Sprint 1A and sprint 4: upload/calculate/data-loader error paths.
5. Sprint 2: deepen state snapshot/replay/rebuild edge coverage.
6. Sprint 6: export, MoM, and cycle manager.
7. Sprint 5: engine edge cases with synthetic fixtures.
8. Sprint 7: performance and large-workbook guardrails.
9. Sprint 8: license/security if this feature remains in scope.
10. Sprint 9: enable CI gates only once the suite is stable.

## Concrete Test Backlog

High priority:

- Completed: `test_routes_scenarios_compare_rejects_cross_session_scenarios`
- Completed: `test_routes_scenarios_load_restores_values_and_pending_edits`
- Completed: `test_browser_capacity_charts_are_nonblank`
- Completed: `test_workflow_calculate_returns_specific_error_when_engine_run_fails`
- Completed: `test_cycle_manager_corrupt_metadata_is_ignored_or_quarantined`
- Still valuable: `test_browser_l9_edit_changes_utilization_chart`
- Still valuable: `test_browser_l12_edit_changes_fte_or_value_chart`
- Still valuable: `test_data_loader_missing_required_sheet_is_classified`
- Still valuable: `test_state_replay_line01_then_line06_matches_live_sequence`
- Not applicable as written: `test_routes_sessions_snapshot_deepcopy_failure_does_not_create_successful_snapshot` because snapshots no longer deepcopy live engine objects.

Medium priority:

- Completed: `test_mom_no_overlapping_periods_returns_empty_comparison`
- `test_inventory_negative_starting_stock_is_handled`
- `test_capacity_zero_available_hours_does_not_crash`
- Completed: `test_export_with_previous_cycle_snapshot_passes_mom_data`
- Completed: `test_scenario_compare_export_without_selection_returns_400`
- `test_rebuild_applies_session_config_before_replay`
- `test_data_loader_duplicate_material_rows_are_deterministic`
- Completed: `test_planning_engine_run_sets_results_and_value_results`

Low priority:

- screenshot regression with baseline images
- cryptographic license edge cases if license is outside demo/release scope
- extensive Excel formatting checks
- pixel-perfect chart comparison

## Sprint Report Template

Each coverage sprint should end with this short report:

```text
Sprint:
New/changed test files:
Production code changed: yes/no
Coverage before:
Coverage after:
Main per-file deltas:
New risks or bugs found:
Not tested and why:
Commands:
```

Minimum commands:

```powershell
python -m py_compile <changed test files>
pytest -v <targeted test files>
pytest --cov=ui --cov=modules --cov-report=term-missing --cov-report=html
python main.py --test
```

For browser work:

```powershell
pytest -v tests/browser
```

For performance work:

```powershell
pytest -v tests/performance -m performance
```

## Completed Sprint Report

Sprint: coverage completion sprint, 2026-05-06.

New/changed test files:

- `tests/test_routes_config.py`
- `tests/test_routes_scenarios.py`
- `tests/test_routes_sessions.py`
- `tests/test_routes_workflow.py`
- `tests/test_cycle_manager.py`
- `tests/test_chart_renderer.py`
- `tests/test_data_loader_errors.py`
- `tests/test_planning_engine_synthetic.py`
- `tests/browser/test_charts.py`
- `tests/performance/test_large_workflow.py`

Infrastructure and docs changed:

- `.coveragerc`
- `.github/workflows/ci.yml`
- `pytest.ini`
- `tests/README.md`
- `docs/tasks/qa-coverage-baseline.md`
- `docs/review/coverage-completion-plan.md`

Production code changed: no calculation or application logic was intentionally
changed for this sprint.

Coverage before: 76% total branch-enabled non-browser coverage.

Coverage after: 81% total branch-enabled non-browser coverage.

Fixture-free CI coverage after: 62%.

Browser validation after: 19 Playwright tests passed, with no browser console
errors.

Main per-file results after the sprint:

| File | Coverage |
|---|---:|
| `modules/planning_engine.py` | 56% |
| `modules/data_loader.py` | 71% |
| `modules/cycle_manager.py` | 96% |
| `modules/chart_renderer.py` | 98% |
| `ui/routes/config.py` | 99% |
| `ui/routes/scenarios.py` | 91% |
| `ui/routes/workflow.py` | 99% |
| `ui/routes/exports.py` | 89% |

New risks or bugs found:

- `modules/cycle_manager.py` emits a pandas `Pandas4Warning` for
  `select_dtypes(include=["object"])`. This is not a test failure, but it should
  be cleaned up before pandas 4 compatibility matters.

Not tested and why:

- Browser edit-to-chart pixel-change assertions for Line 09 and Line 12 remain
  deferred because the nonblank chart checks were stable and lower risk.
- License/security coverage remains parked because the license files are
  deleted in the current working tree.
- Hard coverage gates remain off until the suite has settled in CI.

Commands:

```powershell
python -m py_compile tests/test_routes_workflow.py tests/test_routes_scenarios.py tests/test_routes_sessions.py tests/test_routes_config.py tests/test_cycle_manager.py tests/test_chart_renderer.py tests/test_data_loader_errors.py tests/test_planning_engine_synthetic.py tests/browser/test_charts.py tests/performance/test_large_workflow.py
pytest -m no_fixture -q
python main.py --test
pytest --ignore=tests/browser --cov=ui --cov=modules --cov-report=term-missing --cov-report=xml --cov-report=html
pytest -q tests/browser
pytest -q tests/performance/test_large_workflow.py
```

## Expected Outcome

The 2026-05-06 coverage sprint reached the realistic end state:

- 81% automated Python code coverage
- clear coverage of route, state, replay, and export failure modes
- automated nonblank checks for dashboard, values, and machine charts
- documented performance guardrails for large pending-edit replay and large synthetic result compilation
- less dependence on manual review for regression detection

The remaining gaps should then be deliberate:

- pixel-perfect visual correctness
- edit-to-chart pixel-change assertions for Line 09 and Line 12
- very specific Excel formatting details
- rare infrastructure failures
- branches that require real external systems or customer-specific data
