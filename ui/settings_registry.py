"""Declaratieve registry van configuratie-instellingen (Config-tab, C2).

Eén bron van waarheid per instelling: sleutel, label, tooltip, type, scope,
effect en hoe hij gerenderd/afgehandeld wordt. De Config-tab-API levert
hieruit metadata (`/api/config` → `settings_meta`), de POST-route handelt
velden met `handler='generic'` volledig registry-gedreven af, en de
frontend rendert die velden automatisch — een nieuwe instelling toevoegen
is één `Setting(...)`-regel.

Velden met `handler='legacy'` worden (nog) door de handgeschreven keten in
`ui/routes/config.py` + `ui/engine_rebuild.py` verwerkt; ze staan hier al
wel zodat de UI-metadata (labels, effecten, scope) één bron heeft. Migratie
naar 'generic' gebeurt per veld (zie docs/plan-config-tab-herinrichting.md).

Scope-betekenis:
- 'session': hoort bij de actieve instantie en reist mee met de sessie.
- 'installation': geldt voor alle instanties op deze installatie.

Effect-betekenis (wat er gebeurt bij opslaan met een gewijzigde waarde):
- 'rebuild': volledige herbouw van de actieve instantie.
- 'recalc': gerichte herberekening (bv. PAP-materialen).
- 'value': alleen financiële herberekening.
- 'none': geen herberekening nodig.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class Setting:
    key: str
    group: str            # 'planning' | 'valuation' | ...
    scope: str            # 'session' | 'installation'
    type: str             # 'text' | 'number' | 'bool' | 'composite'
    label: str
    tooltip: str
    effect: str           # 'rebuild' | 'recalc' | 'value' | 'none'
    handler: str = 'legacy'   # 'legacy' | 'generic'
    default: object = None
    placeholder: str = ''

    def coerce(self, value):
        """Coerce een POST-waarde naar het registry-type; ValueError bij rommel."""
        if self.type == 'bool':
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in ('1', 'true', 'ja', 'on', 'yes')
        if self.type == 'number':
            if value in (None, ''):
                return None
            return float(value)
        if self.type == 'text':
            return str(value or '').strip()
        raise ValueError(f'Setting {self.key}: type {self.type} niet generiek te verwerken')


REGISTRY: List[Setting] = [
    # --- Planning (sessie) — legacy-afgehandeld, metadata voor de UI ---
    Setting('site', 'planning', 'session', 'text',
            'Site', 'SAP-plantcode waarmee financiële data wordt gefilterd.',
            effect='rebuild'),
    Setting('forecast_months', 'planning', 'session', 'number',
            'Forecast horizon (maanden)', 'Aantal maanden planningshorizon.',
            effect='rebuild'),
    Setting('unlimited_machines', 'planning', 'session', 'text',
            'Unlimited capacity machines', 'Machinecodes die nooit bottleneck zijn.',
            effect='rebuild'),
    Setting('purchased_and_produced', 'planning', 'session', 'text',
            'Purchased & produced materials', 'materiaal:productiefractie, komma-gescheiden.',
            effect='recalc'),
    Setting('forecast_defaults', 'planning', 'session', 'composite',
            'Forecast standaardvolumes', 'Standaardvolumes voor lege of alle perioden.',
            effect='rebuild'),
    Setting('valuation_params', 'valuation', 'session', 'composite',
            'Valuation parameters', 'De acht waarderingsparameters.',
            effect='value'),

    # --- Generiek afgehandelde velden: registry is de volledige keten ---
    Setting('forecast_align_to_month', 'planning', 'installation', 'bool',
            'Forecast op kalendermaand',
            'Aan (standaard): Line 01 draagt de forecast van zijn eigen '
            'kalendermaand. Uit: positionele VBA-kopie — alleen voor het '
            'cel-voor-cel reproduceren van een klantwerkboek tijdens '
            'validatie (parallelle runs); kan Line 01 een maand verschuiven.',
            effect='rebuild', handler='generic', default=True),
]


def generic_settings() -> List[Setting]:
    return [s for s in REGISTRY if s.handler == 'generic']


def get_setting(key: str) -> Optional[Setting]:
    return next((s for s in REGISTRY if s.key == key), None)


def settings_meta(global_config: dict) -> list:
    """JSON-metadata + huidige waarden voor de frontend-rendering."""
    meta = []
    for s in REGISTRY:
        value = global_config.get(s.key, s.default)
        if s.key == 'valuation_params':
            value = global_config.get('valuation_params') or {}
        meta.append({
            'key': s.key,
            'group': s.group,
            'scope': s.scope,
            'type': s.type,
            'label': s.label,
            'tooltip': s.tooltip,
            'effect': s.effect,
            'handler': s.handler,
            'default': s.default,
            'placeholder': s.placeholder,
            'value': value,
        })
    return meta


def apply_generic_settings(data: dict, global_config: dict) -> List[str]:
    """Verwerk generiek-afgehandelde velden uit een POST-payload.

    Schrijft gewijzigde waarden naar global_config en geeft de effecten van
    de wijzigingen terug (voor de structurele-rebuild-beslissing van de
    route). Ongeldige waarden geven ValueError met de veldnaam."""
    effects: List[str] = []
    for s in generic_settings():
        if s.key not in data:
            continue
        try:
            new_value = s.coerce(data[s.key])
        except (TypeError, ValueError) as exc:
            raise ValueError(f'Ongeldige waarde voor {s.label}: {data[s.key]!r}') from exc
        old_value = global_config.get(s.key, s.default)
        if new_value != old_value:
            global_config[s.key] = new_value
            effects.append(s.effect)
    return effects
