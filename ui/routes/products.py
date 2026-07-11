"""Flask routes for dynamic products (Fase 3 — per-session product overlay).

Every mutation is a STRUCTURAL change (the BOM topology shifts), so add/edit/
delete rebuilds the engine via the same flow as a structural config change
(build clean engine → install baseline → replay pending edits).
"""

from typing import Callable

from flask import Blueprint, current_app, jsonify, request

from modules.product_overlay import normalize_material_number, validate_added_product
from ui.locks import engine_rebuild_lock

_ERR_NO_SESSION = 'Geen actieve sessie'
_ERR_NO_ENGINE = 'Geen actieve berekening — voer eerst een berekening uit.'


def _current_products(sess, engine) -> list:
    """The session's added products; live engine overrides are the fallback
    (same authority rule as get_session_config_overrides)."""
    ap = sess.get('added_products')
    if ap is None and engine is not None:
        ap = (getattr(engine, 'config_overrides', None) or {}).get('added_products')
    return list(ap or [])


def prune_material_state(sess: dict, material_number: str) -> None:
    """Drop all per-material edit state for a removed product (TP3-05).

    pending_edits keys are 'lt||mat||aux||period' (aux can reference the
    material on L02 rows of other materials); value_aux_overrides keys are
    'lt||mat'. Undo/redo stacks are cleared entirely: their entries point at
    rows whose identity changes with the BOM topology.
    """
    mn = str(material_number)
    pending = sess.get('pending_edits') or {}
    sess['pending_edits'] = {
        key: edit for key, edit in pending.items()
        if mn not in key.split('||')[1:3]
    }
    aux_overrides = sess.get('value_aux_overrides') or {}
    sess['value_aux_overrides'] = {
        key: val for key, val in aux_overrides.items()
        if not (len(key.split('||')) > 1 and key.split('||')[1] == mn)
    }
    (sess.get('inventory_overrides') or {}).pop(mn, None)
    for per_lt in (sess.get('capacity_overrides') or {}).values():
        if isinstance(per_lt, dict):
            per_lt.pop(mn, None)
    sess['undo_stack'] = []
    sess['redo_stack'] = []


def create_products_blueprint(
    get_active: Callable[[], tuple],
    global_config: dict,
    save_global_config: Callable[[], None],
    save_sessions_to_disk: Callable[[], None],
    build_clean_engine_for_session: Callable[[dict], object],
    install_clean_engine_baseline: Callable[..., None],
    replay_pending_edits: Callable[[dict, object], None],
    moq_warnings_payload: Callable[[object], dict],
    value_results_payload: Callable[[object], dict],
) -> Blueprint:
    bp = Blueprint('products', __name__)

    def _rebuild_and_payload(sess):
        """Structural rebuild (config.py flow) + full refresh payload.

        Returns (engine, payload) on success or (None, (response, status))
        on failure — the caller rolls the product list back in that case.
        """
        try:
            rebuilt = build_clean_engine_for_session(sess)
        except ValueError as exc:
            # apply_product_overlay rejected the overlay (e.g. a BOM cycle
            # only detectable against fresh workbook data).
            return None, (jsonify({'error': str(exc)}), 400)
        if rebuilt is None:
            return None, (jsonify({
                'error': 'Kon de sessie niet herberekenen. '
                         'Voer eerst een berekening uit.'}), 400)
        install_clean_engine_baseline(sess, rebuilt, clear_machine_overrides=False)
        with current_app.app_context():
            replay_pending_edits(sess, rebuilt)
        sess['engine'] = rebuilt
        payload = {
            'success': True,
            'added_products': _current_products(sess, rebuilt),
            'periods': list(getattr(rebuilt.data, 'periods', []) or []),
            'results': {
                lt: [row.to_dict() for row in rows]
                for lt, rows in (getattr(rebuilt, 'results', {}) or {}).items()
            },
        }
        payload.update(moq_warnings_payload(rebuilt))
        payload.update(value_results_payload(rebuilt))
        return rebuilt, payload

    def _set_products(sess, products: list) -> None:
        sess['added_products'] = products
        engine = sess.get('engine')
        if engine is not None and getattr(engine, 'config_overrides', None) is not None:
            engine.config_overrides['added_products'] = products
        global_config['added_products'] = list(products)

    @bp.route('/api/products/added', methods=['GET'])
    def list_added_products():
        sess, engine = get_active()
        if sess is None:
            return jsonify({'error': _ERR_NO_SESSION}), 400
        if engine is None or getattr(engine, 'data', None) is None:
            return jsonify({'error': _ERR_NO_ENGINE}), 400
        added = _current_products(sess, engine)
        added_numbers = {str(p.get('material_number')) for p in added}
        return jsonify({
            'added_products': added,
            'machines': sorted(engine.data.machines.keys()),
            'materials': [
                {'number': mn, 'name': mat.name}
                for mn, mat in sorted(engine.data.materials.items())
                if mn not in added_numbers
            ],
            'periods': list(engine.data.periods or []),
        })

    @bp.route('/api/products/added', methods=['POST'])
    def upsert_added_product():
        sess, engine = get_active()
        if sess is None:
            return jsonify({'error': _ERR_NO_SESSION}), 400
        if engine is None or getattr(engine, 'data', None) is None:
            return jsonify({'error': _ERR_NO_ENGINE}), 400

        product = request.get_json(force=True, silent=True) or {}
        # Serialize against every other full-rebuild path: a concurrent
        # calculate/product mutation would race on sess['engine'] and the
        # baseline/override stores.
        with engine_rebuild_lock:
            old_products = _current_products(sess, engine)
            old_numbers = {str(p.get('material_number')) for p in old_products}
            mn = normalize_material_number(product.get('material_number'))
            try:
                sanitized = validate_added_product(
                    product,
                    engine.data,
                    other_added=[p for p in old_products
                                 if str(p.get('material_number')) != mn],
                    # The live engine's data already contains the current
                    # overlay; an edit of an existing added product is not a
                    # collision.
                    allow_numbers=old_numbers,
                )
            except ValueError as exc:
                return jsonify({'error': str(exc)}), 400

            new_products = [p for p in old_products
                            if str(p.get('material_number')) != mn]
            new_products.append(sanitized)
            _set_products(sess, new_products)

            rebuilt, payload = _rebuild_and_payload(sess)
            if rebuilt is None:
                _set_products(sess, old_products)  # rollback: rebuild refused
                return payload
            save_global_config()
            save_sessions_to_disk()
        return jsonify(payload)

    @bp.route('/api/products/added/<material_number>', methods=['DELETE'])
    def delete_added_product(material_number):
        sess, engine = get_active()
        if sess is None:
            return jsonify({'error': _ERR_NO_SESSION}), 400
        if engine is None or getattr(engine, 'data', None) is None:
            return jsonify({'error': _ERR_NO_ENGINE}), 400

        mn = normalize_material_number(material_number)
        with engine_rebuild_lock:
            old_products = _current_products(sess, engine)
            new_products = [p for p in old_products
                            if str(p.get('material_number')) != mn]
            if len(new_products) == len(old_products):
                return jsonify({'error': f'Product {mn} is niet gevonden.'}), 404

            prune_material_state(sess, mn)
            _set_products(sess, new_products)

            rebuilt, payload = _rebuild_and_payload(sess)
            if rebuilt is None:
                _set_products(sess, old_products)  # rollback: rebuild refused
                return payload
            save_global_config()
            save_sessions_to_disk()
        return jsonify(payload)

    return bp
