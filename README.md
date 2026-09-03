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
> "put it out tonight" binary sensor and four sensors. Address is picked from three
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
| `calendar.…_raccolta` | Calendario di tutte le frazioni | Il pannello Calendario, la card, e i trigger `calendar` |
| `binary_sensor.…_raccolta_stasera` | Acceso se stasera si espone | Il mattone delle automazioni |
| `sensor.…_da_esporre_stasera` | `Organico, Carta` oppure `nessuna` | Il testo della notifica |
| `sensor.…_prossima_raccolta` | Data della prossima esposizione | Card e template |
| `sensor.…_prossima_esposizione` | Istante di apertura della finestra | `device_class: timestamp`, si legge come «fra 3 ore» |
| `sensor.…_giorni_alla_prossima` | `0` vuol dire stasera | Soglie e colori |
| `sensor.…_zona` | `Calendario Padova Q6 2026` | Controllare di aver preso il calendario giusto (disattivata di serie) |

Ogni entità porta con sé, negli attributi: `frazioni`, `colori` (la palette **ufficiale** del
gestore, in esadecimale), `orario_esposizione`, `orario_raccolta`, `giorni_mancanti`,
`straordinario`, `note`.

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
| Lattine e Imballaggi in plastica | `#FDB913` |

I colori li disegna Home Assistant **dalla 2026.6** in poi; sulle versioni precedenti i
calendari separati funzionano lo stesso, semplicemente senza tinta.

## Chi è coperto

I **181 comuni** serviti dal Gruppo Hera e dalle sue società territoriali, fra cui:

**Veneto e Friuli (AcegasApsAmga)** — Padova, Trieste, Abano Terme, Albignasego, Noventa
Padovana, Ponte San Nicolò, Casalserugo, Selvazzano Dentro…
**Emilia-Romagna (Hera)** — Bologna, Modena, Ferrara, Ravenna, Rimini, Forlì, Cesena, Imola,
Faenza, Riccione…
**Marche (Marche Multiservizi)** — Pesaro, Urbino, Fano…

L'elenco completo non è cablato qui dentro: viene chiesto al gestore ogni volta, quindi resta
aggiornato da solo.

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
attiva l'entità `sensor.…_zona`: risponde per esempio `Calendario Padova Q6 2026`.

Puoi aggiungere **più indirizzi**: casa, i genitori, l'ufficio. Ognuno diventa un dispositivo a sé.

### Opzioni

| Opzione | Di serie | Che cosa cambia |
|---|---|---|
| Eventi con la finestra oraria | acceso | Gli eventi coprono la finestra di esposizione (a Padova 20:00→24:00) invece di essere giornalieri. Serve per far scattare i trigger `calendar` all'ora giusta. |
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
            — {{ state_attr('binary_sensor.CAMBIAMI_raccolta_stasera', 'orario_esposizione') }}
```

### All'apertura vera della finestra

Con gli eventi orari attivi, il trigger scatta alle 20:00 in punto perché è **il gestore** a
dire che si comincia alle 20:00 — non un orario che hai scelto tu.

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
        entity_id: sensor.CAMBIAMI_prossima_esposizione
        to: ~
    conditions:
      - condition: numeric_state
        entity_id: sensor.CAMBIAMI_giorni_alla_prossima
        below: 1
      - condition: state
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
    content: >-
      {% set b = 'binary_sensor.CAMBIAMI_raccolta_stasera' %}
      {% if is_state(b, 'on') %}
      ## Stasera: {{ state_attr(b, 'frazioni') | join(' + ') }}
      {{ state_attr(b, 'orario_esposizione') }}
      {% else %}
      ## Stasera niente
      Prossima: **{{ states('sensor.CAMBIAMI_da_esporre_stasera') }}**
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
sole a mezzanotte, così «stasera» resta «stasera».

Puoi provare il tuo indirizzo **prima di installare**, senza Home Assistant:

```bash
python3 scripts/prova_api.py Padova "VIA BERNARDO TREVISAN" 8
```

Ti dice se quell'indirizzo ha il porta a porta, in quale zona sei, quali frazioni sono
previste e quando sono le prossime otto esposizioni.

## Limiti, e cose da sapere

- **Nessuno di questi endpoint è documentato ufficialmente.** Funzionano oggi; possono cambiare
  domani senza preavviso. Il parsing è scritto per non morire se la forma cambia, ma se il
  gestore spegne un endpoint non c'è integrazione che tenga.
- **Gli identificativi non sono garantiti stabili.** Se il gestore rinumerasse il proprio
  database, l'integrazione se ne accorge (il calendario torna vuoto), riprova a risolvere
  l'indirizzo **per nome** e lo scrive nel log.
- **Gli indirizzi senza porta a porta non sono un guasto.** Sono la normalità in buona parte
  dei centri storici. La configurazione te lo dice subito.
- **Le festività** non sono un caso a parte: il gestore semplicemente non pubblica quei giorni.

## Progetti vicini

Se ti serve solo la data e non ti interessano gli orari di esposizione né i colori, esiste già
una strada, ed è onesto dirlo: la source **`ilrifiutologo_it`** dentro
[mampfes/hacs_waste_collection_schedule](https://github.com/mampfes/hacs_waste_collection_schedule),
che è già nello store HACS di serie. Fa una cosa sola — data e nome della frazione — e la fa
bene. Questa integrazione nasce per tenersi anche il resto: la finestra di esposizione, i
colori ufficiali, la zona, e tre tendine al posto della via da scrivere in maiuscolo esatto.

## Contribuire

Segnalazioni e pull request sono benvenute.

Se la tua città è servita dal Gruppo Hera e qualcosa non torna — un'etichetta di frazione che
non ha l'icona giusta, una finestra oraria diversa da quella padovana — apri una issue e
allega la **diagnostica** (Impostazioni → Dispositivi e servizi → Il Rifiutologo → i tre
puntini → *Scarica diagnostica*). Via e civico vengono oscurati automaticamente: il comune no,
perché senza quello la segnalazione non serve a niente.

```bash
ruff check . && ruff format --check .
```

## Licenza e trasparenza

[MIT](LICENSE).

Progetto **della comunità, non ufficiale**. Non è affiliato, sponsorizzato né approvato dal
Gruppo Hera, da AcegasApsAmga, da Marche Multiservizi o dal servizio Il Rifiutologo. I marchi
citati appartengono ai rispettivi titolari. I dati sono di Il Rifiutologo — Gruppo Hera e
restano soggetti alle loro condizioni d'uso.

[hacs]: https://github.com/hacs/integration
[apri-hacs]: https://my.home-assistant.io/redirect/hacs_repository/?owner=tulio98&repository=ha-rifiutologo&category=integration
[badge-hacs]: https://img.shields.io/badge/HACS-repository%20personalizzato-41BDF5.svg
[badge-ha]: https://img.shields.io/badge/Home%20Assistant-2026.1.0%2B-41BDF5.svg
[badge-licenza]: https://img.shields.io/badge/licenza-MIT-blue.svg
[badge-apri]: https://my.home-assistant.io/badges/hacs_repository.svg
