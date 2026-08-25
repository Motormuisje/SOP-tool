"""Sessie-state `active_combinations` door de ZES sync-/rebuildpunten.

Development guide (docs/ontwikkelhandleiding.md): "Every new piece of state must participate in all six. This is the
single most common source of cross-cutting bugs." Deze testklasse loopt ze
allemaal langs, want dit veld had er geen enkele test voor — en de bugjacht
vond er meteen een gat (een gedupliceerde instantie startte met een lege set).

De zes punten:
1. _sync_global_config_from_engine  — BEWUST niet: per-sessie wat-als, geen
   globale config. Getest als afwezigheid van lekkage tussen sessies.
2. get_session_config_overrides     — een KOUDE herbouw start met de set.
3. snapshot_engine_state / Reset    — Reset zet ze uit.
4. replay_pending_edits             — na een herbouw rekent de werkbank ermee.
5. recalculate_*                    — elke cascade werkt hem bij.
6. save/load_sessions_to_disk       — hij overleeft een herstart.
"""

import copy
import json
from types import SimpleNamespace

import pytest

from modules.fte_engine import FteEngine
from modules.models import LineType, MachineCombination
from tests.test_fte_engine import PERIODS, _data, _demand_rows, _machine, _mat, _routing
from ui.engine_rebuild import get_session_config_overrides, install_clean_engine_baseline
from ui.replay import recalculate_fte_results
from ui.session_store import load_sessions_from_disk, save_sessions_to_disk
from ui.state_snapshot import restore_engine_state, snapshot_engine_state

pytestmark = pytest.mark.no_fixture


class _Engine:
    """Hetzelfde contract als PlanningEngine voor alles wat de syncpunten raken."""

    def __init__(self, data=None, results=None):
        self.data = data
        self.results = results or {}
        self.value_results = {}
        self.active_combinations = []
        self.fte_norm_overrides = {}
        self.fte_results = None
        self.config_overrides = {}

    def recalculate_fte(self, active_combinations=None, norm_overrides=None):
        if active_combinations is not None:
            self.active_combinations = list(active_combinations)
        if norm_overrides is not None:
            self.fte_norm_overrides = dict(norm_overrides)
        if self.data is None:
            return
        self.fte_results = FteEngine(
            self.data, self.results,
            active_combinations=self.active_combinations,
            staffing_norm_overrides=self.fte_norm_overrides).calculate()


def _combo_setup():
    """Twee machines in twee groepen; combinatie C1 deelt één operator."""
    from modules.capacity_engine import CapacityEngine
    from modules.models import MachineGroup

    machines = {'MA': _machine('MA', group='ZZ_G1'), 'MB': _machine('MB', group='ZZ_G2')}
    materials = {
        'ZZ_G1': _mat('ZZ_G1', packaging_machine_group='1', fte_requirements=1.0),
        'ZZ_G2': _mat('ZZ_G2', packaging_machine_group='1', fte_requirements=1.0),
        'PA': _mat('PA'), 'PB': _mat('PB'),
    }
    groups = {'ZZ_G1': MachineGroup('ZZ_G1', ['MA']), 'ZZ_G2': MachineGroup('ZZ_G2', ['MB'])}
    routings = {'PA': [_routing('MA')], 'PB': [_routing('MB')]}
    plan = {'PA': dict.fromkeys(PERIODS, 10000.0),   # 100 uur
            'PB': dict.fromkeys(PERIODS, 5000.0)}    # 50 uur
    combos = {'C1': MachineCombination(combination_id='C1', name='Duo',
                                       machine_codes=['MA', 'MB'], operators=1.0)}
    data = _data(machines, materials, groups, routings, machine_combinations=combos)
    results = CapacityEngine(data, plan, {}).calculate()
    results[LineType.DEMAND_FORECAST.value] = _demand_rows(data, {})
    return data, results


def _hours(engine):
    return engine.fte_results.total_hours[PERIODS[0]]


HOURS_APART = 150.0     # MA 100 + MB 50, elk hun eigen groep
HOURS_COMBINED = 100.0  # één operator over de langst draaiende machine


@pytest.fixture
def env():
    data, results = _combo_setup()
    engine = _Engine(data, results)
    sess = {'id': 's1', 'engine': engine, 'active_combinations': [],
            'pending_edits': {}, 'machine_overrides': {}}
    return SimpleNamespace(data=data, results=results, engine=engine, sess=sess)


def test_the_fixture_itself_shows_the_saving(env):
    """Zonder deze asymmetrie bewijzen de tests hieronder niets."""
    env.engine.recalculate_fte([])
    assert _hours(env.engine) == pytest.approx(HOURS_APART)
    env.engine.recalculate_fte(['C1'])
    assert _hours(env.engine) == pytest.approx(HOURS_COMBINED)


class TestPunt2ConfigOverrides:
    """Een KOUDE herbouw (na herstart, na een parameterwijziging) bouwt de
    engine uit config_overrides. Ontbreekt het veld daar, dan start hij met een
    lege set terwijl de sessie zegt dat een combinatie aanstaat."""

    def test_session_field_rides_along(self, env):
        env.sess['active_combinations'] = ['C1']
        overrides = get_session_config_overrides(env.sess, {})
        assert overrides['active_combinations'] == ['C1']

    def test_engine_is_the_fallback(self, env):
        env.sess.pop('active_combinations')
        env.engine.active_combinations = ['C1']
        overrides = get_session_config_overrides(env.sess, {})
        assert overrides['active_combinations'] == ['C1']

    def test_a_session_without_combinations_inherits_nothing(self, env):
        """Cross-contaminatie: sessie B mag de combinaties van sessie A niet
        uit de gedeelde global config krijgen."""
        overrides = get_session_config_overrides(env.sess,
                                                 {'active_combinations': ['C1']})
        assert 'active_combinations' not in overrides


class TestPunt3ResetBaseline:
    def test_snapshot_captures_the_active_set(self, env):
        env.engine.active_combinations = ['C1']
        snapshot = snapshot_engine_state(env.engine, lambda m, d: 0.0)
        assert snapshot['active_combinations'] == ['C1']

    def test_restore_puts_it_back(self, env):
        env.engine.active_combinations = ['C1']
        snapshot = snapshot_engine_state(env.engine, lambda m, d: 0.0)
        env.engine.active_combinations = []

        restore_engine_state(env.engine, snapshot, {})

        assert env.engine.active_combinations == ['C1']

    def test_an_old_snapshot_does_not_silently_switch_them_off(self, env):
        """Snapshots van vóór dit veld kennen het niet. Dan niets doen is
        beter dan naar leeg terugzetten."""
        env.engine.active_combinations = ['C1']
        snapshot = snapshot_engine_state(env.engine, lambda m, d: 0.0)
        del snapshot['active_combinations']

        restore_engine_state(env.engine, snapshot, {})

        assert env.engine.active_combinations == ['C1']

    def test_a_clean_baseline_switches_them_off(self, env):
        """Reset wist wat-als-capaciteit: machine-overrides én combinaties."""
        env.sess['active_combinations'] = ['C1']
        env.engine.recalculate_fte(['C1'])

        install_clean_engine_baseline(env.sess, env.engine, lambda m, d: 0.0)

        assert env.sess['active_combinations'] == []
        assert env.engine.active_combinations == []
        assert _hours(env.engine) == pytest.approx(HOURS_APART)

    def test_a_config_change_keeps_them(self, env):
        """clear_machine_overrides=False = 'dit is geen Reset'; dan blijven de
        combinaties net als de machine-overrides staan."""
        env.sess['active_combinations'] = ['C1']
        env.engine.recalculate_fte(['C1'])

        install_clean_engine_baseline(env.sess, env.engine, lambda m, d: 0.0,
                                      clear_machine_overrides=False)

        assert env.sess['active_combinations'] == ['C1']
        assert _hours(env.engine) == pytest.approx(HOURS_COMBINED)


class TestPunt45Recalculatie:
    def test_recalculate_reads_the_session_not_the_engine(self, env):
        """De sessie is de bron van waarheid. Een engine die na een herbouw
        met een lege set start, moet door de cascade weer goed komen."""
        env.sess['active_combinations'] = ['C1']
        env.engine.active_combinations = []

        recalculate_fte_results(env.engine, env.sess)

        assert env.engine.active_combinations == ['C1']
        assert _hours(env.engine) == pytest.approx(HOURS_COMBINED)

    def test_switching_them_off_recalculates_back(self, env):
        env.sess['active_combinations'] = ['C1']
        recalculate_fte_results(env.engine, env.sess)
        env.sess['active_combinations'] = []

        recalculate_fte_results(env.engine, env.sess)

        assert _hours(env.engine) == pytest.approx(HOURS_APART)

    def test_an_engine_without_the_hook_is_skipped(self):
        """Oudere/gestubde engines mogen de cascade niet laten crashen."""
        recalculate_fte_results(object(), {'active_combinations': ['C1']})

    def test_replay_after_a_rebuild_restores_the_workbench(self, env):
        """Syncpunt 4 via de ECHTE replay_pending_edits, niet via de helper
        die hij aanroept. Haalt iemand die aanroep weg, dan rekent de werkbank
        na een herstart met een lege set terwijl de sessie zegt van niet —
        en dat merkte geen enkele test."""
        from ui.replay import replay_pending_edits

        env.sess['active_combinations'] = ['C1']
        env.engine.active_combinations = []      # verse engine na herbouw
        env.engine.fte_results = None

        replay_pending_edits(
            env.sess, env.engine,
            apply_volume_change=lambda *a, **k: None,
            apply_machine_overrides=lambda engine, overrides: False,
            recalculate_capacity_and_values=lambda engine, sess: None)

        assert env.engine.active_combinations == ['C1']
        assert _hours(env.engine) == pytest.approx(HOURS_COMBINED)

    def test_replay_with_pending_edits_also_reaches_the_workbench(self, env):
        env.sess['active_combinations'] = ['C1']
        env.sess['pending_edits'] = {'x||y||z||2025-01': {'new_value': 1.0}}
        env.engine.active_combinations = []

        from ui.replay import replay_pending_edits

        replay_pending_edits(
            env.sess, env.engine,
            apply_volume_change=lambda *a, **k: None,
            apply_machine_overrides=lambda engine, overrides: False,
            recalculate_capacity_and_values=lambda engine, sess: None)

        assert _hours(env.engine) == pytest.approx(HOURS_COMBINED)


class TestPunt6Persistentie:
    def test_it_survives_a_restart(self, env, tmp_path):
        env.sess['active_combinations'] = ['C1']
        env.engine.active_combinations = ['C1']
        store = tmp_path / 'sessions_store.json'

        save_sessions_to_disk({'s1': env.sess}, 's1', store, lambda s, e: {})
        loaded, active = load_sessions_from_disk(store)

        assert active == 's1'
        assert loaded['s1']['active_combinations'] == ['C1']

    def test_a_store_from_before_the_field_loads_as_empty(self, tmp_path):
        store = tmp_path / 'sessions_store.json'
        store.write_text(json.dumps({
            'active_session_id': 's1',
            'sessions': {'s1': {'id': 's1', 'file_path': '', 'parameters': {}}},
        }), encoding='utf-8')

        loaded, _ = load_sessions_from_disk(store)

        assert loaded['s1']['active_combinations'] == []

    def test_the_live_engine_wins_over_a_stale_session_field(self, env, tmp_path):
        """De toggle zet beide; raakt de sessie toch achter, dan is de engine
        de verste stand."""
        env.sess['active_combinations'] = []
        env.engine.active_combinations = ['C1']
        store = tmp_path / 'sessions_store.json'

        save_sessions_to_disk({'s1': env.sess}, 's1', store, lambda s, e: {})
        loaded, _ = load_sessions_from_disk(store)

        assert loaded['s1']['active_combinations'] == ['C1']


class TestScenarioRestoresMachines:
    """De reparatie in load_scenario (machines eerst terug naar de baseline,
    dán de scenarioset toepassen) had geen enkele test: hem weghalen liet de
    hele suite groen. Dit is die test, op de echte helpers."""

    def _machine(self, oee):
        return SimpleNamespace(oee=oee, availability_by_period={},
                               shift_hours_override=None)

    def test_an_empty_override_set_really_means_no_overrides(self):
        from ui.state_snapshot import apply_machine_overrides, restore_machines_from_snapshot

        engine = SimpleNamespace(data=SimpleNamespace(machines={'M1': self._machine(0.40)}))
        baseline = {'machines': {'M1': {'oee': 0.85, 'availability_by_period': {},
                                        'shift_hours_override': None}}}

        # Wat load_scenario doet: eerst terug naar de baseline, dan de set.
        restore_machines_from_snapshot(engine, baseline)
        apply_machine_overrides(engine, {})

        assert engine.data.machines['M1'].oee == 0.85, (
            'apply_machine_overrides raakt alleen de machines IN de set en '
            'keert bij een lege set meteen terug — zonder de restore ervoor '
            'bleef de live verlaagde OEE staan')

    def test_a_scenario_with_overrides_lands_on_top_of_the_baseline(self):
        from ui.state_snapshot import apply_machine_overrides, restore_machines_from_snapshot

        engine = SimpleNamespace(data=SimpleNamespace(
            machines={'M1': self._machine(0.40), 'M2': self._machine(0.30)}))
        baseline = {'machines': {
            'M1': {'oee': 0.85, 'availability_by_period': {}, 'shift_hours_override': None},
            'M2': {'oee': 0.80, 'availability_by_period': {}, 'shift_hours_override': None}}}

        restore_machines_from_snapshot(engine, baseline)
        apply_machine_overrides(engine, {'M1': {'oee': 0.60}})

        assert engine.data.machines['M1'].oee == 0.60   # uit het scenario
        assert engine.data.machines['M2'].oee == 0.80   # terug naar baseline


class TestDuplicatedInstance:
    """Regressie op de bugjacht-bevinding: 'Opslaan als instantie' kopieerde
    het veld niet, dus het duplicaat rekende met andere FTE, loonkosten en
    EBITDA dan de instantie waarvan het een kopie heet te zijn."""

    def _snapshot_payload(self, sess, engine):
        """Precies de velden die ui/routes/sessions.py in new_sess zet."""
        return {
            'pending_edits': copy.deepcopy(sess.get('pending_edits', {})),
            'machine_overrides': copy.deepcopy(sess.get('machine_overrides', {})),
            'active_combinations': list(
                getattr(engine, 'active_combinations', None)
                if engine is not None
                and getattr(engine, 'active_combinations', None) is not None
                else (sess.get('active_combinations') or [])
            ),
        }

    def test_the_copy_carries_the_active_set(self, env):
        env.sess['active_combinations'] = ['C1']
        env.engine.active_combinations = ['C1']

        copied = self._snapshot_payload(env.sess, env.engine)

        assert copied['active_combinations'] == ['C1']

    def test_the_copy_computes_the_same_numbers(self, env):
        env.engine.active_combinations = ['C1']
        env.engine.recalculate_fte(['C1'])
        source_hours = _hours(env.engine)

        copied = self._snapshot_payload(env.sess, env.engine)
        copy_engine = _Engine(env.data, env.results)
        recalculate_fte_results(copy_engine, copied)

        assert _hours(copy_engine) == pytest.approx(source_hours)
        assert _hours(copy_engine) == pytest.approx(HOURS_COMBINED)

    def test_a_cold_copy_falls_back_to_the_session_field(self, env):
        """Een duplicaat van een sessie zonder live engine."""
        env.sess['active_combinations'] = ['C1']

        copied = self._snapshot_payload(env.sess, None)

        assert copied['active_combinations'] == ['C1']


class TestWatAlsNormen:
    """De wat-als-normen (fte_norm_overrides) zijn sessiestate naast de
    actieve combinaties en volgen exact dezelfde zes sync-/rebuildpunten.
    Elke test hier spiegelt een bestaand combinatie-geval."""

    OVR = {'ZZ_G1': {'operators_per_hour': 2.0, 'scope': 'group'}}

    def test_de_override_rekent_direct_mee_met_bron_wat_als(self, env):
        env.engine.recalculate_fte([], norm_overrides=self.OVR)
        line = next(l for l in env.engine.fte_results.lines
                    if l.category == 'group' and l.key == 'ZZ_G1')
        assert line.operators_per_hour == pytest.approx(2.0)
        assert line.operators_source == 'wat-als'
        env.engine.recalculate_fte(norm_overrides={})
        line = next(l for l in env.engine.fte_results.lines
                    if l.category == 'group' and l.key == 'ZZ_G1')
        assert line.operators_source != 'wat-als'

    def test_config_overrides_dragen_het_sessieveld(self, env):
        env.sess['fte_norm_overrides'] = dict(self.OVR)
        overrides = get_session_config_overrides(env.sess, {})
        assert overrides['fte_norm_overrides'] == self.OVR

    def test_config_overrides_vallen_terug_op_de_engine(self, env):
        env.sess.pop('fte_norm_overrides', None)
        env.engine.fte_norm_overrides = dict(self.OVR)
        overrides = get_session_config_overrides(env.sess, {})
        assert overrides['fte_norm_overrides'] == self.OVR

    def test_geen_erfenis_uit_de_global_config(self, env):
        overrides = get_session_config_overrides(
            env.sess, {'fte_norm_overrides': dict(self.OVR)})
        assert 'fte_norm_overrides' not in overrides

    def test_snapshot_en_restore_dragen_de_overrides(self, env):
        env.engine.fte_norm_overrides = dict(self.OVR)
        snapshot = snapshot_engine_state(env.engine, lambda m, d: 0.0)
        fresh = _Engine(env.data, env.results)
        restore_engine_state(fresh, snapshot, {})
        assert fresh.fte_norm_overrides == self.OVR

    def test_schone_baseline_zet_ze_uit(self, env):
        env.sess['fte_norm_overrides'] = dict(self.OVR)
        env.engine.fte_norm_overrides = dict(self.OVR)
        install_clean_engine_baseline(env.sess, env.engine, lambda m, d: 0.0,
                                      clear_machine_overrides=True)
        assert env.sess['fte_norm_overrides'] == {}
        assert env.engine.fte_norm_overrides == {}

    def test_configwijziging_laat_ze_staan(self, env):
        env.sess['fte_norm_overrides'] = dict(self.OVR)
        env.engine.fte_norm_overrides = dict(self.OVR)
        install_clean_engine_baseline(env.sess, env.engine, lambda m, d: 0.0,
                                      clear_machine_overrides=False)
        assert env.sess['fte_norm_overrides'] == self.OVR

    def test_replay_leest_de_sessie(self, env):
        env.sess['fte_norm_overrides'] = dict(self.OVR)
        recalculate_fte_results(env.engine, env.sess)
        line = next(l for l in env.engine.fte_results.lines
                    if l.category == 'group' and l.key == 'ZZ_G1')
        assert line.operators_source == 'wat-als'
        assert line.operators_per_hour == pytest.approx(2.0)


    def test_wat_als_overleeft_een_herstart(self, env, tmp_path):
        """De spiegel van test_it_survives_a_restart die ONTBRAK: precies dit
        gat liet de verificatieronde van 2026-08 een wat-als stil verdampen
        bij herstart — cijfers terug op de masterdata-norm, leeg paneel,
        geen melding."""
        ovr = {'ZZ_G1': {'operators_per_hour': 2.0, 'scope': 'group', 'was': 1.0}}
        env.sess['fte_norm_overrides'] = dict(ovr)
        env.engine.fte_norm_overrides = dict(ovr)
        store = tmp_path / 'sessions_store.json'

        save_sessions_to_disk({'s1': env.sess}, 's1', store, lambda s, e: {})
        loaded, _ = load_sessions_from_disk(store)

        assert loaded['s1']['fte_norm_overrides'] == ovr
        # En de koude herbouw leest hem ook echt (het hele punt van de keten).
        overrides = get_session_config_overrides(loaded['s1'], {})
        assert overrides['fte_norm_overrides'] == ovr

    def test_oude_store_zonder_het_veld_laadt_als_leeg(self, tmp_path):
        store = tmp_path / 'sessions_store.json'
        store.write_text(json.dumps({
            'active_session_id': 's1',
            'sessions': {'s1': {'id': 's1', 'file_path': '', 'parameters': {}}},
        }), encoding='utf-8')
        loaded, _ = load_sessions_from_disk(store)
        assert loaded['s1']['fte_norm_overrides'] == {}

    def test_inerte_override_geeft_een_warning(self, env):
        """Een override voor een code die nergens matcht mag niet stil zijn —
        dezelfde regel als een verdwenen combinatie."""
        env.engine.recalculate_fte([], norm_overrides={
            'BESTAAT_NIET': {'operators_per_hour': 3.0, 'scope': 'group'}})
        assert any('BESTAAT_NIET' in w and 'niet mee' in w
                   for w in env.engine.fte_results.warnings), env.engine.fte_results.warnings
        # En een override die WEL matcht, warnt niet.
        env.engine.recalculate_fte([], norm_overrides={
            'ZZ_G1': {'operators_per_hour': 2.0, 'scope': 'group'}})
        assert not any('ZZ_G1' in w for w in env.engine.fte_results.warnings)
