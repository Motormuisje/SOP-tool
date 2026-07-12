"""Helpers for rebuilding clean PlanningEngine instances for UI sessions."""

from modules.planning_engine import PlanningEngine
from ui.parsers import format_purchased_and_produced
from ui.state_snapshot import snapshot_engine_state


def get_config_overrides(global_config: dict) -> dict:
    """Build config_overrides dict from global config for use in PlanningEngine."""
    ov = {}
    if global_config.get('site'):
        ov['site'] = global_config['site']
    if global_config.get('forecast_months'):
        ov['forecast_months'] = int(global_config['forecast_months'])
    if global_config.get('unlimited_machines'):
        ov['unlimited_machines'] = global_config['unlimited_machines']
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

    pap = getattr(engine_data, 'purchased_and_produced', None)
    if pap is not None:
        ov['purchased_and_produced'] = format_purchased_and_produced(pap)
    elif sess.get('purchased_and_produced') is not None:
        # Cold rebuild (restart/warmup): use the session's persisted PAP
        # instead of falling through to the last-active session's value in
        # the shared global config. '' means DELIBERATELY CLEARED and must
        # override the global value too (parses to an empty dict), so only
        # None (field never persisted) falls through.
        ov['purchased_and_produced'] = sess['purchased_and_produced']

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
    return ov


def build_clean_engine_for_session(
    sess: dict,
    global_config: dict,
    params: dict | None = None,
) -> PlanningEngine | None:
    params = params or sess.get('parameters') or {}
    if not params:
        return None
    months_forecast = int(params.get('months_forecast', 12) or 12)
    if global_config.get('forecast_months'):
        months_forecast = int(global_config.get('forecast_months') or months_forecast)
    # App-masterdata (indien aanwezig) geldt bij ELKE rebuild: werkboek-vrije
    # sessies rekenen er volledig uit, werkboek-sessies krijgen de overlay
    # (app = bron van waarheid).
    from ui.master_store import get_current_master_record
    record = get_current_master_record()
    master_data = record['master'] if record else None
    if not sess.get('file_path') and master_data is None:
        return None
    engine = PlanningEngine(
        sess.get('file_path') or None,
        planning_month=params.get('planning_month'),
        months_actuals=int(params.get('months_actuals', 0) or 0),
        months_forecast=months_forecast,
        extract_files=sess.get('extract_files'),
        config_overrides=get_session_config_overrides(sess, global_config),
        master_data=master_data,
    )
    engine.run()
    return engine


def install_clean_engine_baseline(
    sess: dict,
    engine,
    shift_hours_lookup,
    clear_machine_overrides: bool = True,
) -> None:
    sess['reset_baseline'] = snapshot_engine_state(engine, shift_hours_lookup)
    # A fresh calculate invalidates stale machine undo history.
    sess['machine_undo'] = []
    if clear_machine_overrides:
        sess['machine_overrides'] = {}
    # inventory_overrides (L4 starting stock) and capacity_overrides
    # (L7/L9/L11/L12) are session-scoped edit stores. A clean engine baseline
    # implies no edits have been applied yet — reset both stores so Reset
    # genuinely returns to the empty-edit state. Replay re-populates them
    # from pending_edits if needed.
    sess['inventory_overrides'] = {}
    sess['capacity_overrides'] = {}
