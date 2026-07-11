"""
S&OP Planning Engine - Product Overlay (Fase 3)

Injects user-defined "added products" into the shared DataLoader structures
after the workbook is loaded and before any engine runs. The workbook stays
the source of truth: with an empty/absent overlay nothing is mutated, so
baseline runs remain byte-for-byte identical (golden parity).

An added product is a JSON-safe dict (see ADDED_PRODUCT_FIELDS). Validation
errors raise ValueError with a Dutch, user-facing message; the routes turn
those into HTTP 400 responses.
"""

import re
from typing import Dict, Iterable, List, Optional, Set

from modules.forecast_engine import ForecastEngine
from modules.models import (
    BOMItem,
    Material,
    ProductType,
    RawMaterialCost,
    RoutingItem,
    SafetyStockConfig,
    SalesPriceItem,
)

PRODUCT_TYPES = ('bulk', 'packaged', 'raw', 'packaging', 'other')

# Every key an AddedProduct dict may carry. Unknown keys are dropped by
# validate_added_product so persisted session stores stay clean.
ADDED_PRODUCT_FIELDS = (
    'material_number', 'name', 'product_type', 'product_family',
    'flat_volume', 'volumes', 'starting_stock', 'safety_stock',
    'bom_as_parent', 'bom_as_child', 'routing',
    'lead_time', 'moq', 'pap_fraction',
    'sales_price', 'raw_material_cost', 'default_inventory_value',
)

_PERIOD_RE = re.compile(r'^\d{4}-\d{2}$')
_FLOAT_KEY_RE = re.compile(r'^(\d+)\.0+$')


def normalize_material_number(raw) -> str:
    """Normalize a user- or Excel-supplied material number to a clean string.

    Strips whitespace and a trailing ``.0`` float artefact ("600003822.0" →
    "600003822", BUGS.md M1/R2). Non-integer decimals are left untouched.
    """
    s = str(raw if raw is not None else '').strip()
    m = _FLOAT_KEY_RE.match(s)
    if m:
        return m.group(1)
    return s


def find_bom_cycle(parent_to_children: Dict[str, Iterable[str]]) -> Optional[List[str]]:
    """Find one BOM cycle, or None if the graph is acyclic.

    Iterative DFS with three-colour marking; iteration order is sorted so the
    result is deterministic. Returns the cycle as a path ``[a, b, ..., a]``.
    """
    WHITE, GREY, BLACK = 0, 1, 2
    colour: Dict[str, int] = {}
    graph = {p: sorted(set(children)) for p, children in parent_to_children.items()}

    for root in sorted(graph):
        if colour.get(root, WHITE) != WHITE:
            continue
        # Stack entries: (node, iterator index into its child list)
        stack: List[List] = [[root, 0]]
        colour[root] = GREY
        path = [root]
        while stack:
            node, idx = stack[-1]
            children = graph.get(node, [])
            if idx < len(children):
                stack[-1][1] += 1
                child = children[idx]
                c = colour.get(child, WHITE)
                if c == GREY:
                    # Back edge → cycle: slice the current path from child.
                    start = path.index(child)
                    return path[start:] + [child]
                if c == WHITE:
                    colour[child] = GREY
                    stack.append([child, 0])
                    path.append(child)
            else:
                colour[node] = BLACK
                stack.pop()
                path.pop()
    return None


def _fmt_cycle(cycle: List[str]) -> str:
    return ' → '.join(cycle)


def _as_float(value, field: str, minimum: float = 0.0,
              maximum: Optional[float] = None, allow_none: bool = False):
    if value is None or value == '':
        if allow_none:
            return None
        return 0.0
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'Ongeldige waarde voor {field}: "{value}" is geen getal.')
    if f < minimum:
        raise ValueError(f'Ongeldige waarde voor {field}: moet minimaal {minimum:g} zijn.')
    if maximum is not None and f > maximum:
        raise ValueError(f'Ongeldige waarde voor {field}: mag maximaal {maximum:g} zijn.')
    return f


def _known_material_numbers(data) -> Set[str]:
    """All material numbers the workbook knows: master + BOM endpoints."""
    known = set(data.materials.keys())
    for b in data.bom:
        known.add(b.parent_material)
        known.add(b.component_material)
    return known


def validate_added_product(product: dict, data=None, other_added: Iterable[dict] = (),
                           allow_numbers: Iterable[str] = ()) -> dict:
    """Normalize and validate one AddedProduct dict.

    ``data`` is a loaded DataLoader (skipped-checks mode when None, for pure
    shape tests). ``other_added`` are the OTHER overlay products (excluding
    this one), whose material numbers are valid BOM references.
    ``allow_numbers`` are numbers exempt from the workbook-collision check:
    routes validate against a LIVE engine whose data already contains the
    current overlay, so an edit of an existing added product must not be
    rejected as a collision with itself.
    Returns the sanitized dict; raises ValueError (Dutch) on invalid input.
    """
    if not isinstance(product, dict):
        raise ValueError('Ongeldig product: verwacht een object met productvelden.')

    mn = normalize_material_number(product.get('material_number'))
    if not mn:
        raise ValueError('Materiaalnummer is verplicht.')
    name = str(product.get('name') or '').strip()
    if not name:
        raise ValueError('Productnaam is verplicht.')
    ptype = str(product.get('product_type') or 'other').strip().lower()
    if ptype not in PRODUCT_TYPES:
        raise ValueError(
            f'Ongeldig producttype "{ptype}". Toegestaan: {", ".join(PRODUCT_TYPES)}.')

    other_numbers = {
        normalize_material_number(p.get('material_number'))
        for p in other_added if isinstance(p, dict)
    }
    if mn in other_numbers:
        raise ValueError(f'Materiaalnummer {mn} is al als dynamisch product toegevoegd.')

    known: Set[str] = set()
    if data is not None:
        known = _known_material_numbers(data)
        if mn in known and mn not in set(allow_numbers):
            raise ValueError(
                f'Materiaalnummer {mn} bestaat al in het bronbestand. '
                f'Kies een eigen nummerreeks (bijv. 9xxxxxxxx).')

    out = {
        'material_number': mn,
        'name': name,
        'product_type': ptype,
        'product_family': str(product.get('product_family') or '').strip(),
        'flat_volume': _as_float(product.get('flat_volume'), 'vast volume', allow_none=True),
        'starting_stock': _as_float(product.get('starting_stock'), 'startvoorraad'),
        'safety_stock': _as_float(product.get('safety_stock'), 'veiligheidsvoorraad'),
        'lead_time': int(_as_float(product.get('lead_time'), 'lead time') or 0),
        'moq': _as_float(product.get('moq'), 'MOQ'),
        'pap_fraction': _as_float(product.get('pap_fraction'), 'inkoop/productie-fractie',
                                  maximum=1.0, allow_none=True),
        'sales_price': _as_float(product.get('sales_price'), 'verkoopprijs'),
        'raw_material_cost': _as_float(product.get('raw_material_cost'), 'inkoopkost'),
        'default_inventory_value': _as_float(
            product.get('default_inventory_value'), 'voorraadwaarde'),
    }

    volumes = {}
    for period, val in (product.get('volumes') or {}).items():
        ps = str(period).strip()
        if not _PERIOD_RE.match(ps):
            raise ValueError(f'Ongeldige periode "{period}" bij volumes (verwacht JJJJ-MM).')
        volumes[ps] = _as_float(val, f'volume {ps}')
    out['volumes'] = volumes

    def _bom_rows(key: str, ref_field: str, label: str) -> List[dict]:
        rows = []
        for row in (product.get(key) or []):
            if not isinstance(row, dict):
                raise ValueError(f'Ongeldige {label}-rij: verwacht een object.')
            ref = normalize_material_number(row.get(ref_field))
            if not ref:
                raise ValueError(f'{label}: materiaalnummer ontbreekt.')
            if ref == mn:
                raise ValueError(
                    f'{label}: een product kan niet aan zichzelf gekoppeld worden ({mn}).')
            if data is not None and ref not in known and ref not in other_numbers:
                raise ValueError(
                    f'{label}: materiaal {ref} is onbekend '
                    f'(niet in het bronbestand en geen toegevoegd product).')
            qty = _as_float(row.get('qty_per'), f'{label} hoeveelheid per eenheid')
            if qty <= 0:
                raise ValueError(f'{label}: hoeveelheid per eenheid moet groter dan 0 zijn.')
            rows.append({ref_field: ref, 'qty_per': qty})
        return rows

    out['bom_as_parent'] = _bom_rows('bom_as_parent', 'component', 'Stuklijst (componenten)')
    out['bom_as_child'] = _bom_rows('bom_as_child', 'parent', 'Stuklijst (onderdeel van)')

    routing_rows = []
    for row in (product.get('routing') or []):
        if not isinstance(row, dict):
            raise ValueError('Ongeldige routing-rij: verwacht een object.')
        wc = str(row.get('work_center') or '').strip()
        if not wc:
            raise ValueError('Routing: machinecode ontbreekt.')
        if data is not None and wc not in data.machines:
            raise ValueError(
                f'Routing: machine "{wc}" bestaat niet. '
                f'Alleen bestaande machines zijn toegestaan.')
        base_qty = _as_float(row.get('base_quantity'), 'routing basisaantal')
        if base_qty <= 0:
            raise ValueError('Routing: basisaantal moet groter dan 0 zijn.')
        std_time = _as_float(row.get('standard_time'), 'routing standaardtijd')
        if std_time <= 0:
            raise ValueError('Routing: standaardtijd moet groter dan 0 zijn.')
        routing_rows.append({
            'work_center': wc, 'base_quantity': base_qty, 'standard_time': std_time,
        })
    out['routing'] = routing_rows

    return out


def _overlay_edges(added_products: List[dict]) -> List[tuple]:
    """All (parent, component) BOM edges the overlay would add."""
    edges = []
    for p in added_products:
        mn = normalize_material_number(p.get('material_number'))
        for row in (p.get('bom_as_parent') or []):
            edges.append((mn, normalize_material_number(row.get('component'))))
        for row in (p.get('bom_as_child') or []):
            edges.append((normalize_material_number(row.get('parent')), mn))
    return edges


def check_overlay_cycles(data, added_products: List[dict]) -> None:
    """Raise ValueError if the overlay's BOM edges introduce a cycle.

    Any cycle created by the overlay must pass through an added product (all
    overlay edges are incident to one), so it suffices to test whether each
    added product can reach itself over the combined edge set. Pre-existing
    workbook cycles are NOT an error here — they are warned about at load
    time (DataLoader.bom_cycle_warnings).
    """
    graph: Dict[str, Set[str]] = {}
    for b in data.bom:
        graph.setdefault(b.parent_material, set()).add(b.component_material)
    for parent, component in _overlay_edges(added_products):
        graph.setdefault(parent, set()).add(component)

    for p in added_products:
        mn = normalize_material_number(p.get('material_number'))
        # DFS from mn: can we get back to mn?
        stack = sorted(graph.get(mn, set()))
        seen: Set[str] = set()
        parent_of: Dict[str, str] = {c: mn for c in stack}
        while stack:
            node = stack.pop()
            if node == mn:
                # Reconstruct mn → ... → mn for the error message.
                path = [mn]
                cur = mn
                while True:
                    cur = parent_of[cur]
                    path.append(cur)
                    if cur == mn:
                        break
                path.reverse()
                raise ValueError(
                    f'Toegevoegd product {mn} veroorzaakt een BOM-cyclus: '
                    f'{_fmt_cycle(path)}. Pas de stuklijstkoppelingen aan.')
            if node in seen:
                continue
            seen.add(node)
            for child in sorted(graph.get(node, set())):
                if child not in seen:
                    parent_of.setdefault(child, node)
                    stack.append(child)


def apply_product_overlay(data, added_products: List[dict]) -> None:
    """Inject added products into a loaded DataLoader (STEP 1c).

    Validates everything and checks for cycles BEFORE mutating anything, so a
    bad overlay leaves the data untouched. Recomputes BOM levels afterwards —
    without that the level-by-level loop would never process the new
    materials.
    """
    if not added_products:
        return

    # -- Validate all products first (atomicity: no partial mutation). -------
    sanitized: List[dict] = []
    for i, product in enumerate(added_products):
        others = [p for j, p in enumerate(added_products) if j != i]
        sanitized.append(validate_added_product(product, data, other_added=others))
    check_overlay_cycles(data, sanitized)

    site = str(getattr(getattr(data, 'config', None), 'site', '') or '')
    added_numbers = {p['material_number'] for p in sanitized}
    name_by_number = {p['material_number']: p['name'] for p in sanitized}

    # -- Pass 1: register every material (so cross-references resolve). ------
    for p in sanitized:
        mn = p['material_number']
        ptype = ProductType.from_string(p['product_type'])
        data.materials[mn] = Material(
            material_number=mn,
            name=p['name'],
            product_type=ptype,
            product_family=p['product_family'],
            spc_product='',
            product_cluster='',
            product_name=p['name'],
            # Compound production-line / truck / control-room semantics are
            # workbook-only; added products never participate.
            production_line=None,
            grouped_production_line=None,
            mill_machine_group=None,
            packaging_machine_group=None,
            default_inventory_value=p['default_inventory_value'],
            is_active=True,
            product_type_raw=ptype.value,
        )

    # -- Pass 2: edges, routing, volumes, stock and financials. --------------
    for p in sanitized:
        mn = p['material_number']

        def _material_name(number: str) -> str:
            if number in name_by_number:
                return name_by_number[number]
            mat = data.materials.get(number)
            return mat.name if mat else ''

        for row in p['bom_as_parent']:
            comp = row['component']
            if comp not in data.materials and comp not in added_numbers:
                print(f'  >> WAARSCHUWING: overlay-component {comp} onbekend — rij overgeslagen')
                continue
            data.bom.append(BOMItem(
                plant=site, parent_material=mn, parent_name=p['name'],
                component_material=comp, component_name=_material_name(comp),
                quantity_per=row['qty_per'], bom_header_quantity=1.0,
            ))
        for row in p['bom_as_child']:
            parent = row['parent']
            if parent not in data.materials and parent not in added_numbers:
                print(f'  >> WAARSCHUWING: overlay-parent {parent} onbekend — rij overgeslagen')
                continue
            data.bom.append(BOMItem(
                plant=site, parent_material=parent, parent_name=_material_name(parent),
                component_material=mn, component_name=p['name'],
                quantity_per=row['qty_per'], bom_header_quantity=1.0,
            ))

        routing_items = []
        for row in p['routing']:
            wc = row['work_center']
            if wc not in data.machines:
                print(f'  >> WAARSCHUWING: overlay-machine {wc} onbekend — routing overgeslagen')
                continue
            routing_items.append(RoutingItem(
                plant=site, material=mn, material_description=p['name'],
                work_center=wc, base_quantity=row['base_quantity'],
                standard_time=row['standard_time'],
            ))
        if routing_items:
            data.routing.setdefault(mn, []).extend(routing_items)

        _inject_forecast(data, mn, p)

        if p['starting_stock']:
            data.stock_levels[mn] = p['starting_stock']
        # ALWAYS give the product a safety-stock entry: materials without BOM
        # edges are only processed by the standalone pass, which iterates
        # data.safety_stock (planning_engine STEP 4b).
        data.safety_stock[mn] = SafetyStockConfig(
            material_number=mn,
            safety_stock=p['safety_stock'],
            lot_size=0.0,
        )

        if p['lead_time']:
            data.purchase_lead_times[mn] = p['lead_time']
        if p['moq'] > 0:
            data.purchase_moq[mn] = p['moq']
            # InventoryEngine only applies the MOQ ceiling for materials that
            # are member of the purchase sheet.
            data.purchase_sheet_materials.add(mn)
        if p['pap_fraction'] is not None:
            data.purchased_and_produced[mn] = p['pap_fraction']

        if p['sales_price'] > 0:
            data.sales_prices[mn] = SalesPriceItem(
                plant_code=site, product_id=mn,
                volume_2025=1.0, ex_works_revenue=p['sales_price'],
            )
        if p['raw_material_cost'] > 0:
            data.material_costs[mn] = RawMaterialCost(
                plant_code=site, product_code=mn, product_name=p['name'],
                cost_per_unit=p['raw_material_cost'],
            )

    # -- BOM levels are computed once in load_all(); recompute so the new
    #    materials get a level and the level loop stays topologically correct.
    data._calculate_bom_levels()
    print(f'  >> Product overlay: {len(sanitized)} toegevoegd(e) product(en) geïnjecteerd')


def _inject_forecast(data, mn: str, p: dict) -> None:
    """Write the product's volumes into data.forecasts using the same anchor
    math ForecastEngine reads with (planning period i ← anchor + i months)."""
    periods = list(getattr(data, 'periods', []) or [])
    if not periods:
        return
    volumes = p.get('volumes') or {}
    flat = p.get('flat_volume')
    if not volumes and flat is None:
        return  # no demand: product participates via BOM / safety stock only

    actuals = int(getattr(data, 'forecast_actuals_months', 0) or 0)
    first = getattr(data, 'forecast_first_period', None)
    fdict = data.forecasts.setdefault(mn, {})
    if first:
        anchor = ForecastEngine._offset_period(str(first), actuals + 1)
    else:
        # No forecast sheet anchor: force the per-material fallback (sorted
        # keys → first key) to derive periods[0] as the anchor by planting a
        # zero on the key months_actuals+1 BEFORE the first planning period.
        anchor = periods[0]
        fdict.setdefault(ForecastEngine._offset_period(anchor, -(actuals + 1)), 0.0)

    for i, period in enumerate(periods):
        value = volumes.get(period, flat if flat is not None else 0.0)
        fdict[ForecastEngine._offset_period(anchor, i)] = float(value or 0.0)
