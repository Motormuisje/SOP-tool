# Aannames voor ontbrekende klantdata

Alleen de Maastricht-uitgave (NLX1). De site-uitgaven hebben geen machine-inzet
en geen omsteltijden.

## Waarom

De klant levert een deel van de invoer later aan. De informatie-uitvraag van
9 november 2026 zegt daarover voor prioriteit B en C: *een eerste indicatie
volstaat; het staat in de tool als instelling die jullie later zelf aanpassen.*
Tot die waarden er zijn, kan de tool het gat vullen met een **aanname**: een
getal uit een vaste regel, opgeslagen als gewone masterdata en overal te
wijzigen.

## Wat de tool aanneemt

Alleen **omsteltijden** (machine-inzet). Zonder omsteltijd toont het bord voor
een machine geen omsteluren en geen omstelkosten; er bestaat geen terugval.

Regel `omstel-v1`, op het SAP-machinecodeprefix, in uren per omstelling:

| Prefix | Soort | Uren |
|---|---|---|
| PML | maalinstallatie | 2,0 |
| PBA | afvulmachine | 0,5 |
| PSS | breker | 1,0 |
| PWP | zeef | 0,5 |
| PPM | menging/voorbereiding | 1,0 |
| overig | overige installatie | 1,0 |

Machines met onbeperkte capaciteit (Config `MachineUnlimitedCapacity`, bijv.
de virtuele PBA99) krijgen geen aanname. Het tarief per omsteluur blijft leeg:
het bord rekent dan met het machinetarief uit de machinekosten.

In fase 1 tellen omsteluren mee in de **kosten** op het machine-inzetbord, niet
in de **beschikbare capaciteit** van de planning.

## Wat de tool bewust niet aanneemt

- **Bemensingsnormen en loontarieven.** De motor heeft daar al een werkende
  terugval: de Line-12-coëfficiënt per groep en het `default`-tarief. Een kopie
  daarvan als record zou de terugval bevriezen en een later aangeleverde
  klantwaarde maskeren.
- **Doorzet-overrides en MES/PEER-benchmarks.** Dat zijn metingen of
  gezaghebbende klantgetallen; een verzonnen meting misleidt.

## Herkomst

Elke omsteltijd draagt zijn herkomst in de masterdata (`origin`,
`origin_rule`, `origin_value`, ook in het masterwerkboek):

| Label | Betekenis |
|---|---|
| (geen) | ingevuld door klant of gebruiker |
| aanname | door de tool gegenereerd, waarde ongewijzigd |
| aanname, aangepast | gegenereerd, daarna door een gebruiker gewijzigd (uren of eigen tarief) |
| aanname, bevestigd | gegenereerd en door een gebruiker als juist bevestigd |

De toestand volgt uit de huidige waarde: wie een aanname wijzigt en precies
terugzet, heeft weer een ongewijzigde aanname.

## Bediening

Tabblad Machine-inzet, balk boven de tegels:

- **Vul N aanname(s) in** — alleen machines zonder omsteltijd; bestaande
  waarden blijven staan.
- **Bevestig aannames** — markeert de ongewijzigde aannames als bevestigd.
- **Verwijder ongewijzigde aannames** — alleen aannames waarvan de waarde nog
  gelijk is aan de oorspronkelijke en die geen eigen tarief hebben.

Wijzigen gaat zoals altijd: in het veld op het bord of in Config →
Masterdata-tabellen → Omsteltijden. Elke actie verhoogt de masterdataversie en
weigert als iemand anders intussen heeft opgeslagen.

Als de klant de omsteltijden aanlevert: vul ze in (de aanname wordt
"aangepast") of verwijder eerst de ongewijzigde aannames en importeer daarna.

## Technisch

- Generator en toestanden: `modules/placeholder_data.py`.
- Routes: `GET/POST /api/machine_inzet/placeholders` in
  `ui/routes/machine_inzet.py`; weigeren elke store waarvan de site niet in
  `PLACEHOLDER_SITES` staat (nu `NLX1`).
- Tests: `tests/test_placeholder_data.py`,
  `tests/browser/test_pw_machine_inzet.py::test_aannames_voor_ontbrekende_omsteltijden`.
- Een regelwijziging krijgt een nieuwe versie (`omstel-v2`); bestaande aannames
  houden hun eigen `origin_value` en worden daardoor nooit stil "aangepast".
