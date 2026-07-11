"""
S&OP Planning Engine - Master data serialization (master-config vervanging).

The app-managed master store holds POST-PARSE data: ``serialize_master`` runs
over a DataLoader that parsed the master workbook with the existing, VBA-
faithful loaders, and captures the resulting structures. ``hydrate_loader``
puts them back onto a fresh DataLoader. There is deliberately NO second
Excel-parsing implementation — parity between the xlsm path and the store
path is exact and testable.

Scope: everything the master workbook provides that has no monthly-extract
alternative (config, FTE, material master, machines/OEE, safety stock,
purchase settings incl. actuals, cost/price sheets, valuation parameters).
Transactional data (BOM/routing/forecast/stock) keeps coming from the
monthly SAP extracts.
"""

from dataclasses import asdict
from datetime import datetime
from typing import Dict, Optional

from modules.models import (
    Machine,
    MachineCost,
    MachineGroup,
    Material,
    PlanningConfig,
    ProductType,
    RawMaterialCost,
    SafetyStockConfig,
    SalesPriceItem,
    ShiftSystem,
    ValuationParameters,
)

MASTER_SCHEMA_VERSION = 1


def serialize_master(loader) -> dict:
    """Capture a loaded DataLoader's master structures as a JSON-safe dict."""
    config = loader.config
    materials = []
    for material in loader.materials.values():
        item = asdict(material)
        item['product_type'] = material.product_type.value
        materials.append(item)

    machines = []
    for machine in loader.machines.values():
        item = asdict(machine)
        item['shift_system'] = machine.shift_system.value
        machines.append(item)

    return {
        'schema_version': MASTER_SCHEMA_VERSION,
        'config': {
            'initial_date': config.initial_date.isoformat() if config else None,
            'forecast_months': config.forecast_months if config else 12,
            'site': config.site if config else 'NLX1',
            'unlimited_capacity_machine': list(config.unlimited_capacity_machine) if config else [],
            'forecast_actuals_months': getattr(loader, 'forecast_actuals_months', 12),
            'purchased_and_produced': dict(loader.purchased_and_produced or {}),
        },
        'fte': {
            'fte_hours_per_year': loader.fte_hours_per_year,
            'shift_hours': dict(loader.shift_hours or {}),
            'default_shift_name': loader.default_shift_name,
        },
        'materials': materials,
        'machines': machines,
        'safety_stock': {mat: asdict(cfg) for mat, cfg in (loader.safety_stock or {}).items()},
        'purchase': {
            'lead_times': dict(loader.purchase_lead_times or {}),
            'moq': dict(loader.purchase_moq or {}),
            'sheet_materials': sorted(loader.purchase_sheet_materials or []),
            'actuals': {mat: dict(vals) for mat, vals in (loader.purchase_actuals or {}).items()},
        },
        'sales_prices': {mat: asdict(sp) for mat, sp in (loader.sales_prices or {}).items()},
        'material_costs': {mat: asdict(mc) for mat, mc in (loader.material_costs or {}).items()},
        'machine_costs': {mc: asdict(cost) for mc, cost in (loader.machine_costs or {}).items()},
        'valuation_params': asdict(loader.valuation_params) if loader.valuation_params else None,
    }


def hydrate_loader(loader, master: dict) -> None:
    """Fill a DataLoader's master structures from a serialized master dict.

    Mirrors what the xlsm loaders would have produced. The caller applies
    config overrides afterwards and then calls ``finalize_shift_systems``
    (shift systems derive from the FINAL unlimited-machines list, exactly
    like _load_machines does on the xlsm path).
    """
    cfg = master.get('config') or {}
    initial_date = cfg.get('initial_date')
    loader.config = PlanningConfig(
        initial_date=datetime.fromisoformat(initial_date) if initial_date else datetime(2025, 12, 1),
        forecast_months=int(cfg.get('forecast_months') or 12),
        site=str(cfg.get('site') or 'NLX1'),
        unlimited_capacity_machine=list(cfg.get('unlimited_capacity_machine') or []),
    )
    loader.forecast_actuals_months = int(cfg.get('forecast_actuals_months') or 12)
    loader.purchased_and_produced = {
        str(mat): float(val) for mat, val in (cfg.get('purchased_and_produced') or {}).items()
    }
    loader.periods = loader.config.get_periods()

    fte = master.get('fte') or {}
    loader.fte_hours_per_year = float(fte.get('fte_hours_per_year') or 1492)
    loader.shift_hours = {str(k): float(v) for k, v in (fte.get('shift_hours') or {}).items()}
    if '3-shift system' not in loader.shift_hours:
        loader.shift_hours['3-shift system'] = 520
    loader.default_shift_name = str(fte.get('default_shift_name') or '3-shift system')

    loader.materials = {}
    for item in master.get('materials') or []:
        fields = dict(item)
        fields['product_type'] = ProductType(fields['product_type'])
        material = Material(**fields)
        loader.materials[material.material_number] = material

    loader.machines = {}
    for item in master.get('machines') or []:
        fields = dict(item)
        fields['shift_system'] = ShiftSystem(fields['shift_system'])
        machine = Machine(**fields)
        loader.machines[machine.machine_code] = machine
    _rebuild_machine_groups(loader)

    loader.safety_stock = {
        str(mat): SafetyStockConfig(**cfg_dict)
        for mat, cfg_dict in (master.get('safety_stock') or {}).items()
    }

    purchase = master.get('purchase') or {}
    loader.purchase_lead_times = {str(m): int(v) for m, v in (purchase.get('lead_times') or {}).items()}
    loader.purchase_moq = {str(m): float(v) for m, v in (purchase.get('moq') or {}).items()}
    loader.purchase_sheet_materials = set(purchase.get('sheet_materials') or [])
    loader.purchase_actuals = {
        str(m): {str(p): float(v) for p, v in vals.items()}
        for m, vals in (purchase.get('actuals') or {}).items()
    }

    loader.sales_prices = {
        str(mat): SalesPriceItem(**item)
        for mat, item in (master.get('sales_prices') or {}).items()
    }
    loader.material_costs = {
        str(mat): RawMaterialCost(**item)
        for mat, item in (master.get('material_costs') or {}).items()
    }
    loader.machine_costs = {
        str(mc): MachineCost(**item)
        for mc, item in (master.get('machine_costs') or {}).items()
    }

    vp = master.get('valuation_params')
    loader.valuation_params = ValuationParameters(**vp) if vp else None


def _rebuild_machine_groups(loader) -> None:
    """Same derivation as _load_machines: groups from machine.machine_group."""
    groups: Dict[str, list] = {}
    for mc_code, machine in loader.machines.items():
        if machine.machine_group:
            groups.setdefault(machine.machine_group, []).append(mc_code)
    loader.machine_groups = {
        gid: MachineGroup(group_id=gid, machine_codes=mcs,
                          shift_system=ShiftSystem.THREE_SHIFT)
        for gid, mcs in groups.items()
    }


def finalize_shift_systems(loader) -> None:
    """Derive shift systems from the FINAL config (after overrides), exactly
    like _load_machines: UNLIMITED when listed, otherwise 3-shift."""
    unlimited = set(getattr(loader.config, 'unlimited_capacity_machine', []) or [])
    for mc_code, machine in loader.machines.items():
        machine.shift_system = (
            ShiftSystem.UNLIMITED if mc_code in unlimited else ShiftSystem.THREE_SHIFT
        )
