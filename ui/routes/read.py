"""Read-only result and dashboard routes."""

import logging
from typing import Callable

from flask import Blueprint, jsonify

from modules.inventory_quality_engine import InventoryQualityEngine
from modules.models import LineType
from ui.scoping import (
    group_material_set,
    material_l07_hours_by_machine,
    resolve_active_group,
    scale_utilization,
    scope_inventory_quality,
    scope_trend,
    scoped_financials,
    scoped_marker,
)

logger = logging.getLogger(__name__)


def create_read_blueprint(
    get_active: Callable[[], tuple],
    row_payload: Callable[[object], dict],
    moq_warnings_payload: Callable[[object], dict],
) -> Blueprint:
    bp = Blueprint('read', __name__)

    @bp.route('/api/results')
    def get_results():
        sess, current_engine = get_active()
        if current_engine is None:
            return jsonify({'error': 'No calculations run'}), 400

        results = {
            lt: [row_payload(row) for row in rows]
            for lt, rows in current_engine.results.items()
        }

        baseline = sess.get('reset_baseline') if sess else None
        baseline_results = None
        if baseline and baseline.get('results'):
            baseline_results = {
                lt: [
                    {
                        'material_number': row.get('material_number', ''),
                        'aux_column': row.get('aux_column', ''),
                        'values': row.get('values', {}),
                    }
                    for row in rows
                ]
                for lt, rows in baseline['results'].items()
            }

        response = {'periods': current_engine.data.periods, 'results': results}
        if baseline_results:
            response['baseline_results'] = baseline_results
        response.update(moq_warnings_payload(current_engine))
        return jsonify(response)

    @bp.route('/api/value_results')
    def get_value_results():
        sess, current_engine = get_active()
        if current_engine is None:
            return jsonify({'error': 'No calculations run'}), 400

        if not current_engine.value_results:
            return jsonify({'error': 'No value planning results available'}), 400

        results = {
            lt: [row_payload(row) for row in rows]
            for lt, rows in current_engine.value_results.items()
        }
        consolidation = [
            row_payload(row)
            for row in current_engine.value_results.get(LineType.CONSOLIDATION.value, [])
        ]

        baseline = sess.get('reset_baseline') if sess else None
        baseline_value_results = None
        if baseline and baseline.get('value_results'):
            baseline_value_results = {
                lt: [
                    {
                        'material_number': row.get('material_number', ''),
                        'aux_column': row.get('aux_column', ''),
                        'values': row.get('values', {}),
                    }
                    for row in rows
                ]
                for lt, rows in baseline['value_results'].items()
            }

        response = {
            'periods': current_engine.data.periods,
            'results': results,
            'consolidation': consolidation,
        }
        if baseline_value_results:
            response['baseline_value_results'] = baseline_value_results

        # Material groups (view scoping): add the honest scoped P&L block
        # next to the untouched full payload. No group active → no extra
        # keys, byte-identical response.
        group = resolve_active_group(sess)
        if group is not None:
            mats, _ = group_material_set(group, current_engine.data)
            response['scoped_consolidation'] = scoped_financials(
                current_engine, mats, current_engine.data.periods)
            response['scoped'] = scoped_marker(group, current_engine.data)
        return jsonify(response)

    @bp.route('/api/dashboard')
    def get_dashboard():
        sess, current_engine = get_active()
        if current_engine is None:
            return jsonify({'error': 'No calculations run'}), 400

        periods = current_engine.data.periods
        materials_count = len(current_engine.data.materials)

        util_rows = current_engine.results.get(LineType.UTILIZATION_RATE.value, [])
        all_util_vals = [value * 100 for row in util_rows for value in row.values.values() if value is not None]
        avg_utilization = round(sum(all_util_vals) / len(all_util_vals), 1) if all_util_vals else 0.0

        fte_rows = current_engine.results.get(LineType.FTE_REQUIREMENTS.value, [])
        latest_period = periods[-1] if periods else None
        total_fte = round(
            sum(row.values.get(latest_period, 0.0) for row in fte_rows), 2
        ) if latest_period else 0.0

        utilization_by_machine = [
            {
                'machine': row.material_name,
                'group': row.aux_column or '',
                'values': {period: round(value * 100, 1) for period, value in row.values.items()},
            }
            for row in util_rows
        ]

        fte_by_group = [
            {
                'group': row.material_name,
                'values': {period: round(value, 2) for period, value in row.values.items()},
            }
            for row in fte_rows
        ]

        financials = {}
        for row in current_engine.value_results.get(LineType.CONSOLIDATION.value, []):
            key = row.material_number.replace('ZZZZZZ_', '')
            decimals = 6 if key == 'ROCE' else 0
            financials[key] = {period: round(value, decimals) for period, value in row.values.items()}

        if 'INVENTORY VALUE' in financials:
            inv_starting = sum(
                r.starting_stock
                for r in current_engine.value_results.get(LineType.INVENTORY.value, [])
            )
            financials['INVENTORY VALUE']['Starting stock'] = round(inv_starting, 0)

        inventory_quality: list = []
        top_10_overstocks: list = []
        total_overstock = 0.0
        try:
            current_engine._iq_cache = InventoryQualityEngine(
                current_engine.data,
                current_engine.results,
                current_engine.value_results,
            ).calculate()
            iq_result = current_engine._iq_cache or {}
            inventory_quality = iq_result.get('per_material', [])
            top_10_overstocks = iq_result.get('top_10_overstocks', [])
            total_overstock = iq_result.get('total_overstock', 0.0)
        except Exception:
            logger.exception("InventoryQualityEngine failed; dashboard will show empty quality data")

        demand_trend = {}
        for row in current_engine.results.get(LineType.TOTAL_DEMAND.value, []):
            for period in periods:
                demand_trend[period] = round(demand_trend.get(period, 0.0) + row.values.get(period, 0.0), 1)

        inventory_trend = {}
        target_trend = {}
        for row in current_engine.results.get(LineType.INVENTORY.value, []):
            for period in periods:
                inventory_trend[period] = round(
                    inventory_trend.get(period, 0.0) + row.values.get(period, 0.0), 1
                )
        for row in current_engine.results.get(LineType.MIN_TARGET_STOCK.value, []):
            for period in periods:
                target_trend[period] = round(target_trend.get(period, 0.0) + row.values.get(period, 0.0), 1)

        payload = {
            'periods': periods,
            'kpis': {
                'materials': materials_count,
                'avg_utilization': avg_utilization,
                'total_fte': total_fte,
                'total_overstock': total_overstock,
            },
            'utilization_by_machine': utilization_by_machine,
            'fte_by_group': fte_by_group,
            'financials': financials,
            'inventory_quality': inventory_quality,
            'top_10_overstocks': top_10_overstocks,
            'demand_trend': demand_trend,
            'inventory_trend': inventory_trend,
            'target_trend': target_trend,
        }

        # Material groups (view scoping, Fase materiaalgroepen): with an
        # active group the per-material aggregates are re-summed over the
        # group; machine utilization becomes the group's SHARE (ratio of
        # material-L07 hours); fixed-cost/derived financials are replaced by
        # the honest scoped block. Without an active group the code above is
        # untouched and the payload stays byte-identical (golden parity).
        group = resolve_active_group(sess)
        if group is not None:
            data = current_engine.data
            mats, _missing = group_material_set(group, data)
            results = current_engine.results
            payload['demand_trend'] = scope_trend(
                results.get(LineType.TOTAL_DEMAND.value, []), mats, periods)
            payload['inventory_trend'] = scope_trend(
                results.get(LineType.INVENTORY.value, []), mats, periods)
            payload['target_trend'] = scope_trend(
                results.get(LineType.MIN_TARGET_STOCK.value, []), mats, periods)

            scoped_iq, scoped_top10, scoped_overstock = scope_inventory_quality(
                inventory_quality, mats)
            payload['inventory_quality'] = scoped_iq
            payload['top_10_overstocks'] = scoped_top10

            payload['financials'] = scoped_financials(current_engine, mats, periods)

            l07_rows = results.get(LineType.CAPACITY_UTILIZATION.value, [])
            full_hours = material_l07_hours_by_machine(l07_rows, None, periods)
            group_hours = material_l07_hours_by_machine(l07_rows, mats, periods)
            scoped_util = []
            scoped_util_vals = []
            for entry in utilization_by_machine:
                mc_code = entry['machine']
                scaled = scale_utilization(
                    entry['values'],
                    group_hours.get(mc_code, {}),
                    full_hours.get(mc_code, {}),
                )
                scoped_util.append({**entry, 'values': scaled})
                scoped_util_vals.extend(v for v in scaled.values() if v is not None)
            payload['utilization_by_machine'] = scoped_util

            payload['kpis'] = {
                'materials': len(mats),
                'avg_utilization': round(
                    sum(scoped_util_vals) / len(scoped_util_vals), 1
                ) if scoped_util_vals else 0.0,
                'total_fte': total_fte,  # niet toerekenbaar; frontend toont "—"
                'total_overstock': scoped_overstock,
            }
            payload['scoped'] = scoped_marker(group, data)
        return jsonify(payload)

    @bp.route('/api/capacity')
    def get_capacity():
        _, current_engine = get_active()
        if current_engine is None:
            return jsonify({'error': 'No calculations run'}), 400

        utilization = []
        for row in current_engine.results.get(LineType.UTILIZATION_RATE.value, []):
            utilization.append({
                'machine': row.material_name,
                'group': row.product_family or '',
                'values': {period: round(value * 100, 1) for period, value in row.values.items()}
            })

        return jsonify({
            'periods': current_engine.data.periods,
            'utilization': utilization
        })

    @bp.route('/api/inventory')
    def get_inventory():
        _, current_engine = get_active()
        if current_engine is None:
            return jsonify({'error': 'No calculations run'}), 400

        inv_rows = current_engine.results.get(LineType.INVENTORY.value, [])
        tgt_rows = current_engine.results.get(LineType.MIN_TARGET_STOCK.value, [])

        target_lookup = {row.material_number: row.values for row in tgt_rows}
        periods = current_engine.data.periods

        data = []
        ok, low, high = 0, 0, 0

        for row in inv_rows:
            target = target_lookup.get(row.material_number, {})
            avg_inv = sum(row.values.get(period, 0) for period in periods) / len(periods) if periods else 0
            avg_tgt = sum(target.get(period, 0) for period in periods) / len(periods) if target and periods else 0

            status = 'OK'
            if avg_inv <= 0:
                status = 'LOW'
                low += 1
            elif avg_tgt > 0:
                if avg_inv < avg_tgt * 0.5:
                    status = 'LOW'
                    low += 1
                elif avg_inv > avg_tgt * 2:
                    status = 'HIGH'
                    high += 1
                else:
                    ok += 1
            else:
                ok += 1

            data.append({
                'material_number': row.material_number,
                'material_name': row.material_name,
                'status': status,
                'values': row.values
            })

        return jsonify({
            'periods': current_engine.data.periods,
            'summary': {'healthy': ok, 'low': low, 'high': high},
            'data': data
        })

    @bp.route('/api/inventory_quality')
    def get_inventory_quality():
        _, current_engine = get_active()
        if current_engine is None:
            return jsonify({'error': 'No calculations run'}), 400

        engine = InventoryQualityEngine(
            current_engine.data,
            current_engine.results,
            current_engine.value_results,
        )
        return jsonify(engine.calculate())

    return bp
