# Checklist manuele validatie — Apex Rainier fase 3

**Uitgevoerd door:** ______________  **Datum:** ______________
**Versie/commit:** `a18e54b` (tag `milestone-fase-3`)

Doorloop de checks per testsoort (secties A–I, samen ± 1,5–2 uur; secties
zijn ook los uit te voeren, alleen A → B horen als eerste). Vink af, plak
per check een screenshot (Excel-/Word-versie in `exports/`) en noteer bij
een afwijking wat je zág in plaats van wat er had moeten staan.

**Voorbereiding:** `python main.py` → browser opent de app. Houd een
maandwerkboek (MS_RECONC .xlsm) klaar.

---

## A. Masterdata in de app

**A1 — Statuskaart.** Open de Config-tab.
*Verwacht:* kaart "Masterdata" toont "Masterdata in de app, versie N" met
aantallen per dataset (of de importknop als er nog niets is — importeer dan
eerst het werkboek).
☐ OK — Screenshot — Opmerkingen: ______________

**A2 — Materiaal hernoemen.** Open de materialen-grid, wijzig de naam van
één materiaal (bv. voeg " TEST" toe), sla op.
*Verwacht:* melding "Masterdata opgeslagen (versie N+1). Herbereken sessies
om de wijziging toe te passen." Grid toont de nieuwe naam.
☐ OK — Screenshot — Opmerkingen: ______________

**A3 — Naam komt door na herberekening** *(de fix van 12-07)*. Ga naar de
actieve instantie en klik Calculate.
*Verwacht:* de nieuwe naam staat in de planningstabel bij dat materiaal —
óók als deze instantie op een werkboek draait.
☐ OK — Screenshot — Opmerkingen: ______________

**A4 — Terugdraaien.** Zet de naam terug via de grid en herbereken.
*Verwacht:* originele naam terug in tabel; versieteller weer +1.
☐ OK — Screenshot — Opmerkingen: ______________

**A5 — Prijswijziging werkt financieel door.** Wijzig in de dataset
verkoopprijzen de prijs van één materiaal fors (bv. ×2), sla op en
herbereken.
*Verwacht:* de omzet van dat materiaal (financiële tab/grafiek) beweegt
evenredig mee; andere materialen ongewijzigd. Zet daarna terug + herbereken.
☐ OK — Screenshot — Opmerkingen: ______________

**A6 — Foutieve invoer wordt geweigerd.** Zet in een numeriek veld (bv.
veiligheidsvoorraad of prijs) tekst zoals "abc" en probeer op te slaan.
*Verwacht:* duidelijke Nederlandse foutmelding; er wordt níéts opgeslagen
(versieteller ongewijzigd, waarde in de grid na heropenen ongewijzigd).
☐ OK — Screenshot — Opmerkingen: ______________

**A7 — Re-import met diff-bevestiging.** Importeer hetzelfde (of een nieuw)
werkboek nogmaals via de masterdata-kaart.
*Verwacht:* de app toont eerst een verschiloverzicht (aantallen/gewijzigde
sleutels) en overschrijft pas na expliciete bevestiging — de app is de bron
van waarheid, een import gebeurt nooit stilzwijgend.
☐ OK — Screenshot — Opmerkingen: ______________

**A8 — Materiaal deactiveren.** Zet in de materialen-grid de Actief-vlag
van één (klein) materiaal uit, sla op, herbereken.
*Verwacht:* het materiaal verdwijnt uit de planning (geen lijnen meer).
Zet de vlag weer aan + herbereken: het materiaal is terug met dezelfde
cijfers als vóór de deactivering.
☐ OK — Screenshot — Opmerkingen: ______________

## B. Sessies & persistentie

**B1 — Nieuwe instantie.** Maak een tweede instantie aan, upload het
werkboek, Calculate.
*Verwacht:* tabel gevuld; perioden lopen van de planningsmaand t/m 12
maanden vooruit; geen foutmeldingen.
☐ OK — Screenshot — Opmerkingen: ______________

**B2 — Wisselen zonder lekkage.** Wissel een paar keer tussen beide
instanties.
*Verwacht:* waarden, config-velden (site, forecast-maanden, valuatie) én
filters horen telkens bij de gekozen instantie; niets "lekt" mee van de
vorige.
☐ OK — Screenshot — Opmerkingen: ______________

**B3 — Instantie hernoemen.** Hernoem de tweede instantie.
*Verwacht:* nieuwe naam overal zichtbaar (lijst, kop) en blijft na herstart.
☐ OK — Screenshot — Opmerkingen: ______________

**B4 — Parameters wijzigen.** Verander in de tweede instantie de
planningsmaand of het aantal actuals-maanden en herbereken.
*Verwacht:* de periodekolommen verschuiven mee; de eerste instantie
behoudt haar eigen parameters.
☐ OK — Screenshot — Opmerkingen: ______________

**B5 — Herstart.** Sluit de app volledig af en start opnieuw.
*Verwacht:* beide instanties staan er nog; na warm-up tonen ze dezelfde
cijfers, namen en parameters als vóór de herstart.
☐ OK — Screenshot — Opmerkingen: ______________

**B6 — Config per instantie na herstart.** Wissel na de herstart naar de
tweede instantie en open de Config-tab.
*Verwacht:* de config-velden tonen de waarden van déze instantie, niet die
van de eerst geladen instantie.
☐ OK — Screenshot — Opmerkingen: ______________

## C. Bewerkingen & cascade

**C1 — Forecast-edit cascadeert.** Wijzig één L01-cel (demand forecast)
fors, bv. ×2.
*Verwacht:* L03/L04/L06 van dat materiaal bewegen mee; de machinegrafiek
van de betrokken machinegroep verandert; tabel en grafiek vertellen
hetzelfde verhaal.
☐ OK — Screenshot — Opmerkingen: ______________

**C2 — Undo.** Maak de edit ongedaan.
*Verwacht:* alle afgeleide lijnen exact terug naar de oude waarden.
☐ OK — Screenshot — Opmerkingen: ______________

**C3 — Cascade naar componenten.** Wijzig het productieplan (L06) van een
eindproduct met een BOM.
*Verwacht:* de afgeleide vraag (L03/L08) van zijn componenten beweegt mee —
de keten ouder → kind klopt.
☐ OK — Screenshot — Opmerkingen: ______________

**C4 — Combinatie + herstart (replay).** Doe twee edits na elkaar (eerst
L01, dan L06 van een ander materiaal), noteer twee afgeleide waarden,
herstart de app.
*Verwacht:* na de herstart staan exact dezelfde eindwaarden — de opgeslagen
bewerkingen worden in de juiste volgorde opnieuw toegepast.
☐ OK — Screenshot — Opmerkingen: ______________

**C5 — Bulk-edit.** Selecteer meerdere perioden van een lijn (slepen) en
pas ze in één keer aan.
*Verwacht:* alle geselecteerde cellen krijgen de nieuwe waarde; de cascade
loopt één keer netjes door.
☐ OK — Screenshot — Opmerkingen: ______________

**C6 — Startvoorraad-edit (L04).** Wijzig de startvoorraad van een
materiaal.
*Verwacht:* de voorraadlijn (L04) schuift over de hele horizon mee en de
productie-/inkoopplanning reageert waar de voorraad onder de
veiligheidsvoorraad zou zakken.
☐ OK — Screenshot — Opmerkingen: ______________

**C7 — Reset.** Klik Reset na de bovenstaande edits.
*Verwacht:* alles terug naar de baseline; de bewerkingenlijst is leeg; ook
startvoorraad- en bulk-edits zijn weg.
☐ OK — Screenshot — Opmerkingen: ______________

**C8 — Commentaar.** Zet een commentaar op een cel, herstart de app.
*Verwacht:* commentaar-indicator zichtbaar en de tekst blijft bewaard.
☐ OK — Screenshot — Opmerkingen: ______________

## D. Dynamische producten

**D1 — Aangekocht product.** Voeg een product toe met sourcing
"aangekocht", inclusief MOQ en levertijd.
*Verwacht:* inkooplijnen aanwezig; orders respecteren de MOQ (geen order
kleiner dan de MOQ) en de levertijd (orders schuiven naar voren).
☐ OK — Screenshot — Opmerkingen: ______________

**D2 — Geproduceerd product.** Voeg een product toe met sourcing
"geproduceerd", inclusief BOM-regel en routing (machine + uren).
*Verwacht:* productielijnen aanwezig; de gekozen machinegroep toont extra
uren; de BOM-component krijgt afgeleide vraag.
☐ OK — Screenshot — Opmerkingen: ______________

**D3 — Mix-product.** Voeg een product toe met sourcing "mix" (bv. 30%
aangekocht / 70% geproduceerd).
*Verwacht:* zowel inkoop- als productielijnen, in de opgegeven verhouding.
☐ OK — Screenshot — Opmerkingen: ______________

**D4 — Financiële aansluiting.** Controleer de financiële cijfers voor de
drie testproducten.
*Verwacht:* omzet = prijs × volume; kosten (grondstof/machine) sluiten aan
bij de ingevoerde parameters; de totalen op het dashboard zijn met de
producten meegegroeid.
☐ OK — Screenshot — Opmerkingen: ______________

**D5 — Wisselen en verwijderen.** Wissel naar de andere instantie en terug;
verwijder daarna één testproduct.
*Verwacht:* producten blijven bij hun eigen instantie; na verwijderen is
het product overal weg (tabel, grafieken, financieel) en klopt de planning
weer zonder het product.
☐ OK — Screenshot — Opmerkingen: ______________

## E. Grafiek-analyse

**E1 — Automatische detectie.** Vergroot de financiële grafiek, klik
"Analyse".
*Verwacht:* paneel naast de grafiek toont de grootste beweging met de
producten die haar verklaren; niets is afgeknipt.
☐ OK — Screenshot — Opmerkingen: ______________

**E2 — Twee punten klikken.** Klik twee punten in de grafiek.
*Verwacht:* een pijl verbindt de punten; het paneel verklaart precies dát
verschil; de productbijdragen tellen op tot (ongeveer) het totale verschil.
☐ OK — Screenshot — Opmerkingen: ______________

**E3 — Volumegrafiek.** Sluit, vergroot de volumegrafiek en analyseer een
beweging.
*Verwacht:* zelfde analyse-ervaring; bijdragen per product in eenheden
i.p.v. euro's.
☐ OK — Screenshot — Opmerkingen: ______________

**E4 — FTE-drill.** Analyseer de FTE-grafiek en klik door.
*Verwacht:* je ziet door welke producten de FTE-verandering komt.
☐ OK — Screenshot — Opmerkingen: ______________

**E5 — Overige grafieken.** Open de analyse ook op een machinegrafiek en op
de voorraadkwaliteitsgrafiek.
*Verwacht:* elke grafiek heeft een werkende analyse-knop met een logisch
verhaal (uren per product, kwaliteitscategorieën).
☐ OK — Screenshot — Opmerkingen: ______________

**E6 — Naar tabel.** Klik "naar tabel" op de top-movers.
*Verwacht:* de planningstabel filtert op die producten en je kunt er direct
een waarde aanpassen (inputfout-scenario).
☐ OK — Screenshot — Opmerkingen: ______________

**E7 — Analyse-export.** Exporteer de analyse.
*Verwacht:* Excel-bestand met dezelfde cijfers als het paneel.
☐ OK — Screenshot — Opmerkingen: ______________

## F. Materiaalgroepen

**F1 — Groep opslaan.** Sla vanuit de analyse een groep op (bv. "top 10
movers 04-26→06-26").
*Verwacht:* de groep staat in de dropdown boven de planningstabel.
☐ OK — Screenshot — Opmerkingen: ______________

**F2 — Combineren met linetypes.** Selecteer de groep en filter daarna op
linetypes.
*Verwacht:* beide filters werken samen; je ziet alleen de gekozen lijnen
van de groepsmaterialen.
☐ OK — Screenshot — Opmerkingen: ______________

**F3 — Terug naar "Alle groepen"** *(bugcheck 11-07)*. Kies in de dropdown
weer "Alle groepen".
*Verwacht:* álle rijen komen terug; je zit niet vast in de groepsweergave.
☐ OK — Screenshot — Opmerkingen: ______________

**F4 — Maak actief.** Activeer de groep.
*Verwacht:* banner "actieve groep" zichtbaar; dashboard toont de
groepsbijdrage (bijdragemarge — vaste kosten/EBIT/ROCE bewust verborgen);
machines tonen de uren van de groep; de dropdown toont de groep met
"· actief".
☐ OK — Screenshot — Opmerkingen: ______________

**F5 — Analyse onder actieve groep.** Doe een grafiekanalyse terwijl de
groep actief is.
*Verwacht:* de analyse werkt op de gescoopte cijfers en de bijdragen
sluiten aan op het gescoopte totaal.
☐ OK — Screenshot — Opmerkingen: ______________

**F6 — Groep hoort bij de instantie.** Wissel met actieve groep naar de
andere instantie en terug.
*Verwacht:* de andere instantie kent de groep niet en is ongescoopt; terug
in de eerste instantie is de groep nog steeds actief.
☐ OK — Screenshot — Opmerkingen: ______________

**F7 — Actieve groep overleeft herstart.** Herstart de app met de groep
actief.
*Verwacht:* na warm-up is de groep nog actief (banner + gescoopte cijfers).
☐ OK — Screenshot — Opmerkingen: ______________

**F8 — Lege doorsnede.** Filter met actieve groep op een linetype die geen
groepsmateriaal heeft.
*Verwacht:* nette uitleg + knop "Herstel filters" (geen stille lege tabel).
☐ OK — Screenshot — Opmerkingen: ______________

**F9 — Deactiveren en verwijderen.** Zet de groep uit (dropdown → "Alle
groepen") en verwijder haar daarna.
*Verwacht:* banner weg, dashboard en machines weer fabrieksbreed; na
verwijderen is de groep uit de dropdown.
☐ OK — Screenshot — Opmerkingen: ______________

## G. Machines & capaciteit

**G1 — OEE aanpassen.** Wijzig de OEE van één machine.
*Verwacht:* automatische herberekening; bezetting in tabel én grafiek
consistent.
☐ OK — Screenshot — Opmerkingen: ______________

**G2 — Doeldoorzet.** Gebruik de directe doorzet-aanpassing op een machine.
*Verwacht:* de OEE wordt evenredig aangepast om de doeldoorzet te halen en
de herberekening volgt automatisch.
☐ OK — Screenshot — Opmerkingen: ______________

**G3 — Machine-drill.** Klik door op een machine.
*Verwacht:* je ziet welke producten uren op die machine draaien; de som van
de productuurbijdragen klopt met het machinetotaal.
☐ OK — Screenshot — Opmerkingen: ______________

**G4 — Machine-overrides ongedaan maken.** Maak de OEE-wijziging (G1)
ongedaan (undo of reset).
*Verwacht:* bezetting en FTE exact terug naar de oude waarden.
☐ OK — Screenshot — Opmerkingen: ______________

**G5 — FTE volgt capaciteit.** Vergelijk de FTE-lijnen (L10–L12) vóór en ná
een forse capaciteitswijziging (bv. G1 opnieuw, of een grote forecast-edit).
*Verwacht:* de FTE-behoefte beweegt logisch mee met de gedraaide uren.
☐ OK — Screenshot — Opmerkingen: ______________

## H. Exports

**H1 — Planningsexport.** Exporteer het planningswerkboek en open het.
*Verwacht:* Excel opent zonder reparatiemelding; structuur klopt (lijnen,
perioden, groepering); steekproef van 3 cellen = exact de UI-waarden.
☐ OK — Screenshot — Opmerkingen: ______________

**H2 — Export bevat de bewerkingen.** Doe een herkenbare edit (bv. L01 een
rond getal) en exporteer opnieuw.
*Verwacht:* de geëxporteerde cel toont de bewerkte waarde, niet de
oorspronkelijke.
☐ OK — Screenshot — Opmerkingen: ______________

**H3 — Export blijft fabrieksbreed onder actieve groep.** Activeer een
groep en exporteer.
*Verwacht:* het exportbestand bevat de volledige fabriek (bewuste keuze:
groepen scopen alleen de weergave, nooit de cijfers die de deur uitgaan).
☐ OK — Screenshot — Opmerkingen: ______________

**H4 — MoM-export** *(indien vorige maand beschikbaar)*.
*Verwacht:* delta-werkboek met verschillen t.o.v. de vorige maand.
☐ OK — Screenshot — Opmerkingen: ______________

**H5 — DB-export.** Draai de platte database-export.
*Verwacht:* exportbestand met één rij per materiaal × lijn × periode;
aantallen plausibel.
☐ OK — Screenshot — Opmerkingen: ______________

## I. Afsluitend

**I1 — Geen fouten.** Blik terug over de hele sessie.
*Verwacht:* geen rode foutmeldingen of lege schermen gezien.
☐ OK — Opmerkingen: ______________

**I2 — Taal & meldingen.** Beoordeel de meldingen die je onderweg zag.
*Verwacht:* alle gebruikersgerichte meldingen in begrijpelijk Nederlands,
met een handelingsperspectief (wat moet ik nu doen).
☐ OK — Opmerkingen: ______________

**I3 — Opruimen.** Verwijder de testproducten (D), de testgroep (F), de
tweede instantie (B) en draai masterdata-testwijzigingen (A) terug.
*Verwacht:* verwijderen werkt netjes; de overige data blijft intact.
☐ OK — Opmerkingen: ______________

**I4 — Schone eindstaat.** Herstart de app een laatste keer.
*Verwacht:* alleen de echte instantie(s) en data zijn er nog; cijfers
identiek aan het begin van de sessie (vóór de testwijzigingen).
☐ OK — Opmerkingen: ______________

---

**Eindoordeel:** ☐ Alles akkoord ☐ Akkoord met opmerkingen ☐ Afwijkingen gevonden

**Handtekening / paraaf:** ______________
