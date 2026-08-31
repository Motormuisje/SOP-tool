# Plan — tabblad "Machine-inzet": omstellingen & combinaties

**Site-scope: NLX1 (zelfde regels als de werkbank).** Vraag van de klant
(2026-08-09): *"ik wil de omsteltijden en combinaties in een aparte tab doen;
productiegetallen komen van de planning-tab — dit is hoe we het systeem
completer maken."*

## 1. Kernprincip: de planning is de bron, deze tab leest

De capaciteitsmotor produceert per machine × product × periode al de
draaiuren (Line 07). Dit tabblad **bezit geen productiegetallen** — het leest
ze en beantwoordt de vraag die de planning zelf niet stelt: *hoe vaak wissel
ik van product op een machine, wat kost dat aan omsteltijd, en loont het om
machines te combineren?* Alles wat hier wordt ingevuld volgt de bestaande
doctrines: masterdata is de bron (import is populatie), wat-als is
sessiestate met bronlabel, één eigenaar per getal.

## 2. Wat er op het tabblad komt

1. **Omstellingen per machine per periode** (tabel + heatmapje, zelfde stijl
   als de werkbank): aantal verschillende producten met uren op de machine,
   het **geschatte** aantal omstellingen, de omsteluren en het percentage van
   het beschikbaarheidsvenster dat eraan opgaat.
2. **Combinatiebeheer verhuist hierheen** — de bestaande kaart met vinkjes en
   de variantenvergelijking, ongewijzigd in werking (zelfde sessiestate
   `active_combinations`, zelfde routes). Combinaties en omstellingen zijn
   allebei "hoe zet ik mijn machines in"; de FTE-werkbank blijft over mensen
   gaan en houdt een compacte samenvatting met sprong hierheen.
3. **Invulpaden op de tab zelf**: omsteltijden inline aanpasbaar
   (write-through naar de masterdata met versiecontrole), en het geschatte
   aantal omstellingen per machine × periode overschrijfbaar als
   sessie-wat-als met bronlabel — exact het stramien van de bemensingsnormen.

## 3. Het rekenmodel, eerlijk over wat het weet

- **Masterdata** (nieuw dataset `changeover_times`): per machine een
  omsteltijd in uren per omstelling. Bewust op machineniveau beginnen — een
  volledige van-product-naar-product-matrix is het klantmodel-ideaal maar
  vult niemand; het sleutelformaat (MACHINE, later uitbreidbaar naar
  MACHINE|VAN|NAAR met de machinewaarde als terugval) laat de verfijning
  toe zonder migratie.
- **Aantal omstellingen zonder volgorde-informatie** = (aantal producten met
  draaiuren op de machine in die periode) − 1, ondergrens 0. Dat is een
  **schatting** en heet ook zo op het scherm ("geschat — volgorde onbekend").
  Geen schijnprecisie: de echte telling vergt de productievolgorde, en dat
  is precies de geparkeerde vervolgtaak.
- **"Machinevolgorde wisselen"** — de VOLGORDE per machine bestaat sinds 1b als weergave-wat-als (slepen op het bord); fase 3 maakt er een echte telling met VAN|NAAR-tijden van. De oorspronkelijke taak
  krijgt hier zijn thuis als fase 3: een volgorde per machine per periode als
  sessie-wat-als, die de schatting vervangt door een echte telling en
  volgorde-afhankelijke omsteltijden mogelijk maakt.

## 4. Doorwerking in de capaciteit — fase 2, niet stiekem

Omsteluren horen het **beschikbaarheidsvenster** te verlagen (de Line
11-kant, zoals gepland onderhoud) — niet de benodigde uren te verhogen.
Fase 1 toont het effect uitsluitend op de tab (informatief, met de expliciete
melding dat de planning er nog niet mee rekent). Fase 2 laat het meerekenen
in de capaciteitsmotor, in dezelfde zorgvuldigheidsronde als de
doorzet-override-doorwerking die daar al gepland staat: additiviteitsbewijs
(lege dataset = byte-identiek), golden baseline hernieuwen met het bewijs
ernaast, browsertests op de cascade.

## 5. Fasering

| Fase | Inhoud | Raakt rekenkern |
|---|---|---|
| 1 | **GEBOUWD (2026-08-09).** Dataset `changeover_times` + tabblad (telling uit de planning, invulpaden, combinaties verhuisd; omsteltijden lezen live uit de store omdat de motor ze nog niet consumeert; aantal-overrides zijn weergave-wat-als met persistentie via sessiestore/scenario's/duplicaat en Reset-semantiek — bewust nog niet door config_overrides/snapshot/replay, dat volgt zodra fase 2 ze laat meerekenen) | nee |
| 1b | **GEBOUWD (2026-08-26, presentatie herzien t/m 2026-09-01).** Klantvraag: *"meteen zien welke molen welk product maakt, in welke volgorde en hoeveel omstelling ze kosten; en een waarde plakken: de kosten van die omsteltijd."* **Presentatie = planbord C2** (klantkeuze uit vier concepten): links één machinelijst (gegroepeerd per machinegroep; sortering kosten/omstellingen/zonder-tijd-eerst; zoeken op machine én product), rechts het bord van de gekozen machine over alle maanden — producten als blokken in **volgorde** (breedte ≈ draaiuren, minimumbreedte als handvat; labels naam → korte code → volgnummer met legenda), wissels als amber gaten die het AANTAL volgen (schatting of wat-als), per maand de rekening (klikbaar aantal = wat-als). **Volgorde wijzigen = blokken slepen op het bord zelf** (geen chips, pijltjes of detailrij; sessie-wat-als `changeover_sequences`, per machine over de hele horizon, zelfde persistentie als de aantal-overrides; verouderde entries worden gesnoeid met waarschuwing). **Kosten** = aantal × omsteltijd × tarief, gerekend op onafgeronde uren; tarief = `cost_per_hour` op `changeover_times` (masterdata, optioneel) met terugval op het machinetarief uit `machine_costs`, alles live uit de store, met herkomstlabel. KPI-strip (omstellingen, omsteluren, kosten, invulstatus). Gedocumenteerd ontwerp: Reset én Bereken wissen de omstel-wat-als; venster = groepsvenster (Line 11); nan/inf en negatieve handwaarden worden geweigerd/geklemd; leegmaken van een omsteltijd mét tarief/toelichting wordt geweigerd. Audits 2026-08-31 en 2026-09-01 (7+5 zoekers, tegensprekers) verwerkt. | nee |
| 2 | Omsteluren verlagen het venster in de capaciteitsmotor (samen met de doorzet-override-doorwerking: één golden-hernieuwing voor beide) | ja |
| 3 | Van de bestaande volgorde-wat-als (1b) een rekenende maken: echte telling i.p.v. producten−1, volgorde-afhankelijke tijden (VAN|NAAR); de state verhuist dan naar de volledige zes syncpunten | ja |

## 6. Vragen aan de klant (beginwaarden — populatie, geen blokkade)

1. Omsteltijd per machine volstaat als start, of zijn er machines waar het
   per productfamilie wezenlijk verschilt? (Bepaalt wanneer het sleutelformaat
   wordt uitgebreid.)
2. Is er MES-data over werkelijke omstellingen (aantal/duur) die we als
   beginwaarde kunnen inlezen? Import vult, de gebruiker verfijnt.
3. Telt een omstelling volledig als capaciteitsverlies, of deels (bemande
   omstelling versus onbemande)? Bepaalt of er ook een FTE-component aan de
   werkbank wordt toegevoegd.
