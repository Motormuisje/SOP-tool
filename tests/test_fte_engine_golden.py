"""Werkbank tegen de golden fixture: additiviteit en L12-pariteit.

Slaat over zonder SOP_GOLDEN_FIXTURE (zie tests/README.md). Deze twee
eigenschappen zijn de kern van Fase A: de werkbank verandert geen enkel
bestaand planningsgetal, en zonder bemensingsnormen reproduceert hij Line 12
exact — inclusief trucks en controlekamer.
"""

import pytest

from modules.fte_engine import CATEGORY_GROUP, CATEGORY_MACHINE, FteEngine
from modules.models import LineType


def test_workbench_adds_no_line_type(planning_engine_result):
    engine = planning_engine_result
    assert set(engine.results) == set(engine.EXPECTED_LINE_TYPES)
    assert engine.fte_results is not None
    assert engine.fte_results.periods == engine.data.periods


def test_direct_fte_reproduces_line_12(planning_engine_result):
    """Zonder staffing_norms valt elke groep terug op de L12-coëfficiënt, dus
    het totaal moet per periode gelijk zijn aan de som van Line 12."""
    engine = planning_engine_result
    assert not (getattr(engine.data, 'staffing_norms', None) or {}), \
        'deze pariteitstest gaat over de situatie zonder bemensingsnormen'

    l12_rows = engine.results[LineType.FTE_REQUIREMENTS.value]
    result = engine.fte_results
    for period in engine.data.periods:
        expected = sum(row.values.get(period, 0.0) for row in l12_rows)
        # approx: dezelfde termen, andere optelvolgorde (groep-voor-groep vs
        # rij-voor-rij) — het verschil zit in het 16e cijfer.
        assert result.total_direct_fte[period] == pytest.approx(expected), (
            f'afwijking in {period}')


def test_machine_rows_are_detail_only(planning_engine_result):
    result = planning_engine_result.fte_results
    machines = [line for line in result.lines if line.category == CATEGORY_MACHINE]
    groups = [line for line in result.lines if line.category == CATEGORY_GROUP]

    assert machines and groups
    assert all(line.counts_in_total is False for line in machines)
    for period in result.periods:
        assert result.total_fte[period] == pytest.approx(
            sum(g.fte[period] for g in groups))


def test_recalculating_the_workbench_does_not_touch_planning_rows(planning_engine_result):
    engine = planning_engine_result
    before = {lt: [dict(row.values) for row in rows]
              for lt, rows in engine.results.items()}

    FteEngine(engine.data, engine.results, value_results=engine.value_results).calculate()

    after = {lt: [dict(row.values) for row in rows]
             for lt, rows in engine.results.items()}
    assert after == before
