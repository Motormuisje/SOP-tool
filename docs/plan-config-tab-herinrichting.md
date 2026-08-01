# Plan: herinrichting Config-tab

Status: voorstel (2026-07-28). Doel: de Config-tab overzichtelijk maken voor
gebruikers ÉN het toevoegen/aanpassen van instellingen goedkoop maken voor
ontwikkelaars. Hangt samen met het Excel-onafhankelijkheidsplan (F3-legacy-
opruiming landt hier als fase C3).

---

## 1. Diagnose — wat er nu staat en waarom het knelt

De tab heeft zes kaarten in twee secties (`ui/templates/index.html` vanaf
`id="config-tab"`, r1374):

| # | Kaart | Sectie | Opslaan via |
|---|---|---|---|
| 1 | Planning Configuratie (site, horizon, unlimited machines, PAP, forecast-defaults) | actieve instantie | gezamenlijke knop onder kaart 2 |
| 2 | Valuation Parameters (8 velden + reset) | actieve instantie | zelfde knop |
| 3 | Dynamische producten (+ Product toevoegen) | actieve instantie | eigen modal |
| 4 | Masterdata (in app): import, status, grids, werkboek-export/-import, spiegel | app-breed | direct per actie |
| 5 | Master Data File (legacy) + "→ Importeer naar app" | app-breed | direct |
| 6 | Mappen (uploads/exports/sessies) | app-breed | eigen knop |

De vier structurele problemen:

1. **Scope is onzichtbaar.** Per-instantie en installatie-brede instellingen
   staan visueel gelijkwaardig naast elkaar. Welke wijziging geldt voor welke
   sessie, en wat een sessiewissel doet met wat je ziet, is nergens
   uitgelegd. (De global-config-spiegel is precies de plek waar historisch de
   meeste bugs zaten — zie docs/ontwikkelhandleiding.md "state model".)
2. **Effect is onzichtbaar.** Site/horizon wijzigen triggert een volledige
   herbouw; valuation-params alleen een waardeherberekening; forecast-
   defaults een rebuild. De gebruiker ziet één "Opslaan" en merkt pas aan de
   wachttijd wat er gebeurde. Drie verschillende opslaan-mechanismen (knop
   kaart 1+2, knop kaart 6, direct bij kaart 4/5) zonder logica.
3. **Dubbelingen en verdwaalde instellingen.** PAP heeft een veld in kaart 1
   én een eigen modal in de Planning-toolbar. UoM-conversiebeheer (ook
   installatie-breed) woont alleen in de Planning-toolbar. Twee master-
   kaarten (app + legacy) beconcurreren elkaar — de kleine lettertjes moeten
   het verschil uitleggen. Kaart 3 (producten) is geen configuratie maar
   scenario-inhoud.
4. **Toevoegen is duur.** Eén nieuwe instelling = HTML-kaart bewerken +
   `loadConfigTab` + `saveConfigSettings` + `/api/config` GET én POST +
   `global_config`-persistentie + `get_config_overrides` + evt. de zes
   syncpunten. Daarom heeft `forecast_align_to_month` nu wél een override-
   keten maar géén UI-toggle: de drempel ligt te hoog.

## 2. Doelbeeld

### 2.1 Drie zichtbare lagen

```
┌─ DEZE INSTANTIE ──────────────────────────────── [badge: sessienaam] ─┐
│  Planning        site · horizon · uitlijning · unlimited machines    │
│  Financieel      valuation-params · PAP (één plek)                   │
│  Forecast        standaardvolumes                                    │
├─ DEZE INSTALLATIE (site) ─────────────── [badge: alle instanties] ───┤
│  Masterdata      één kaart: bron+versie · werkboek · grids · spiegel │
│  Datakwaliteit   UoM-conversies (beheer) · consistentie-instellingen │
│  Opslag          mappen                                              │
├─ SYSTEEM ────────────────────────────────────────────────────────────┤
│  versie-info · opslaglocaties · diagnose                             │
└──────────────────────────────────────────────────────────────────────┘
```

Elke kaart draagt een scopebadge ("deze instantie" / "alle instanties") en
een effectlabel ("wijziging → volledige herberekening" / "→ alleen
financiën" / "→ geldt bij volgende berekening").

### 2.2 Eén opslagmodel

- Dirty-state per veld; één zwevende opslagbalk verschijnt zodra er
  wijzigingen zijn: "3 wijzigingen · herberekening nodig · [Opslaan]
  [Verwerpen]". De balk somt het zwaarste effect op, zodat niemand verrast
  wordt door een lange rebuild.
- Installatie-brede acties (masterdata-import, mappen) blijven direct-met-
  bevestiging, maar krijgen hetzelfde visuele patroon (actieknop op de
  kaart, resultaat als statusregel op de kaart).

### 2.3 Settings-registry — de kern voor "makkelijk toevoegen"

Eén declaratieve bron van waarheid, `ui/settings_registry.py`:

```python
SETTINGS = [
    Setting(
        key='site',                       # global_config / override-key
        group='planning',                 # kaart
        scope='session',                  # session | installation
        type='text',                      # text|number|bool|money|list|select
        label='Site', tooltip='SAP-plantcode…',
        effect='full-rebuild',            # none|value-recalc|full-rebuild
        default_from='file_defaults.site',# waar de defaultwaarde vandaan komt
        validator=r'^[A-Z]{2}[A-Z0-9]{2}$',
    ),
    Setting(key='forecast_align_to_month', group='planning', scope='session',
            type='bool', effect='full-rebuild',
            label='Forecast op kalendermaand',
            tooltip='Uit = positionele VBA-modus (alleen voor validatie)'),
    ...
]
```

Wat de registry aandrijft:

1. **Backend**: `/api/config` GET en POST worden generiek — GET levert per
   veld `{value, default, overridden, effect, scope}`; POST valideert via de
   registry en weet per veld welk effect getriggerd moet worden (de
   bestaande `structural_config_changed`-logica in `ui/routes/config.py`
   verdwijnt als handgeschreven lijst en volgt de registry).
2. **Override-keten**: `get_config_overrides` loopt over registry-velden met
   scope `session` in plaats van de handgeschreven if-reeks in
   `ui/engine_rebuild.py:8-35`. Een nieuw veld doet automatisch mee met
   rebuilds, sessiewissel en persistentie — het zes-syncpunten-risico wordt
   een registry-eigenschap in plaats van een checklist.
3. **Frontend**: één renderfunctie bouwt de kaarten uit `/api/config`-
   metadata (label, tooltip, type, badge, effectlabel, override-indicator
   met "reset naar default"-knopje per veld). Nieuw veld toevoegen = één
   registry-regel, nul regels HTML/JS.
4. **Tests**: één parametrische test die voor élk registry-veld controleert:
   GET toont het, POST persisteert het, override-keten past het toe na
   rebuild, en het juiste effect vuurt. Nieuwe velden zijn automatisch
   gedekt.

Eerste bewijslast: `forecast_align_to_month` als UI-toggle via de registry
(heeft de hele keten al, mist alleen UI — precies het gat dat het huidige
model liet vallen).

## 3. Opruimingen die met de herindeling meekomen

- **Master-kaarten samenvoegen** (= F3 uit het Excel-onafhankelijkheidsplan):
  één kaart "Masterdata" met bronstatus (store-versie, importdatum,
  spiegelstatus), werkboek-export/-import, dataset-grids. De legacy
  "Master Data File"-kaart verdwijnt; de file-defaults-adoptflow verhuist
  naar de store-import (defaults worden bij import aangeboden).
- **PAP-ontdubbeling**: het veld verdwijnt uit de kaart; de bestaande
  PAP-modal wordt de enige editor en is vanaf beide plekken (toolbar én
  Financieel-kaart) te openen.
- **UoM-beheer krijgt een kaart** onder "Datakwaliteit": actieve conversies,
  afgewezen verdachten, verwijderknoppen — zelfde data als de bestaande
  modal, maar vindbaar zonder dat er een verdachte open hoeft te staan.
- **Producten-kaart verhuist** uit Config naar de Planning-tab (of krijgt
  minimaal het label "Scenario-inhoud — geen configuratie") zodat de
  Config-tab puur instellingen bevat.
- **Walkthrough en teksten** bijwerken op de nieuwe indeling.

## 4. Fasering

| Fase | Inhoud | Karakter |
|---|---|---|
| C1 | Herindeling in drie lagen, scopebadges, effectlabels, dirty-state-opslagbalk | puur UI, geen gedragswijziging; grootste zichtbare winst |
| C2 | Settings-registry backend + frontend; bestaande velden migreren; `/api/config` generiek (backward compatible); `forecast_align_to_month`-toggle als bewijs | de structurele investering |
| C3 | Master-kaarten samenvoegen (F3), PAP-ontdubbeling, UoM-kaart, producten verhuizen | opruiming, deels afhankelijk van C2 |
| C4 | Per-veld override-reset, zoek/filterveld, inline validatiefouten | polijst |

Volgorde-rationale: C1 kan vandaag en maakt de tab direct leesbaar; C2 is de
investering die elke volgende instelling goedkoop maakt; C3 wacht bewust op
C2 zodat de samengevoegde masterkaart meteen in het registry-patroon landt.

## 5. Randvoorwaarden en risico's

- **API-compatibiliteit**: `/api/config` behoudt bestaande sleutels naast de
  nieuwe metadata-vorm tot de site-edities gesynct zijn; `test_routes_config`
  moet groen blijven tijdens de migratie.
- **De zes syncpunten** (docs/ontwikkelhandleiding.md): de registry vervángt de handgeschreven
  keten niet in één klap — per veld migreren, met de parametrische test als
  vangnet. Velden die nog niet gemigreerd zijn blijven op het oude pad.
- **Site-edities**: index.html is huisstijlbestand; wijzigingen gaan als
  patch naar SOP-WSK/SOP-ANK, klassennamen blijven ongewijzigd (purged
  Tailwind-builds). Geen nieuwe Tailwind-klassen gebruiken die niet in de
  vendor-build zitten; bij twijfel inline styles zoals de bestaande modals.
- **Geen gedragswijziging in C1**: alleen verplaatsen en labelen; elke
  numerieke uitkomst blijft identiek. Rekenlogica raakt dit plan nergens.

## 6. Definition of done per fase

- C1: elke kaart heeft scopebadge + effectlabel; er is één opslagbalk; een
  screenshotvergelijking oud/nieuw zit bij de PR.
- C2: een nieuw registry-veld toevoegen kost aantoonbaar één regel (demo:
  `forecast_align_to_month`); de parametrische test dekt alle velden.
- C3: er is nog precies één masterdata-ingang in de UI; PAP heeft één
  editor; grep op `master_file` in index.html levert nul UI-elementen.
- C4: elk overschreven veld toont een reset; zoekveld filtert kaarten live.
