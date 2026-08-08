# Plan — werkbank: alles aanpasbaar, met SAP/MES als populatie

**Site-scope: uitsluitend Maastricht (NLX1).** Machinevolgorde wisselen is een
aparte vervolgtaak ná goedkeuring van de werkbank en staat hier bewust niet in.

Dit plan verving op 2026-08-06 een eerdere versie, na een richtlijn van de
klant die het ontwerp fundamenteel kantelt:

> "In feite moeten alle getallen aanpasbaar zijn; neem SAP/MES-data echt
> enkel als populeren van de data."

## 1. Eerste principe: alles aanpasbaar — import is populatie

SAP-routing, MES-metingen en PEER-cijfers zijn **beginwaarden**: ze vullen de
masterdata, daarna is de masterdata — volledig bewerkbaar — de werkelijkheid
waarmee gerekend wordt. Dit is dezelfde beweging die eerder met materialen en
prijzen is gemaakt (werkboek → app-masterdata als bron van waarheid), nu
consequent doorgetrokken naar alle capaciteits- en FTE-getallen.

Drie regels houden dit eerlijk:

1. **Geen dood getal.** Elk getal dat de werkbank toont heeft een invulpad:
   inline met write-through naar de masterdata-PATCH (zoals de
   bemensingsnormen al werken: base_version, 409 bij conflict), of één klik
   naar het juiste masterdata-grid.
2. **Invullen is een zichtbare handeling.** Elke invulling draagt een
   bronlabel (import / handmatig / MES overgenomen / …) en de beginwaarde
   blijft ernaast zichtbaar. Niets telt *stil* mee of *stil* niet mee — dat
   deel van de oude doctrine staat onverkort.
3. **Een invulling werkt overal door.** Eén getal, één waarheid: wat de
   planner invult telt in de héle keten (capaciteit, planning, FTE, waarde),
   niet alleen in het paneel waar hij het intypte. Import overschrijft nooit
   een klantbewerking (bestaand merge-gedrag van de store, nu de regel voor
   alles).

## 2. Wat de inventaris vond (geverifieerd, met bestand:regel in het rapport)

De doorlichting van alle werkbankgetallen, alle masterdata-grids en de
enginedoorwerking leverde drie structurele bevindingen op:

1. **De doorzet-override rekent maar half mee.** `throughput_overrides` is
   invulbaar (grid mét bronlabelveld) en de FTE-motor past hem toe, maar
   `capacity_engine` gebruikt hem nérgens: planning, Line 07-uren, bezetting
   en bottlenecks blijven op de SAP-routing rekenen. Hetzelfde getal heeft
   twee waarheden — strijdig met regel 3.
2. **Het getal waarmee gerekend wordt is onzichtbaar.** De SAP-doorzet
   (routing AUX2) staat nergens in de app; `FteLine.throughput_norm` is een
   dood veld (gedeclareerd, geserialiseerd, nooit gevuld) en
   `throughput_source` wordt nergens gerenderd. De planner ziet MES/PEER
   naast een norm die er niet staat, en een actieve override is in de
   werkbank onzichtbaar — een getal dat stil meetelt.
3. **Een reeks invulpaden ontbreekt of loopt dood.** Machines (en hun
   kosten) zijn niet toe te voegen in de app; ploegvensters niet aan te
   maken; machine-detailvelden (`shift_hours_override`,
   `availability_by_period`) onbereikbaar; 15 van de ~18 materiaalvelden na
   aanmaak niet meer bewerkbaar; purchase actuals bevroren op de importmaand;
   de bruto→netto-FTE-velden (ziekte%, verlof, ADV) zijn invulbaar maar
   rekenen nergens in door; een lege getalcel wordt bij opslaan stil 0; een
   regel zonder loontarief rekent stil met €0.

## 3. Fase 1 — nu: presenteren + bestaande invulpaden ontsluiten

Geen enginewerk; de bestaande datasets en het write-through-stramien volstaan.

| # | Element | Invulpad |
|---|---|---|
| 1 | **Knelpuntenmatrix** (benuttingsheatmap groep × periode) onder de KPI's; celklik zet periodefilter en scrolt naar de groep; toont altijd de hele horizon | leeswerk (afgeleide ratio, bewust niet invulbaar — stuur via uren/normen) |
| 2 | **Piek naast gemiddelde** op de KPI-tegels, piekmaand klikbaar; plus **aggregatie-sublabels** ("gem. per periode" / "som over horizon" / periodenaam) | leeswerk |
| 3 | **Periodebereik-presets**, standaard "komende 3 maanden" | leeswerk |
| 4 | **Aanname-chips zijn invulvelden.** De amber "aanname 1,0"-chip op `operators_source='default'` opent direct de bestaande inline normcel; het telkaartje "n regels rekenen op een aanname" filtert erop | inline (bestaand write-through) |
| 5 | **Doorzetkolom die de waarheid toont**: per machineregel de doorzet waarmee gerekend wordt + bronchip (SAP-routing / override met bron). Zolang `throughput_norm` niet gevuld is (fase 2) toont de kolom de overridewaarde uit de masterdata en "SAP" zonder getal — eerlijk over wat er nog niet zichtbaar kan zijn | invulbaar: klik opent de override-invoer (write-through naar `throughput_overrides`, bron "handmatig") |
| 6 | **"Neem over als beginwaarde"-actie op MES/PEER-cellen**: schrijft een `ThroughputOverride` met bron "MES overgenomen" resp. "PEER overgenomen". Expliciete handeling; MES zelf blijft referentie en rekent nooit vanzelf mee | schrijft override via bestaande PATCH |
| 7 | **Loonkosten invulbaar per functiegroep, nu.** Niet wachten op FIN: het `labor_rates`-grid heeft al "+ rij"; de werkbank krijgt een directe sprong + chip die de status toont ("sitebreed tarief" → "eigen tarieven, n groepen"). FIN-antwoord = betere beginwaarde, geen voorwaarde. **Stille €0** (regel zonder tarief én zonder default) wordt een zichtbare waarschuwing op de regel | masterdata-grid (bestaand, addable) |
| 8 | **Combinatiegetallen bewerkbaar vanuit het paneel**: operators-samen en doorzetfactor(en) in het combinatiepaneel openen de bijbehorende rij in het `machine_combinations`-grid | sprong naar grid (bestaand, addable) |
| 9 | **Indirect-sectie**: driverchips (vast · per ton · per truck · per machine), maintenance-badge (§6.6), klikbare uitsplitsing achter de tegel "waarvan indirect", en per regel een sprong naar de `indirect_activities`-rij | sprong naar grid (bestaand, addable) |
| 10 | **Materialiteitsdrempel op alle delta's** (vast; grijs "≈ 0" met exact getal in tooltip) en **eerlijkheidsmelding** op het vergelijkingspaneel (rekent met opgeslagen normen; melding bij onopgeslagen wijzigingen) | leeswerk |
| 11 | **Machinedetail standaard uit**, uitklap per groep; **aannamenstrip** onder de KPI-rij (effectieve uren, bezettingsdoel, tariefstatus, n aannamenormen) — elke chip is een sprong naar zijn invulpad | leeswerk + sprongen |
| 12 | **Keuzelijsten op alle sleutel-invoer** (klantvraag 2026-08-06: "teveel risico op een verkeerde naam of sleutel intypen"). "+ rij" opent een sleutelkiezer i.p.v. een prompt; paarsleutels (MACHINE\|MATERIAAL) zijn twee velden met elk hun eigen lijst; zoeken werkt op een deel van naam óf code; een suggestieveld weigert codes die niet in de lijst staan (vrije ID's zoals een nieuwe combinatie blijven vrij). Ook: wizard-materiaalnummer/familie, csv-machinecellen (per token, reeds gekozen codes niet opnieuw aangeboden), configvelden unlimited-machines en purchased&produced, en de MES-overname (materiaal wordt gekozen, niet getypt) | invulveiligheid op bestaande paden |

## 4. Fase 2 — enginewerk: invullingen laten dóórwerken

Dit is de kern van de richtlijn en het zwaarste werk. Volgorde van belang:

1. **Doorzet-override doorwerken in de capaciteitsmotor.** `capacity_engine`
   past `throughput_overrides` toe op de Line 07-uren (zelfde
   sleutel `machine|materiaal`, zelfde OEE-behandeling als de FTE-motor), zodat
   planning, bezetting, bottlenecks én werkbank hetzelfde getal zien. Dit
   raakt de rekenkern: eigen verificatieronde met (a) bewijs dat een lege
   override-set byte-identieke resultaten geeft (additiviteit), (b) golden
   baseline opnieuw genereren mét dat bewijs ernaast, (c) browsertests op de
   cascade planning→werkbank.
2. **`FteLine.throughput_norm` vullen** met de effectief meegerekende doorzet
   (routing-AUX2 dan wel override) + `throughput_source` renderen. Daarmee
   wordt kolom 5 uit fase 1 volwaardig en is er geen stil meetellend getal
   meer.
3. **Bruto→netto-parameters laten doorwerken.** Ziekte%, verlof, ADV en
   training zijn nu "afleidingshulp" die niets doet. Ze gaan
   `fte_hours_per_year` daadwerkelijk afleiden (`derive_effective_fte_hours`
   bestaat al), met de afgeleide waarde zichtbaar naast het veld en een
   expliciete bevestigingsstap — invullen dat niets doet is erger dan geen
   veld.
4. **Lege cel ≠ nul.** `_masterCellValue` maakt van een leeggemaakte getalcel
   stil 0; dat wordt een expliciete keuze (leeg = niet ingevuld = weigeren of
   bewust wissen, nooit stil 0).
5. **Override-randgevallen zichtbaar**: een override ≤ 0 of zonder basisdoorzet
   wordt nu stil genegeerd op een warninglijst na — dat wordt een zichtbare
   melding op de regel zelf.
6. **Afwijkingsbadge norm vs MES** (klantvraag §6.1): amber > X%, rood > 2·X%,
   met X als één sitewaarde in masterdata (default 10%, label "voorlopig").
   Kan pas zinvol ná stap 2 (er moet een norm zichtbaar zijn om tegen af te
   wijken).

## 5. Fase 3 — ontbrekende invulpaden in de masterdata

Zuivere uitbreiding van de bestaande grids/formulieren, geen rekenwerk:

- **Machines toevoegen** in de app (incl. `machine_costs`-rij), naar het
  stramien van de productwizard; machine-detailvelden bewerkbaar
  (`shift_hours_override`; `availability_by_period` heeft een eigen
  periode-editor nodig).
- **Ploegvenster toevoegen** in het FTE-formulier (nu alleen bestaande
  sleutels bewerkbaar).
- **Materiaalvelden ontsluiten** die na aanmaak vastzitten
  (`fte_requirements`, `ton_per_truck`, `control_room`,
  machinegroep-toewijzingen, …).
- **Purchase actuals invulbaar** met de import als beginwaarde (nu "bevroren
  op importmaand").
- **Losse "+ rij"** voor `safety_stock`, `material_costs`, `sales_prices`
  (nu alleen via de alles-in-één-productwizard).
- **Systematisch bronlabel**: per record zichtbaar of het de importwaarde is
  of een bewerking (schema-uitbreiding; nu heeft alleen
  `throughput_overrides` een bronveld).

## 6. Fase 4 — wacht op klantantwoord of op goedkeuring van de werkbank

- **Cyclusafsluiting / besliskaart** (scenario-referentie + MT-samenvatting,
  altijd mét masterdata-versiestempel en voorbehouden; vergt
  compare-uitbreiding).
- **Combinaties per periode aan/uit** (raakt alle zes sync-/rebuildpunten;
  §6.4 eerst).
- **Meetdatum bij benchmarks** (alleen als de klant een meetdatum meelevert).

## 7. Wat er door de richtlijn is omgekeerd — en wat blijft staan

Omgekeerd (was afgewezen, mag nu — als expliciete handeling met bron):

- **Doorzet invullen vanuit de werkbank** (was: "overrides alleen in de
  masterdata-tabellen"). Het blijft dezelfde dataset en dezelfde PATCH; alleen
  de ingang zit nu waar de planner kijkt.
- **"Neem MES/PEER over"** (was: verboden knop). Toegestaan als expliciete
  overname die een override mét bronlabel schrijft; MES rekent nooit vanzelf.

Blijft afgewezen, met de oorspronkelijke jurygrond:

- **±-bandbreedte op loonkosten** — verzonnen onzekerheidsgetal.
- **Norm-wat-als per variant in de vergelijking** — de richtlijn zegt dat
  alles ínvulbaar moet zijn in de data, niet dat vergelijkingen mogen rekenen
  met normen die in geen enkele masterdata-versie bestaan.
- **Stille jaarbasis-normalisatie, per-gebruiker drempels, "euro's
  eerst"-herordening, optimizer, extra grafieken** — ongewijzigd.
- **MES die vanzelf meerekent** — de overname is een handeling, geen sluis.

## 8. Klantvragen worden beginwaarde-verbeteringen

| Klantvraag (§6 F2-CF-plan) | Was | Wordt |
|---|---|---|
| 6.1 brontriage doorzet | blokkade voor de triagekolom | invulpad bestaat vast; klantantwoord zet de drempel en de voorkeursbron |
| 6.3 loonkosten per functiegroep | wachten op FIN | planner vult nu al tarieven in; FIN-cijfers vervangen de beginwaarde |
| 6.4 combinatieregels | blokkade voor per-periode | combinaties blijven hele-horizon tot bevestigd |
| 6.6 maintenance wel/niet | badge | badge + activiteit staat in de masterdata en is nu al aan/uit te zetten |
