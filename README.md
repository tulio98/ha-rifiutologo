# Il Rifiutologo per Home Assistant

**Il calendario della raccolta porta a porta del Gruppo Hera dentro Home Assistant**, con
le entità giuste per farsi avvisare la sera in cui bisogna mettere fuori il sacco.

[![hacs][badge-hacs]][hacs]
[![Home Assistant][badge-ha]](#requisiti)
[![Licenza MIT][badge-licenza]](LICENSE)

[![Apri in HACS][badge-apri]][apri-hacs]

> **In English** — Home Assistant integration for the kerbside waste collection calendar of
> Gruppo Hera and its local companies (AcegasApsAmga in Padua and Trieste, Marche Multiservizi,
> Hera in Emilia-Romagna): 181 Italian municipalities. It creates a calendar entity, a
> "put it out tonight" binary sensor and three sensors. The address is picked from three
> searchable dropdowns. Unofficial, community-made, not affiliated with Gruppo Hera.

---

## Perché

Il servizio **Il Rifiutologo** pubblica un dato che quasi nessuno usa per intero:

> La data del calendario **non è il giorno in cui passa il camion. È la sera in cui si espone.**

A Padova il gestore dichiara per esempio *«dalle 20:00 alle 24:00»* per l'esposizione e
*«dalle 05:00 del giorno successivo»* per la raccolta. Sono due cose diverse, e confonderle
vuol dire mandarsi una notifica il giorno dopo, quando il sacco è già stato ritirato — o non
ritirato.

Questa integrazione tiene quel dato, e ci costruisce sopra le entità.

## Che cosa crea

Per ogni indirizzo configurato nasce un dispositivo con queste entità:

| Entità | Che cos'è | A cosa serve |
|---|---|---|
| **Calendario esposizioni** (`calendar`) | Tutte le sere dell'anno; il suo **stato** dice se in questo momento si può esporre — `Si può esporre` / `Non adesso` | La [card della settimana](#in-dashboard), il pannello Calendario, e i trigger `calendar` con `offset` |
| **Da esporre stasera** (`sensor`) | `Organico, Carta` oppure `nessuna` | Il testo della notifica |
| **Inizio esposizione** (`sensor`) | L'istante in cui la finestra si apre | `device_class: timestamp`: Home Assistant lo legge da sé come «Tra 3 ore», «Domani», «1 ora fa» |
| **Esposizione stasera** (`binary_sensor`) | Acceso finché c'è tempo per esporre | Il mattone delle automazioni |
| **Zona di raccolta** (`sensor`) | `Calendario Padova Q6 2026` | Controllare di aver preso il calendario giusto (diagnostica, disattivata di serie) |

Quattro sono accese di serie e rispondono a quattro domande diverse; la quinta, *Zona di
raccolta*, è diagnostica e nasce spenta. Stasera alle 20:20, a Padova Q2, la pagina dice:

```text
Calendario esposizioni ........ Si può esporre
Da esporre stasera ............ Indifferenziato, Organico
Inizio esposizione ............ 1 ora fa
Esposizione stasera ........... Sì
```

Domani mattina alle 10 le stesse righe dicono **«Non adesso» · «nessuna» · «Domani» · «No»**.

> **Quattro entità sono state ritirate nella 0.6.0**: *Finestra di esposizione aperta*
> (adesso è lo stato del calendario), *Prossima raccolta* e *Giorni alla prossima*
> (entrambe dentro *Inizio esposizione*, che in più sa l'ora e si legge da sola), e
> *Raccolte in settimana* (l'agenda è passata sugli attributi del calendario). Chi
> aggiorna non le trova più: l'integrazione le toglie dal registro da sola, al primo
> avvio, invece di lasciarle lì in stato «non disponibile».

> **Gli `entity_id` dipendono dalla lingua di Home Assistant**, perché li genera lui dal nome
> dell'entità: in italiano diventano `sensor.<indirizzo>_da_esporre_stasera`, in inglese
> `sensor.<indirizzo>_waste_to_put_out_tonight`. Negli esempi qui sotto c'è `CAMBIAMI`:
> aprine il dispositivo e copia gli id veri.
>
> Le entità **per frazione** sono a metà: il nome della frazione lo scrive il gestore
> (`Organico`, `Imballaggi in vetro`) e resta uguale in ogni lingua, ma il calendario porta
> davanti la parola «Calendario» — `Calendar` in inglese — per non chiamarsi come il
> sensore della stessa frazione.

Le entità che descrivono **una sera di raccolta** — *Esposizione stasera*, *Da esporre
stasera* e *Inizio esposizione* — portano con sé questi attributi:

| Attributo | Contenuto |
|---|---|
| `frazioni` | `["Indifferenziato", "Organico"]` |
| `colori` | `{"Organico": "#701100", ...}` — la palette **ufficiale** del gestore |
| `data` | la data della sera di esposizione |
| `giorni_mancanti` | `0` vuol dire stasera; non scende mai sotto zero |
| `giorno_settimana` | il numero ISO del giorno: `1` è lunedì, `7` è domenica |
| `inizio_esposizione` / `fine_esposizione` | i due istanti veri della finestra, in ISO con il fuso; la fine può cadere il giorno dopo |
| `orario_esposizione` | la frase del gestore, **solo se vale per tutte le frazioni della sera** |
| `orari_esposizione` | mappa frazione → orario: dice sempre la verità |
| `orario_raccolta` / `orari_raccolta` | idem, per il passaggio del mezzo |
| `note` / `note_per_frazione` | la nota del gestore, con la stessa regola: lo scalare solo se vale per tutte |
| `straordinario` | se il gestore segnala una raccolta eccezionale |

*Zona di raccolta* espone invece `pdf`, `allegati` e `nota`.

### La settimana, negli attributi del calendario

**Calendario esposizioni** risponde anche alla domanda «quante volte esco da qui a
domenica»: nei suoi attributi c'è una voce per **sera**, non per bidone — due frazioni la
stessa sera fanno una voce sola.

> **Se quello che cerchi è vedere la settimana, non è qui.** Da Home Assistant 2026 la
> schermata che si apre cliccando un'entità non mostra **nessun** attributo: stanno
> dietro **⋮ → Dettagli**, e quel menù compare solo agli amministratori. Gli attributi
> qui sotto sono il canale per **template, automazioni e card** — per gli occhi c'è la
> [card `calendar` in vista settimanale](#in-dashboard), che è fatta apposta.

| Attributo | Contenuto |
|---|---|
| `calendario` | **il calendario della settimana, da leggere a occhio**: `mer 16/09 → Indifferenziato, Organico` |
| `da` / `a` | i due estremi della finestra: oggi e oggi più sei giorni |
| `frazioni` | tutte quelle che compaiono nella settimana, nell'ordine in cui capitano |
| `giorni` | una voce per sera, **con gli stessi attributi della tabella qui sopra** |

`calendario` è un dizionario **piatto**, e la forma non è un capriccio. Aprendo l'entità,
Home Assistant disegna così un attributo fatto di dizionari — cioè `giorni`:

```text
- frazioni:
    - Indifferenziato
    - Organico
  colori:
    Indifferenziato: '#7C7C81'
  data: '2026-09-16'
  …altre dodici righe, per UN giorno
```

e così un dizionario piatto — cioè `calendario`:

```text
mer 16/09: Indifferenziato, Organico
ven 18/09: Organico
dom 20/09: Carta
lun 21/09: Organico
```

Una lista di stringhe finirebbe tutta su una riga sola, unita da virgole: il dizionario
piatto è **l'unica forma che venga fuori a righe**. I due attributi non sono due verità
diverse — `calendario` è la proiezione leggibile di `giorni`, calcolata dalla stessa
agenda nello stesso istante — e `giorni` resta perché le date, gli orari e i colori
dai nomi abbreviati non si ricavano.

I nomi dei giorni seguono la **lingua di Home Assistant**: italiano e inglese sono
tradotti, ogni altra lingua ripiega sull'inglese, come fa Home Assistant con qualunque
testo che non ha.

Le regole sono quelle di tutto il resto dell'integrazione, non altre:

- una sera già chiusa **sparisce**, anche se è quella di oggi — nel centro storico di
  Modena si espone dalle 00:00 alle 07:00, e a mezzogiorno oggi è già andato;
- una sera ancora aperta **resta**, anche se è quella di ieri — a Bologna alle due di
  notte il sacco va ancora messo fuori. È l'unico caso in cui l'elenco comincia prima di `da`;
- di ogni sera restano **solo le frazioni non scadute**, esattamente come in *Da esporre stasera*.

Finché per stasera c'è qualcosa da esporre, la prima voce di `giorni` è la stessa sera che
racconta *Da esporre stasera*: guardano lo stesso elenco e non possono dire cose diverse.
Quando stasera non tocca, le due divergono **di proposito**: *Da esporre stasera* dice
`nessuna`, mentre `giorni` è già passato alla prima sera utile, che è il suo mestiere.

### I calendari a colori

Attivando **«Un calendario per ogni frazione»** nelle opzioni nasce un'entità calendario per
ogni tipo di rifiuto, ciascuna con il colore che le assegna il gestore — e non un colore
inventato: arriva dal campo `pittogramma.colore` dell'API.

| Frazione (Padova) | Colore |
|---|---|
| Organico | ![](docs/colori/701100.png) `#701100` |
| Indifferenziato | ![](docs/colori/7C7C81.png) `#7C7C81` |
| Carta | ![](docs/colori/0093D0.png) `#0093D0` |
| Imballaggi in vetro | ![](docs/colori/15A53F.png) `#15A53F` |
| Lattine | ![](docs/colori/FDB913.png) `#FDB913` |
| Imballaggi in plastica | ![](docs/colori/FDB913.png) `#FDB913` |

Lattine e plastica hanno lo stesso colore perché il gestore le fa esporre insieme.
I colori li disegna Home Assistant **dalla 2026.2** in poi — `CalendarEntity.initial_color`
non esiste nella 2026.1 ed esiste nella 2026.2 — e sulla 2026.1, che è il minimo che questa
integrazione dichiara, i calendari separati funzionano lo stesso, semplicemente senza tinta.

### Un sensore per ogni frazione

> Le due opzioni per frazione si possono accendere **insieme**: nascono un calendario e un
> sensore per ogni tipo di rifiuto, e si distinguono dal nome — *Carta* è il sensore, che
> dice la data; *Calendario Carta* è il calendario, che serve alla card a colori.

Attivando **«Un sensore per ogni frazione»** nasce un sensore per tipo di rifiuto — a
Padova sei: *Organico*, *Indifferenziato*, *Carta*, *Lattine*, *Imballaggi in plastica*,
*Imballaggi in vetro*. Risponde alla domanda che il calendario complessivo non risponde:
**e il vetro quando passa?**

Lo stato è la data della prossima esposizione di quella frazione (`device_class: date`).
Negli attributi:

| Attributo | Contenuto |
|---|---|
| `frazione` | il nome, come lo scrive il gestore |
| `colore` | il colore ufficiale di quella frazione |
| `giorni_mancanti` | `0` vuol dire stasera |
| `giorno_settimana` | `1` è lunedì, `7` è domenica |
| `inizio_esposizione` / `fine_esposizione` | la finestra **di quella frazione**, che nella stessa sera può differire dalle altre |
| `orario_esposizione` / `orario_raccolta` | le frasi del gestore |
| `nota` / `straordinario` | quello che il gestore segnala su quel conferimento |
| `prossime` | le prossime cinque date, per vedere il passo a colpo d'occhio |

**Non guarda mai indietro**: un sensore `date` che pubblica ieri è un sensore che mente.
Per sapere se stanotte si è ancora in tempo c'è *Esposizione stasera*.

## «Adesso» e «stasera» non sono la stessa cosa

È la distinzione che serve di più e che si nota di meno.

| | Si accende | Si spegne | Risponde a |
|---|---|---|---|
| **Esposizione stasera** (`binary_sensor`) | a mezzanotte del giorno di raccolta | quando l'ultima finestra si chiude | «oggi tocca, e sono ancora in tempo?» |
| **Calendario esposizioni** (`calendar`) | all'ora dichiarata dal gestore (19:00, 20:00…) | alla stessa ora dell'altro | «posso uscire **adesso**?» |

Alle sei di sera del giorno della carta il primo dice sì e il secondo dice no — ed è la
risposta giusta: il sacco fuori a quell'ora è fuori regolamento.

Lo stato del calendario **è** la finestra di esposizione, non una sua approssimazione: gli
istanti dei suoi eventi li danno le stesse due funzioni che accendono i sensori. C'è un
test che confronta le due cose minuto per minuto, su tutte le forme in cui il gestore
scrive l'orario.

Dove il gestore **non** dichiara un'apertura — «entro le 04:00» è un termine, non un
inizio — la finestra vale da mezzanotte, perché in quel caso non c'è nessun'ora prima
della quale sia vietato esporre.

## L'orario di esposizione, che cambia da comune a comune

Questo è il punto in cui è più facile sbagliare, e l'integrazione lo tratta in quattro modi
perché il gestore lo dichiara in quattro modi. Sono tutti e quattro verificati sul backend:

| Come lo dichiara il gestore | Esempio | Che cosa ne fa l'integrazione |
|---|---|---|
| Finestra dentro la giornata | **Padova** `20:00 → 24:00` | Evento dalle 20:00 alla mezzanotte |
| Finestra che **scavalca la mezzanotte** | **Bologna** `20:00 → 06:00` | Evento fino alle 06:00 **del giorno dopo**; alle due di notte il sensore è ancora acceso |
| Inizio uguale a fine, testo *«entro le…»* | **Faenza** `04:00 → 04:00`, *«entro le 04:00»* | È una **scadenza**, non una durata: l'evento resta giornaliero e la frase esatta del gestore finisce nella descrizione |
| Inizio uguale a fine, testo *«dalle…»* | `20:00 → 20:00`, *«dalle 20:00»* | È un'**apertura** senza chiusura dichiarata: l'evento va dalle 20:00 a mezzanotte, che è la scadenza che l'integrazione usa ovunque quando il gestore non ne dichiara una |

Gli ultimi due casi hanno la stessa forma numerica e significato opposto: a distinguerli è
**il testo che scrive il gestore**, non un'ipotesi. Censendo il backend, la forma
`inizio = fine` compare 5.836 volte come «entro le» e 1.382 volte come «dalle».
E quando il gestore non dichiara una durata, l'integrazione non se la fabbrica.

🔴 **E l'orario cambia anche dentro lo stesso comune.** A Padova non c'è un orario «di
Padova»: campionando gli indirizzi, il Quartiere 2 espone `19:00 → 24:00`, gli altri
quartieri `20:00 → 24:00`, e in Quartiere 4 compare perfino un `entro le 24:00`, cioè la
forma senza finestra. È il motivo per cui l'integrazione **chiede** l'orario indirizzo per
indirizzo invece di ricavarlo dal comune: cablarlo sarebbe stato più semplice e sbagliato
per un residente su cinque.

Conseguenze pratiche, tutte e tre da tenere a mente:

1. **«Esposizione stasera» si spegne alla chiusura della finestra, non a mezzanotte.** A
   Padova coincidono; a Bologna no.
2. **Anche «Inizio esposizione» guarda la finestra**, non solo la data. A Modena si espone
   *dalle 00:00 alle 07:00*: dalle 07:00 in poi la raccolta di oggi è chiusa, e indicare
   oggi mentre il sensore dell'esposizione è spento sarebbero due entità che si
   contraddicono.
3. **Le frazioni scadute spariscono dall'elenco.** A Gradara una frazione chiude alle 23:00 e
   l'altra alle 06:00: dopo le 23:00 «Da esporre stasera» nomina solo la seconda.

E da qui nasce una distinzione che vale la pena tenere a mente, perché le due entità
rispondono a due domande diverse:

- **«Esposizione stasera»** e **«Da esporre stasera»** dicono *che cosa si può ancora
  mettere fuori adesso*. A Bologna, alle due di notte, parlano ancora della sera prima — ed
  è giusto.
- **«Inizio esposizione»** guarda solo in avanti: la prima raccolta la cui data non è
  passata **e** la cui finestra non è ancora chiusa. Non indica mai un giorno passato, e non
  dice mai «oggi» quando per oggi non c'è più niente da fare. Nella sera stessa mostra
  l'apertura di stasera — «1 ora fa» vuol dire che la finestra è aperta da un'ora.

## Chi è coperto

I **181 comuni** serviti dal Gruppo Hera e dalle sue società territoriali. L'elenco non è
cablato qui dentro: viene chiesto al gestore ogni volta, quindi resta aggiornato da solo.

| Zona | Quanti | Qualche nome |
|---|---|---|
| Bologna e provincia | 47 | Bologna, Budrio, Casalecchio di Reno, Baricella |
| Pesaro e Urbino (Marche Multiservizi) | 38 | Pesaro, Urbino, Urbania, Cagli, Fermignano |
| Modena e provincia | 32 | Modena, Formigine, Fiorano Modenese, Castelfranco Emilia |
| Ravenna e provincia | 18 | Ravenna, Faenza, Cervia, Bagnacavallo |
| Rimini e provincia | 18 | Rimini, Cattolica, Bellaria Igea Marina, Riccione |
| Forlì-Cesena | 17 | Cesena, Cesenatico, Gambettola, Bagno di Romagna |
| **Padova (AcegasApsAmga)** | 6 | Padova, Abano Terme, Albignasego, Noventa Padovana, Ponte San Nicolò, Casalserugo |
| **Trieste (AcegasApsAmga)** | 1 | Trieste |
| Ferrara | 1 | Ferrara |
| Firenze (alta valle) | 3 | Firenzuola, Marradi, Palazzuolo sul Senio |

Se il tuo comune non è in questa tendina, il gestore non lo serve con Il Rifiutologo:
**Forlì, Fano e Selvazzano Dentro, per esempio, non ci sono**, anche se le rispettive
province sono coperte.

## Requisiti

- **Home Assistant 2026.1.0** o successivo
- Un indirizzo con la **raccolta porta a porta**. Attenzione: non tutti ce l'hanno. A Padova
  circa un indirizzo su tre è servito da cassonetti stradali o isole ecologiche, e per quelli
  il gestore non pubblica nessun calendario. L'integrazione **te lo dice durante la
  configurazione** invece di lasciarti con entità mute.

## Installazione

### Con HACS (consigliato)

1. HACS → menu in alto a destra → **Repository personalizzati**
2. Repository: `https://github.com/tulio98/ha-rifiutologo` — Tipo: **Integration**
3. Cerca **Il Rifiutologo**, installa
4. **Riavvia Home Assistant**

[![Apri in HACS][badge-apri]][apri-hacs]

### A mano

Copia la cartella `custom_components/rifiutologo/` dentro la tua `config/custom_components/`
e riavvia Home Assistant.

## Configurazione

**Impostazioni → Dispositivi e servizi → Aggiungi integrazione → Il Rifiutologo**

Tre passi, tutti con una **casella di ricerca**, tutti alimentati dall'elenco vero del gestore:

1. **Comune** — 181 voci
2. **Via** — a Padova sono 2200: **si cercano, non si scorrono**
3. **Civico** — sono stringhe: esistono `1/A`, `1/SNC`, `2/2`

Scrivi **qualunque pezzo** del nome, anche in mezzo: `bernardo` trova `VIA BERNARDO
TREVISAN`, e `bernardo trevisan` pure. Serve, perché a Padova quasi tutte le vie cominciano con «VIA» e una
ricerca che guardasse solo l'inizio non filtrerebbe niente.

> Se scrivi qualcosa che nell'elenco del gestore non c'è, l'integrazione **te lo dice**
> invece di ripresentarti il modulo in silenzio. Il campo è cercabile, non libero.

**La zona non te la chiede nessuno**, ed è giusto così: l'API lavora per indirizzo, e il turno
di raccolta è una conseguenza del civico. Se vuoi la conferma di quale calendario ti è toccato,
attiva l'entità *Zona di raccolta*: risponde per esempio `Calendario Padova Q6 2026`.

Puoi aggiungere **più indirizzi**: casa, i genitori, l'ufficio. Ognuno diventa un dispositivo a sé.
E se traslochi, **Riconfigura** cambia indirizzo senza perdere la cronologia.

### Opzioni

| Opzione | Di serie | Che cosa cambia |
|---|---|---|
| Un calendario per ogni frazione | spento | Aggiunge un'entità calendario per frazione, col colore ufficiale |
| Un sensore per ogni frazione | spento | Aggiunge un sensore per frazione: la data della **sua** prossima esposizione |
| Giorni da guardare in avanti | 365 (fra 30 e 365) | Fra due raccolte del **vetro** possono passare 35 giorni: con un orizzonte corto sparisce |

> Le opzioni erano quattro. La quarta, «Eventi con la finestra oraria» — l'unica accesa di
> serie — è stata **tolta**. Non era
> più una preferenza estetica da quando lo **stato** del calendario è diventato la risposta
> a «si può esporre adesso»: con gli eventi giornalieri quella riga avrebbe detto «Si può
> esporre» alle nove del mattino. Dove il gestore non dichiara nessun orario gli eventi
> restano giornalieri da soli, che è l'unico caso in cui aveva senso.

## Automazioni

### Il promemoria della sera

Le 19:30 valgono per Padova Q2, dove la finestra apre alle 19:00: **scegli l'ora guardando
la tua**, o dove il gestore apre di notte la condizione sarà sempre falsa e non arriverà
mai niente, senza nessun errore.

```yaml
automation:
  - alias: "Rifiuti - promemoria della sera"
    triggers:
      - trigger: time
        at: "19:30:00"
    conditions:
      - condition: state
        entity_id: binary_sensor.CAMBIAMI_esposizione_stasera
        state: "on"
    actions:
      - action: notify.mobile_app_CAMBIAMI
        data:
          title: "Stasera si espone"
          message: >-
            {{ state_attr('binary_sensor.CAMBIAMI_esposizione_stasera', 'frazioni') | join(', ') }}
            — {{ state_attr('binary_sensor.CAMBIAMI_esposizione_stasera', 'orario_esposizione')
                 or 'vedi il calendario' }}
```

### All'apertura vera della finestra

Il trigger scatta all'ora che dice **il gestore** — non a un orario scelto da te. A Padova
Q2 sono le 19:00, in altri quartieri le 20:00, a Ferrara le 07:00.

> Il calendario ha un evento **per frazione**: in una sera con due frazioni questo trigger
> scatta due volte, e arrivano due notifiche. Se ne vuoi una sola, usa il promemoria a
> orario fisso qui sopra, che legge l'elenco già unito.

```yaml
automation:
  - alias: "Rifiuti - si apre la finestra di esposizione"
    triggers:
      - trigger: calendar
        event: start
        entity_id: calendar.CAMBIAMI_calendario_esposizioni
        offset: "-00:30:00"   # mezz'ora prima
    actions:
      - action: notify.mobile_app_CAMBIAMI
        data:
          title: "Fra mezz'ora si espone"
          message: "{{ trigger.calendar_event.summary }} — {{ trigger.calendar_event.description }}"
```

### Un annuncio vocale solo se qualcuno è in casa

*Esposizione stasera* si accende a **mezzanotte**, non all'apertura della finestra: con
questo trigger l'altoparlante parla alle 00:00. Se lo vuoi a un'ora civile, aggiungi una
condizione `time` oppure fai scattare l'annuncio sul calendario, come qui sopra.

```yaml
automation:
  - alias: "Rifiuti - annuncio"
    triggers:
      - trigger: state
        entity_id: binary_sensor.CAMBIAMI_esposizione_stasera
        to: "on"
    conditions:
      - condition: numeric_state
        entity_id: zone.home
        above: 0
    actions:
      - action: tts.speak
        target:
          entity_id: tts.piper
        data:
          media_player_entity_id: media_player.CAMBIAMI
          message: >-
            Stasera tocca a {{ states('sensor.CAMBIAMI_da_esporre_stasera') }}.
```

## In dashboard

```yaml
type: vertical-stack
cards:
  - type: markdown
    content: |-
      {% set b = 'binary_sensor.CAMBIAMI_esposizione_stasera' %}
      {% if is_state(b, 'on') %}
      ## Stasera: {{ state_attr(b, 'frazioni') | join(' + ') }}
      {{ state_attr(b, 'orario_esposizione') or '' }}
      {% else %}
      ## Stasera niente
      Prossima: **{{ state_attr('sensor.CAMBIAMI_inizio_esposizione', 'data') }}**
      {{ state_attr('sensor.CAMBIAMI_inizio_esposizione', 'frazioni') | join(' + ') }}
      {% endif %}
  - type: calendar
    initial_view: listWeek
    entities:
      - calendar.CAMBIAMI_calendario_esposizioni
```

### Il calendario della settimana

È la card qui sopra, e vale la pena isolarla perché è **la** risposta alla domanda
«che cosa si raccoglie questa settimana»:

```yaml
type: calendar
title: La settimana dei rifiuti
initial_view: listWeek
entities:
  - calendar.CAMBIAMI_calendario_esposizioni
```

```text
venerdì                                    11 settembre 2026
  19:00 - 00:00   ●  Organico
domenica                                   13 settembre 2026
  19:00 - 00:00   ●  Lattine
  19:00 - 00:00   ●  Imballaggi in plastica
mercoledì                                  16 settembre 2026
  19:00 - 00:00   ●  Indifferenziato
  19:00 - 00:00   ●  Organico
```

I giorni senza raccolta non compaiono, i nomi dei giorni sono nella **lingua di Home
Assistant**, e toccando una riga si apre il dettaglio con l'orario di esposizione.

Quattro cose che si vedono solo sul vetro:

- **Senza `initial_view: listWeek` esce il mese**, che è il valore di serie della card.
- **Dal telefono non serve nemmeno la card**: il pannello **Calendario** in barra
  laterale apre già in vista settimanale quando lo schermo è stretto.
- **La finestra della card è la stessa dell'attributo `giorni`** — da oggi ai sei giorni
  seguenti — quindi la card e gli attributi della stessa entità non possono raccontare
  settimane diverse ai bordi. Non è un'opzione della card: Home Assistant ridefinisce
  `listWeek` come «lista di 7 giorni a partire da oggi».
- **La card non sa che una sera è scaduta.** Dove la finestra finisce prima di mezzanotte —
  nel centro storico di Modena si espone dalle 00:00 alle 07:00 — dalle sette a mezzanotte
  la riga resta lì, mentre l'attributo `giorni` l'ha già tolta. In quel caso **hanno ragione
  gli attributi**: tieni accanto alla card *Da esporre stasera*.

Vuoi ogni riga **col colore ufficiale** del gestore? Accendi «Un calendario per ogni
frazione» nelle opzioni ed elenca quelli, **senza** il calendario complessivo — se
metti tutti e due, ogni riga compare due volte:

```yaml
type: calendar
title: La settimana dei rifiuti
initial_view: listWeek
entities:
  - calendar.CAMBIAMI_calendario_organico
  - calendar.CAMBIAMI_calendario_indifferenziato
  - calendar.CAMBIAMI_calendario_carta
  - calendar.CAMBIAMI_calendario_lattine
  - calendar.CAMBIAMI_calendario_imballaggi_in_plastica
  - calendar.CAMBIAMI_calendario_imballaggi_in_vetro
```

> Il colore si scrive alla **prima creazione** dell'entità. Chi aveva già i calendari
> per frazione da una versione precedente non li vede ricolorare da soli: si cambia a
> mano nelle impostazioni dell'entità, oppure si spegne e si riaccende l'opzione.

### E la stessa settimana come testo

Se preferisci una card di testo, senza plugin e senza helper:

```yaml
type: markdown
content: |-
  {% set s = 'calendar.CAMBIAMI_calendario_esposizioni' %}
  ## Questa settimana
  {% for quando, cosa in (state_attr(s, 'calendario') or {}).items() -%}
  **{{ quando }}** · {{ cosa }}
  {% endfor %}
```

L'agenda della settimana sta **negli attributi del calendario**, che è il posto giusto:
`calendario` è il dizionario piatto qui sopra, `giorni` la settimana completa con date,
orari e colori ufficiali per chi costruisce qualcosa di più elaborato.

Niente tabella di nomi dei giorni da mantenere a mano: le etichette arrivano già pronte
nella lingua di Home Assistant.

## Come funziona sotto

L'integrazione parla con il backend che il sito [ilrifiutologo.it](https://www.ilrifiutologo.it)
dichiara in chiaro nel proprio sorgente. Cinque endpoint, in `GET`, in sola lettura, **senza
autenticazione e senza chiave**:

```
https://webapp-ambiente.gruppohera.it/rifiutologo/rifiutologoweb/
    getComuni.php
    getIndirizzi.php?idComune=
    getNumeriCivici.php?idComune=&idIndirizzo=
    getCalendarioPap.php?idComune=&idIndirizzo=&idCivico=&isBusiness=0&date=&giorniDaMostrare=
    getAllegatiPap.php?idComune=&idIndirizzo=&idCivico=&isBusiness=0
```

Il calendario viene chiesto **due volte al giorno**: è un calendario annuale, cambia qualche
volta l'anno, e non c'è motivo di disturbare il gestore più spesso. Le entità si ricalcolano da
sole a mezzanotte **e a ogni apertura e chiusura di finestra**, così «stasera» resta
«stasera» — e «si può esporre» diventa vero all'ora giusta — senza altre chiamate.

### Provare un indirizzo prima di installare

Serve solo `aiohttp`, non Home Assistant:

```bash
python3 scripts/prova_api.py Padova "VIA BERNARDO TREVISAN" 8
```

Ti dice se quell'indirizzo ha il porta a porta, in quale zona sei, quali frazioni sono
previste, **che genere di orario dichiara il gestore** e quando sono le prossime otto
esposizioni. Con `--anonimo` via, civico e identificativi non compaiono nell'uscita: è la
forma da allegare a una segnalazione.

## Limiti, e cose da sapere

- **Nessuno di questi endpoint è documentato ufficialmente.** Funzionano oggi; possono cambiare
  domani senza preavviso. Il parsing è scritto per non morire se la forma cambia, ma se il
  gestore spegne un endpoint non c'è integrazione che tenga.
- **Gli identificativi non sono garantiti stabili.** Se il gestore rinumerasse il proprio
  database, l'integrazione se ne accorge (il calendario torna vuoto), riprova a risolvere
  l'indirizzo **per nome**, e scrive un avviso nel log *solo quando il rimedio ha davvero
  funzionato*. Ci riprova a cadenza, non una volta sola.
- **I log contengono il tuo indirizzo, ma non per colpa dell'integrazione.** Le sue righe
  citano solo il comune; sono gli `entity_id` — che Home Assistant costruisce dal nome del
  dispositivo, cioè dall'indirizzo — a comparire nei log di serie. La **diagnostica** invece
  oscura via e civico davvero. Se alleghi dei log a una segnalazione, dagli un'occhiata.
- **Gli indirizzi senza porta a porta non sono un guasto.** Sono la normalità in buona parte
  dei centri storici. La configurazione te lo dice subito.
- **Le festività** non sono un caso a parte: il gestore semplicemente non pubblica quei giorni.

## Contribuire

Segnalazioni e pull request sono benvenute.

Se la tua città è servita dal Gruppo Hera e qualcosa non torna — un'etichetta di frazione che
non ha l'icona giusta, una finestra oraria diversa da quella padovana — apri una issue e
allega l'uscita di `scripts/prova_api.py ... --anonimo`, oppure la **diagnostica**
(Impostazioni → Dispositivi e servizi → Il Rifiutologo → i tre puntini → *Scarica diagnostica*).
Nella diagnostica via e civico vengono oscurati automaticamente; il comune no, perché senza
quello la segnalazione non serve a niente. Nei **log**, invece, l'indirizzo compare dentro gli
`entity_id`: se ne alleghi, guardali prima.

```bash
ruff check . && ruff format --check . && pytest
```

L'icona si rigenera con `python3 scripts/genera_icona.py` (serve Pillow): se ne vuoi un'altra,
cambia lo script o sostituisci i due PNG in `custom_components/rifiutologo/brand/`.

## Licenza e trasparenza

[MIT](LICENSE).

Progetto **della comunità, non ufficiale**. Non è affiliato, sponsorizzato né approvato dal
Gruppo Hera, da AcegasApsAmga, da Marche Multiservizi o dal servizio Il Rifiutologo. I marchi
citati appartengono ai rispettivi titolari, e sono usati solo per dire con quale servizio
l'integrazione parla. I dati sono di Il Rifiutologo — Gruppo Hera e restano soggetti alle loro
condizioni d'uso.

[hacs]: https://github.com/hacs/integration
[apri-hacs]: https://my.home-assistant.io/redirect/hacs_repository/?owner=tulio98&repository=ha-rifiutologo&category=integration
[badge-hacs]: https://img.shields.io/badge/HACS-repository%20personalizzato-41BDF5.svg
[badge-ha]: https://img.shields.io/badge/Home%20Assistant-2026.1.0%2B-41BDF5.svg
[badge-licenza]: https://img.shields.io/badge/licenza-MIT-blue.svg
[badge-apri]: https://my.home-assistant.io/badges/hacs_repository.svg
