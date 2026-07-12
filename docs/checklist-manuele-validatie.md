# Checklist manuele validatie — Apex Rainier fase 3

**Uitgevoerd door:** ______________  **Datum:** ______________
**Versie/commit:** `86e0237` (tag `milestone-fase-3`)

Doorloop de checks in volgorde — samen vormen ze één sessie van ± 45–60 min.
Vink af, plak per check een screenshot (in de Word-versie in `exports/`) en
noteer afwijkingen. Verwacht gedrag staat bij elke check; wijkt iets af,
noteer dan wat je zag i.p.v. wat er had moeten staan.

**Voorbereiding:** `python main.py` → browser opent op de app. Houd een
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

## B. Sessies & persistentie

**B1 — Nieuwe instantie.** Maak een tweede instantie aan, upload het
werkboek, Calculate.
*Verwacht:* tabel gevuld; perioden lopen van de planningsmaand t/m 12
maanden vooruit; geen foutmeldingen.
☐ OK — Screenshot — Opmerkingen: ______________

**B2 — Wisselen.** Wissel een paar keer tussen beide instanties.
*Verwacht:* waarden, config-velden én filters horen telkens bij de gekozen
instantie; niets "lekt" mee van de vorige.
☐ OK — Screenshot — Opmerkingen: ______________

**B3 — Herstart.** Sluit de app volledig af en start opnieuw.
*Verwacht:* beide instanties staan er nog; na warm-up tonen ze dezelfde
cijfers als vóór de herstart.
☐ OK — Screenshot — Opmerkingen: ______________

## C. Bewerkingen & cascade

**C1 — Forecast-edit.** Wijzig één L01-cel (demand forecast) fors, bv. ×2.
*Verwacht:* L03/L04/L06 van dat materiaal bewegen mee; de machinegrafiek
van de betrokken machinegroep verandert; tabel en grafiek vertellen
hetzelfde verhaal.
☐ OK — Screenshot — Opmerkingen: ______________

**C2 — Undo.** Maak de edit ongedaan.
*Verwacht:* alle afgeleide lijnen exact terug naar de oude waarden.
☐ OK — Screenshot — Opmerkingen: ______________

**C3 — Reset.** Doe twee edits (L01 + L06), klik daarna Reset.
*Verwacht:* alles terug naar de baseline; de bewerkingenlijst is leeg.
☐ OK — Screenshot — Opmerkingen: ______________

**C4 — Commentaar.** Zet een commentaar op een cel, herstart de app.
*Verwacht:* commentaar-indicator zichtbaar en de tekst blijft bewaard.
☐ OK — Screenshot — Opmerkingen: ______________

## D. Dynamische producten

**D1 — Product toevoegen (mix).** Voeg een product toe met sourcing "mix",
inclusief MOQ en een BOM-regel; sla op.
*Verwacht:* volledige herberekening; het product heeft alle relevante
lijnen (L01 t/m L12 waar van toepassing) én verschijnt in de financiële
cijfers (omzet/kosten sluiten aan bij prijs × volume).
☐ OK — Screenshot — Opmerkingen: ______________

**D2 — Product overleeft wisselen.** Wissel naar de andere instantie en
terug.
*Verwacht:* het toegevoegde product staat er nog met dezelfde cijfers; de
andere instantie heeft het product níét.
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

**E3 — FTE-drill.** Analyseer de FTE-grafiek en klik door.
*Verwacht:* je ziet door welke producten de FTE-verandering komt.
☐ OK — Screenshot — Opmerkingen: ______________

**E4 — Naar tabel.** Klik "naar tabel" op de top-movers.
*Verwacht:* de planningstabel filtert op die producten en je kunt er direct
een waarde aanpassen (inputfout-scenario).
☐ OK — Screenshot — Opmerkingen: ______________

**E5 — Analyse-export.** Exporteer de analyse.
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

**F6 — Deactiveren.** Zet de groep weer uit (dropdown → "Alle groepen").
*Verwacht:* banner weg; dashboard en machines weer fabrieksbreed.
☐ OK — Screenshot — Opmerkingen: ______________

**F7 — Lege doorsnede.** Activeer de groep en filter op een linetype die
geen groepsmateriaal heeft.
*Verwacht:* nette uitleg + knop "Herstel filters" (geen stille lege tabel).
☐ OK — Screenshot — Opmerkingen: ______________

## G. Machines & capaciteit

**G1 — OEE aanpassen.** Wijzig de OEE van één machine.
*Verwacht:* automatische herberekening; bezetting in tabel én grafiek
consistent.
☐ OK — Screenshot — Opmerkingen: ______________

**G2 — Machine-drill.** Klik door op een machine.
*Verwacht:* je ziet welke producten uren op die machine draaien.
☐ OK — Screenshot — Opmerkingen: ______________

## H. Exports

**H1 — Planningsexport.** Exporteer het planningswerkboek en open het.
*Verwacht:* structuur klopt (lijnen, perioden, groepering); steekproef van
3 cellen = exact de UI-waarden.
☐ OK — Screenshot — Opmerkingen: ______________

**H2 — MoM-export** *(indien vorige maand beschikbaar)*.
*Verwacht:* delta-werkboek met verschillen t.o.v. de vorige maand.
☐ OK — Screenshot — Opmerkingen: ______________

## I. Afsluitend

**I1 — Geen fouten.** Blik terug over de hele sessie.
*Verwacht:* geen rode foutmeldingen of lege schermen gezien; alle meldingen
waren in het Nederlands en begrijpelijk.
☐ OK — Opmerkingen: ______________

**I2 — Opruimen.** Verwijder het testproduct (D1), de testgroep (F1) en de
tweede instantie (B1) als je die niet houdt.
*Verwacht:* verwijderen werkt netjes en de overige data blijft intact.
☐ OK — Opmerkingen: ______________

---

**Eindoordeel:** ☐ Alles akkoord ☐ Akkoord met opmerkingen ☐ Afwijkingen gevonden

**Handtekening / paraaf:** ______________
