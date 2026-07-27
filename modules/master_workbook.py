"""
S&OP Planning Engine - Master workbook (per-site Excel editing medium).

The app master store stays the runtime source of truth; this module renders
it to a clean, per-site Excel workbook (one table per dataset, columns =
dataclass field names) and parses an edited copy back into a master dict.
The legacy MS_RECONC format is deliberately NOT reproduced here — this is
the app's own stable format, guarded by a round-trip test
(export -> parse == original master) and by validation-through-hydration on
import (same mechanism as the dataset PATCH route).

Month data stays out by design: purchase ACTUALS are not exported, and an
import preserves the store's existing actuals untouched (F2 principle:
master data and month data must not mix silently).

The _Meta sheet carries site + store version so an import can refuse a
workbook from another site and detect edits based on a stale export.
"""

import dataclasses
import typing
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from modules.models import (
    Machine,
    MachineCost,
    Material,
    RawMaterialCost,
    SafetyStockConfig,
    SalesPriceItem,
    ValuationParameters,
)

WORKBOOK_SCHEMA_VERSION = 1

SHEET_META = '_Meta'
SHEET_CONFIG = 'Config'
SHEET_FTE = 'FTE'
SHEET_MATERIALS = 'Materialen'
SHEET_MACHINES = 'Machines'
SHEET_SAFETY = 'Veiligheidsvoorraad'
SHEET_PURCHASE = 'Inkoop'
SHEET_PRICES = 'Verkoopprijzen'
SHEET_MATERIAL_COSTS = 'Grondstofkosten'
SHEET_MACHINE_COSTS = 'Machinekosten'
SHEET_VALUATION = 'Waardering'

_KEY_COLUMN = 'sleutel'
_AVAILABILITY_PREFIX = 'beschikbaarheid '


def _field_names(dc) -> List[str]:
    return [f.name for f in dataclasses.fields(dc)]


def _casters(dc) -> Dict[str, callable]:
    """Per-field cell->value casters derived from the dataclass type hints.

    Cells come back from Excel as str/float/bool/None; the master dict must
    carry the same shapes serialize_master produces. Enum-valued fields
    (product_type, shift_system) are stored as their string value and stay
    strings here — hydration converts them.
    """
    hints = typing.get_type_hints(dc)
    defaults = {f.name: f.default for f in dataclasses.fields(dc)
                if f.default is not dataclasses.MISSING}
    casters = {}
    for name, hint in hints.items():
        origin = typing.get_origin(hint)
        args = typing.get_args(hint)
        optional = origin is typing.Union and type(None) in args
        if optional:
            inner = next(a for a in args if a is not type(None))
        else:
            inner = hint
        casters[name] = _make_caster(inner, optional, defaults.get(name, dataclasses.MISSING))
    return casters


def _make_caster(inner, optional, default):
    def cast(value):
        empty = value is None or (isinstance(value, str) and not value.strip())
        if empty:
            # An empty cell means "the default", exactly like an absent value
            # in the dataclass — is_active must default to True, not False.
            if default is not dataclasses.MISSING:
                return default.value if hasattr(default, 'value') else default
            if optional:
                return None
            if inner is bool:
                return False
            if inner is int:
                return 0
            if inner is float:
                return 0.0
            return ''
        if inner is bool:
            return _to_bool(value)
        if inner is int:
            return int(float(value))
        if inner is float:
            return float(value)
        if inner is str:
            return str(value).strip()
        return value  # enums-as-strings, dicts — passed through
    return cast


def _to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('1', 'true', 'waar', 'ja', 'x', 'yes')


def _row_dict(headers, row) -> dict:
    return {h: row[i] if i < len(row) else None for i, h in enumerate(headers) if h}


def _is_empty_row(values) -> bool:
    return all(v is None or (isinstance(v, str) and not v.strip()) for v in values)


# ------------------------------------------------------------------ export


def export_master_workbook(master: dict, path, site: str,
                           store_version, exported_at: Optional[str] = None) -> None:
    """Render the master dict to the per-site workbook at `path` (atomic:
    written to a temp name first, then replaced)."""
    import openpyxl

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    _write_kv(wb, SHEET_META, [
        ('schema_version', WORKBOOK_SCHEMA_VERSION),
        ('site', site),
        ('store_version', store_version),
        ('exported_at', exported_at or datetime.now().isoformat(timespec='seconds')),
        ('let_op', 'Gegenereerd door de app. Bewerk de gegevensbladen; laat _Meta ongemoeid.'),
    ])

    cfg = master.get('config') or {}
    _write_kv(wb, SHEET_CONFIG, [
        ('initial_date', cfg.get('initial_date') or ''),
        ('forecast_months', cfg.get('forecast_months')),
        ('site', cfg.get('site') or ''),
        ('unlimited_capacity_machine', ','.join(cfg.get('unlimited_capacity_machine') or [])),
        ('forecast_actuals_months', cfg.get('forecast_actuals_months')),
        ('forecast_align_to_month', bool(cfg.get('forecast_align_to_month', True))),
        ('purchased_and_produced', ','.join(
            f'{m}:{v}' for m, v in (cfg.get('purchased_and_produced') or {}).items())),
    ])

    fte = master.get('fte') or {}
    fte_rows = [
        ('fte_hours_per_year', fte.get('fte_hours_per_year')),
        ('default_shift_name', fte.get('default_shift_name') or ''),
    ]
    for shift_name, hours in sorted((fte.get('shift_hours') or {}).items()):
        fte_rows.append((f'shift_hours.{shift_name}', hours))
    _write_kv(wb, SHEET_FTE, fte_rows)

    _write_table(wb, SHEET_MATERIALS, _field_names(Material),
                 master.get('materials') or [])

    machine_fields = [f for f in _field_names(Machine) if f != 'availability_by_period']
    periods = sorted({p for m in (master.get('machines') or [])
                      for p in (m.get('availability_by_period') or {})})
    machine_headers = machine_fields + [f'{_AVAILABILITY_PREFIX}{p}' for p in periods]
    machine_rows = []
    for m in master.get('machines') or []:
        row = {f: m.get(f) for f in machine_fields}
        for p in periods:
            row[f'{_AVAILABILITY_PREFIX}{p}'] = (m.get('availability_by_period') or {}).get(p)
        machine_rows.append(row)
    _write_table(wb, SHEET_MACHINES, machine_headers, machine_rows)

    _write_keyed_table(wb, SHEET_SAFETY, _field_names(SafetyStockConfig),
                       master.get('safety_stock') or {})

    purchase = master.get('purchase') or {}
    materials = sorted(set(purchase.get('lead_times') or {})
                       | set(purchase.get('moq') or {})
                       | set(purchase.get('sheet_materials') or []))
    _write_table(wb, SHEET_PURCHASE,
                 ['material', 'lead_time', 'moq', 'in_purchase_sheet'],
                 [{
                     'material': m,
                     'lead_time': (purchase.get('lead_times') or {}).get(m),
                     'moq': (purchase.get('moq') or {}).get(m),
                     'in_purchase_sheet': m in set(purchase.get('sheet_materials') or []),
                 } for m in materials])

    _write_keyed_table(wb, SHEET_PRICES, _field_names(SalesPriceItem),
                       master.get('sales_prices') or {})
    _write_keyed_table(wb, SHEET_MATERIAL_COSTS, _field_names(RawMaterialCost),
                       master.get('material_costs') or {})
    _write_keyed_table(wb, SHEET_MACHINE_COSTS, _field_names(MachineCost),
                       master.get('machine_costs') or {})

    vp = master.get('valuation_params') or {}
    _write_kv(wb, SHEET_VALUATION,
              [(name, vp.get(name)) for name in _field_names(ValuationParameters)])

    path = Path(path)
    tmp = path.with_name(path.name + '.tmp')
    wb.save(str(tmp))
    tmp.replace(path)


def _write_kv(wb, sheet, rows):
    ws = wb.create_sheet(sheet)
    ws.append(['naam', 'waarde'])
    for key, value in rows:
        ws.append([key, value])


def _write_table(wb, sheet, headers, rows):
    ws = wb.create_sheet(sheet)
    ws.append(list(headers))
    for row in rows:
        ws.append([row.get(h) for h in headers])


def _write_keyed_table(wb, sheet, fields, keyed: dict):
    headers = [_KEY_COLUMN] + list(fields)
    ws = wb.create_sheet(sheet)
    ws.append(headers)
    for key in sorted(keyed):
        item = keyed[key]
        ws.append([key] + [item.get(f) for f in fields])


# ------------------------------------------------------------------- parse


class MasterWorkbookError(ValueError):
    """Structured parse/validation failure with a user-facing message."""


def parse_master_workbook(path) -> Tuple[dict, dict]:
    """Parse an (edited) master workbook back into (master, meta).

    Purchase actuals are intentionally absent from the workbook; the caller
    merges the current store's actuals back in. Raises MasterWorkbookError
    with a Dutch, user-facing message on structural problems.
    """
    import openpyxl

    try:
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    except Exception as exc:
        raise MasterWorkbookError(f'Werkboek niet leesbaar: {exc}') from exc
    try:
        sheets = {ws.title: ws for ws in wb.worksheets}
        missing = [s for s in (SHEET_META, SHEET_CONFIG, SHEET_FTE, SHEET_MATERIALS,
                               SHEET_MACHINES, SHEET_SAFETY, SHEET_PURCHASE,
                               SHEET_PRICES, SHEET_MATERIAL_COSTS,
                               SHEET_MACHINE_COSTS, SHEET_VALUATION)
                   if s not in sheets]
        if missing:
            raise MasterWorkbookError(
                'Dit is geen masterwerkboek van de app: ontbrekende bladen '
                + ', '.join(missing))

        meta = dict(_read_kv(sheets[SHEET_META]))
        cfg_raw = dict(_read_kv(sheets[SHEET_CONFIG]))
        fte_raw = dict(_read_kv(sheets[SHEET_FTE]))
        vp_raw = dict(_read_kv(sheets[SHEET_VALUATION]))

        master = {
            'schema_version': 1,
            'config': _parse_config(cfg_raw),
            'fte': _parse_fte(fte_raw),
            'materials': _parse_table(sheets[SHEET_MATERIALS], Material),
            'machines': _parse_machines(sheets[SHEET_MACHINES]),
            'safety_stock': _parse_keyed_table(sheets[SHEET_SAFETY], SafetyStockConfig),
            'purchase': _parse_purchase(sheets[SHEET_PURCHASE]),
            'sales_prices': _parse_keyed_table(sheets[SHEET_PRICES], SalesPriceItem),
            'material_costs': _parse_keyed_table(sheets[SHEET_MATERIAL_COSTS], RawMaterialCost),
            'machine_costs': _parse_keyed_table(sheets[SHEET_MACHINE_COSTS], MachineCost),
            'valuation_params': _parse_valuation(vp_raw),
        }
        return master, meta
    finally:
        wb.close()


def _read_kv(ws):
    rows = ws.iter_rows(values_only=True)
    next(rows, None)  # header
    for row in rows:
        if not row or row[0] is None:
            continue
        yield str(row[0]).strip(), (row[1] if len(row) > 1 else None)


def _read_table(ws):
    rows = ws.iter_rows(values_only=True)
    header = next(rows, None) or ()
    headers = [str(h).strip() if h is not None else '' for h in header]
    for row in rows:
        if _is_empty_row(row):
            continue
        yield _row_dict(headers, row)


def _parse_config(raw: dict) -> dict:
    pap = {}
    for entry in str(raw.get('purchased_and_produced') or '').split(','):
        parts = entry.strip().split(':')
        if len(parts) == 2:
            try:
                pap[parts[0].strip()] = float(parts[1].strip())
            except ValueError:
                continue
    initial_date = raw.get('initial_date')
    if isinstance(initial_date, datetime):
        initial_date = initial_date.isoformat()
    return {
        'initial_date': str(initial_date or '') or None,
        'forecast_months': int(float(raw.get('forecast_months') or 12)),
        'site': str(raw.get('site') or '').strip(),
        'unlimited_capacity_machine': [
            m.strip() for m in str(raw.get('unlimited_capacity_machine') or '').split(',')
            if m.strip()],
        'forecast_actuals_months': int(float(raw.get('forecast_actuals_months') or 12)),
        'forecast_align_to_month': _to_bool(raw.get('forecast_align_to_month', True)),
        'purchased_and_produced': pap,
    }


def _parse_fte(raw: dict) -> dict:
    shift_hours = {}
    for key, value in raw.items():
        if key.startswith('shift_hours.') and value is not None:
            shift_hours[key[len('shift_hours.'):]] = float(value)
    return {
        'fte_hours_per_year': float(raw.get('fte_hours_per_year') or 1492),
        'shift_hours': shift_hours,
        'default_shift_name': str(raw.get('default_shift_name') or '3-shift system'),
    }


def _parse_table(ws, dc) -> list:
    casters = _casters(dc)
    fields = _field_names(dc)
    items = []
    for row in _read_table(ws):
        item = {}
        for f in fields:
            item[f] = casters[f](row.get(f)) if f in casters else row.get(f)
        items.append(item)
    return items


def _parse_machines(ws) -> list:
    casters = _casters(Machine)
    fields = [f for f in _field_names(Machine) if f != 'availability_by_period']
    items = []
    for row in _read_table(ws):
        item = {f: casters[f](row.get(f)) for f in fields}
        availability = {}
        for col, value in row.items():
            if col.startswith(_AVAILABILITY_PREFIX) and value is not None:
                availability[col[len(_AVAILABILITY_PREFIX):].strip()] = float(value)
        item['availability_by_period'] = availability
        items.append(item)
    return items


def _parse_keyed_table(ws, dc) -> dict:
    casters = _casters(dc)
    fields = _field_names(dc)
    keyed = {}
    for row in _read_table(ws):
        key = row.get(_KEY_COLUMN)
        if key is None or str(key).strip() == '':
            continue
        keyed[str(key).strip()] = {f: casters[f](row.get(f)) for f in fields}
    return keyed


def _parse_purchase(ws) -> dict:
    lead_times, moq, sheet_materials = {}, {}, []
    for row in _read_table(ws):
        material = str(row.get('material') or '').strip()
        if not material:
            continue
        if row.get('lead_time') is not None:
            lead_times[material] = int(float(row['lead_time']))
        if row.get('moq') is not None:
            moq[material] = float(row['moq'])
        if _to_bool(row.get('in_purchase_sheet')):
            sheet_materials.append(material)
    return {
        'lead_times': lead_times,
        'moq': moq,
        'sheet_materials': sorted(sheet_materials),
        # Actuals zijn maanddata en staan bewust niet in het werkboek; de
        # importroute behoudt de actuals van de huidige store.
        'actuals': {},
    }


def _parse_valuation(raw: dict) -> Optional[dict]:
    values = {}
    for name in _field_names(ValuationParameters):
        value = raw.get(name)
        if value is None:
            continue
        values[name] = int(float(value)) if name.startswith('days_') else float(value)
    return values or None
