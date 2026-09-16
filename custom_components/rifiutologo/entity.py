"""Base comune a tutte le entita', attributi condivisi, entita' per frazione."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any, Final

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Calendario, GiornoRaccolta, slug
from .const import (
    ATTRIBUTION,
    DOMAIN,
    GIORNI_SETTIMANA,
    MANUFACTURER,
    giorni_abbreviati,
)
from .coordinator import RifiutologoConfigEntry, RifiutologoCoordinator
from .orari import agenda, apertura, chiusura

URL_SERVIZIO = "https://www.ilrifiutologo.it"


class RifiutologoEntity(CoordinatorEntity[RifiutologoCoordinator]):
    """Ogni entita' appartiene a un indirizzo, che e' il "dispositivo"."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(self, coordinator: RifiutologoCoordinator, chiave: str) -> None:
        """Aggancia l'entita' al coordinator e al dispositivo dell'indirizzo."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{chiave}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
            name=coordinator.indirizzo,
            manufacturer=MANUFACTURER,
            model=coordinator.comune_nome,
            configuration_url=URL_SERVIZIO,
            entry_type=DeviceEntryType.SERVICE,
        )


def _concorde(valori: dict[str, str]) -> str | None:
    """Il valore comune a tutte le frazioni, oppure None se non concordano.

    Meglio nessun orario che un orario che vale solo per una frazione su tre.
    """
    distinti = set(valori.values())
    return distinti.pop() if len(distinti) == 1 else None


def attributi_giorno(giorno: GiornoRaccolta | None, oggi: date) -> dict[str, Any]:
    """Attributi comuni che descrivono una sera di esposizione."""
    if giorno is None:
        return {
            "frazioni": [],
            "colori": {},
            "data": None,
            "giorno_settimana": None,
            "giorni_mancanti": None,
            "inizio_esposizione": None,
            "fine_esposizione": None,
            "orario_esposizione": None,
            "orari_esposizione": {},
            "orario_raccolta": None,
            "orari_raccolta": {},
            "straordinario": False,
            "note": None,
            "note_per_frazione": {},
        }

    orari = giorno.orari_per_frazione
    orari_raccolta = giorno.orari_raccolta_per_frazione
    note = giorno.note_per_frazione

    return {
        "frazioni": giorno.frazioni,
        "colori": {
            c.frazione: c.colore for c in giorno.conferimenti if c.colore is not None
        },
        "data": giorno.giorno.isoformat(),
        # ISO: 1 e' lunedi', 7 e' domenica. Qui va il NUMERO perche' questo
        # attributo lo leggono i template, e un numero non cambia con la lingua
        # di chi guarda. Il nome del giorno, per chi legge a occhio, sta
        # nell'attributo `calendario` del sensore della settimana, e li' segue
        # `hass.config.language`.
        #
        # (Un commento precedente diceva che "gli attributi non si traducono":
        # era falso. Home Assistant traduce il NOME di un attributo, e anche il
        # suo valore quando e' preso da un elenco fisso dichiarato nello
        # strings.json - schema `state_attributes` in hassfest/translations.py.
        # Quello che non si puo' tradurre e' un valore libero come una data.)
        "giorno_settimana": giorno.giorno.isoweekday(),
        # Zero vuol dire stasera. Non scende sotto zero: quando la finestra
        # scavalca la mezzanotte il giorno di esposizione resta "adesso", non
        # diventa "ieri".
        "giorni_mancanti": max(0, (giorno.giorno - oggi).days),
        # Gli stessi due istanti su cui si regolano il calendario e i risvegli
        # del coordinator, non un secondo conto fatto qui: `fine_esposizione`
        # e' la piu' tarda fra le frazioni ancora in elenco, e puo' cadere il
        # giorno dopo. Senza finestra dichiarata sono la mezzanotte e la
        # mezzanotte successiva, cioe' "quel giorno" detto senza inventare ore.
        "inizio_esposizione": apertura(giorno).isoformat(),
        "fine_esposizione": chiusura(giorno).isoformat(),
        # Il gestore dichiara la finestra in cui si ESPONE, non quella in cui
        # passa il camion: sono due cose diverse e vanno tenute distinte.
        # Lo scalare c'e' solo quando tutte le frazioni della sera concordano;
        # la mappa dice sempre la verita', frazione per frazione.
        "orario_esposizione": _concorde(orari),
        "orari_esposizione": orari,
        "orario_raccolta": _concorde(orari_raccolta),
        "orari_raccolta": orari_raccolta,
        "straordinario": any(c.straordinario for c in giorno.conferimenti),
        # Anche la nota va per frazione: su una sera con piu' frazioni capita
        # spesso che appartenga a una sola, e prendere la prima non nulla la
        # faceva valere per tutte.
        "note": _concorde(note),
        "note_per_frazione": note,
    }


def _frazioni_distinte(giorni: list[GiornoRaccolta]) -> list[str]:
    """Le frazioni di piu' sere, senza doppioni e nell'ordine in cui capitano."""
    viste: dict[str, None] = {}
    for giorno in giorni:
        viste.update(dict.fromkeys(giorno.frazioni))
    return list(viste)


def _etichetta_giorno(giorno: date, lingua: str | None) -> str:
    """L'etichetta di una sera: "mer 16/09", come si legge su un calendario.

    Il nome del giorno segue la lingua di Home Assistant, non quella di chi ha
    scritto il codice. Con una lingua che l'integrazione non parla si ripiega
    sull'inglese, come fa Home Assistant con qualunque testo non tradotto.

    La data e' giorno/mese perche' il servizio e' italiano; l'anno non serve in
    una finestra di sette giorni, e la data completa sta in `giorni`.
    """
    abbreviazioni = giorni_abbreviati(lingua)
    return f"{abbreviazioni[giorno.isoweekday() - 1]} {giorno:%d/%m}"


def attributi_settimana(
    dati: Calendario | None, adesso: datetime, lingua: str | None
) -> dict[str, Any]:
    """La settimana di esposizioni, nelle due forme che servono a due lettori.

    Stanno sul CALENDARIO perche' l'agenda e' il suo mestiere, e stanno insieme
    perche' sono la stessa settimana guardata in due modi:

    - `calendario` e' un dizionario PIATTO, "mer 16/09" -> "Indifferenziato,
      Organico". E' quello che si legge a occhio, e la forma non e' un
      capriccio: Home Assistant rende un attributo che contiene dizionari come
      un blocco YAML (`ha-attribute-value.ts`) e una lista di stringhe la unisce
      con le virgole su una riga sola. Un dizionario piatto e' l'unica forma che
      venga fuori a righe.
    - `giorni` e' la stessa settimana per intero, una voce per sera con la
      stessa forma che hanno gli altri attributi: serve ai template e alle card,
      che dai nomi abbreviati non ricaverebbero ne' le date ne' gli orari ne' i
      colori.

    Non sono due verita' diverse: la prima e' la proiezione leggibile della
    seconda, presa dalla stessa agenda nello stesso istante.
    """
    oggi = adesso.date()
    giorni = agenda(dati, adesso, GIORNI_SETTIMANA)
    return {
        # Le date non si ripetono dentro una finestra di sette giorni, quindi
        # nessuna chiave puo' scavalcarne un'altra.
        "calendario": {
            _etichetta_giorno(giorno.giorno, lingua): ", ".join(giorno.frazioni)
            for giorno in giorni
        },
        # `da` e' oggi, ma la prima sera dell'elenco puo' essere quella di IERI,
        # se la sua finestra scavalca la mezzanotte ed e' ancora aperta. E' roba
        # ancora da fare: nasconderla sarebbe il difetto.
        "da": oggi.isoformat(),
        "a": (oggi + timedelta(days=GIORNI_SETTIMANA - 1)).isoformat(),
        "frazioni": _frazioni_distinte(giorni),
        "giorni": [attributi_giorno(giorno, oggi) for giorno in giorni],
    }


# --- le entita' che nascono una per frazione ----------------------------------


@callback
# Sette argomenti, tutti nominati: sono i sette pezzi che distinguono una
# piattaforma dall'altra, e comprimerli in un oggetto di appoggio nasconderebbe
# la cosa che conta - che il prefisso e il dominio del registro devono
# corrispondere, o la pulizia cancella le entita' sbagliate.
def collega_per_frazione[T: Entity](  # noqa: PLR0913
    hass: HomeAssistant,
    entry: RifiutologoConfigEntry,
    *,
    attiva: bool,
    dominio: str,
    prefisso: str,
    costruttore: Callable[[str, str | None, str], T],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> list[T]:
    """Crea un'entita' per frazione, e continua a crearne quando ne compaiono.

    Sta qui e non dentro una piattaforma perche' la usano in due, il calendario
    e i sensori, e le tre cose delicate che fa - quando si puo' ripulire il
    registro, in che ordine si assegnano le chiavi, e quando NON si deve creare
    niente - sono esattamente quelle che non conviene scrivere due volte.

    `costruttore` riceve nome della frazione, colore ufficiale e chiave stabile.
    Ritorna le entita' note adesso, cosi' chi chiama le aggiunge insieme alle
    proprie in una chiamata sola.
    """
    coordinator = entry.runtime_data
    frazioni_create: set[str] = set()
    chiavi_usate: set[str] = set()

    @callback
    def _mancanti() -> list[T]:
        """Le entita' per frazione che ancora non esistono."""
        if not attiva or coordinator.data is None:
            return []
        colori = coordinator.data.frazioni
        chiavi = coordinator.data.chiavi_frazione
        nuove: list[T] = []
        # In ordine di NOME e non nell'ordine dell'API: l'assegnazione delle
        # chiavi non deve dipendere da come il gestore elenca le frazioni, che
        # cambia da solo mentre la finestra dei giorni scorre.
        for frazione in sorted(colori):
            if frazione in frazioni_create:
                continue
            frazioni_create.add(frazione)
            nuove.append(
                costruttore(
                    frazione,
                    colori[frazione],
                    # Il ripiego e' irraggiungibile finche' `frazioni` e
                    # `chiavi_frazione` scorrono gli stessi conferimenti, come
                    # fanno oggi: costa nulla, ed evita un KeyError se un domani
                    # le due mappe divergessero.
                    _chiave_libera(
                        chiavi.get(frazione) or slug(frazione), chiavi_usate
                    ),
                )
            )
        return nuove

    if not attiva:
        # Si ripulisce SOLO qui, che e' l'unico caso in cui l'utente ha davvero
        # detto di non volerle. Dedurre l'elenco atteso dallo scarico corrente
        # cancellerebbe le frazioni stagionali, quelle fuori dall'orizzonte, e
        # tutto quanto ogni volta che il calendario torna temporaneamente vuoto:
        # insieme all'entita' se ne andrebbero il nome scelto a mano, l'area e
        # le automazioni che la citano.
        _rimuovi_per_frazione(hass, entry, dominio, prefisso)

    iniziali = _mancanti()

    @callback
    def _al_dato_nuovo() -> None:
        """Una frazione stagionale puo' comparire mesi dopo la configurazione.

        Gli sfalci a primavera, per esempio: senza questo l'entita' nascerebbe
        solo al riavvio successivo di Home Assistant.
        """
        # Si guarda lo stato della voce e non un flag registrato con
        # async_on_unload: quelle callback girano DOPO che le piattaforme sono
        # state smontate, quindi un flag arriverebbe sempre tardi. Fra lo
        # smontaggio e la fine dello scaricamento la voce e' UNLOAD_IN_PROGRESS,
        # ed e' li' che un aggiornamento creerebbe un'entita' orfana.
        if entry.state is not ConfigEntryState.LOADED:
            return
        if nuove := _mancanti():
            async_add_entities(nuove)

    entry.async_on_unload(coordinator.async_add_listener(_al_dato_nuovo))
    return iniziali


@callback
def _rimuovi_per_frazione(
    hass: HomeAssistant, entry: RifiutologoConfigEntry, dominio: str, prefisso: str
) -> None:
    """Toglie dal registro TUTTE le entita' per frazione di una piattaforma.

    Si chiama solo quando l'opzione e' spenta. Senza, spegnendola le entita'
    resterebbero per sempre nel registro in stato "unavailable": Home Assistant
    le ripulisce da sola soltanto quando si rimuove l'intera voce.

    Il prefisso deve essere quello delle sole entita' per frazione: le entita'
    fisse della stessa piattaforma hanno unique_id che non cominciano cosi', e
    restano dove sono.
    """
    registro = er.async_get(hass)
    intero = f"{entry.entry_id}_{prefisso}"

    for voce in er.async_entries_for_config_entry(registro, entry.entry_id):
        if voce.domain == dominio and voce.unique_id.startswith(intero):
            registro.async_remove(voce.entity_id)


@callback
def _chiave_libera(radice: str, usate: set[str]) -> str:
    """Una chiave di unique_id che non collide con quelle gia' assegnate.

    La radice arriva gia' stabile da `Calendario.chiavi_frazione`: e' l'id del
    macroprodotto, che non dipende dall'ordine. Questo e' l'ultimo paracadute,
    per il caso in cui il gestore non dichiari l'id e due nomi diversi diano lo
    stesso slug: senza, Home Assistant scarterebbe il duplicato e un'entita'
    sparirebbe in silenzio.
    """
    chiave = radice
    contatore = 1
    while chiave in usate:
        contatore += 1
        chiave = f"{radice}_{contatore}"
    usate.add(chiave)
    return chiave


# --- le entita' ritirate ------------------------------------------------------

ENTITA_RITIRATE: Final[tuple[tuple[str, str], ...]] = (
    (Platform.BINARY_SENSOR, "finestra_aperta"),
    (Platform.SENSOR, "prossima_raccolta"),
    (Platform.SENSOR, "giorni_alla_prossima"),
    (Platform.SENSOR, "settimana"),
)
"""Le entita' che l'integrazione non crea piu', da togliere dal registro.

Senza, resterebbero li' in stato "non disponibile" per sempre: una riga grigia
in fondo alla pagina del dispositivo, cioe' peggio del disordine che si voleva
togliere. Home Assistant le ripulisce da solo soltanto quando si rimuove
l'intera voce di configurazione.
"""


@callback
def rimuovi_entita_ritirate(hass: HomeAssistant, entry: RifiutologoConfigEntry) -> None:
    """Toglie dal registro le entita' che questa versione non crea piu'.

    Si confronta l'unique_id ESATTO, non un prefisso come fa
    `_rimuovi_per_frazione`: "prossima_" si porterebbe via anche
    `prossima_esposizione`, che invece resta ed e' una delle tre che si vedono.

    Idempotente: dal secondo avvio non trova piu' niente da togliere.
    """
    registro = er.async_get(hass)
    ritirate = {
        (dominio, f"{entry.entry_id}_{chiave}") for dominio, chiave in ENTITA_RITIRATE
    }
    for voce in er.async_entries_for_config_entry(registro, entry.entry_id):
        if (voce.domain, voce.unique_id) in ritirate:
            registro.async_remove(voce.entity_id)
