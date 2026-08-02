"""Settings-registry (Config-tab C2): consistentie + parametrische dekking.

Elke instelling met handler='generic' wordt hier automatisch getest: POST
persisteert, GET toont de waarde in settings_meta, en het effect stuurt de
structurele-rebuild-beslissing. Een nieuw registry-veld is dus gedekt
zonder een test aan te raken."""

import pytest

from ui.settings_registry import (
    REGISTRY,
    apply_generic_settings,
    generic_settings,
    get_setting,
    settings_meta,
)

# Hergebruik de blueprint-fixture van de config-routes.
from tests.test_routes_config import config_route_app  # noqa: F401

pytestmark = pytest.mark.no_fixture


# ------------------------------------------------------------- consistentie


def test_registry_is_consistent():
    keys = [s.key for s in REGISTRY]
    assert len(keys) == len(set(keys)), 'dubbele registry-sleutels'
    for s in REGISTRY:
        assert s.scope in ('session', 'installation'), s.key
        assert s.effect in ('rebuild', 'recalc', 'value', 'none'), s.key
        assert s.type in ('text', 'number', 'bool', 'composite'), s.key
        assert s.handler in ('legacy', 'generic'), s.key
        assert s.label and s.tooltip, f'{s.key}: label/tooltip verplicht'


def test_generic_settings_have_workable_types():
    # 'composite' kan niet generiek: die velden horen bij de legacy-keten.
    for s in generic_settings():
        assert s.type in ('text', 'number', 'bool'), s.key


# --------------------------------------------------- parametrisch: elk veld


def _changed_value(setting, current):
    """Een waarde die gegarandeerd afwijkt van de huidige."""
    if setting.type == 'bool':
        return not bool(current if current is not None else setting.default)
    if setting.type == 'number':
        return (float(current) if current not in (None, '') else 0.0) + 1.0
    return str(current or '') + '_X'


@pytest.mark.parametrize('setting', generic_settings(), ids=lambda s: s.key)
def test_generic_setting_round_trip_via_routes(config_route_app, setting):
    gc = config_route_app.global_config
    new_value = _changed_value(setting, gc.get(setting.key, setting.default))

    res = config_route_app.client.post('/api/config/settings',
                                       json={setting.key: new_value})
    assert res.status_code == 200, res.get_json()
    assert gc[setting.key] == setting.coerce(new_value)
    assert config_route_app.save_calls, 'global_config niet gepersisteerd'

    meta = {m['key']: m for m in
            config_route_app.client.get('/api/config').get_json()['settings_meta']}
    assert meta[setting.key]['value'] == setting.coerce(new_value)
    assert meta[setting.key]['effect'] == setting.effect
    assert meta[setting.key]['scope'] == setting.scope


@pytest.mark.parametrize('setting', generic_settings(), ids=lambda s: s.key)
def test_generic_setting_flows_into_override_chain(setting):
    """Scope-sessie/installatie: het veld moet na wijziging in de
    config_overrides van elke rebuild terechtkomen."""
    from ui.engine_rebuild import get_config_overrides
    gc = {setting.key: _changed_value(setting, setting.default)}
    coerced = setting.coerce(gc[setting.key])
    gc[setting.key] = coerced
    ov = get_config_overrides(gc)
    assert ov.get(setting.key) == coerced, (
        f'{setting.key} ontbreekt in get_config_overrides — voeg de '
        f'doorvoer toe in ui/engine_rebuild.py')


# ----------------------------------------------------------- apply-gedrag


def test_apply_generic_settings_is_noop_for_unchanged_value():
    """Registry-machinerie blijft werken voor toekomstige generieke velden;
    getest met een tijdelijk injectieveld (forecast_align_to_month is
    verhuisd naar de masterdata-Config-tabel)."""
    from ui.settings_registry import REGISTRY, Setting
    dummy = Setting('test_flag', 'planning', 'installation', 'bool',
                    'Testvlag', 'alleen voor deze test',
                    effect='rebuild', handler='generic', default=True)
    REGISTRY.append(dummy)
    try:
        gc = {'test_flag': True}
        assert apply_generic_settings({'test_flag': True}, gc) == []
        assert apply_generic_settings({'test_flag': False}, gc) == ['rebuild']
        assert gc['test_flag'] is False
    finally:
        REGISTRY.remove(dummy)


def test_forecast_align_moved_to_master_config():
    """forecast_align_to_month is géén registry-veld meer: de masterdata-
    Config-tabel is de enige bron van waarheid; serialize/hydrate en de
    store-overlay dragen hem (zie test_master_data)."""
    assert get_setting('forecast_align_to_month') is None
    assert all(s.key != 'forecast_align_to_month' for s in generic_settings())
