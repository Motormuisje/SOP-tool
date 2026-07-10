# QA Coverage Baseline

Date: 2026-04-19

Command:

```powershell
$env:SOP_GOLDEN_FIXTURE = "$env:LOCALAPPDATA\SOPPlanningEngine\fixtures\golden_MS_RECONC.xlsm"
pytest --cov=ui --cov=modules --cov-report=term-missing --cov-report=html
```

Result: 10 tests passed.

## Summary

- Overall coverage: 48% (5416 statements, 2804 missed)
- `ui`: 36% (2473 statements, 1586 missed)
- `modules`: 59% (2943 statements, 1218 missed)

The result is inside the expected 15-70% range for the first measurement
pass. The engine modules get meaningful coverage from the golden pipeline
tests, while the UI layer is mostly untested beyond import/registration
paths and the state-model tests.

## Top Five Lowest-Coverage Files

| File | Coverage | Notes |
| --- | ---: | --- |
| `ui/errors.py` | 7% | Expected gap; error-classification branches need targeted tests. |
| `modules/inventory_quality_engine.py` | 9% | Expected gap; optional quality overlay is not exercised by current golden tests. |
| `ui/routes/scenarios.py` | 9% | Expected gap; Flask route behavior is Layer 2 work. |
| `ui/routes/workflow.py` | 11% | Expected gap; upload/calculate routes need Flask client tests. |
| `ui/routes/edits.py` | 12% | Expected gap; edit endpoints and cascade route behavior need Layer 2 tests. |

## Per-Area Notes

The `modules` package is substantially covered by the full golden pipeline:
core engines such as BOM, forecast, inventory, and value planning are high.
Lower module coverage is concentrated in optional or orchestration-heavy
areas such as inventory quality, MoM comparison, database export, and parts
of `planning_engine.py` that are not reached by the current fixture path.

The `ui` package has lower coverage because most route files are not called
through a Flask test client yet. That is expected for Layer 1. Future Layer 2
tests should target route behavior, session switching, edit import/export,
scenario flows, and workflow upload/calculate paths.

The HTML report was generated in `htmlcov/` and is intentionally ignored.

## Post Layer 2 Sprint

Date: 2026-04-19

Command:

```powershell
$env:SOP_GOLDEN_FIXTURE = "$env:LOCALAPPDATA\SOPPlanningEngine\fixtures\golden_MS_RECONC.xlsm"
pytest --cov=ui --cov=modules --cov-report=term
```

Result: 18 tests passed.

Overall coverage increased from 48% to 51% (5416 statements, 2641 missed).
The gain came from Flask route tests for workflow, edit, machine reset,
pending-edit persistence, and session management routes.

Notable route-file changes:

- `ui/routes/workflow.py`: 11% -> 51%
- `ui/routes/edits.py`: 12% -> 17%
- `ui/routes/edit_state.py`: 28% -> 64%
- `ui/routes/machines.py`: 49% -> 56%
- `ui/routes/sessions.py`: 20% -> 49%

The remaining low-coverage route modules are expected gaps for future route
test sprints: scenarios, config, read, PAP, exports, and license routes.
`POST /api/sessions/snapshot` was intentionally skipped after route testing
exposed a production bug where engine deepcopy failure is swallowed and the
snapshot is returned as successful but uncalculated.

## Post Layer 3 Sprint

Date: 2026-04-19

Browser tests run on demand with `SOP_GOLDEN_FIXTURE` set and are not part of
the `pytest --cov` suite because they start a real Flask subprocess. Coverage
numbers below are from the unit + route suite only and are **unchanged** by the
browser tests.

```powershell
$env:SOP_GOLDEN_FIXTURE = "$env:LOCALAPPDATA\SOPPlanningEngine\fixtures\golden_MS_RECONC.xlsm"
pytest --cov=ui --cov=modules --cov-report=term
```

Result: same 18 tests, 51% overall coverage. Browser tests do not move this
number because `pytest-cov` does not instrument code running inside a
`subprocess.Popen` server.

New browser tests added (Playwright, Chromium only):

- `tests/browser/test_load.py`: 3 tests - page loads, table renders, period headers
- `tests/browser/test_edits.py`: 3 tests - cell edit, heatmap class, undo
- `tests/browser/test_sessions.py`: 3 tests - session list, switch, delete

Total browser tests: 9. Run with:

```powershell
$env:SOP_GOLDEN_FIXTURE = "$env:LOCALAPPDATA\SOPPlanningEngine\fixtures\golden_MS_RECONC.xlsm"
pytest tests/browser/ -v
```

Subprocess coverage gap: all Flask route code executed via browser tests is not
captured. The unit + route coverage (51%) remains the authoritative number for
CI purposes. Browser tests verify rendered DOM state and client-side behavior
that no HTTP-level test can cover.

## Coverage Completion Sprint

Date: 2026-05-06

Source: full non-browser coverage run after the coverage completion sprint.

Command:

```powershell
$env:SOP_GOLDEN_FIXTURE = "$env:LOCALAPPDATA\SOPPlanningEngine\fixtures\golden_MS_RECONC.xlsm"
pytest --cov=ui --cov=modules --cov-report=term-missing --cov-report=html --cov-report=xml
```

Current measured baseline:

- Overall coverage with branch measurement enabled: 81% (5,577 statements,
  2,138 branches)
- Statement misses: 899
- Partial branch misses: 247
- Fixture-free CI coverage slice: 62% (`pytest -m no_fixture --cov=ui --cov=modules`)
- Browser validation: 19 passed (`pytest -q tests/browser`)
- Measurement model:
  - route/API tests count toward Python coverage
  - browser tests validate rendered product behavior
  - browser subprocess coverage is intentionally not required unless it becomes stable

Top ten lowest-coverage files:

| File | Coverage | Missing lines |
| --- | ---: | ---: |
| `modules/planning_engine.py` | 56% | 336 |
| `ui/app.py` | 56% | 79 |
| `modules/data_loader.py` | 71% | 180 |
| `ui/paths.py` | 74% | 3 |
| `modules/capacity_engine.py` | 77% | 90 |
| `modules/inventory_engine.py` | 82% | 28 |
| `ui/routes/machines.py` | 84% | 35 |
| `ui/routes/sessions.py` | 86% | 15 |
| `ui/state_snapshot.py` | 87% | 19 |
| `ui/volume_change.py` | 87% | 28 |

Note: license files are deleted in the current working tree, so license coverage
is no longer an active hotspot in this measurement. Browser tests remain outside
this coverage number.

New coverage added in this sprint:

- route edge cases for scenarios, sessions, workflow calculate errors, and config master-file upload
- cycle-manager corrupt/missing metadata and snapshot persistence paths
- static chart renderer PNG smoke coverage
- data-loader parsing/config edge cases without a customer workbook
- planning-engine orchestration/export helper coverage with synthetic fixtures
- Playwright canvas nonblank checks for dashboard, values, and machine charts
- performance guardrails for large pending-edit replay and large synthetic result compilation

Known warning surfaced by the new tests: `modules/cycle_manager.py` uses
`select_dtypes(include=["object"])`, which pandas warns will change behavior in
pandas 4. Production code was intentionally left unchanged during this
test-only sprint.
