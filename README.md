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
> "put it out tonight" binary sensor and four sensors. The address is picked from three
> dropdowns, no typing. Unofficial, community-made, not affiliated with Gruppo Hera.

---

## Perché

Il servizio **Il Rifiutologo** pubblica un dato che quasi nessuno usa per intero:

> La data del calendario **non è il giorno in cui passa il camion. È la sera in cui si espone.**

A Padova il gestore dichiara *«dalle 20:00 alle 24:00»* per l'esposizione e *«dalle 05:00 del
giorno successivo»* per la raccolta. Sono due cose diverse, e confonderle vuol dire mandarsi
una notifica il giorno dopo, quando il sacco è già stato ritirato — o non ritirato.

Questa integrazione tiene quel dato, e ci costruisce sopra le entità.

## Che cosa crea

Per ogni indirizzo configurato nasce un dispositivo con queste entità:

| Entità | Che cos'è | A cosa serve |
|---|---|---|
| **Raccolta** (`calendar`) | Calendario di tutte le frazioni | Il pannello Calendario, la card, e i trigger `calendar` |
| **Raccolta stasera** (`binary_sensor`) | Acceso finché c'è tempo per esporre | Il mattone delle automazioni |
| **Da esporre stasera** (`sensor`) | `Organico, Carta` oppure `nessuna` | Il testo della notifica |
| **Prossima raccolta** (`sensor`) | Data della prossima raccolta, da oggi in avanti | Card e template |
| **Prossima esposizione** (`sensor`) | Istante in cui si apre la sua finestra | `device_class: timestamp`, si legge come «fra 3 ore» |
| **Giorni alla prossima** (`sensor`) | `0` vuol dire stasera | Soglie e colori |
| **Zona di raccolta** (`sensor`) | `Calendario Padova Q6 2026` | Controllare di aver preso il calendario giusto (disattivata di serie) |

> **Gli `entity_id` dipendono dalla lingua di Home Assistant**, perché li genera lui dal nome
> dell'entità: in italiano diventano `sensor.<indirizzo>_da_esporre_stasera`, in inglese
> `sensor.<indirizzo>_waste_to_put_out_tonight`. Negli esempi qui sotto c'è `CAMBIAMI`:
> aprine il dispositivo e copia gli id veri.

Le entità che descrivono **una sera di raccolta** — *Raccolta stasera*, *Da esporre stasera*,
*Prossima raccolta* e *Prossima esposizione* — portano con sé questi attributi:

| Attributo | Contenuto |
|---|---|
| `frazioni` | `["Indifferenziato", "Organico"]` |
| `colori` | `{"Organico": "#701100", ...}` — la palette **ufficiale** del gestore |
| `data` | la data della sera di esposizione |
| `giorni_mancanti` | `0` vuol dire stasera; non scende mai sotto zero |
| `orario_esposizione` | la frase del gestore, **solo se vale per tutte le frazioni della sera** |
| `orari_esposizione` | mappa frazione → orario: dice sempre la verità |
| `orario_raccolta` / `orari_raccolta` | idem, per il passaggio del mezzo |
| `note` / `note_per_frazione` | la nota del gestore, con la stessa regola: lo scalare solo se vale per tutte |
| `straordinario` | se il gestore segnala una raccolta eccezionale |

*Giorni alla prossima* espone solo il numero; *Zona di raccolta* espone `pdf`, `allegati` e `nota`.

### I calendari a colori

Attivando **«Un calendario per ogni frazione»** nelle opzioni nasce un'entità calendario per
ogni tipo di rifiuto, ciascuna con il colore che le assegna il gestore — e non un colore
inventato: arriva dal campo `pittogramma.colore` dell'API.

| Frazione (Padova) | Colore |
|---|---|
| Organico | `#701100` |
| Indifferenziato | `#7C7C81` |
| Carta | `#0093D0` |
| Imballaggi in vetro | `#15A53F` |
| Lattine | `#FDB913` |
| Imballaggi in plastica | `#FDB913` |

Lattine e plastica hanno lo stesso colore perché il gestore le fa esporre insieme.
I colori li disegna Home Assistant **dalla 2026.6** in poi; sulle versioni precedenti i
calendari separati funzionano lo stesso, semplicemente senza tinta.

## L'orario di esposizione, che cambia da comune a comune

Questo è il punto in cui è più facile sbagliare, e l'integrazione lo tratta in tre modi
perché il gestore lo dichiara in tre modi. Sono tutti e tre verificati sul backend:

| Come lo dichiara il gestore | Esempio | Che cosa ne fa l'integrazione |
|---|---|---|
| Finestra dentro la giornata | **Padova** `20:00 → 24:00` | Evento dalle 20:00 alla mezzanotte |
| Finestra che **scavalca la mezzanotte** | **Bologna** `20:00 → 06:00` | Evento fino alle 06:00 **del giorno dopo**; alle due di notte il sensore è ancora acceso |
| Inizio uguale a fine | **Faenza** `04:00 → 04:00`, testo *«entro le 04:00»* | Non è una durata, è una scadenza: l'evento resta **giornaliero** e la frase esatta del gestore finisce nella descrizione |

Il terzo caso merita una riga in più: inventare una finestra di 24 ore sarebbe stato comodo e
sbagliato. Quando il gestore non dichiara una durata, l'integrazione non se la fabbrica.

Conseguenza pratica: **il sensore «Raccolta stasera» si spegne alla chiusura della finestra,
non a mezzanotte.** A Padova coincidono; a Bologna no.

E da qui nasce una distinzione che vale la pena tenere a mente, perché le due entità
rispondono a due domande diverse:

- **«Raccolta stasera»** e **«Da esporre stasera»** dicono *che cosa si può ancora mettere
  fuori adesso*. A Bologna, alle due di notte, parlano ancora della sera prima — ed è giusto.
- **«Prossima raccolta»**, **«Prossima esposizione»** e **«Giorni alla prossima»** guardano
  solo in avanti, da oggi. Non mostrano mai una data passata.

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

Tre passi, tutti a tendina, tutti alimentati dall'elenco vero del gestore:

1. **Comune** — 181 voci
2. **Via** — a Padova sono 2200; comincia a digitare per filtrare
3. **Civico** — sono stringhe: esistono `1/A`, `1/SNC`, `2/2`

**La zona non te la chiede nessuno**, ed è giusto così: l'API lavora per indirizzo, e il turno
di raccolta è una conseguenza del civico. Se vuoi la conferma di quale calendario ti è toccato,
attiva l'entità *Zona di raccolta*: risponde per esempio `Calendario Padova Q6 2026`.

Puoi aggiungere **più indirizzi**: casa, i genitori, l'ufficio. Ognuno diventa un dispositivo a sé.
E se traslochi, **Riconfigura** cambia indirizzo senza perdere la cronologia.

### Opzioni

| Opzione | Di serie | Che cosa cambia |
|---|---|---|
| Eventi con la finestra oraria | acceso | Gli eventi coprono la finestra di esposizione invece di essere giornalieri. Serve per far scattare i trigger `calendar` all'ora giusta. |
| Un calendario per ogni frazione | spento | Aggiunge un'entità calendario per frazione, col colore ufficiale |
| Giorni da guardare in avanti | 365 | Fra due raccolte del **vetro** possono passare 35 giorni: con un orizzonte corto sparisce |

## Automazioni

### Il promemoria della sera

```yaml
automation:
  - alias: "Rifiuti - promemoria della sera"
    triggers:
      - trigger: time
        at: "19:30:00"
    conditions:
      - condition: state
        entity_id: binary_sensor.CAMBIAMI_raccolta_stasera
        state: "on"
    actions:
      - action: notify.mobile_app_CAMBIAMI
        data:
          title: "Stasera si espone"
          message: >-
            {{ state_attr('binary_sensor.CAMBIAMI_raccolta_stasera', 'frazioni') | join(', ') }}
            — {{ state_attr('binary_sensor.CAMBIAMI_raccolta_stasera', 'orario_esposizione')
                 or 'vedi il calendario' }}
```

### All'apertura vera della finestra

Con gli eventi orari attivi, il trigger scatta all'ora che dice **il gestore** — non a un
orario scelto da te. A Padova sono le 20:00, a Bologna pure, a Ferrara le 07:00.

```yaml
automation:
  - alias: "Rifiuti - si apre la finestra di esposizione"
    triggers:
      - trigger: calendar
        event: start
        entity_id: calendar.CAMBIAMI_raccolta
        offset: "-00:30:00"   # mezz'ora prima
    actions:
      - action: notify.mobile_app_CAMBIAMI
        data:
          title: "Fra mezz'ora si espone"
          message: "{{ trigger.calendar_event.summary }} — {{ trigger.calendar_event.description }}"
```

### Un annuncio vocale solo se qualcuno è in casa

```yaml
automation:
  - alias: "Rifiuti - annuncio"
    triggers:
      - trigger: state
        entity_id: binary_sensor.CAMBIAMI_raccolta_stasera
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
      {% set b = 'binary_sensor.CAMBIAMI_raccolta_stasera' %}
      {% if is_state(b, 'on') %}
      ## Stasera: {{ state_attr(b, 'frazioni') | join(' + ') }}
      {{ state_attr(b, 'orario_esposizione') or '' }}
      {% else %}
      ## Stasera niente
      Prossima: **{{ states('sensor.CAMBIAMI_prossima_raccolta') }}**
      {{ state_attr('sensor.CAMBIAMI_prossima_raccolta', 'frazioni') | join(' + ') }}
      fra {{ states('sensor.CAMBIAMI_giorni_alla_prossima') }} giorni
      {% endif %}
  - type: calendar
    initial_view: listWeek
    entities:
      - calendar.CAMBIAMI_raccolta
```

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
sole a mezzanotte **e alla chiusura della finestra di esposizione**, così «stasera» resta
«stasera» senza altre chiamate.

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

## Progetti vicini

Se ti serve solo la data e non ti interessano gli orari di esposizione né i colori, esiste già
una strada, ed è onesto dirlo: la source **`ilrifiutologo_it`** dentro
[mampfes/hacs_waste_collection_schedule](https://github.com/mampfes/hacs_waste_collection_schedule),
che è già nello store HACS di serie. Fa una cosa sola — data e nome della frazione — e la fa
bene. Questa integrazione nasce per tenersi anche il resto: la finestra di esposizione (anche
dove scavalca la mezzanotte), i colori ufficiali, la zona, e tre tendine al posto della via da
scrivere in maiuscolo esatto.

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
