"""Helpers for rebuilding clean PlanningEngine instances for UI sessions."""

from modules.planning_engine import PlanningEngine
from ui.parsers import format_purchased_and_produced
from ui.state_snapshot import snapshot_engine_state


def get_config_overrides(global_config: dict) -> dict:
    """Build config_overrides dict from global config for use in PlanningEngine."""
    ov = {}
    # Confirmed UoM conversion factors are site-installation state (a
    # property of the material's SAP base unit, not of a session): read
    # fresh from the store on EVERY rebuild path so calculate, session
    # switch, restart warmup and reset all apply the same factors.
    from ui.uom_store import get_confirmed_overrides
    uom_overrides = get_confirmed_overrides()
    if uom_overrides:
        ov['uom_overrides'] = uom_overrides
    # Met een app-masterstore zijn de masterdata-tabellen de enige bron van
    # waarheid voor structurele config; legacy-globals (uit de oude
    # Config-kaart of global_config.json) gelden alleen nog ZONDER store,
    # anders zouden oude overschrijvingen de tabel stil overrulen.
    from ui.master_store import get_current_master_record
    _record = get_current_master_record()
    if _record is None:
        if global_config.get('site'):
            ov['site'] = global_config['site']
        if global_config.get('unlimited_machines'):
            ov['unlimited_machines'] = global_config['unlimited_machines']
        if global_config.get('forecast_align_to_month') is not None:
            ov['forecast_align_to_month'] = bool(global_config['forecast_align_to_month'])
        # Horizon idem: het oude invoerveld is weg, dus een achtergebleven
        # global zou de masterdata-Config-tabel permanent overschaduwen.
        if global_config.get('forecast_months'):
            ov['forecast_months'] = int(global_config['forecast_months'])
    else:
        # De masterdata-Config-tabel neemt de rol van de oude global over:
        # de horizon uit de store stuurt de load (periodes/forecast-inlezen),
        # zodat loader- en enginehorizon gelijk blijven (zie
        # resolve_months_forecast voor de enginekant).
        _months = ((_record.get('master') or {}).get('config') or {}).get('forecast_months')
        if _months:
            ov['forecast_months'] = int(_months)
    if _record is None:
        # Idem PAP en VP: de global is een spiegel van de laatst actieve
        # sessie; mét store zou een verse sessie daar andermans wat-als van
        # erven en zou de spiegel de masterdefault overschaduwen. Sessie-
        # overrides reizen via get_session_config_overrides, niet hierlangs.
        if global_config.get('purchased_and_produced'):
            ov['purchased_and_produced'] = global_config['purchased_and_produced']
        vp = global_config.get('valuation_params')
        if vp and any(float(v or 0) != 0 for v in vp.values()):
            ov['valuation_params'] = vp
    fc_defaults = global_config.get('forecast_defaults')
    if fc_defaults and (fc_defaults.get('default') not in (None, '') or fc_defaults.get('per_material')):
        ov['forecast_defaults'] = fc_defaults
    if global_config.get('added_products'):
        ov['added_products'] = global_config['added_products']
    return ov


def get_calculate_config_overrides(sess: dict | None, global_config: dict) -> dict:
    """Overrides for /api/calculate on the ACTIVE session.

    The global config is only a MIRROR of the active session: it is refreshed
    on a session switch when the target has a live engine, so after switching
    to a still-warming/cold session it is stale. A recalculate must therefore
    take the per-session state (valuation params, purchased_and_produced,
    forecast defaults, added products) session/engine-first — never silently
    DROP this session's values or INHERIT another session's. That is exactly
    the rebuild rule, so delegate to it. Fallback semantics per field: VP/PAP
    fall through to the global config for a fresh session (config-tab values,
    visible before the first calculate); forecast defaults and added products
    are NEVER inherited from the mirror — saving/adding them writes the
    session field, so a missing field means "not this session's".
    """
    return get_session_config_overrides(sess, global_config)


def get_session_config_overrides(sess: dict | None, global_config: dict) -> dict:
    """Build config_overrides for a session-specific engine rebuild."""
    ov = get_config_overrides(global_config)
    if sess is None:
        return ov
    engine_data = getattr(sess.get('engine'), 'data', None)
    from ui.master_store import get_current_master_record
    _store_exists = get_current_master_record() is not None

    # VP: mét masterstore zijn de masterdata-tabellen de enige VP-editor.
    # Geen engine-/sessiesnapshot doorsturen — die bevat de OUDE waarden en
    # zou elke master-VP-wijziging bij rebuild terugdraaien (hydrate/overlay
    # leveren de actuele waarden). Storeless: engine-first zoals vanouds.
    if not _store_exists:
        vp_obj = getattr(engine_data, 'valuation_params', None)
        if vp_obj is not None:
            ov['valuation_params'] = {
                '1': vp_obj.direct_fte_cost_per_month,
                '2': vp_obj.indirect_fte_cost_per_month,
                '3': vp_obj.overhead_cost_per_month,
                '4': vp_obj.sga_cost_per_month,
                '5': vp_obj.depreciation_per_year,
                '6': vp_obj.net_book_value,
                '7': vp_obj.days_sales_outstanding,
                '8': vp_obj.days_payable_outstanding,
            }
        elif sess.get('valuation_params'):
            ov['valuation_params'] = sess['valuation_params']

    # PAP: het sessieveld is de wat-als-bron ('' betekent BEWUST leeg; alleen
    # een nooit-gezet veld (None) valt door). De PAP-editor schrijft sessie
    # én engine, dus sessie-eerst is ook voor live sessies correct. Mét store
    # valt een nooit-gezet veld door naar de masterdefault via de overlay —
    # de engine-snapshot bevat de oude default en zou master-PAP-wijzigingen
    # (incl. verwijderde splits) bij elke rebuild terugdraaien. Storeless
    # blijft de snapshot de terugval voor sessies van vóór de sessieveld-era.
    sess_pap = sess.get('purchased_and_produced')
    if sess_pap is not None:
        ov['purchased_and_produced'] = sess_pap
    elif not _store_exists:
        pap = getattr(engine_data, 'purchased_and_produced', None)
        if pap is not None:
            ov['purchased_and_produced'] = format_purchased_and_produced(pap)

    # Forecast defaults are per-session state: the session dict is
    # authoritative, a live engine's own config_overrides is the fallback.
    # A session WITHOUT defaults must never inherit them from the shared
    # global config (cross-session contamination on rebuild) — global only
    # feeds fresh /api/calculate runs of the active session.
    fd = sess.get('forecast_defaults')
    if fd is None:
        engine = sess.get('engine')
        fd = (getattr(engine, 'config_overrides', None) or {}).get('forecast_defaults')
    if fd:
        ov['forecast_defaults'] = fd
    else:
        ov.pop('forecast_defaults', None)

    # Added products (Fase 3) follow the same per-session rule as forecast
    # defaults: the session dict is authoritative, a live engine's own
    # config_overrides is the fallback, and a session without products must
    # never inherit them from the shared global config on rebuild.
    ap = sess.get('added_products')
    if ap is None:
        engine = sess.get('engine')
        ap = (getattr(engine, 'config_overrides', None) or {}).get('added_products')
    if ap:
        ov['added_products'] = ap
    else:
        ov.pop('added_products', None)

    # Actieve machinecombinaties (F2-CF) zijn per-sessie scenario-staat, met
    # dezelfde regel: de sessie is de bron, de live engine de terugval, en een
    # sessie zonder combinaties erft ze NOOIT uit de gedeelde global config.
    # Zonder dit veld startte een verse engine-run met een lege set terwijl de
    # sessie zei dat een combinatie aan stond — de werkbank stond dan één
    # herberekening lang op de verkeerde bezetting.
    ac = sess.get('active_combinations')
    if ac is None:
        ac = getattr(sess.get('engine'), 'active_combinations', None)
    if ac:
        ov['active_combinations'] = list(ac)
    else:
        ov.pop('active_combinations', None)
    # Wat-als-normen: zelfde regel als de combinaties hierboven.
    norm_overrides = sess.get('fte_norm_overrides')
    if norm_overrides is None:
        norm_overrides = getattr(sess.get('engine'), 'fte_norm_overrides', None)
    if norm_overrides:
        ov['fte_norm_overrides'] = dict(norm_overrides)
    else:
        ov.pop('fte_norm_overrides', None)
    return ov


def resolve_months_forecast(params: dict | None, global_config: dict) -> int:
    """Horizon voor een herbouw: masterdata-Config wint mét store, de legacy
    global alleen storeless (het oude Config-kaartveld is weg), anders de
    sessieparameter waarmee oorspronkelijk gerekend is."""
    months = int((params or {}).get('months_forecast', 12) or 12)
    from ui.master_store import get_current_master_record
    record = get_current_master_record()
    if record is not None:
        store_months = ((record.get('master') or {}).get('config') or {}).get('forecast_months')
        if store_months:
            return int(store_months)
    elif global_config.get('forecast_months'):
        return int(global_config['forecast_months'])
    return months


def build_clean_engine_for_session(
    sess: dict,
    global_config: dict,
    params: dict | None = None,
) -> PlanningEngine | None:
    params = params or sess.get('parameters') or {}
    if not params:
        return None
    months_forecast = resolve_months_forecast(params, global_config)
    # App-masterdata (indien aanwezig) geldt bij ELKE rebuild: werkboek-vrije
    # sessies rekenen er volledig uit, werkboek-sessies krijgen de overlay
    # (app = bron van waarheid). De bronkeuze ligt centraal in
    # ui/master_source.py — dezelfde beslisser als upload en calculate.
    from ui.master_source import resolve_for_session
    src = resolve_for_session(sess)
    if src is None:
        return None
    # A store-backed session still needs the monthly extracts: the store
    # holds master data only, and DataLoader.load_all would fall through to
    # the workbook loaders (pd.read_excel(None) crash) for BOM/routing/
    # forecast/stock. Mirrors the /api/calculate guard.
    if src.file_path is None and not sess.get('extract_files'):
        return None
    engine = PlanningEngine(
        src.file_path,
        planning_month=params.get('planning_month'),
        months_actuals=int(params.get('months_actuals', 0) or 0),
        months_forecast=months_forecast,
        extract_files=sess.get('extract_files'),
        config_overrides=get_session_config_overrides(sess, global_config),
        master_data=src.master_data,
    )
    engine.run()
    # Bronlabel NIET hier op de sessie zetten: deze build kan nog worden
    # weggegooid (staleness-guards in de install-paden). Het label reist mee
    # op de engine en wordt pas bij install toegepast (zie
    # install_clean_engine_baseline).
    engine._resolved_master_source = src
    return engine


def install_clean_engine_baseline(
    sess: dict,
    engine,
    shift_hours_lookup,
    clear_machine_overrides: bool = True,
) -> None:
    sess['reset_baseline'] = snapshot_engine_state(engine, shift_hours_lookup)
    # Bronmarkering hoort bij de daadwerkelijk geïnstalleerde engine.
    _src = getattr(engine, '_resolved_master_source', None)
    if _src is not None:
        _src.apply_to_session(sess)
    # A fresh calculate invalidates stale machine undo history.
    sess['machine_undo'] = []
    if clear_machine_overrides:
        sess['machine_overrides'] = {}
        # Actieve combinaties (F2-CF) zijn dezelfde soort wat-als-capaciteit
        # als machine-overrides en volgen dezelfde vlag: een Reset zet ze uit,
        # een configwijziging (clear_machine_overrides=False) laat ze staan.
        sess['active_combinations'] = []
        engine.active_combinations = []
        sess['fte_norm_overrides'] = {}
        engine.fte_norm_overrides = {}
        if hasattr(engine, 'recalculate_fte'):
            engine.recalculate_fte([], norm_overrides={})
    # inventory_overrides (L4 starting stock) and capacity_overrides
    # (L7/L9/L11/L12) are session-scoped edit stores. A clean engine baseline
    # implies no edits have been applied yet — reset both stores so Reset
    # genuinely returns to the empty-edit state. Replay re-populates them
    # from pending_edits if needed.
    sess['inventory_overrides'] = {}
    sess['capacity_overrides'] = {}
