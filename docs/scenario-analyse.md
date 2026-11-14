# Scenario-analyse

## Wat-als bouwen

Tabblad Planning, knop **Wat-als**. Twee stuurknoppen:

- **Vraag aanpassen** voor een productfamilie, één materiaal of alle producten,
  over een periode, met een percentage (10 = 10 % meer, −10 = 10 % minder,
  −100 = geen vraag).
- **Machinebeschikbaarheid** van één machine over een periode (0 % = stilstand).

De stuurknop wordt gewone celbewerkingen (Line 01 resp. Line 09) via de
bulkroute: één undo-stap, bewaard en na een herstart herspeeld zoals elke
bewerking, met de volledige cascade. Het voorbeeld toont vooraf hoeveel cellen
veranderen.

Let op bij stilstand: de geplande productie blijft staan en wordt niet
verplaatst. Bij 0 % beschikbaarheid zet de berekening de benutting op 0 (zoals
de VBA; zie BUGS.md Q8), dus de machine lijkt rustig. De vergelijking toont
zulke maanden als **Geplande uren zonder capaciteit**.

## Vergelijken

Knop **Vergelijk** (zichtbaar zodra er één scenario is opgeslagen). Tot vier
kolommen: opgeslagen scenario's en/of de huidige stand. De eerste gekozen kolom
is de basis; de andere tonen het verschil.

| Kerncijfer | Bron |
|---|---|
| EBIT, operationele kasstroom, omzet, kostprijs, brutomarge, EBITDA | horizongetal van de consolidatie (aux_2: som over de maanden, zoals Excel) |
| Voorraadwaarde, werkkapitaal | horizongetal (gemiddelde; voorraadwaarde inclusief beginvoorraad) |
| ROCE | horizongetal: totale EBIT / gemiddeld geïnvesteerd vermogen; verschil in procentpunten |
| Totale vraag, productie, inkoopontvangsten | som over de materiaalregels (ton) |
| Eindvoorraad | som van Line 04 in de laatste maand |
| Maanden onder minimumdoel / met negatieve voorraad | telling materiaal-maanden (Line 04 tegen Line 05) |
| Overbelaste machine-maanden, hoogste benutting | Line 10 per machine; onbeperkte machines tellen niet mee |
| Geplande uren zonder capaciteit | Line 07 machine-uren > 0 terwijl Line 09 = 0 |
| FTE | Line 12 per maand opgeteld, gemiddeld over de horizon |

Er wordt niets opnieuw berekend; de cijfers komen uit het opgeslagen scenario
of de huidige berekening. Verschillen alleen bij dezelfde horizon. Groen/rood
alleen waar hoger eenduidig beter of slechter is. Per kolom staat welke invoer
afwijkt en of het scenario op een andere masterdataversie is berekend. Klik een
telling voor de regels erachter.

Code: `ui/scenario_kpis.py`, route `POST /api/scenarios/kpis` in
`ui/routes/scenarios.py`. Tests: `tests/test_scenario_kpis.py`,
`tests/browser/test_pw_scenario_kpis.py`.
