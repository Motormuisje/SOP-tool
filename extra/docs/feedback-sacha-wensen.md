# Feedback op functionele wensen S&OP APEX (Sacha)

Status: concept ter afstemming. Antwoord opgebouwd rond de drie gevraagde
punten: technische haalbaarheid, impact op de huidige structuur, en indicatieve
prioritering/fasering. Tijdsinschattingen (in weken) zijn indicatief (incl.
testen) en deels afhankelijk van de openstaande vragen.

---

## Concept-mail

**Onderwerp:** RE: Functionele wensen S&OP APEX, haalbaarheid, impact en fasering

Hoi Sacha,

Bedankt voor het uitgebreide overzicht. Hieronder onze beoordeling, opgebouwd
rond de drie punten waar je feedback op vraagt: technische haalbaarheid, impact
op de huidige structuur, en indicatieve prioritering/fasering, plus een
indicatie van de benodigde tijd (in weken) aan onze kant. Een paar wensen kunnen
we pas scherp inschatten na een korte verduidelijking; die vragen staan onderaan.

### 1. Technische haalbaarheid

| Wens | Haalbaarheid |
|---|---|
| Bulk-aanpassing volumes (selectie + uniform +250) | Goed haalbaar. Celselectie bestaat al; alleen "pas waarde/delta toe op selectie" is nieuw |
| Opmerkingen per regel/machine/periode (+ user/datum) | Haalbaar (nieuw) |
| Doorklik per machine (volumes, historie, capaciteit) | Haalbaar; data is aanwezig, detailweergave is nieuw |
| Doorzet per machine vs capaciteit | Grotendeels aanwezig |
| Effective throughput aanpassen in machines-tab + auto-herrekenen | Indirect (via OEE/beschikbaarheid/shift) bestaat al. **Direct** een throughput-waarde invoeren en terugrekenen is nieuw maar haalbaar |
| Grafieken vergroten (popup) | Goed haalbaar |
| Projected Financial Metrics: trends, afwijkingen, inzoom/drill | Haalbaar; trends deels aanwezig, afwijking-visualisatie en drill zijn nieuw |
| Structurele integratie in de basis-Python | Haalbaar; past in onze werkwijze |
| Producten dynamisch toevoegen via Python | Haalbaar, maar ingrijpend; vraagt eerst ontwerp + proof-of-concept |
| Forecast: vaste defaultvolumes automatisch toevoegen | Haalbaar, maar we willen het gebruiksdoel eerst scherp krijgen (zie vraag onderaan) |
| Eén geïntegreerde oplossing (APEX + Python) | Deels: master sheet vervangen is goed haalbaar; een directe koppeling met jullie bronsysteem is lastiger en systeemafhankelijk |

### 2. Impact op de huidige structuur

We onderscheiden drie niveaus van impact:

**Laag (bouwt op bestaande bouwstenen, geen kernwijziging)**
- Grafieken vergroten (popup-infrastructuur bestaat al).
- Bulk-aanpassing (gebruikt de bestaande celselectie en de bestaande
  reken-cascade).
- Doorzet vs capaciteit (vooral presentatie van wat al berekend wordt).

**Middel (voegt nieuwe opslag of weergave toe)**
- Opmerkingen, forecast-defaultvolumes en een directe throughput-invoer voegen
  elk **nieuwe instelbare gegevens** toe. Die moeten correct bewaard en hersteld
  worden over sessies en herstarts heen, en op het juiste moment een
  herberekening triggeren. Dit is goed in te passen, maar het is precies het deel
  van de structuur waar we zorgvuldig moeten zijn (en waar de meeste testtijd in
  gaat zitten).
- Machine-drilldown en de uitbreiding van de financiële metrics voegen vooral
  nieuwe weergaven toe op bestaande data; beperkte structurele impact.

**Hoog (raakt de kern van het model)**
- Producten dynamisch toevoegen raakt de gedeelde datastructuren en de
  stuklijst-/berekeningsvolgorde van het hele model (forecast, productie/inkoop,
  capaciteit, financieel, export). Dit verdient een apart ontwerptraject met een
  proof-of-concept vóór bouw.
- De structurele basis-integratie en de geïntegreerde APEX+Python-oplossing zijn
  bewuste architectuurkeuzes; positief voor onderhoudbaarheid op termijn, maar
  apart te plannen.

### 3. Indicatieve prioritering / fasering

We stellen voor het werk op te delen in drie sprints. De inschatting hieronder
is indicatief.

| Sprint | Inhoud | Indicatie  |
|---|---|---|
| **Sprint 1 (quick wins, lage impact)** | Grafiek vergroten, bulk-aanpassing volumes, forecast-defaultvolumes | ~1 week |
| **Sprint 2 (uitbreidingen, nieuwe data/weergaven)** | Opmerkingen, machine-drilldown, directe effective throughput, financiële metrics (trend/afwijking/drill) | ~2 weken |
| **Sprint 3 (architectuur/strategie)** | Producten dynamisch toevoegen, structurele basis-integratie, geïntegreerde oplossing | apart te scopen na ontwerp/PoC |

Sprint 1 kunnen we vrijwel direct starten. Sprint 3 begint met een korte
werksessie + proof-of-concept, zodat we impact en tijd verantwoord kunnen
vastleggen voordat we bouwen.

### Leveringsstrategie / timing

De vraag is vooral *wanneer* jullie wat in handen willen hebben. Twee opties:

**Optie A (Sprint 1 los opleveren, incrementeel)**
We leveren het product van Sprint 1 direct op, en starten daarna Sprint 2.
- *Voordeel:* snelle, zichtbare meerwaarde; jullie kunnen de quick wins meteen
  gebruiken en de richting valideren vóór de grotere investering van Sprint 2;
  laag risico.
- *Nadeel:* twee opleveringen i.p.v. één; iets meer release-overhead.

**Optie B (Sprint 1 + 2 samen opleveren, Sprint 3 apart)**
We bundelen Sprint 1 en 2 tot één release en plannen Sprint 3 los (omdat die
naar verwachting meer tijd en een ontwerptraject vraagt).
- *Voordeel:* één samenhangend, vollediger pakket; minder release-momenten.
- *Nadeel:* langere wachttijd tot de eerste oplevering (~3 weken i.p.v. ~1);
  feedback komt later.

**Onze aanbeveling:** Optie A. Sprint 1 bestaat uit laag-risico quick wins die
snel waarde opleveren en jullie de kans geven om vroeg bij te sturen. Sprint 2
volgt als tweede release, en Sprint 3 pakken we als apart ontwerp-eerst traject.
Mocht je liever in één keer een vollediger geheel ontvangen, dan is Optie B
prima haalbaar; laat ons weten wat qua timing het beste past.

### Nog even afstemmen (zodat we de inschatting kunnen aanscherpen)

1. Opmerkingen: vrije tekst of een gestructureerde reden-code? En wel/niet mee in
   de Excel-export?
2. Effective throughput: wil je een **directe** invoer (welke eenheid, bijv.
   stuks/uur of stuks/maand, en hoe moet die terugwerken: als schaalfactor op de
   output of als aangepaste capaciteit), of volstaat de bestaande indirecte route
   via OEE/beschikbaarheid/shift?
3. Afwijkingen in de financiële metrics: t.o.v. welke referentie (vorige cyclus,
   budget/target, of vorige berekening)?
4. Forecast vaste defaultvolumes: kun je het gebruiksdoel toelichten? Concreet:
   in welke situatie wil je vaste volumes automatisch toevoegen, op welk niveau
   (per product, per productgroep of globaal), en alleen waar de forecast leeg is
   of altijd erbovenop?
5. Geïntegreerde oplossing: in welke mate willen jullie integreren? We zien drie
   gradaties: (a) de master sheet vervangen door beheer in Python/config (goed
   haalbaar, neemt al veel dubbele logica en losse-bestand-afhankelijkheden weg),
   (b) een gedeeltelijke koppeling, of (c) een volledige directe pipeline met
   jullie bronsysteem (lastiger en sterk afhankelijk van wat dat systeem aan
   export/API biedt).
6. Producten dynamisch toevoegen: harde wens op korte termijn, of vooral een
   richtingvraag?

Zodra we hier helderheid op hebben, scherpen we de inschatting aan en stellen we
een concrete planning per sprint voor.

Met vriendelijke groet,
[Abdel / Anas]



