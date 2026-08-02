# Richtlijnen voor validatie-screenshots (lessen uit de review)

Algemene lessen uit de screenshot-review, toe te passen op elke check.

1. **Toon de volledige keten, niet alleen het eindresultaat.** Bij een
   wijziging: uitgangssituatie → de plek waar je het wijzigt (invoer/config)
   → het resultaat. Vaak 3 beelden (bv. A5, A9, A11, A12, B4, C9, C11).
2. **Toon het bedieningselement/de invoer zelf**, niet alleen het effect: de
   config-pagina met het gewijzigde veld, de grid waar je typt (A11, A12, B6,
   B10).
3. **Toon het effect op het JUISTE, specifieke object.** Bij een prijswijziging
   de financiële regel van dát product, niet een generiek totaaloverzicht (A5).
4. **Gebruik parallelle Excel-validatie** voor cijfermatige claims waar dat kan
   (A8, A10). Bewaar die screenshots.
5. **Het gecontroleerde element moet daadwerkelijk zichtbaar zijn** in het beeld
   (de commentaar-indicator bij C8).
6. **Wijzig realistisch en voldoende** — meerdere maanden/een merkbare stap,
   niet één cel — zodat het effect zichtbaar is (C10).
7. **Correcte, consistente vakterminologie** in titels en notities
   ("purchase receipt", niet een eigen vertaling) (C12).
8. **Elke screenshot toont het onderwerp van de check** — geen ongerelateerde
   of restant-data (B5, en het restant-testproduct bij B9).
9. **Screenshots leggen soms echte zaken bloot** — neem die serieus. Negatieve
   voorraad bleek by-design (backorder, matcht Excel); "001" bleek een
   restant-testproduct dat opgeruimd moest worden (B9). De parallelle
   Excel-run legde een grondstofkost-verschil op 2 materialen bloot (zie
   `bevinding-parallelle-run-grondstofkost.md`) — nooit stilzwijgend
   wegpoetsen of een formule aanpassen; karakteriseren en flaggen.
10. **Parallelle run als bewijslaag.** Voor cijfermatige checks: draai de
    app-rekenkern parallel naast het klant-Excel-model op hetzelfde
    bronbestand en toon een vergelijkingspaneel (App | Klant-Excel | Δ). De
    Excel-outputsheets (Planning/Values_Planning) zijn formule-gedreven en
    via Excel-COM uit te lezen; Δ=0 is het sterkste parallel-run-bewijs
    (P_*.png bij E1/E3/F7/H1/H13/I9/I12).
11. **Wees eerlijk in het paneel.** Toon nooit een valse Δ=0. Waar iets
    afwijkt (F7 grondstofkost): componenten die matchen groen, de afwijkende
    rood, met verwijzing naar de bevinding. Eerlijk bewijs is meer waard dan
    mooi bewijs.
12. **Spiegel de edit in beide engines.** Voor edit-tests: voer dezelfde edit uit
    in de app én in de klant-Excel (formule-model), en bewijs dat de productabel
    én de consolidatie meebewegen (Δ=0). Niet elk edit-type is spiegelbaar —
    volume/prijs/kost wél, machine/valuatie/product-add niet (statische Excel-
    lagen). Zie `parallelle-run-methodiek.md` voor de dekkingsmatrix.
13. **Uitputtende review vindt wat losse controles missen.** Een tweede
    verschil (directe FTE-kost) kwam pas boven bij de volledige consolidatie-
    vergelijking; het bleek de eerste (grondstofkost) bijna op te heffen (EBIT
    +0,8%). Vergelijk álle regels, niet alleen de verwachte. En let op
    neveneffecten: verificatie-runs kunnen de masterdata-store vervuilen —
    altijd met try/finally reverten en de eindstaat tegen de baseline checken.
