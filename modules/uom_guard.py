"""
S&OP Planning Engine - UoM Guard
Detects unit-of-measure mismatches in BOM data (kg-dosed components in
ton-based recipes) and applies user-confirmed conversion overrides.

Background: the SAP BOM extract carries no component UoM column. SAP stores
component quantities in the component's own base unit, so a kg-managed
additive lands in a ton-based recipe with a quantity ~1000x too large. The
June 2026 Winterswijk cycle turned three additives (a few kg per ton of
slurry) into hundreds of tons of monthly demand and a -9.1M EUR inventory
consolidation. This module makes that class of error detectable and
correctable at load time.

Detection is heuristic and NEVER auto-applies: suspects are surfaced for the
user to confirm. Confirmed factors persist per site (ui/uom_store.py) and are
applied on every subsequent load, so re-pasting the same extract next month
is safe without re-confirmation.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from modules.models import BOMItem

# A recipe whose component mass ratios sum above this is suspect: one ton of
# product cannot take much more than one ton of ingredients. Some slack is
# left for yield loss and piece-goods components (pallets, containers) that
# legitimately ride on top of the mass balance.
SUSPECT_TOTAL = 1.5

# Below this the imbalance is too mild to point at a component: kg-entered
# lines are ~1000x oversized and blow recipes far past 2x output, while
# totals in the 1.5-2x band are more often odd-but-real recipes (yield
# loss, blends). Those get a recipe warning, never component suspects.
FLAG_TOTAL = 2.0

# The greedy reclassification stops once the remaining total drops to this
# bound (recipes with real yield loss sit slightly above 1.0).
TARGET_UPPER = 1.35

# Never reclassify a component when doing so would drop the recipe total
# below this bound: that would mean flagging the bulk of the recipe itself,
# which is exactly the false positive users must never see.
TARGET_LOWER = 0.5

# kg -> ton
DEFAULT_FACTOR = 0.001

# Component-UoM handling when the extract DOES carry a unit column
# (BOMItem.component_uom). Mass units convert to tons at load time and are
# trusted afterwards; anything else (PC, ST, PAL, ...) is a piece good that
# rides on top of the mass balance and never participates in it.
MASS_UNIT_FACTORS = {
    'TO': 1.0, 'T': 1.0, 'TON': 1.0,
    'KG': 0.001,
    'G': 0.000001,
}


@dataclass
class SuspectRecipe:
    """One recipe (parent + production version) a component is suspect in."""
    parent_material: str
    parent_name: str
    production_version: Optional[str]
    ratio: float             # component qty per 1 header unit, as loaded
    converted_ratio: float   # same after applying the proposed factor

    def to_dict(self) -> dict:
        return {
            'parent_material': self.parent_material,
            'parent_name': self.parent_name,
            'production_version': self.production_version,
            'ratio': self.ratio,
            'converted_ratio': self.converted_ratio,
        }


@dataclass
class UomSuspect:
    """A component suspected of being in kg while the recipe is in tons."""
    component_material: str
    component_name: str
    proposed_factor: float
    recipes: List[SuspectRecipe] = field(default_factory=list)

    @property
    def max_ratio(self) -> float:
        return max((r.ratio for r in self.recipes), default=0.0)

    def to_dict(self) -> dict:
        return {
            'component_material': self.component_material,
            'component_name': self.component_name,
            'proposed_factor': self.proposed_factor,
            'max_ratio': self.max_ratio,
            'recipes': [r.to_dict() for r in self.recipes],
        }


@dataclass
class RecipeWarning:
    """A recipe whose mass balance stays implausible even after
    reclassification. Surfaced so an undetectable mismatch is at least
    visible instead of silently wrong."""
    parent_material: str
    parent_name: str
    production_version: Optional[str]
    total_ratio: float
    residual_ratio: float

    def to_dict(self) -> dict:
        return {
            'parent_material': self.parent_material,
            'parent_name': self.parent_name,
            'production_version': self.production_version,
            'total_ratio': self.total_ratio,
            'residual_ratio': self.residual_ratio,
        }


# One recipe = one (plant, parent, production version, BOM number,
# alternative): a parent may carry several alternative BOMs under one
# production version, and each alternative must balance on its own. Plant is
# part of the key because rows with a BLANK plant cell pass the site filter
# and must not merge into another plant's recipe totals.
RecipeKey = Tuple[str, str, Optional[str], Optional[str], Optional[str]]


def _recipe_key(item: BOMItem) -> RecipeKey:
    return (item.plant, item.parent_material, item.production_version,
            item.bill_of_material, item.alternative_bom)


def _bucket_recipes(
    bom: List[BOMItem],
    piece_components: Optional[set] = None,
) -> Tuple[Dict[RecipeKey, List[BOMItem]], Dict[RecipeKey, float], Dict[RecipeKey, float]]:
    """Split BOM rows into heuristic candidates, trusted mass, and output mass.

    Coproducts count toward the OUTPUT side of the balance: a sieve-residue
    recipe consuming 6.67 t input for 1 t product + 5.67 t coproduct is in
    balance, not suspect. Rows with a known component UoM are authoritative:
    mass units count toward the input balance but are never suspects (the
    loader already converted them); piece units (PC, ST, PAL, ...) stay
    outside the mass balance entirely. `piece_components` extends that piece
    treatment to components the MATERIAL MASTER marks as packaging goods —
    big bags and pallets legitimately ride along at 1-2 per ton and would
    otherwise both trip the balance and get falsely flagged.
    """
    piece_components = piece_components or set()
    recipes: Dict[RecipeKey, List[BOMItem]] = {}
    trusted: Dict[RecipeKey, float] = {}
    outputs: Dict[RecipeKey, float] = {}
    for item in bom:
        key = _recipe_key(item)
        if item.is_coproduct or item.quantity_per <= 0:
            outputs[key] = outputs.get(key, 0.0) + abs(item.quantity_per)
            continue
        if item.component_material in piece_components:
            continue
        if item.component_uom:
            unit = str(item.component_uom).strip().upper()
            if unit in MASS_UNIT_FACTORS:
                trusted[key] = trusted.get(key, 0.0) + item.quantity_per
            continue
        recipes.setdefault(key, []).append(item)
    return recipes, trusted, outputs


def _flag_recipe(
    items: List[BOMItem],
    trusted_mass: float,
    target_upper: float,
    target_lower: float,
    proposed_factor: float,
) -> Tuple[List[BOMItem], float]:
    """Pick the components that, converted, make the recipe plausible.

    Reclassifies the largest contributors first: kg-entered lines are by
    construction ~1000x oversized, so they dominate the total. Stops as soon
    as the remaining balance is plausible so genuine bulk components are
    never reached. Returns (flagged items, remaining total).
    """
    remaining = trusted_mass + sum(i.quantity_per for i in items)
    flagged: List[BOMItem] = []
    for item in sorted(items, key=lambda i: i.quantity_per, reverse=True):
        if remaining <= target_upper:
            break
        after = remaining - item.quantity_per + item.quantity_per * proposed_factor
        if after < target_lower:
            # Removing this line would gut the recipe; it is the bulk.
            continue
        if item.quantity_per <= target_upper and after > target_upper:
            # A small, individually-plausible line whose conversion does not
            # even make the recipe plausible is genuine bulk riding inside an
            # unresolvable recipe — flagging it would be the false positive
            # this function promises to avoid.
            continue
        remaining = after
        flagged.append(item)
    return flagged, remaining


def analyze_bom(
    bom: List[BOMItem],
    suspect_total: float = SUSPECT_TOTAL,
    flag_total: float = FLAG_TOTAL,
    target_upper: float = TARGET_UPPER,
    target_lower: float = TARGET_LOWER,
    proposed_factor: float = DEFAULT_FACTOR,
    piece_components: Optional[set] = None,
) -> Tuple[List[UomSuspect], List[RecipeWarning]]:
    """Scan BOM recipes for unit-of-measure suspects.

    Returns (suspects, warnings). Suspects are aggregated per component
    (an override is a property of the material, not of one recipe), each
    carrying the recipes it was flagged in. Warnings list recipes whose
    mass balance remains implausible after reclassification.

    The balance is judged against the recipe's OUTPUT mass: 1 header unit
    plus coproduct quantities. All thresholds scale with that output.
    """
    recipes, trusted, outputs = _bucket_recipes(bom, piece_components)
    suspects: Dict[str, UomSuspect] = {}
    warnings: List[RecipeWarning] = []

    for key, items in recipes.items():
        parent, pv = key[1], key[2]
        output = 1.0 + outputs.get(key, 0.0)
        total = trusted.get(key, 0.0) + sum(i.quantity_per for i in items)
        if total <= suspect_total * output:
            continue

        if total <= flag_total * output:
            # Too mild to point at a component: warn about the recipe and
            # leave the numbers alone.
            warnings.append(RecipeWarning(
                parent_material=parent,
                parent_name=items[0].parent_name if items else '',
                production_version=pv,
                total_ratio=total,
                residual_ratio=total,
            ))
            continue

        flagged, remaining = _flag_recipe(
            items, trusted.get(key, 0.0),
            target_upper * output, target_lower * output, proposed_factor)

        for item in flagged:
            suspect = suspects.setdefault(item.component_material, UomSuspect(
                component_material=item.component_material,
                component_name=item.component_name,
                proposed_factor=proposed_factor,
            ))
            suspect.recipes.append(SuspectRecipe(
                parent_material=parent,
                parent_name=item.parent_name,
                production_version=pv,
                ratio=item.quantity_per,
                converted_ratio=item.quantity_per * proposed_factor,
            ))

        if remaining > suspect_total * output:
            warnings.append(RecipeWarning(
                parent_material=parent,
                parent_name=items[0].parent_name if items else '',
                production_version=pv,
                total_ratio=total,
                residual_ratio=remaining,
            ))

    ordered = sorted(suspects.values(), key=lambda s: s.max_ratio, reverse=True)
    return ordered, warnings


def apply_uom_overrides(
    bom: List[BOMItem], overrides: Dict[str, float]
) -> List[Tuple[str, float, int]]:
    """Multiply quantity_per by the confirmed factor for matching components.

    Mutates the BOMItem list in place (before any engine consumes it).
    Returns [(component, factor, rows_affected)] for reporting. Components
    without BOM rows this cycle simply report zero rows — the override
    stays stored for when they return.
    """
    applied: List[Tuple[str, float, int]] = []
    for component, factor in overrides.items():
        if not factor or factor == 1:
            continue
        count = 0
        for item in bom:
            if item.component_material != component:
                continue
            # Rows with an authoritative mass UoM were already converted at
            # load time; applying the stored factor again would shrink the
            # dose another 1000x the month the extract gains a UoM column.
            if item.component_uom and str(item.component_uom).strip().upper() in MASS_UNIT_FACTORS:
                continue
            item.quantity_per *= factor
            count += 1
        applied.append((component, factor, count))
    return applied
