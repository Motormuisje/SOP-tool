# Plan — werkbankpresentatie: opties, variabelen en opbouw

**Site-scope: uitsluitend Maastricht (NLX1).** Machinevolgorde wisselen is een
aparte vervolgtaak ná goedkeuring van de werkbank en staat hier bewust niet in.

Dit plan is de synthese van drie onafhankelijk gemaakte ontwerpen
(invalshoeken: planner-werkproces, financieel beslisser, datavertrouwen),
gejureerd op drie criteria (meerwaarde/duidelijkheid, haalbaarheid tegen de
echte engine-code, correctheid/vertrouwen). Afgewezen ideeën staan onderaan
mét reden — die lijst is net zo belangrijk als de bouwlijst.

## 1. Ordenend principe

De pagina volgt de maandcyclus van de planner, van boven naar beneden:

1. **Signaleren** — waar en wanneer knelt de bemensing? (KPI's, knelpuntenmatrix)
2. **Draaien** — aan wat je mag draaien: normen (via masterdata) en
   combinaties (sessie-wat-als). Eén eigenaar per getal blijft de wet.
3. **Doorgeven** — wat betekent het voor kosten en marge, en wat meld je het MT.

Daar doorheen geweven de vertrouwenslaag: **elk getal draagt zijn herkomst**
(SAP-routing, MES-meting, PEER, masterdata-norm, aanname), aannames staan als
chips op het scherm in plaats van in iemands hoofd, en er telt niets stil mee
of stil niet mee.

## 2. Fase 1 — nu te bouwen (bestaande engine en payload volstaan)

| # | Element | Beslissing die het dient | Variabelen | Vorm |
|---|---|---|---|---|
| 1 | **Knelpuntenmatrix**: benuttingsheatmap groep × periode, direct onder de KPI's | Waar/wanneer knelt het de komende maanden — de openingsvraag van elke cyclus | `FteLine.utilization` per periode (zit al in de payload); drempels van `_fteUtilizationClass` | Rijen = groepen + indirecte regels met venster, kolommen = periodes, cel = gekleurd blokje met %. Celklik zet het periodefilter en scrolt naar de groep. Toont altijd de hele horizon |
| 2 | **Piek naast gemiddelde** op de KPI-tegels | Werven/inhuren/ploegen plan je op de piekmaand, niet op het horizongemiddelde | `totals.*` per periode (al in payload) | Subregel per tegel: "32,1 gem. · piek 36,4 (2026-10)", piekmaand klikbaar; vervalt bij gekozen periode |
| 3 | **Aggregatie-sublabels** op de KPI-tegels | KPI's correct overnemen in rapportages | bestaande `_fteAgg` | Microlabel "gem. per periode" / "som over horizon" / de periodenaam |
| 4 | **Periodebereik-presets**, standaard "komende 3 maanden" | De ploegbeslissing van déze cyclus gaat over de komende maanden; "alle periodes" verdunt het venster | `data.periods` + kalendermaand | Bereikkeuze (3 mnd / 6 mnd / hele horizon / één maand); tabel en tegels volgen het bereik, de heatmap niet |
| 5 | **Herkomstchips op de bemensingsnorm** | Welke normen moet ik laten valideren vóór ik het totaal extern toon | `operators_source` (al in payload) | Bron-kolom wordt chip; `default` wordt amber "aanname 1,0" met telkaartje "n regels rekenen op een aanname" dat erop filtert |
| 6 | **Loonkosten-herkomstchip** "sitebreed tarief — FIN-uitvraag loopt" | Voorkomt dat één gemiddeld tarief gelezen wordt als FIN-gevalideerd | `labor_rates` (alleen `default` aanwezig) | Chip op de KPI-tegel, de kolomkop en in het waardeketenpaneel; verdwijnt vanzelf zodra er functiegroeptarieven zijn (§6.3) |
| 7 | **Materialiteitsdrempel op alle delta's** | Voorkomt beslissen op ruis (nu kleurt 0,001 FTE al groen/rood) | één gedeelde drempelfunctie i.p.v. epsilon 1e-9 | Onder de drempel grijs "≈ 0" met exact getal in tooltip; zelfde drempel voor tegels, vergelijking en waardeketen — vast, niet per gebruiker |
| 8 | **Eerlijkheidsmelding bij de vergelijking** | De vergelijking rekent met `engine.data` — dus met de **opgeslagen** normen, niet met wat je net intypte (geverifieerd, bestaande stille valkuil) | `_fteState.dirtyNorms` | Melding op het vergelijkingspaneel zodra er onopgeslagen normen zijn, plus vast bijschrift "gelijk volume, gelijke periodes — alleen de bemensingsaanname verschilt" |
| 9 | **Indirect-sectie met driverchips + uitsplitsing** | Vast vs volumegedreven uit elkaar houden; §6.6 (maintenance) zichtbaar maken i.p.v. impliciet | `IndirectActivity.driver`, `is_active` | Subkop "Indirect" met chip per regel (vast · per ton · per truck · per machine); maintenance-badge "telt mee — bevestiging OPS (§6.6)"; de tegel "waarvan indirect" klapt een minitabel uit. Aan/uit blijft in de masterdata-tabellen |
| 10 | **Machinedetail standaard uit** | Leesbaar voor wie het model niet kent: standaard alleen regels die in het totaal meetellen | bestaand vinkje | Uitklappijltje per groepsrij toont de machines ingesprongen en grijs |
| 11 | **Aannamenregister-strip** onder de KPI-rij | "Kan dit cijfer het MT in?" — de aannames als één regel chips | fte-params, bezettingsdoel, tariefstatus | "Effectieve uren 1.492 (additief) · bezettingsdoel 85% · sitebreed tarief · n aannamenormen", uitklapbaar |

## 3. Fase 2 — klein enginewerk eerst

| # | Element | Enginewerk | Vorm |
|---|---|---|---|
| 12 | **Doorzet-triage norm vs MES** (klantvraag §6.1) | `FteLine.throughput_norm` bestaat in het contract (fte_engine.py) maar wordt **nergens gevuld** — geverifieerd. Eerst vullen vanuit de SAP-routing/override in `_machine_lines` | Eén kolom "Doorzet t/u": "norm → MES" met bronchip (SAP/override) en afwijkings-%; amber > X%, rood > 2·X%. Drempel X is één sitewaarde in masterdata (default 10%, label "voorlopig" tot de klant §6.1 beantwoordt). Telkaartje "n normen wijken > X% af" filtert erop. MES rekent nooit mee — doctrine |
| 13 | **Niet-meegeteld-paneel** | payload-uitbreiding: inactieve activiteiten meesturen | Opvouwbaar, grijs (bewuste keuze, geen fout): per post naam, klantnorm en reden ("volumebron onbevestigd", "wacht op §6.6") |

## 4. Fase 3 — wacht op klantantwoord of op goedkeuring van de werkbank

- **Cyclusafsluiting / besliskaart**: huidige stand vergelijken met een
  vastgezet scenario en een MT-samenvatting produceren — altijd mét
  masterdata-versiestempel en de voorbehouden (sitebreed tarief, aannamenormen,
  maintenance in/uit). Een kale kopieerregel zonder herkomst is afgewezen.
  Vergt uitbreiding van `/api/fte/compare` (die varieert nu alleen
  combinatiesets).
- **Combinaties per periode aan/uit**: reële seizoensbeslissing, maar raakt de
  sessiestate door alle zes sync-/rebuildpunten en §6.4 (welke combinaties
  zijn überhaupt toegestaan) staat nog open. Pas na goedkeuring.
- **Meetdatum bij benchmarks**: alleen als de klant een meetdatum meelevert;
  zonder databron bouwen we het niet.

## 5. Bewust afgewezen (met de jurygrond)

- **±-bandbreedte op loonkosten** — de ±10% is zelf een getal zonder herkomst;
  schijnprecisie bestrijden met nieuwe schijnprecisie.
- **Norm-wat-als per variant** — schept een tweede eigenaar van de norm;
  binnen een week circuleren delta's waarvan niemand de normstand kent.
- **Variantenkast (checkbox-matrix, vrij samenstellen)** — overlaadt de pagina
  terwijl §6.4 nog niet eens vastlegt welke combinaties toegestaan zijn.
- **KPI-herordening "euro's eerst" / referentie-anker met delta-tegels** —
  herframet een plannerswerkbank tot financieel dashboard en verdubbelt het
  rekenwerk om tegels te decoreren.
- **Stille jaarbasis-normalisatie** — som ÷ periodes × 12 zonder dat te zeggen
  is precies de verborgen aanname die we overal anders uitbannen.
- **Per-gebruiker instelbare afwijkingsdrempel** — een signaal dat per kijker
  verschilt is niet reproduceerbaar; screenshots dragen het signaal niet.
- **"Reken met MES"-knop, doorzet-bewerking in de werkbank, optimizer,
  extra grafieken** — doctrine (benchmarks rekenen nooit mee; één eigenaar
  per getal; zes tegels is de grens) en scope.
- **Machinevolgorde wisselen** — expliciete klantuitspraak: aparte taak, later.

## 6. Wat dit oplevert per open klantvraag

| Klantvraag (§6 F2-CF-plan) | Zichtbaar als |
|---|---|
| 6.1 brontriage doorzet, drempel X | doorzet-triagekolom + telkaartje (fase 2), drempel gelabeld "voorlopig" |
| 6.3 loonkosten per functiegroep | sitebreed-tariefchip die vanzelf verdwijnt zodra FIN levert |
| 6.4 combinatieregels | combinaties blijven hele-horizon-wat-als tot de regels bevestigd zijn |
| 6.6 maintenance wel/niet | badge op de maintenance-regel + niet-meegeteld-paneel maakt beide lezingen controleerbaar |

Zo is de werkbank zelf het antwoordformulier: elke openstaande vraag staat als
chip of badge op het scherm, en het antwoord van de klant haalt hem weg.
