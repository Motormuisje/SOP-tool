"""What the user sees live must equal what a restart rebuilds.

docs/ontwikkelhandleiding.md ("Cascade-invariant per lijntype"): after a
restart the engine is rebuilt from the workbook and the saved pending_edits
are replayed. If live behaviour diverges from that replay, the live behaviour
is wrong, because the replay is what survives a restart.

Each case drives a seeded random sequence of user operations through the
real code paths on one live session, then builds the restart view the way
ui/app.py::_build_and_install_session_engine does:

    save_sessions_to_disk -> load_sessions_from_disk
    -> build_clean_engine_for_session
    -> install_clean_engine_baseline(clear_machine_overrides=False)
    -> replay_pending_edits

and compares every planning row (keyed by line type, material number and
normalised aux column), every starting stock and the value_results rows
(consolidation included), plus the edit state a restart carries forward
(pending_edits, the override stores, the machine parameters).

Operations: Line 01 forecast, Line 05 target, Line 06 production/purchase,
L4 starting stock and L7/L9/L11 capacity cells through /api/update_volume
(apply_volume_change); undo and redo through /api/undo and /api/redo;
setting an earlier edit back to its original value; machine OEE,
availability and shift hours through /api/machines/update and
/api/machines/undo; value-planning aux factors through /api/update_value_aux;
Reset through /api/reset_edits.

Two client models:
- "server": pending_edits is left to the server alone.
- "client": also does what ui/templates/index.html does around those calls:
  _commitPlanEditNow persists every cell edit (/api/sessions/edits/persist,
  cell key built with `aux_column || ''`), and undoEdit/redoEdit replace the
  whole store with _rebuildCellEditsFromResults (/api/sessions/edits/sync).

Building an engine from the golden workbook takes about ten seconds, so each
distinct build (the calculate build and the restart build, keyed by every
input the app passes to it) is made once and deep-copied per case.
"""

import contextlib
import copy
import io
import json
import math
import random
from collections import defaultdict

import pytest
from flask import Flask

from modules.models import LineType
from modules.planning_engine import PlanningEngine
from ui.engine_rebuild import (
    build_clean_engine_for_session,
    get_session_config_overrides,
    install_clean_engine_baseline,
)
from ui.master_source import resolve_for_session
from ui.parsers import valuation_params_from_config
from ui.pending_edits import aux_str
from ui.replay import recalculate_value_results, replay_pending_edits
from ui.routes.edit_state import create_edit_state_blueprint
from ui.routes.edits import create_edits_blueprint
from ui.routes.machines import create_machines_blueprint
from ui.serializers import planning_value_payload
from ui.session_store import load_sessions_from_disk, save_sessions_to_disk
from ui.state_snapshot import (
    apply_machine_overrides,
    ensure_reset_baseline,
    machine_overrides_from_engine,
    restore_engine_state,
    snapshot_has_manual_edits,
)
from ui.volume_change import (
    EDITABLE_LINE_TYPES,
    SHIFT_HOURS_LOOKUP_FALLBACK,
    VALUE_AUX_EDITABLE_LINE_TYPES,
    apply_volume_change,
    recalculate_capacity_and_values,
)

PARAMETERS = {'planning_month': '2025-12', 'months_actuals': 11, 'months_forecast': 12}
SESSION_ID = 'state-sequence-session'
REL_TOL = 1e-6
ABS_TOL = 1e-9  # float noise around zero; a relative tolerance alone never matches 0 vs 1e-13
MAX_REPORTED = 8

L01 = LineType.DEMAND_FORECAST.value
L02 = LineType.DEPENDENT_DEMAND.value
L04 = LineType.INVENTORY.value
L05 = LineType.MIN_TARGET_STOCK.value
L06_PROD = LineType.PRODUCTION_PLAN.value
L06_PURCH = LineType.PURCHASE_RECEIPT.value
L07 = LineType.CAPACITY_UTILIZATION.value
L09 = LineType.AVAILABLE_CAPACITY.value
L11 = LineType.SHIFT_AVAILABILITY.value

FACTORS = (0.5, 0.75, 1.25, 1.5, 2.0)


class HarnessError(Exception):
    """An operation or a precondition failed. Kept apart from AssertionError
    so an xfail(raises=AssertionError) only ever matches the invariant."""


def _require(condition, message):
    if not condition:
        raise HarnessError(message)


# ---------------------------------------------------------------------------
# Engines: the calculate build and the restart build
# ---------------------------------------------------------------------------

_ENGINES = {}


def _quiet():
    return contextlib.redirect_stdout(io.StringIO())


def _copy_engine(engine):
    """Deep copy of a built engine. The loader keeps a pandas ExcelFile with
    an open handle; it is only read during load, so the copy shares it."""
    excel = getattr(getattr(engine, 'data', None), 'excel_file', None)
    return copy.deepcopy(engine, {id(excel): excel} if excel is not None else {})


def _build_key(kind, sess, params):
    # Every input the app feeds into the build. The master and UoM stores are
    # isolated per test by conftest (always empty), so they are constant.
    return json.dumps(
        [kind, sess.get('file_path'), sess.get('extract_files'), params,
         get_session_config_overrides(sess, {})],
        sort_keys=True, default=str,
    )


def _calculated_session(golden_fixture_path, app):
    """A session as upload + /api/calculate leave it (ui/routes/workflow.py:
    _session_payload, then PlanningEngine(..., get_config_overrides()) ->
    install_clean_engine_baseline -> replay_pending_edits)."""
    sess = {
        'id': SESSION_ID,
        'file_path': str(golden_fixture_path),
        'filename': golden_fixture_path.name,
        'custom_name': 'State sequences',
        'engine': None,
        'value_results': {},
        'metadata': {'planning_month': PARAMETERS['planning_month']},
        'uploaded_at': '2026-11-14T00:00:00',
        'undo_stack': [],
        'redo_stack': [],
        'pending_edits': {},
        'value_aux_overrides': {},
        'machine_overrides': {},
        'added_products': [],
    }
    key = _build_key('calculate', sess, PARAMETERS)
    if key not in _ENGINES:
        src = resolve_for_session(sess)
        with _quiet():
            engine = PlanningEngine(
                src.file_path,
                planning_month=PARAMETERS['planning_month'],
                months_actuals=PARAMETERS['months_actuals'],
                months_forecast=PARAMETERS['months_forecast'],
                extract_files=sess.get('extract_files'),
                config_overrides=get_session_config_overrides(sess, {}),
                master_data=src.master_data,
            )
            engine.run()
        _ENGINES[key] = (engine, src)
    base, src = _ENGINES[key]
    engine = _copy_engine(base)
    src.apply_to_session(sess)
    install_clean_engine_baseline(sess, engine, SHIFT_HOURS_LOOKUP_FALLBACK)
    with _quiet(), app.app_context():
        _replay(sess, engine)
    sess['engine'] = engine
    sess['parameters'] = dict(PARAMETERS)
    return sess


def _clean_engine_for(sess, params=None):
    """build_clean_engine_for_session(sess, global_config={}), built once per
    distinct input and deep-copied after that."""
    key = _build_key('restart', sess, params or sess.get('parameters'))
    if key not in _ENGINES:
        with _quiet():
            _ENGINES[key] = build_clean_engine_for_session(sess, {}, params)
    base = _ENGINES[key]
    return None if base is None else _copy_engine(base)


def _replay(sess, engine):
    replay_pending_edits(
        sess, engine, apply_volume_change, apply_machine_overrides,
        recalculate_capacity_and_values)


def _restart_view(sess, store_dir, app):
    """Persist, reload and rebuild the session the way a restart does
    (ui/app.py::_build_and_install_session_engine, without the locks)."""
    store = store_dir / 'sessions_store.json'
    save_sessions_to_disk({sess['id']: sess}, sess['id'], store, machine_overrides_from_engine)
    loaded, _active = load_sessions_from_disk(store)
    restarted = loaded[sess['id']]
    engine = _clean_engine_for(restarted)
    _require(engine is not None, 'the reloaded session could not be rebuilt')
    install_clean_engine_baseline(restarted, engine, SHIFT_HOURS_LOOKUP_FALLBACK,
                                  clear_machine_overrides=False)
    log = io.StringIO()
    with contextlib.redirect_stdout(log), app.app_context():
        _replay(restarted, engine)
    restarted['engine'] = engine
    replay_notes = [line for line in log.getvalue().splitlines()
                    if line.startswith('[replay_pending_edits]')]
    return restarted, engine, replay_notes


# ---------------------------------------------------------------------------
# The real blueprints around one live session
# ---------------------------------------------------------------------------

class _Harness:
    """Edits, edit-state and machines blueprints with the callbacks ui/app.py
    passes them (persistence to disk is the only thing left out: the restart
    view persists explicitly)."""

    def __init__(self, golden_fixture_path):
        self.global_config = {}
        self.sessions = {}
        app = Flask(__name__)
        app.config['TESTING'] = True
        app.config['PROPAGATE_EXCEPTIONS'] = True
        self.app = app

        def get_active():
            sess = self.sessions.get(SESSION_ID)
            return sess, (sess or {}).get('engine')

        def ensure_baseline(sess, engine):
            ensure_reset_baseline(sess, engine, SHIFT_HOURS_LOOKUP_FALLBACK)

        def install_baseline(sess, engine, clear_machine_overrides=True):
            install_clean_engine_baseline(sess, engine, SHIFT_HOURS_LOOKUP_FALLBACK,
                                          clear_machine_overrides=clear_machine_overrides)

        def no_save():
            return None

        app.register_blueprint(create_edits_blueprint(
            get_active,
            VALUE_AUX_EDITABLE_LINE_TYPES,
            self.global_config,
            apply_volume_change,
            ensure_baseline,
            lambda engine, sess: recalculate_value_results(engine, sess),
            no_save,
            valuation_params_from_config,
            lambda engine, snapshot: restore_engine_state(engine, snapshot, self.global_config),
            snapshot_has_manual_edits,
            _clean_engine_for,
            install_baseline,
        ))
        app.register_blueprint(create_edit_state_blueprint(
            self.sessions, EDITABLE_LINE_TYPES, no_save))
        app.register_blueprint(create_machines_blueprint(
            get_active,
            machine_overrides_from_engine,
            lambda machine, data: SHIFT_HOURS_LOOKUP_FALLBACK(machine, data),
            ensure_baseline,
            lambda engine, sess: recalculate_capacity_and_values(engine, sess),
            planning_value_payload,
            no_save,
        ))
        self.client = app.test_client()
        self.sess = _calculated_session(golden_fixture_path, app)
        self.sessions[SESSION_ID] = self.sess

    @property
    def engine(self):
        return self.sess['engine']


# ---------------------------------------------------------------------------
# What the browser does with aux values (ui/templates/index.html)
# ---------------------------------------------------------------------------

def _js_string(value):
    """String(value) in the browser, for a value that came through Flask's
    JSON: an int-like float has lost its '.0'."""
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    return str(value)


def _js_nullish(value):
    """String(value ?? ''): the data-aux of a period cell (index.html:9326)."""
    return '' if value is None else _js_string(value)


def _js_or_empty(value):
    """`value || ''`: cell keys (index.html:9280, :9378, :8698) and the
    starting-stock cell's data-aux. 0 and '' are falsy, '0' is not."""
    if value is None or value == '' or (isinstance(value, (int, float)) and value == 0):
        return ''
    return _js_string(value)


# ---------------------------------------------------------------------------
# A seeded operation sequence
# ---------------------------------------------------------------------------

def _nonzero_periods(row, periods):
    return [p for p in periods if abs(float(row.values.get(p, 0.0) or 0.0)) > 1e-9]


def _sorted_rows(rows):
    return sorted(rows, key=lambda r: (str(r.material_number), aux_str(r.aux_column)))


def _fmt(value):
    if isinstance(value, float):
        return f'{value:.6g}'
    return repr(value)


class _Sequence:
    WEIGHTS = {
        'forecast': 3.0, 'target': 2.0, 'plan': 3.0, 'stock': 2.0, 'capacity': 2.0,
        'machine': 1.0, 'machine_undo': 0.5, 'value_aux': 0.5, 'undo': 2.0, 'redo': 1.5,
        'revert': 1.5, 'reset': 0.25,
    }

    def __init__(self, harness, seed, client_model):
        self.h = harness
        self.rng = random.Random(seed)
        self.client_sync = client_model == 'client'
        self.ops = []
        self.focus = self._pick_focus()

    # -- choosing ------------------------------------------------------------

    def _pick_focus(self):
        """One finished product with a forecast and a production plan, plus
        its BOM children and grandchildren: edits that share materials are
        where cascades interact."""
        results = self.h.engine.results
        periods = self.h.engine.data.periods
        with_forecast = {r.material_number for r in results[L01] if _nonzero_periods(r, periods)}
        produced = {r.material_number for r in results[L06_PROD] if _nonzero_periods(r, periods)}
        root = self.rng.choice(sorted(with_forecast & produced))
        children = sorted({r.material_number for r in results[L02] if str(r.aux_column) == root})
        grandchildren = sorted({r.material_number for r in results[L02] if str(r.aux_column) in children})
        return {root, *children, *grandchildren}

    def _pick_row(self, line_type, predicate=None, need_values=True):
        engine = self.h.engine
        rows = [
            r for r in engine.results.get(line_type, [])
            if (predicate is None or predicate(r))
            and (not need_values or _nonzero_periods(r, engine.data.periods))
        ]
        focused = [r for r in rows if r.material_number in self.focus]
        pool = focused if focused and self.rng.random() < 0.65 else rows
        return self.rng.choice(_sorted_rows(pool)) if pool else None

    def _new_value(self, old, digits=3, allow_zero=False):
        for _ in range(10):
            if allow_zero and self.rng.random() < 0.1:
                value = 0.0
            else:
                value = round(old * self.rng.choice(FACTORS), digits)
            if abs(value - old) > 1e-6:
                return value
        return round(old + 1.0, digits)

    def _available(self):
        sess = self.h.sess
        available = dict(self.WEIGHTS)
        if not sess.get('undo_stack'):
            available.pop('undo')
        if not sess.get('redo_stack'):
            available.pop('redo')
        if not sess.get('pending_edits'):
            available.pop('revert')
        if not sess.get('machine_undo'):
            available.pop('machine_undo')
        return available

    def step(self):
        available = self._available()
        kinds = sorted(available)
        kind = self.rng.choices(kinds, weights=[available[k] for k in kinds])[0]
        getattr(self, f'_op_{kind}')()

    # -- cell edits through /api/update_volume -------------------------------

    def _edit_cell(self, label, line_type, row, period, new_value):
        old = row.starting_stock if period == 'starting_stock' else row.get_value(period)
        if period == 'starting_stock':
            aux_sent = _js_or_empty(aux_str(row.aux_column))    # index.html:9379; aux arrives as row_payload's string
        else:
            aux_sent = _js_nullish(row.aux_column)     # index.html:9326
        material = str(row.material_number)
        response = self.h.client.post('/api/update_volume', json={
            'line_type': line_type, 'material_number': material,
            'aux_column': aux_sent, 'period': period, 'new_value': new_value,
        })
        data = response.get_json() or {}
        applied = (data.get('edit_meta') or {}).get('new_value', new_value)
        self.ops.append(
            f'{label}: {line_type} | {material} | aux {aux_sent!r} | {period}: '
            f'{_fmt(float(old))} -> {_fmt(float(applied))} [{response.status_code}]')
        _require(response.status_code == 200, f'{self.ops[-1]}: {data.get("error")}')
        if self.client_sync:
            self._persist_like_the_browser(line_type, row, material, aux_sent, period, data)

    def _persist_like_the_browser(self, line_type, row, material, aux_sent, period, data):
        """index.html _commitPlanEditNow: persist under the cell's data-key."""
        key = f'{line_type}||{material}||{_js_or_empty(aux_str(row.aux_column))}||{period}'
        row_data = next(
            (r for r in (data.get('results') or {}).get(line_type, [])
             if str(r.get('material_number')) == material
             and _js_nullish(r.get('aux_column')) == aux_sent),
            None,
        )
        meta = data.get('edit_meta') or {}
        entry = ((row_data or {}).get('manual_edits') or {}).get(period)
        original = entry['original'] if entry else meta.get('original_value', meta.get('old_value'))
        response = self.h.client.post('/api/sessions/edits/persist', json={
            'session_id': SESSION_ID, 'key': key,
            'original': original, 'new_value': meta.get('new_value'),
        })
        _require(response.status_code == 200, f'persist {key}: {response.get_json()}')

    def _op_forecast(self):
        row = self._pick_row(L01)
        period = self.rng.choice(_nonzero_periods(row, self.h.engine.data.periods))
        self._edit_cell('forecast', L01, row, period,
                        self._new_value(row.get_value(period), allow_zero=True))

    def _op_target(self):
        row = self._pick_row(L05)
        period = self.rng.choice(_nonzero_periods(row, self.h.engine.data.periods))
        self._edit_cell('target', L05, row, period, self._new_value(row.get_value(period)))

    def _op_plan(self):
        line_type = self.rng.choice((L06_PROD, L06_PURCH))
        row = self._pick_row(line_type)
        if row is None:
            line_type = L06_PROD
            row = self._pick_row(line_type)
        period = self.rng.choice(_nonzero_periods(row, self.h.engine.data.periods))
        self._edit_cell('plan', line_type, row, period,
                        self._new_value(row.get_value(period), allow_zero=True))

    def _op_stock(self):
        row = self._pick_row(L04, predicate=lambda r: float(r.starting_stock or 0) > 0,
                             need_values=False)
        self._edit_cell('stock', L04, row, 'starting_stock',
                        self._new_value(float(row.starting_stock), allow_zero=True))

    def _op_capacity(self):
        line_type = self.rng.choice((L07, L09, L11))
        # L7 overrides act on machine-group rows only (CapacityEngine._apply_user_overrides).
        predicate = (lambda r: r.product_type == 'Machine Group') if line_type == L07 else None
        row = self._pick_row(line_type, predicate=predicate)
        period = self.rng.choice(_nonzero_periods(row, self.h.engine.data.periods))
        digits = 4 if line_type == L09 else 2
        self._edit_cell('capacity', line_type, row, period,
                        self._new_value(row.get_value(period), digits=digits))

    def _op_revert(self):
        """Type the original value back into an earlier edited cell."""
        key = self.rng.choice(sorted(self.h.sess['pending_edits']))
        line_type, material, aux, period = key.split('||')
        original = float(self.h.sess['pending_edits'][key]['original'])
        rows = [r for r in self.h.engine.results.get(line_type, [])
                if str(r.material_number) == material]
        row = next((r for r in rows if aux_str(r.aux_column) == aux), None)
        if row is None and len(rows) == 1:
            row = rows[0]
        _require(row is not None, f'revert: no row for pending key {key!r}')
        self._edit_cell('revert', line_type, row, period, original)

    # -- undo / redo through the edits blueprint ------------------------------

    def _undo_redo(self, label, path):
        response = self.h.client.post(path)
        data = response.get_json() or {}
        self.ops.append(f'{label} [{response.status_code}]')
        _require(response.status_code == 200, f'{self.ops[-1]}: {data.get("error")}')
        if self.client_sync and not data.get('error'):
            self._sync_like_the_browser(data)

    def _sync_like_the_browser(self, data):
        """index.html undoEdit/redoEdit -> _applyVolumeChangeResult ->
        _syncCellEditsFromResults -> _syncPendingEditsToServer."""
        edits = {}
        for line_type, rows in (data.get('results') or {}).items():
            for row in rows or []:
                for period, edit in (row.get('manual_edits') or {}).items():
                    key = (f"{row.get('line_type') or line_type}||{row.get('material_number')}"
                           f"||{_js_or_empty(aux_str(row.get('aux_column')))}||{period}")
                    original = float(edit.get('original') or 0)
                    new_value = float(edit['new']) if edit.get('new') is not None else original
                    edits[key] = {'original': original, 'new_value': new_value}
        response = self.h.client.post('/api/sessions/edits/sync', json={
            'session_id': SESSION_ID, 'edits': edits})
        _require(response.status_code == 200, f'sync: {response.get_json()}')

    def _op_undo(self):
        self._undo_redo('undo', '/api/undo')

    def _op_redo(self):
        self._undo_redo('redo', '/api/redo')

    def _op_reset(self):
        response = self.h.client.post('/api/reset_edits')
        self.ops.append(f'reset [{response.status_code}]')
        _require(response.status_code == 200, f'{self.ops[-1]}: {(response.get_json() or {}).get("error")}')

    # -- machines and value-planning aux ---------------------------------------

    def _machine_edit(self, code, field, value):
        response = self.h.client.post('/api/machines/update', json={
            'machine': code, 'field': field, 'value': value})
        self.ops.append(f'machine: {code} {field} -> {_fmt(value)} [{response.status_code}]')
        _require(response.status_code == 200, f'{self.ops[-1]}: {response.get_json()}')

    def _op_machine(self):
        machines = self.h.engine.data.machines
        code = self.rng.choice(sorted(c for c, m in machines.items() if m.machine_group))
        machine = machines[code]
        field = self.rng.choice(('oee', 'availability', 'shift_hours'))
        if field == 'oee':
            choices = [v for v in (0.5, 0.6, 0.8, 0.95) if abs(v - float(machine.oee)) > 1e-9]
        elif field == 'availability':
            choices = [60.0, 80.0, 100.0, 110.0]
        else:
            current = getattr(machine, 'shift_hours_override', None)
            choices = [v for v in (400.0, 480.0, 600.0) if current is None or abs(v - current) > 1e-9]
        self._machine_edit(code, field, self.rng.choice(choices))

    def _op_machine_undo(self):
        response = self.h.client.post('/api/machines/undo')
        self.ops.append(f'machine undo [{response.status_code}]')
        _require(response.status_code == 200, f'{self.ops[-1]}: {response.get_json()}')

    def _op_value_aux(self):
        engine = self.h.engine
        candidates = []
        for line_type in sorted(VALUE_AUX_EDITABLE_LINE_TYPES):
            for row in engine.value_results.get(line_type, []):
                try:
                    aux = float(row.aux_column)
                except (TypeError, ValueError):
                    continue
                if aux > 0 and any(abs(float(v or 0)) > 1e-9 for v in row.values.values()):
                    candidates.append((line_type, str(row.material_number), aux))
        line_type, material, aux = self.rng.choice(sorted(candidates))
        value = self._new_value(aux, digits=4)
        response = self.h.client.post('/api/update_value_aux', json={
            'line_type': line_type, 'material_number': material, 'new_value': value})
        self.ops.append(
            f'value aux: {line_type} | {material}: {_fmt(aux)} -> {_fmt(value)} [{response.status_code}]')
        _require(response.status_code == 200, f'{self.ops[-1]}: {response.get_json()}')


# ---------------------------------------------------------------------------
# Comparing live with the restart view
# ---------------------------------------------------------------------------

def _close(a, b):
    return math.isclose(float(a), float(b), rel_tol=REL_TOL, abs_tol=ABS_TOL)


def _aux_close(a, b):
    left, right = aux_str(a), aux_str(b)
    if left == right:
        return True
    try:
        return _close(float(left), float(right))
    except ValueError:
        return False


def _diff_rows(section, live_by_lt, replay_by_lt, with_stock):
    """Differences as (section, line type, material, aux, period, live, replayed).

    Rows pair on (line type, material, aux_str(aux)); a computed aux (the L10
    ratio, an L9 shift-hours average) that moved within tolerance still pairs,
    anything left over pairs in order and reports the aux itself."""
    def by_material(rows_by_lt):
        grouped = defaultdict(list)
        for line_type, rows in rows_by_lt.items():
            for row in rows or []:
                grouped[(line_type, str(row.material_number))].append(row)
        return grouped

    live, replay = by_material(live_by_lt), by_material(replay_by_lt)
    diffs = []
    for key in sorted(set(live) | set(replay)):
        line_type, material = key
        left, right = list(live.get(key, [])), list(replay.get(key, []))
        pairs = []
        for same in (lambda a, b: aux_str(a) == aux_str(b), _aux_close):
            for row in list(left):
                match = next((r for r in right if same(row.aux_column, r.aux_column)), None)
                if match is not None:
                    pairs.append((row, match))
                    left.remove(row)
                    right.remove(match)
        for row, match in zip(left, right):
            pairs.append((row, match))
            diffs.append((section, line_type, material, aux_str(row.aux_column), 'aux',
                          aux_str(row.aux_column), aux_str(match.aux_column)))
        for row in left[len(right):]:
            diffs.append((section, line_type, material, aux_str(row.aux_column), '(row)', 'present', 'missing'))
        for row in right[len(left):]:
            diffs.append((section, line_type, material, aux_str(row.aux_column), '(row)', 'missing', 'present'))
        for a, b in pairs:
            aux = aux_str(a.aux_column)
            if with_stock and not _close(a.starting_stock or 0.0, b.starting_stock or 0.0):
                diffs.append((section, line_type, material, aux, 'starting_stock',
                              a.starting_stock, b.starting_stock))
            for period in sorted(set(a.values) | set(b.values)):
                va, vb = a.values.get(period), b.values.get(period)
                if va is None or vb is None or not _close(va, vb):
                    diffs.append((section, line_type, material, aux, period, va, vb))
    return diffs


def _edit_state(sess, engine):
    capacity = {
        (lt, mat, period): float(value)
        for lt, by_mat in (sess.get('capacity_overrides') or {}).items()
        for mat, by_period in by_mat.items()
        for period, value in by_period.items()
    }
    machines = {
        code: (float(m.oee),
               tuple(sorted((p, float(v)) for p, v in (m.availability_by_period or {}).items())),
               None if m.shift_hours_override is None else float(m.shift_hours_override))
        for code, m in engine.data.machines.items()
    }
    return {
        'pending_edits': {k: (float(v['original']), float(v['new_value']))
                          for k, v in (sess.get('pending_edits') or {}).items()},
        'inventory_overrides': {k: float(v) for k, v in (sess.get('inventory_overrides') or {}).items()},
        'capacity_overrides': capacity,
        'value_aux_overrides': {
            k: float(v.get('new_value', 0) if isinstance(v, dict) else v)
            for k, v in (sess.get('value_aux_overrides') or {}).items()},
        'machines': machines,
    }


def _same(a, b):
    if isinstance(a, tuple) and isinstance(b, tuple):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return _close(a, b)
    return a == b


def _diff_edit_state(live, replay):
    diffs = []
    for store in live:
        for key in sorted(set(live[store]) | set(replay[store]), key=str):
            a, b = live[store].get(key, 'absent'), replay[store].get(key, 'absent')
            if not _same(a, b):
                diffs.append(f'{store} {key!r}: live {a!r} | restart {b!r}')
    return diffs


def _compare(live_sess, live_engine, restart_sess, restart_engine):
    cells = _diff_rows('results', live_engine.results, restart_engine.results, with_stock=True)
    cells += _diff_rows('value_results', live_engine.value_results, restart_engine.value_results,
                        with_stock=False)
    state = _diff_edit_state(_edit_state(live_sess, live_engine),
                             _edit_state(restart_sess, restart_engine))
    return cells, state


def _report(title, ops, cells, state, replay_notes, live_sess):
    lines = [title, 'operations:']
    lines += [f'  {i}. {op}' for i, op in enumerate(ops, 1)] or ['  (none)']
    if cells:
        lines.append(f'first differing cells ({len(cells)} in total): '
                     'section | line type | material | aux | period | live | replayed')
        for section, lt, mat, aux, period, va, vb in cells[:MAX_REPORTED]:
            lines.append(f'  {section} | {lt} | {mat} | {aux!r} | {period} | {_fmt(va)} | {_fmt(vb)}')
    if state:
        lines.append(f'edit state that differs after the restart ({len(state)}):')
        lines += [f'  {d}' for d in state[:MAX_REPORTED]]
    if replay_notes:
        lines.append('replay log:')
        lines += [f'  {n}' for n in replay_notes[:MAX_REPORTED]]
    lines.append('pending_edits saved for the restart (in replay order):')
    lines += [f'  {k} = {v}' for k, v in (live_sess.get('pending_edits') or {}).items()] or ['  (none)']
    return '\n'.join(lines)


def _run_and_compare(golden_fixture_path, tmp_path, title, drive):
    harness = _Harness(golden_fixture_path)
    with _quiet():
        ops = drive(harness)
    restart_sess, restart_engine, notes = _restart_view(harness.sess, tmp_path, harness.app)
    cells, state = _compare(harness.sess, harness.engine, restart_sess, restart_engine)
    assert not (cells or state), _report(title, ops, cells, state, notes, harness.sess)


def _row(engine, line_type, material):
    return next(r for r in engine.results.get(line_type, []) if str(r.material_number) == material)


# ---------------------------------------------------------------------------
# Known divergences (xfail, strict: a fix turns them into a failure, which
# says to remove the mark). Each has a minimal directed case further down.
# ---------------------------------------------------------------------------

L05_AUX_KEY = (
    'L05 pending key embeds the computed aux (average target), which moves after the edit; '
    'setting the cell back pops a key that does not exist and the edit returns after a restart')
L11_AUX_KEY = (
    "L11 pending key embeds the aux, which becomes 'Machine override' after a shift-hours edit; "
    'setting the cell back pops a key that does not exist and the edit returns after a restart')
L05_CLIENT_REKEY = (
    'the browser sync after undo re-keys an L05 edit under the moved aux; the next undo pops '
    'the key recorded at edit time and the edit returns after a restart')
L05_DROPPED = (
    'an L05 target edit is dropped from the inventory calculation by a later forecast or stock '
    'recalculation of the material (or its undo) while the cell keeps showing it; replay '
    'recalculates in a different order')
N4_ORDER = (
    'N4: the browser sync after undo/redo rewrites pending_edits in results order, so replay '
    'recalculates L01 before L05 and keeps a target edit that live had dropped')
REPLAY_DROPS_PIN = (
    'replay treats an edit whose value equals the fresh engine value as a revert and drops it, '
    'so a pinned plan cell floats again after a restart')


def _xfail(reason):
    return pytest.mark.xfail(strict=True, raises=AssertionError, reason=reason)


# 27 and 38 are the first seeds above 16 that draw a machine undo.
# 39 and 43 found the L11 aux-key and dropped-L05-target divergences; kept as regressions.
SERVER_SEEDS = {seed: None for seed in (*range(1, 17), 27, 38, 39, 43)}
CLIENT_SEEDS = {seed: None for seed in range(1, 11)}
CLIENT_SEEDS.update({16: None, 59: None})

SEQUENCE_CASES = [
    pytest.param(seed, model, id=f'{model}-seed{seed}', marks=[_xfail(reason)] if reason else [])
    for model, seeds in (('server', SERVER_SEEDS), ('client', CLIENT_SEEDS))
    for seed, reason in sorted(seeds.items())
]


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------

def test_restart_without_edits_equals_live(golden_fixture_path, tmp_path):
    """The harness itself: a calculated session that is restarted untouched
    (valuation parameters and PAP now travel as session config) must look the
    same."""
    _run_and_compare(golden_fixture_path, tmp_path, 'no operations', lambda harness: [])


def _random_driver(seed, client_model):
    def drive(harness):
        sequence = _Sequence(harness, seed, client_model)
        for _ in range(sequence.rng.randint(5, 15)):
            sequence.step()
        return sequence.ops
    return drive


@pytest.mark.parametrize('seed, client_model', SEQUENCE_CASES)
def test_random_sequence_live_equals_restart(golden_fixture_path, tmp_path, seed, client_model):
    _run_and_compare(
        golden_fixture_path, tmp_path,
        f'seed {seed}, client model {client_model!r}: live and restart disagree',
        _random_driver(seed, client_model))


# -- minimal directed sequences, one per divergence ---------------------------

def _l05_row_with_values(engine):
    periods = engine.data.periods
    return next(r for r in _sorted_rows(engine.results[L05])
                if r.aux_column and len(_nonzero_periods(r, periods)) == len(periods))


def test_l05_cell_set_back_to_its_original_stays_reverted(golden_fixture_path, tmp_path):
    """target edit, then type the original back into the same cell."""
    def drive(harness):
        sequence = _Sequence(harness, 0, 'server')
        row = _l05_row_with_values(harness.engine)
        material, period = str(row.material_number), harness.engine.data.periods[3]
        original, aux_before = row.get_value(period), aux_str(row.aux_column)
        sequence._edit_cell('target', L05, row, period, round(original * 2, 3))
        moved = _row(harness.engine, L05, material)
        _require(aux_str(moved.aux_column) != aux_before, 'precondition: the L05 aux did not move')
        sequence._edit_cell('revert', L05, moved, period, original)
        return sequence.ops
    _run_and_compare(golden_fixture_path, tmp_path, 'L05 edit, then set back', drive)


def test_l05_edit_undone_with_the_browser_sync_stays_undone(golden_fixture_path, tmp_path):
    """client model: target edit, an unrelated forecast edit, undo, undo."""
    def drive(harness):
        sequence = _Sequence(harness, 0, 'client')
        engine = harness.engine
        row = _l05_row_with_values(engine)
        period = engine.data.periods[3]
        sequence._edit_cell('target', L05, row, period, round(row.get_value(period) * 2, 3))
        other = next(r for r in _sorted_rows(engine.results[L01])
                     if r.material_number != row.material_number and r.get_value(period) > 0)
        sequence._edit_cell('forecast', L01, other, period, round(other.get_value(period) * 1.5, 3))
        sequence._op_undo()
        sequence._op_undo()
        _require(not harness.sess['undo_stack'], 'precondition: both edits are undone')
        return sequence.ops
    _run_and_compare(golden_fixture_path, tmp_path,
                     'L05 edit, forecast edit, undo, undo (browser sync)', drive)


def test_l11_cell_set_back_after_a_shift_hours_edit_stays_reverted(golden_fixture_path, tmp_path):
    """L11 edit, shift hours of a machine in that group, any cell edit (it puts
    the edit markers back on the rebuilt capacity rows), set the L11 cell back."""
    def drive(harness):
        sequence = _Sequence(harness, 0, 'server')
        engine = harness.engine
        machines = engine.data.machines
        period = engine.data.periods[4]
        row = next(r for r in _sorted_rows(engine.results[L11])
                   if any(m.machine_group == r.material_number for m in machines.values()))
        group = str(row.material_number)
        original, aux_before = row.get_value(period), aux_str(row.aux_column)
        machine = sorted(code for code, m in machines.items() if m.machine_group == group)[0]
        sequence._edit_cell('capacity', L11, row, period, round(original / 2, 2))
        sequence._machine_edit(machine, 'shift_hours', 600.0)
        _require(aux_str(_row(harness.engine, L11, group).aux_column) != aux_before,
                 'precondition: the L11 aux did not move')
        other = next(r for r in _sorted_rows(engine.results[L01]) if r.get_value(period) > 0)
        sequence._edit_cell('forecast', L01, other, period, round(other.get_value(period) * 1.5, 3))
        sequence._edit_cell('revert', L11, _row(harness.engine, L11, group), period, original)
        return sequence.ops
    _run_and_compare(golden_fixture_path, tmp_path, 'L11 edit, shift hours, set back', drive)


def _produced_material_with_target(engine, period):
    with_forecast = {r.material_number for r in engine.results[L01]
                     if _nonzero_periods(r, engine.data.periods)}
    plans = {r.material_number: r for r in engine.results[L06_PROD]}
    return next(
        r for r in _sorted_rows(engine.results[L05])
        if r.material_number in with_forecast and r.material_number in plans
        and r.get_value(period) > 0 and plans[r.material_number].get_value(period) > 0
    )


def _l05_edit_that_moves_the_plan(sequence):
    engine = sequence.h.engine
    period = engine.data.periods[6]
    row = _produced_material_with_target(engine, period)
    material = str(row.material_number)
    before = dict(_row(engine, L06_PROD, material).values)
    sequence._edit_cell('target', L05, row, period, round(row.get_value(period) * 2, 3))
    after = _row(sequence.h.engine, L06_PROD, material).values
    _require(any(not _close(before[p], after.get(p, 0.0)) for p in before),
             'precondition: the target edit did not change the production plan')
    return material


def test_l05_edit_survives_an_undone_forecast_edit(golden_fixture_path, tmp_path):
    """target edit, forecast edit on the same material, undo."""
    def drive(harness):
        sequence = _Sequence(harness, 0, 'server')
        material = _l05_edit_that_moves_the_plan(sequence)
        forecast = _row(harness.engine, L01, material)
        period = _nonzero_periods(forecast, harness.engine.data.periods)[0]
        sequence._edit_cell('forecast', L01, forecast, period,
                            round(forecast.get_value(period) * 1.25, 3))
        sequence._op_undo()
        return sequence.ops
    _run_and_compare(golden_fixture_path, tmp_path,
                     'L05 edit, L01 edit (same material), undo', drive)


def test_browser_sync_after_undo_keeps_the_replay_order(golden_fixture_path, tmp_path):
    """client model: target edit, forecast edit on the same material, an
    unrelated forecast edit, undo. Without the browser sync the same sequence
    agrees with its restart (both drop the target edit)."""
    def drive(harness):
        sequence = _Sequence(harness, 0, 'client')
        material = _l05_edit_that_moves_the_plan(sequence)
        engine = harness.engine
        forecast = _row(engine, L01, material)
        period = _nonzero_periods(forecast, engine.data.periods)[0]
        sequence._edit_cell('forecast', L01, forecast, period,
                            round(forecast.get_value(period) * 1.25, 3))
        other = next(r for r in _sorted_rows(engine.results[L01])
                     if str(r.material_number) != material and r.get_value(period) > 0)
        sequence._edit_cell('forecast', L01, other, period, round(other.get_value(period) * 1.5, 3))
        sequence._op_undo()
        return sequence.ops
    _run_and_compare(golden_fixture_path, tmp_path,
                     'L05, L01 (same material), L01 elsewhere, undo (browser sync)', drive)


def test_plan_pinned_at_the_workbook_value_stays_pinned(golden_fixture_path, tmp_path):
    """forecast x2 (the plan moves from c0 to c1), pin the plan at c0, set the
    forecast back, forecast x2 again: live keeps c0, a restart shows c1."""
    def drive(harness):
        sequence = _Sequence(harness, 0, 'server')
        engine = harness.engine
        period = engine.data.periods[2]
        plans = {r.material_number: r for r in engine.results[L06_PROD]}
        forecast = next(r for r in _sorted_rows(engine.results[L01])
                        if r.material_number in plans and r.get_value(period) > 0
                        and plans[r.material_number].get_value(period) > 0)
        material, f0 = str(forecast.material_number), forecast.get_value(period)
        c0 = plans[material].get_value(period)
        sequence._edit_cell('forecast', L01, forecast, period, round(f0 * 2, 3))
        _require(not _close(_row(harness.engine, L06_PROD, material).get_value(period), c0),
                 'precondition: the forecast edit did not move the plan')
        sequence._edit_cell('plan', L06_PROD, _row(harness.engine, L06_PROD, material), period, c0)
        sequence._edit_cell('revert', L01, _row(harness.engine, L01, material), period, f0)
        sequence._edit_cell('forecast', L01, _row(harness.engine, L01, material), period,
                            round(f0 * 2, 3))
        return sequence.ops
    _run_and_compare(golden_fixture_path, tmp_path, 'pin the plan at its workbook value', drive)
