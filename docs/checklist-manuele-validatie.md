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

**A9 — Machinegegevens bewerken.** Wijzig de OEE van een machine in de masterdata-grid en herbereken.
*Verwacht:* de bezetting/capaciteit beweegt mee bij de eerstvolgende berekening.
☐ OK — Screenshot — Opmerkingen: ______________

**A10 — Veiligheidsvoorraad bewerken.** Verhoog de veiligheidsvoorraad van een materiaal en herbereken.
*Verwacht:* de voorraadplanning (L04/L05) schuift mee omhoog.
☐ OK — Screenshot — Opmerkingen: ______________

**A11 — Valuatieparameters bewerken.** Wijzig een valuatieparameter (bv. directe FTE-kost) en herbereken.
*Verwacht:* EBIT/ROCE op het dashboard bewegen mee.
☐ OK — Screenshot — Opmerkingen: ______________

**A12 — Grondstofkosten bewerken.** Wijzig de grondstofkost van een materiaal en herbereken.
*Verwacht:* de bijdragemarge/kosten van dat materiaal bewegen mee.
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

**B7 — Derde instantie.** Maak een derde instantie aan naast de twee bestaande.
*Verwacht:* alle drie staan los in de Files-lijst met eigen cijfers.
☐ OK — Screenshot — Opmerkingen: ______________

**B8 — Instantie verwijderen.** Verwijder één instantie.
*Verwacht:* de instantie is weg; de overige instanties en hun data blijven intact.
☐ OK — Screenshot — Opmerkingen: ______________

**B9 — Scenario opslaan en laden.** Sla een scenario op binnen een instantie, doe een edit, laad het scenario terug.
*Verwacht:* de instantie keert terug naar de opgeslagen staat.
☐ OK — Screenshot — Opmerkingen: ______________

**B10 — Config-isolatie bij edit.** Doe een config-wijziging in instantie A; controleer instantie B.
*Verwacht:* instantie B is onaangeroerd (geen lekkage van config tussen instanties).
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

**C9 — Redo na undo.** Doe een edit, undo, dan redo.
*Verwacht:* redo herstelt exact de bewerkte waarde en de cascade.
☐ OK — Screenshot — Opmerkingen: ______________

**C10 — Minimum-doelvoorraad-edit (L05).** Wijzig de minimum-doelvoorraad van een materiaal.
*Verwacht:* de productie-/inkoopplanning reageert waar de voorraad onder het doel zou zakken.
☐ OK — Screenshot — Opmerkingen: ______________

**C11 — Herhaalde edit op dezelfde cel.** Wijzig dezelfde cel twee keer achter elkaar, dan undo.
*Verwacht:* de undo keert terug naar de oorspronkelijke waarde (niet de tussenwaarde).
☐ OK — Screenshot — Opmerkingen: ______________

**C12 — Purchase receipt-edit (L06 inkoop).** Wijzig de purchase receipt (inkoopontvangst) van een ingekocht materiaal.
*Verwacht:* de voorraad (L04) en het purchase plan (L07) bewegen consistent mee.
☐ OK — Screenshot — Opmerkingen: ______________



## D. Dynamische producten

**D1 — Aangekocht product (MOQ + lead time).** Voeg een aangekocht product toe met MOQ 250 en lead time 2 maanden.
*Verwacht:* inkooplijnen aanwezig; geen order kleiner dan 250; orders schuiven de lead time naar voren.
☐ OK — Screenshot — Opmerkingen: ______________

**D2 — Geproduceerd met BOM + routing.** Voeg een geproduceerd product toe met een bestaand materiaal als component en een machine-routing.
*Verwacht:* productielijnen aanwezig; de machinegroep krijgt extra uren; de component krijgt afgeleide vraag.
☐ OK — Screenshot — Opmerkingen: ______________

**D3 — Mix-product (PAP-verdeling).** Voeg een mix-product toe met 30% aangekocht / 70% geproduceerd.
*Verwacht:* zowel inkoop- als productielijnen in de opgegeven verhouding.
☐ OK — Screenshot — Opmerkingen: ______________

**D4 — Financiële aansluiting (3 producten).** Controleer omzet en kosten van de drie testproducten.
*Verwacht:* omzet = prijs × volume; grondstof-/machinekost sluit aan; dashboardtotalen zijn meegegroeid.
☐ OK — Screenshot — Opmerkingen: ______________

**D5 — Product gebruikt een ánder toegevoegd product *(gemelde bug)*.** Voeg product B toe dat testproduct A (uit D1) als BOM-component gebruikt.
*Verwacht:* A staat in de componentenlijst (gemarkeerd 'toegevoegd'); B slaat op; A krijgt afgeleide vraag van B.
☐ OK — Screenshot — Opmerkingen: ______________

**D6 — Edge: MOQ groter dan de vraag.** Voeg een aangekocht product toe met een klein volume maar een grote MOQ.
*Verwacht:* de order is minstens de MOQ; er ontstaat overschot dat de voorraad opbouwt.
☐ OK — Screenshot — Opmerkingen: ______________

**D7 — Edge: bronbestand-nummer geweigerd.** Probeer een product toe te voegen met een materiaalnummer dat al in het bronbestand staat.
*Verwacht:* nette Nederlandse foutmelding; niets wordt toegevoegd.
☐ OK — Screenshot — Opmerkingen: ______________

**D8 — Edge: zelf-referentie geweigerd.** Probeer een product op te slaan dat zichzelf als component heeft.
*Verwacht:* foutmelding 'kan niet aan zichzelf gekoppeld worden'; niets opgeslagen.
☐ OK — Screenshot — Opmerkingen: ______________

**D9 — Product bewerken (upsert).** Open een bestaand testproduct, wijzig het volume en sla op.
*Verwacht:* de planning herberekent met de nieuwe waarde; er ontstaat geen duplicaat (zelfde nummer).
☐ OK — Screenshot — Opmerkingen: ______________

**D10 — Verwijderen + sessiewissel.** Wissel naar de andere instantie en terug; verwijder daarna één testproduct.
*Verwacht:* producten blijven bij hun eigen instantie; na verwijderen is het product overal weg en klopt de planning zonder het product.
☐ OK — Screenshot — Opmerkingen: ______________

**D11 — Mix-grenswaarden (0 en 1).** Voeg mix-producten toe met productiefractie 0 en 1.
*Verwacht:* fractie 0 = volledig inkoop, fractie 1 = volledig productie; geen dode velden.
☐ OK — Screenshot — Opmerkingen: ______________

**D12 — Startvoorraad + veiligheidsvoorraad.** Voeg een product toe met een startvoorraad en een veiligheidsvoorraad.
*Verwacht:* de voorraadlijn start op de startvoorraad en blijft boven de veiligheidsvoorraad.
☐ OK — Screenshot — Opmerkingen: ______________

**D13 — Component-product verwijderen.** Verwijder een toegevoegd product dat als component van een ander toegevoegd product is gebruikt.
*Verwacht:* nette afhandeling (waarschuwing/geen crash); de afhankelijke planning herberekent.
☐ OK — Screenshot — Opmerkingen: ______________

**D14 — Edge: BOM-cyclus geweigerd.** Probeer twee producten te maken die elkaar als component gebruiken (A→B→A).
*Verwacht:* de cyclus wordt geweigerd met een duidelijke Nederlandse melding.
☐ OK — Screenshot — Opmerkingen: ______________




## E. Grafiek-analyse

**E1 — Automatische detectie (financieel).** Vergroot de financiële grafiek en klik 'Analyse'.
*Verwacht:* paneel toont de grootste beweging met de verklarende producten; niets afgeknipt.
☐ OK — Screenshot — Opmerkingen: ______________

**E2 — Twee punten met verbindingspijl.** Klik twee punten in de grafiek.
*Verwacht:* een pijl verbindt de punten; het paneel verklaart precies dát verschil; de bijdragen tellen op tot ~het verschil.
☐ OK — Screenshot — Opmerkingen: ______________

**E3 — Volumegrafiek.** Analyseer een beweging in de volumegrafiek.
*Verwacht:* zelfde ervaring; bijdragen in eenheden i.p.v. euro's.
☐ OK — Screenshot — Opmerkingen: ______________

**E4 — FTE-drill naar producten.** Analyseer de FTE-grafiek en klik door.
*Verwacht:* je ziet door welke producten de FTE-verandering komt.
☐ OK — Screenshot — Opmerkingen: ______________

**E5 — Machinegrafiek-analyse.** Open de analyse op een machine-/capaciteitsgrafiek.
*Verwacht:* werkende analyse met uren per product.
☐ OK — Screenshot — Opmerkingen: ______________

**E6 — Voorraadkwaliteit-analyse.** Open de analyse op de voorraadkwaliteitsgrafiek.
*Verwacht:* logische uitsplitsing naar categorieën/producten.
☐ OK — Screenshot — Opmerkingen: ______________

**E7 — Top-movers naar tabel.** Klik 'naar tabel' op de top-movers.
*Verwacht:* de planningstabel filtert op die producten; je kunt direct een waarde aanpassen.
☐ OK — Screenshot — Opmerkingen: ______________

**E8 — Movers aanpasbaar (inputfout).** Pas via de top-mover-tabel een waarde aan.
*Verwacht:* de wijziging cascadeert normaal; de grafiek en het paneel bewegen mee.
☐ OK — Screenshot — Opmerkingen: ______________

**E9 — Excel-export van de analyse.** Exporteer de analyse.
*Verwacht:* Excel-bestand met dezelfde cijfers als het paneel.
☐ OK — Screenshot — Opmerkingen: ______________

**E10 — Edge: identieke punten.** Selecteer twee punten met (vrijwel) dezelfde waarde.
*Verwacht:* het paneel meldt netjes 'geen noemenswaardig verschil' i.p.v. een lege/foutieve uitsplitsing.
☐ OK — Screenshot — Opmerkingen: ______________

**E11 — Edge: dalende beweging.** Analyseer een duidelijke daling.
*Verwacht:* de bijdragen zijn negatief en verklaren de daling; tekens kloppen.
☐ OK — Screenshot — Opmerkingen: ______________

**E12 — Edge: analyse na een edit.** Doe een edit en heropen de analyse.
*Verwacht:* het paneel gebruikt de nieuwe cijfers, niet de oude.
☐ OK — Screenshot — Opmerkingen: ______________

**E13 — Analyse onder actieve groep.** Doe een analyse terwijl een materiaalgroep actief is.
*Verwacht:* de analyse werkt op de gescoopte cijfers; de bijdragen sluiten aan op het gescoopte totaal.
☐ OK — Screenshot — Opmerkingen: ______________

**E14 — Meerdere grafieken achter elkaar.** Analyseer 3 verschillende grafieken na elkaar zonder te herladen.
*Verwacht:* elke analyse is correct en onafhankelijk; geen restanten van de vorige.
☐ OK — Screenshot — Opmerkingen: ______________

**E15 — ROCE-grafiek-analyse.** Open de analyse op de ROCE-grafiek.
*Verwacht:* werkende analyse; de beweging wordt logisch verklaard (ratio-metric).
☐ OK — Screenshot — Opmerkingen: ______________

**E16 — Export bevat alle bijdragers.** Exporteer een analyse met meerdere bijdragers en open het bestand.
*Verwacht:* alle bijdragers uit het paneel staan in het Excel-bestand met de juiste delta's.
☐ OK — Screenshot — Opmerkingen: ______________

**E17 — Bewaar als groep vanuit analyse.** Klik 'Bewaar als groep' op de top-movers van een analyse.
*Verwacht:* er ontstaat een materiaalgroep met precies die producten.
☐ OK — Screenshot — Opmerkingen: ______________

**E18 — Analyse-drill en terug.** Klik in de analyse door op een product en weer terug.
*Verwacht:* de drill toont het productdetail; 'terug' keert netjes naar de grafiekanalyse.
☐ OK — Screenshot — Opmerkingen: ______________




## F. Materiaalgroepen

**F1 — Groep opslaan vanuit analyse.** Sla een groep op (bv. 'top 10 movers 04-26→06-26').
*Verwacht:* de groep verschijnt in de dropdown boven de tabel.
☐ OK — Screenshot — Opmerkingen: ______________

**F2 — Tweede groep opslaan.** Sla een tweede, andere groep op.
*Verwacht:* beide groepen staan in de dropdown; ze zijn los selecteerbaar.
☐ OK — Screenshot — Opmerkingen: ______________

**F3 — Combineren met linetype-filter.** Selecteer een groep en filter daarna op linetypes.
*Verwacht:* beide filters werken samen; alleen de gekozen lijnen van de groepsmaterialen.
☐ OK — Screenshot — Opmerkingen: ______________

**F4 — Terug naar 'Alle groepen' *(bugcheck 11-07)*.** Kies in de dropdown weer 'Alle groepen'.
*Verwacht:* álle rijen komen terug; je zit niet vast in de groepsweergave.
☐ OK — Screenshot — Opmerkingen: ______________

**F5 — Wisselen tussen twee groepen.** Wissel direct van groep 1 naar groep 2.
*Verwacht:* de tabel toont meteen de materialen van groep 2, geen mengbeeld.
☐ OK — Screenshot — Opmerkingen: ______________

**F6 — Maak actief (scoping).** Activeer een groep.
*Verwacht:* banner zichtbaar; dashboard toont de bijdragemarge van de groep; machines tonen de groepsuren; dropdown toont '· actief'.
☐ OK — Screenshot — Opmerkingen: ______________

**F7 — Bijdragemarge klopt.** Controleer de gescoopte financiële cijfers.
*Verwacht:* bijdragemarge = omzet − grondstof − machinekost; vaste kosten/EBIT/ROCE zijn bewust weggelaten.
☐ OK — Screenshot — Opmerkingen: ______________

**F8 — FTE/capaciteit blijven fabrieksbreed.** Bekijk FTE en capaciteit onder een actieve groep.
*Verwacht:* die blijven fabrieksbreed (eerlijkheidsregel); alleen omzet/kosten/volume zijn gescoopt.
☐ OK — Screenshot — Opmerkingen: ______________

**F9 — Analyse onder actieve groep.** Doe een grafiekanalyse met de groep actief.
*Verwacht:* gescoopte labels bekend; bijdragen sluiten aan op het gescoopte totaal.
☐ OK — Screenshot — Opmerkingen: ______________

**F10 — Groep hoort bij de instantie.** Wissel met actieve groep naar de andere instantie en terug.
*Verwacht:* de andere instantie kent de groep niet en is ongescoopt; terug is de groep nog actief.
☐ OK — Screenshot — Opmerkingen: ______________

**F11 — Actieve groep overleeft herstart.** Herstart de app met een groep actief.
*Verwacht:* na warm-up is de groep nog actief (banner + gescoopte cijfers).
☐ OK — Screenshot — Opmerkingen: ______________

**F12 — Lege doorsnede.** Filter met actieve groep op een linetype zonder groepsmateriaal.
*Verwacht:* nette uitleg + knop 'Herstel filters'; geen stille lege tabel.
☐ OK — Screenshot — Opmerkingen: ______________

**F13 — Deactiveren.** Zet de groep uit via 'Alle groepen'.
*Verwacht:* banner weg; dashboard en machines weer fabrieksbreed.
☐ OK — Screenshot — Opmerkingen: ______________

**F14 — Groep verwijderen.** Verwijder een opgeslagen groep.
*Verwacht:* de groep verdwijnt uit de dropdown; als hij actief was, wordt gedeactiveerd.
☐ OK — Screenshot — Opmerkingen: ______________

**F15 — Edge: groep met verwijderd materiaal.** Verwijder een materiaal/product dat in een groep zit en open de groep.
*Verwacht:* de groep negeert het ontbrekende materiaal netjes (geen crash, teller klopt).
☐ OK — Screenshot — Opmerkingen: ______________

**F16 — Edge: undo onder actieve groep.** Doe een edit onder een actieve groep en maak hem ongedaan.
*Verwacht:* undo herstelt alleen de edit; de actieve groep en scoping blijven intact.
☐ OK — Screenshot — Opmerkingen: ______________

**F17 — Edge: groep opslaan met huidige filters.** Filter de tabel en sla dan een groep op.
*Verwacht:* de groep bevat exact de zichtbare materialen op dat moment.
☐ OK — Screenshot — Opmerkingen: ______________

**F18 — Export blijft fabrieksbreed onder groep.** Exporteer met een actieve groep.
*Verwacht:* het exportbestand bevat de volledige fabriek (groepen scopen alleen de weergave).
☐ OK — Screenshot — Opmerkingen: ______________

**F19 — Groep = hele fabriek.** Maak een groep met alle materialen en activeer.
*Verwacht:* de gescoopte cijfers zijn gelijk aan de fabrieksbrede cijfers.
☐ OK — Screenshot — Opmerkingen: ______________

**F20 — Groep hernoemen.** Hernoem een opgeslagen groep.
*Verwacht:* de nieuwe naam staat in de dropdown en blijft na herstart.
☐ OK — Screenshot — Opmerkingen: ______________

**F21 — Edge: lege groepsnaam geweigerd.** Probeer een groep met een lege naam op te slaan.
*Verwacht:* nette foutmelding; er wordt geen groep aangemaakt.
☐ OK — Screenshot — Opmerkingen: ______________

**F22 — Groep met één materiaal.** Maak een groep met exact één materiaal en activeer.
*Verwacht:* de scoping werkt correct op dat ene materiaal (geen deling-door-nul in de marge).
☐ OK — Screenshot — Opmerkingen: ______________




## G. Machines & capaciteit

**G1 — OEE aanpassen.** Wijzig de OEE van één machine.
*Verwacht:* automatische herberekening; bezetting in tabel én grafiek consistent.
☐ OK — Screenshot — Opmerkingen: ______________

**G2 — Doeldoorzet (reverse-OEE).** Gebruik de directe doorzet-aanpassing.
*Verwacht:* de OEE wordt evenredig aangepast om de doeldoorzet te halen; herberekening volgt.
☐ OK — Screenshot — Opmerkingen: ______________

**G3 — Machine-drill naar producten.** Klik door op een machine.
*Verwacht:* je ziet welke producten uren draaien; de som klopt met het machinetotaal.
☐ OK — Screenshot — Opmerkingen: ______________

**G4 — OEE-override ongedaan maken.** Maak de OEE-wijziging ongedaan (undo/reset).
*Verwacht:* bezetting en FTE exact terug naar de oude waarden.
☐ OK — Screenshot — Opmerkingen: ______________

**G5 — FTE volgt capaciteit.** Vergelijk FTE-lijnen vóór/ná een forse capaciteitswijziging.
*Verwacht:* de FTE-behoefte beweegt logisch mee met de gedraaide uren.
☐ OK — Screenshot — Opmerkingen: ______________

**G6 — Capaciteits-override persistent.** Wijzig een capaciteitscel (L07/L09/L11/L12) en herstart de app.
*Verwacht:* de override staat er na de herstart nog en de cijfers kloppen.
☐ OK — Screenshot — Opmerkingen: ______________

**G7 — Edge: OEE = 0.** Zet de OEE van een machine op 0.
*Verwacht:* nette afhandeling (machine effectief buiten gebruik of duidelijke melding), geen deling-door-nul.
☐ OK — Screenshot — Opmerkingen: ______________

**G8 — Edge: unlimited-capacity machine.** Controleer een machine uit de 'unlimited capacity'-lijst.
*Verwacht:* die wordt nooit als bottleneck getoond; bezetting begrensd tot 100% beschikbaar.
☐ OK — Screenshot — Opmerkingen: ______________

**G9 — Bezetting boven 100%.** Verhoog de vraag zodat een machine overbelast raakt.
*Verwacht:* de grafiek toont de overbezetting duidelijk (>100%) i.p.v. stil af te kappen.
☐ OK — Screenshot — Opmerkingen: ______________

**G10 — Machine × groep-scoping.** Bekijk de machine-uren onder een actieve materiaalgroep.
*Verwacht:* de machinegrafiek toont de uren van de groepsmaterialen.
☐ OK — Screenshot — Opmerkingen: ______________

**G11 — Beschikbaarheid aanpassen.** Wijzig de beschikbaarheid (%) van een machine.
*Verwacht:* de capaciteit per periode schaalt mee; bezetting herberekend.
☐ OK — Screenshot — Opmerkingen: ______________

**G12 — Shift-uren aanpassen.** Wijzig de shift-uren per maand van een machine.
*Verwacht:* de beschikbare uren en de bezetting bewegen consistent mee.
☐ OK — Screenshot — Opmerkingen: ______________

**G13 — Machine-redo na undo.** Wijzig OEE, undo, dan redo.
*Verwacht:* redo herstelt de OEE-wijziging en de bezetting exact.
☐ OK — Screenshot — Opmerkingen: ______________

**G14 — Meerdere machine-edits + reset.** Doe drie machine-edits en klik reset.
*Verwacht:* alle machines staan exact terug op de baseline.
☐ OK — Screenshot — Opmerkingen: ______________




## H. Exports

**H1 — Planningsexport (structuur + waarden).** Exporteer het planningswerkboek en open het.
*Verwacht:* opent zonder reparatiemelding; structuur klopt; steekproef van 3 cellen = exact de UI-waarden.
☐ OK — Screenshot — Opmerkingen: ______________

**H2 — Export bevat de bewerkingen.** Doe een herkenbare edit en exporteer opnieuw.
*Verwacht:* de geëxporteerde cel toont de bewerkte waarde, niet de oorspronkelijke.
☐ OK — Screenshot — Opmerkingen: ______________

**H3 — Export bevat toegevoegde producten.** Exporteer met een toegevoegd product in de sessie.
*Verwacht:* het product staat met al zijn lijnen in de export.
☐ OK — Screenshot — Opmerkingen: ______________

**H4 — Export fabrieksbreed onder groep.** Activeer een groep en exporteer.
*Verwacht:* het bestand bevat de volledige fabriek (bewuste keuze).
☐ OK — Screenshot — Opmerkingen: ______________

**H5 — MoM-delta-export.** Exporteer de maand-over-maand-delta (indien vorige maand beschikbaar).
*Verwacht:* delta-werkboek met verschillen t.o.v. de vorige maand.
☐ OK — Screenshot — Opmerkingen: ______________

**H6 — DB-export (plat).** Draai de platte database-export.
*Verwacht:* één rij per materiaal × lijn × periode; aantallen plausibel.
☐ OK — Screenshot — Opmerkingen: ______________

**H7 — Analyse-export.** Exporteer een grafiekanalyse.
*Verwacht:* Excel met dezelfde cijfers als het analysepaneel.
☐ OK — Screenshot — Opmerkingen: ______________

**H8 — Edge: export direct na herstart.** Herstart en exporteer meteen (warme sessie).
*Verwacht:* de export klopt; geen lege of half-geladen data.
☐ OK — Screenshot — Opmerkingen: ______________

**H9 — Edge: export met commentaar.** Zet commentaar op een cel en exporteer.
*Verwacht:* de opmerking komt mee (of wordt netjes genegeerd) zonder de cijfers te verstoren.
☐ OK — Screenshot — Opmerkingen: ______________

**H10 — Twee instanties, aparte exports.** Exporteer beide instanties.
*Verwacht:* elk exportbestand hoort bij de juiste instantie (cijfers/perioden kloppen per instantie).
☐ OK — Screenshot — Opmerkingen: ______________

**H11 — FTE-sheet in de export.** Open de FTE requirements-sheet in de export.
*Verwacht:* de FTE-totalen per periode kloppen met het dashboard.
☐ OK — Screenshot — Opmerkingen: ______________

**H12 — Voorraadkwaliteit-sheet.** Open de Inventory quality-sheet in de export.
*Verwacht:* de categorieën/waarden kloppen met de UI-grafiek.
☐ OK — Screenshot — Opmerkingen: ______________

**H13 — Values-planning-sheet.** Steekproef 3 cellen uit de Values_Planning-sheet.
*Verwacht:* de financiële waarden komen exact overeen met de UI.
☐ OK — Screenshot — Opmerkingen: ______________

**H14 — DB-export-kolomstructuur.** Bekijk de kolomkoppen van de DB-export.
*Verwacht:* één rij per materiaal × lijn × periode met de verwachte kolommen (materiaal, lijn, periode, waarde, site).
☐ OK — Screenshot — Opmerkingen: ______________




## I. Afsluitend

**I1 — Geen fouten.** Blik terug over de hele sessie.
*Verwacht:* geen rode foutmeldingen of lege schermen gezien.
☐ OK — Screenshot — Opmerkingen: ______________

**I2 — Taal & meldingen.** Beoordeel de meldingen.
*Verwacht:* alle gebruikersgerichte meldingen in begrijpelijk Nederlands met handelingsperspectief.
☐ OK — Screenshot — Opmerkingen: ______________

**I3 — Consistentie tabel ↔ grafiek.** Vergelijk een paar tabelwaarden met de bijbehorende grafiek.
*Verwacht:* tabel en grafiek vertellen hetzelfde verhaal (geen divergentie).
☐ OK — Screenshot — Opmerkingen: ______________

**I4 — Consistentie dashboard ↔ detail.** Vergelijk een dashboard-KPI met de onderliggende detailregels.
*Verwacht:* de KPI is de correcte optelsom van de details.
☐ OK — Screenshot — Opmerkingen: ______________

**I5 — Herstart-stabiliteit.** Herstart de app een laatste keer.
*Verwacht:* alle instanties + data intact; cijfers identiek aan vóór de herstart.
☐ OK — Screenshot — Opmerkingen: ______________

**I6 — Opruimen.** Verwijder testproducten, testgroepen en de tweede instantie; draai masterdata-testwijzigingen terug.
*Verwacht:* verwijderen werkt netjes; de overige data blijft intact.
☐ OK — Screenshot — Opmerkingen: ______________

**I7 — Schone eindstaat.** Herstart nog een keer na het opruimen.
*Verwacht:* alleen de echte instantie(s) en data zijn er nog.
☐ OK — Screenshot — Opmerkingen: ______________

**I8 — Golden-parity intact.** Bevestig dat de kern onaangeroerd is (python main.py --test).
*Verwacht:* de pariteits-smoke slaagt; de single-file-flow is byte-identiek gebleven.
☐ OK — Screenshot — Opmerkingen: ______________

**I9 — Voorraad lopend saldo.** Steekproef: voorraad einde periode = begin + ontvangsten − vraag.
*Verwacht:* het lopende voorraadsaldo (L04) klopt over de periodeketen.
☐ OK — Screenshot — Opmerkingen: ______________

**I10 — Alle linetypes aanwezig.** Controleer dat alle verwachte linetypes (L01–L12) in de resultaten zitten.
*Verwacht:* geen ontbrekende lijnen; de EXPECTED_LINE_TYPES-set is compleet.
☐ OK — Screenshot — Opmerkingen: ______________

**I11 — Geen ongeldige cijfers.** Scan de resultaten op NaN/oneindig/None in numerieke velden.
*Verwacht:* alle waarden zijn geldige getallen (geen NaN/inf/None waar een getal hoort).
☐ OK — Screenshot — Opmerkingen: ______________

**I12 — Golden vs live steekproef.** Vergelijk een steekproef live-cijfers met de golden-baseline.
*Verwacht:* de kern is byte-identiek aan de golden-referentie (rekenkern onaangeroerd).
☐ OK — Screenshot — Opmerkingen: ______________


---

**Eindoordeel:** ☐ Alles akkoord ☐ Akkoord met opmerkingen ☐ Afwijkingen gevonden

**Handtekening / paraaf:** ______________

