"""
S&OP Planning Engine - Data Models
All data structures used in the planning calculations.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from datetime import datetime
from enum import Enum


class ProductType(Enum):
    RAW_MATERIAL = "Raw Material"
    BULK_PRODUCT = "Bulk Product"
    PACKAGED_PRODUCT = "Packaged Product"
    PACKAGING_GOODS = "Packaging Goods"
    OTHER = "Other"
    
    @classmethod
    def from_string(cls, value: str) -> 'ProductType':
        if not value:
            return cls.OTHER
        value_lower = value.lower()
        if "raw" in value_lower:
            return cls.RAW_MATERIAL
        elif "bulk" in value_lower:
            return cls.BULK_PRODUCT
        elif "packaged" in value_lower or "packed" in value_lower:
            return cls.PACKAGED_PRODUCT
        elif "packaging" in value_lower:
            return cls.PACKAGING_GOODS
        return cls.OTHER


class LineType(Enum):
    DEMAND_FORECAST = "01. Demand forecast"
    DEPENDENT_DEMAND = "02. Dependent demand"
    TOTAL_DEMAND = "03. Total demand"
    INVENTORY = "04. Inventory"
    MIN_TARGET_STOCK = "05. Minimum target stock"
    PRODUCTION_PLAN = "06. Production plan"
    PURCHASE_RECEIPT = "06. Purchase receipt"
    PURCHASE_PLAN = "07. Purchase plan"
    CAPACITY_UTILIZATION = "07. Capacity utilization"
    DEPENDENT_REQUIREMENTS = "08. Dependent requirements"
    AVAILABLE_CAPACITY = "09. Available capacity"
    UTILIZATION_RATE = "10. Utilization rate"
    SHIFT_AVAILABILITY = "11. Shift availability"
    FTE_REQUIREMENTS = "12. FTE requirements"
    CONSOLIDATION = "13. Consolidation"


class ShiftSystem(Enum):
    TWO_SHIFT = "2-shift system"
    THREE_SHIFT = "3-shift system"
    CONTINUOUS = "24/7 production"
    UNLIMITED = "Unlimited"


# Shift hours per month (based on FTE sheet)
SHIFT_HOURS = {
    ShiftSystem.TWO_SHIFT: 4160 / 12,      # ~347 hours/month
    ShiftSystem.THREE_SHIFT: 6240 / 12,    # 520 hours/month
    ShiftSystem.CONTINUOUS: 8760 / 12,     # 730 hours/month
    ShiftSystem.UNLIMITED: 999999,
}

# FTE hours per year
FTE_HOURS_PER_YEAR = 1492

# F2-CF FTE parameters. `fte_hours_per_year` (the 1492 above) stays the leading
# number for every calculation; the derivation fields below only document how
# the client reaches it and are shown as an aid in the workbench. Changing a
# derivation field therefore never changes a planning number by itself —
# `utilization_rate` is the one exception: it scales AVAILABLE FTE (supply),
# not required FTE.
FTE_PARAM_DEFAULTS = {
    'utilization_rate': 0.85,
    'gross_hours_per_year': 2080.0,
    'leave_hours_per_year': 0.0,
    'adv_hours_per_year': 0.0,
    'holiday_hours_per_year': 0.0,
    'illness_pct': 0.0,
    'training_pct': 0.0,
}


def derive_effective_fte_hours(params: Dict[str, float]) -> float:
    """Bruto → effectieve uren per FTE per jaar, zoals het klantmodel rekent.

    base = bruto − verlof − ADV − feestdagen
    netto = base − base×ziekte% − base×training%  =  base × (1 − ziekte% − training%)

    Let op de vorm: het klantmodel (blad 'FTE' van 'OEE model MTO APEX
    voorbeeld.xlsx') trekt BEIDE percentages van DEZELFDE basis af; het
    stapelt ze niet. Met 2080 − 224 − 112 − 48 = 1696 geeft dat
    1696 − 169,60 − 33,92 = 1492,48 — het getal dat het model als
    'Working hours per FTE per year' voert. Achtereenvolgens
    vermenigvuldigen (×0,90 ×0,98) zou 1495,87 geven en dus 3,4 uur per FTE
    per jaar te veel.

    Puur een afleidingshulp: de aanroeper vergelijkt de uitkomst met het
    ingestelde eindgetal en toont het verschil. Nooit stil substitueren.
    """
    gross = float(params.get('gross_hours_per_year') or 0.0)
    base = gross - float(params.get('leave_hours_per_year') or 0.0) \
        - float(params.get('adv_hours_per_year') or 0.0) \
        - float(params.get('holiday_hours_per_year') or 0.0)
    deduction = float(params.get('illness_pct') or 0.0) \
        + float(params.get('training_pct') or 0.0)
    return max(base * (1.0 - deduction), 0.0)


@dataclass
class Material:
    material_number: str
    name: str
    product_type: ProductType
    product_family: str
    spc_product: Optional[str] = None
    product_cluster: Optional[str] = None
    product_name: Optional[str] = None
    production_line: Optional[str] = None
    grouped_production_line: Optional[str] = None
    mill_machine_group: Optional[str] = None
    packaging_machine_group: Optional[str] = None
    truck_operation: int = 0
    fte_requirements: float = 0.0
    ton_per_truck: Optional[float] = None
    time_per_truck: Optional[float] = None
    control_room: int = 0
    default_inventory_value: float = 0.0
    is_active: bool = True
    # Raw product-type string from Material Master (before enum conversion).
    # For truck/control-room materials VBA puts a line-type name here (e.g.
    # "01. Demand forecast") to tell TruckOperationsFormulas which line to SUMIFS over.
    product_type_raw: str = ''
    
    @property
    def is_purchased(self) -> bool:
        return self.product_type in [ProductType.RAW_MATERIAL, ProductType.PACKAGING_GOODS]
    
    @property
    def is_produced(self) -> bool:
        return self.product_type in [ProductType.BULK_PRODUCT, ProductType.PACKAGED_PRODUCT]


@dataclass
class BOMItem:
    plant: str
    parent_material: str
    parent_name: str
    component_material: str
    component_name: str
    quantity_per: float
    bom_header_quantity: float = 1.0
    is_coproduct: bool = False
    production_version: Optional[str] = None
    # Component base unit when the extract carries a UoM column (absent in
    # today's SAP export). When set, the unit is authoritative: mass units
    # are converted at load time and the UoM guard treats the row as
    # trusted instead of applying heuristics (modules/uom_guard.py).
    component_uom: Optional[str] = None
    # SAP recipe identity. A parent can carry several alternative BOMs whose
    # lines all share one production version; the UoM guard's mass balance
    # must judge each alternative on its own or three 1.0-recipes read as
    # one 3.0-recipe (false positive).
    bill_of_material: Optional[str] = None
    alternative_bom: Optional[str] = None


@dataclass
class RoutingItem:
    plant: str
    material: str
    material_description: str
    work_center: str
    base_quantity: float
    standard_time: float
    production_version: Optional[str] = None
    
    @property
    def time_per_unit(self) -> float:
        if self.base_quantity > 0:
            return self.standard_time / self.base_quantity
        return 0.0


@dataclass
class Machine:
    machine_id: str
    machine_code: str
    name: str
    oee: float
    machine_group: Optional[str] = None
    availability_by_period: Dict[str, float] = field(default_factory=dict)
    shift_system: ShiftSystem = ShiftSystem.THREE_SHIFT
    shift_hours_override: Optional[float] = None

    def get_availability(self, period: str) -> float:
        return self.availability_by_period.get(period, 1.0)

    def get_available_hours(self, period: str) -> float:
        base_hours = (self.shift_hours_override
                      if self.shift_hours_override is not None
                      else SHIFT_HOURS.get(self.shift_system, 520))
        return base_hours * self.oee * self.get_availability(period)


@dataclass
class MachineGroup:
    group_id: str
    machine_codes: List[str]
    shift_system: ShiftSystem = ShiftSystem.THREE_SHIFT
    
    def get_shift_hours(self) -> float:
        return SHIFT_HOURS.get(self.shift_system, 520)


@dataclass
class SafetyStockConfig:
    material_number: str
    safety_stock: float
    lot_size: float
    strategic_stock: float = 0.0
    target_stock: float = 0.0
    use_moving_average: bool = False


@dataclass
class PlanningConfig:
    initial_date: datetime
    forecast_months: int = 12
    site: str = "NLX1"
    unlimited_capacity_machine: List[str] = field(default_factory=lambda: ['PBA99'])
    # Read the demand forecast by calendar month (default) instead of by column
    # position.
    #
    # The VBA copies a fixed block of Forecast-sheet columns onto the Planning
    # sheet (ForecastStartClmn = ForecastActualStartClmn + ForecastActualsMonths
    # + 1). Where that block does not begin on the Config initial_date, the whole
    # demand line lands off its own calendar month — measured at +1 month for
    # NLX1 and +4 for NLK1, while NLU1 happened to line up. Line 01 must carry the
    # forecast of the month in its own column, so month keying is the default.
    #
    # False restores the VBA's positional copy. Keep that only for reproducing a
    # client workbook cell-for-cell during validation; it can misalign Line 01.
    forecast_align_to_month: bool = True
    
    def get_periods(self) -> List[str]:
        periods = []
        for i in range(self.forecast_months):
            year = self.initial_date.year + (self.initial_date.month + i - 1) // 12
            month = ((self.initial_date.month + i - 1) % 12) + 1
            periods.append(f"{year}-{str(month).zfill(2)}")
        return periods


@dataclass
class PlanningRow:
    """Single row in the planning output."""
    material_number: str
    material_name: str
    product_type: str
    product_family: str
    spc_product: str
    product_cluster: str
    product_name: str
    line_type: str
    aux_column: Optional[str] = None
    aux_2_column: Optional[str] = None
    starting_stock: float = 0.0
    values: Dict[str, float] = field(default_factory=dict)
    manual_edits: Dict = field(default_factory=dict)  # { period: { original: float, new: float } }

    def get_value(self, period: str) -> float:
        return self.values.get(period, 0.0)
    
    def set_value(self, period: str, value: float):
        self.values[period] = value
    
    def to_dict(self) -> Dict:
        return {
            'material_number': self.material_number,
            'material_name': self.material_name,
            'product_type': self.product_type,
            'product_family': self.product_family,
            'spc_product': self.spc_product,
            'product_cluster': self.product_cluster,
            'product_name': self.product_name,
            'line_type': self.line_type,
            'aux_column': self.aux_column,
            'aux_2_column': self.aux_2_column,
            'starting_stock': self.starting_stock,
            'values': self.values,
            'manual_edits': self.manual_edits,
        }


@dataclass
class ValuationParameters:
    """Financial parameters for value calculations."""
    direct_fte_cost_per_month: float  # Cost number 1
    indirect_fte_cost_per_month: float  # Cost number 2
    overhead_cost_per_month: float  # Cost number 3
    sga_cost_per_month: float  # Cost number 4
    depreciation_per_year: float  # Cost number 5
    net_book_value: float  # Cost number 6
    days_sales_outstanding: int  # Cost number 7
    days_payable_outstanding: int  # Cost number 8


@dataclass
class SalesPriceItem:
    """Average sales price for a product."""
    plant_code: str
    product_id: str
    volume_2025: float
    ex_works_revenue: float
    
    @property
    def price_per_unit(self) -> float:
        if self.volume_2025 > 0:
            return self.ex_works_revenue / self.volume_2025
        return 0.0


@dataclass
class RawMaterialCost:
    """Cost per unit for raw materials."""
    plant_code: str
    product_code: str
    product_name: str
    cost_per_unit: float


@dataclass
class MachineCost:
    """Machine hour cost."""
    plant_code: str
    cost_center: str
    variable_cost_per_hour: float  # Activity type 50


# ── F2-CF: capacity & FTE workbench master data ─────────────────────────────
# These are master data in the same sense as Machine/SafetyStockConfig: they
# are edited in the app and the master workbook, never derived from a monthly
# extract. The FTE engine (modules/fte_engine.py) is their only consumer, so
# adding them changes no existing planning line.


@dataclass
class StaffingNorm:
    """Operators needed per running hour of a machine group or machine.

    Mirrors the '# FTE Staffing' column of the client OEE/FTE model: how many
    people a group needs while it runs, independent of how many hours it runs.
    ``scope`` decides whether ``code`` is a machine-group id (the ZZ-material
    that represents the group) or a single machine code; machine-level norms
    win over the group norm for that machine.
    """
    code: str
    operators_per_hour: float
    scope: str = 'group'  # 'group' | 'machine'
    function_group: str = ''
    description: str = ''


@dataclass
class LaborRate:
    """Employer cost of one FTE per year for a function group.

    ``function_group`` is free text shared with StaffingNorm/IndirectActivity;
    the reserved name 'default' is the site-wide fallback used until the FIN
    breakdown arrives.
    """
    function_group: str
    cost_per_fte_per_year: float
    description: str = ''


@dataclass
class MachineCombination:
    """Machines run together by one shared operator pool.

    A combination is a master-data DEFINITION: which machines can be combined,
    how many operators the combination then needs, and what sharing an operator
    does to throughput. Which combinations are ACTIVE is scenario state per
    session, not master data.

    ``throughput_factor`` applies to every member; ``throughput_factor_by_machine``
    overrides it per machine code (a slaved machine may lose more than its
    partner). Factor 1.0 = no throughput effect.
    """
    combination_id: str
    name: str = ''
    machine_codes: List[str] = field(default_factory=list)
    operators: float = 0.0
    throughput_factor: float = 1.0
    throughput_factor_by_machine: Dict[str, float] = field(default_factory=dict)
    function_group: str = ''
    description: str = ''
    is_active: bool = True

    def factor_for(self, machine_code: str) -> float:
        return float(self.throughput_factor_by_machine.get(machine_code,
                                                           self.throughput_factor))


@dataclass
class IndirectActivity:
    """Labour that is not driven by machine routing hours.

    One row per activity, with an explicit driver so the FTE engine never has
    to guess how to scale it:

    - ``fixed``       — a standing crew. ``fte_per_shift`` × shifts, or
                        ``fte_per_period`` when the crew is stated directly.
    - ``per_ton``     — ``hours_per_unit`` hours per ton of ``volume_source``.
    - ``per_truck``   — tons ÷ ``tons_per_truck`` = trucks, × ``hours_per_unit``.
    - ``per_machine`` — ``machine_count`` ÷ ``machines_per_fte`` (maintenance).

    Cost fields are informational for the value cascade (Fase B); the FTE
    engine only produces hours and FTE.
    """
    activity_id: str
    name: str = ''
    driver: str = 'fixed'  # 'fixed' | 'per_ton' | 'per_truck' | 'per_machine'
    fte_per_period: float = 0.0
    fte_per_shift: float = 0.0
    shifts: float = 0.0
    hours_per_unit: float = 0.0
    tons_per_truck: float = 0.0
    machines_per_fte: float = 0.0
    machine_count: float = 0.0
    cost_per_machine_per_year: float = 0.0
    opex_pct: float = 0.0
    function_group: str = ''
    # Free text describing where this activity and its numbers come from.
    # Carries the seed's provenance ("klantmodel rij 185: 14.645 t ÷ 22 t/truck
    # …") so nobody has to reverse-engineer a norm from a bare number.
    description: str = ''
    # Which volume feeds a per_ton/per_truck driver: a material number, a
    # product family, or '' for the site total.
    volume_source: str = ''
    # Which planning line that volume is read from. Empty = the demand
    # forecast (trucks and handling follow what leaves the site). Set it to
    # '06. Production plan' for an activity that scales with what is made.
    volume_line: str = ''
    is_active: bool = True


@dataclass
class ThroughputOverride:
    """Master-data override of the effective throughput of machine × product.

    SAP routing stays the calculation source; this is the escape hatch for
    machine/product pairs where the client's MES or PEER norm is authoritative.
    ``source`` is the provenance label shown in the workbench ('MES', 'PEER',
    'SAP', or free text).
    """
    machine_code: str
    material_number: str
    throughput_t_per_hour: float
    source: str = ''
    note: str = ''


@dataclass
class BenchmarkThroughput:
    """Measured / peer throughput shown next to the norm — never calculated with.

    Feeds the workbench's 'actual vs norm' column (MES_OEE Mills, PEER_Capacity).
    """
    machine_code: str
    material_number: str = ''
    mes_t_per_hour: float = 0.0
    peer_t_per_hour: float = 0.0
    mes_oee: float = 0.0
    note: str = ''


@dataclass
class ChangeoverTime:
    """Omsteltijd per machine (uren per omstelling) — masterdata.

    Fase 1 van het machine-inzet-tabblad: op machineniveau, bewust simpel.
    Het sleutelformaat laat een latere verfijning naar productovergangen
    (MACHINE|VAN|NAAR met de machinewaarde als terugval) toe zonder migratie.
    Rekent in fase 1 nergens in mee: het tabblad toont de geschatte
    omsteluren; doorwerking op het beschikbaarheidsvenster is fase 2.
    """
    machine_code: str
    hours_per_changeover: float = 0.0
    description: str = ''
