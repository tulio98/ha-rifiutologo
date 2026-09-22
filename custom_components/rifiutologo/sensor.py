"""I sensori: che cosa esporre stasera, da che ora, e in che zona si abita."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from homeassistant.components.sensor import (
    DOMAIN as DOMINIO_SENSORE,
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import Conferimento, GiornoRaccolta
from .const import (
    CONF_SENSORI_PER_FRAZIONE,
    DEFAULT_SENSORI_PER_FRAZIONE,
    PROSSIME_DA_ELENCARE,
    icona_per_frazione,
)
from .coordinator import RifiutologoConfigEntry, RifiutologoCoordinator
from .entity import RifiutologoEntity, attributi_giorno, collega_per_frazione
from .orari import apertura, apertura_conferimento, scadenza, solo_aperti

NESSUNA = "nessuna"
LUNGHEZZA_MASSIMA_STATO = 255


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RifiutologoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Crea i sensori dell'indirizzo, e se chiesto uno per ogni frazione."""
    coordinator = entry.runtime_data

    @callback
    def _costruisci(frazione: str, colore: str | None, chiave: str) -> SensorEntity:
        return SensoreFrazione(coordinator, frazione, colore, chiave)

    per_frazione = collega_per_frazione(
        hass,
        entry,
        attiva=entry.options.get(
            CONF_SENSORI_PER_FRAZIONE, DEFAULT_SENSORI_PER_FRAZIONE
        ),
        dominio=DOMINIO_SENSORE,
        # Le entita' fisse hanno unique_id come "<voce>_zona": nessuna comincia
        # con "frazione_", quindi la pulizia del registro non le sfiora.
        prefisso="frazione_",
        costruttore=_costruisci,
        async_add_entities=async_add_entities,
    )
    async_add_entities(
        [
            SensoreEsposizioneStasera(coordinator),
            SensoreProssimaEsposizione(coordinator),
            SensoreZona(coordinator),
            *per_frazione,
        ]
    )


class _SensoreBase(RifiutologoEntity, SensorEntity):
    """Comodita' condivise dai sensori."""

    @property
    def _oggi(self) -> date:
        """La data di oggi secondo il fuso di Home Assistant."""
        return self.coordinator.oggi

    @property
    def _prossimo_giorno(self) -> GiornoRaccolta | None:
        """La prossima raccolta, da oggi in avanti. Non guarda mai indietro."""
        return self.coordinator.prossima

    @property
    def _giorno_di_oggi(self) -> GiornoRaccolta | None:
        """La raccolta da esporre adesso, se il momento e' arrivato.

        Qui si usa `attuale` e non `prossima`: dove la finestra scavalca la
        mezzanotte, alle due di notte si e' ancora in tempo per esporre la
        raccolta di ieri sera, e quella e' la risposta giusta alla domanda
        "che cosa metto fuori adesso".

        E si tengono solo le frazioni la cui finestra e' ancora aperta: in una
        sera con orari diversi, quella che chiude prima non va piu' elencata.
        """
        giorno = self.coordinator.attuale
        if giorno is None or giorno.giorno > self._oggi:
            return None
        return solo_aperti(giorno, dt_util.now())


class SensoreEsposizioneStasera(_SensoreBase):
    """Che cosa va messo fuori adesso. E' il sensore da usare per le notifiche."""

    _attr_translation_key = "esposizione_stasera"

    def __init__(self, coordinator: RifiutologoCoordinator) -> None:
        """Costruisce il sensore."""
        super().__init__(coordinator, "esposizione_stasera")

    @property
    def native_value(self) -> str | None:
        """Elenco delle frazioni da esporre, oppure "nessuna"."""
        if self.coordinator.data is None:
            return None
        if (giorno := self._giorno_di_oggi) is None:
            return NESSUNA
        return ", ".join(giorno.frazioni)[:LUNGHEZZA_MASSIMA_STATO]

    @property
    def icon(self) -> str:
        """Icona della prima frazione di stasera, o il bidone vuoto."""
        if (giorno := self._giorno_di_oggi) is None or not giorno.frazioni:
            return "mdi:trash-can-outline"
        return icona_per_frazione(giorno.frazioni[0])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Dettagli della sera in corso."""
        return attributi_giorno(self._giorno_di_oggi, self._oggi)


class SensoreProssimaEsposizione(_SensoreBase):
    """L'istante in cui si apre la finestra di esposizione.

    Si chiama "Inizio esposizione" e non piu' "Prossima esposizione", e il conto
    non e' cambiato di una riga: cambiato e' il nome, che prometteva il futuro e
    mostrava l'apertura della sera IN CORSO. "Inizio esposizione - 1 ora fa" e'
    una frase vera e utile; "Prossima esposizione - 1 ora fa" si contraddiceva
    da sola.

    La chiave di traduzione resta `prossima_esposizione`: cambiarla farebbe
    sparire l'icona, che `icons.json` indicizza proprio su quella.

    Home Assistant lo rende da solo in forma relativa e nella lingua di chi
    guarda - "Tra 1 ora", "Domani", "1 ora fa" - ed e' il motivo per cui non
    esiste piu' un sensore che conta i giorni: quello sarebbe un tempo relativo
    scritto nel database, che le regole di Home Assistant vietano per iscritto.
    """

    _attr_translation_key = "prossima_esposizione"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: RifiutologoCoordinator) -> None:
        """Costruisce il sensore."""
        super().__init__(coordinator, "prossima_esposizione")

    @property
    def native_value(self) -> datetime | None:
        """Inizio della finestra dichiarata dal gestore.

        Si prende il piu' presto fra gli inizi della sera, non il primo della
        lista, e si contano solo i conferimenti che dichiarano una finestra
        vera: dove inizio e fine coincidono quell'ora e' un TERMINE ("entro le
        04:00"), non un'apertura. Senza nessuna finestra si ripiega sulla
        mezzanotte, che e' il modo onesto di dire "quel giorno".
        """
        giorno = self._prossimo_giorno
        return apertura(giorno) if giorno is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Dettagli della prossima raccolta."""
        return attributi_giorno(self._prossimo_giorno, self._oggi)


class SensoreFrazione(_SensoreBase):
    """Quando tocca a UNA frazione: la domanda "e il vetro quando passa?".

    Lo stato e' la data della prossima esposizione di quella frazione, e come
    "Inizio esposizione" non guarda mai indietro: un sensore con device_class
    DATE che pubblica ieri e' un sensore che mente. Chi vuole sapere se si e'
    ancora in tempo stanotte usa "Esposizione stasera", che quel mestiere lo fa.
    """

    _attr_device_class = SensorDeviceClass.DATE

    def __init__(
        self,
        coordinator: RifiutologoCoordinator,
        frazione: str,
        colore: str | None,
        chiave: str,
    ) -> None:
        """Costruisce il sensore di una frazione."""
        super().__init__(coordinator, f"frazione_{chiave}")
        self._frazione = frazione
        self._colore = colore
        self._attr_name = frazione
        self._attr_icon = icona_per_frazione(frazione)

    def _sue_sere(self, adesso: datetime) -> list[tuple[GiornoRaccolta, Conferimento]]:
        """Le sere ancora da fare in cui compare questa frazione.

        Stesso metro di `prossima_raccolta`, applicato alla singola frazione:
        data non passata E finestra non ancora chiusa. Servono entrambe, per
        gli stessi due motivi.
        """
        calendario = self.coordinator.data
        if calendario is None:
            return []
        oggi = adesso.date()
        trovate: list[tuple[GiornoRaccolta, Conferimento]] = []
        for giorno in calendario.giorni:
            if giorno.giorno < oggi:
                continue
            for conferimento in giorno.conferimenti:
                if (
                    conferimento.frazione == self._frazione
                    and scadenza(giorno, conferimento) > adesso
                ):
                    trovate.append((giorno, conferimento))
                    break
            if len(trovate) >= PROSSIME_DA_ELENCARE:
                break
        return trovate

    @property
    def native_value(self) -> date | None:
        """La data della prossima esposizione di questa frazione."""
        sere = self._sue_sere(dt_util.now())
        return sere[0][0].giorno if sere else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Tutto quello che il gestore dice di QUESTA frazione."""
        adesso = dt_util.now()
        sere = self._sue_sere(adesso)
        base: dict[str, Any] = {
            "frazione": self._frazione,
            "colore": self._colore,
            "prossime": [giorno.giorno.isoformat() for giorno, _ in sere],
        }
        if not sere:
            return base | {
                "giorni_mancanti": None,
                "giorno_settimana": None,
                "inizio_esposizione": None,
                "fine_esposizione": None,
                "orario_esposizione": None,
                "orario_raccolta": None,
                "nota": None,
                "straordinario": False,
            }

        giorno, conferimento = sere[0]
        return base | {
            "giorni_mancanti": (giorno.giorno - adesso.date()).days,
            "giorno_settimana": giorno.giorno.isoweekday(),
            "inizio_esposizione": apertura_conferimento(
                giorno, conferimento
            ).isoformat(),
            "fine_esposizione": scadenza(giorno, conferimento).isoformat(),
            "orario_esposizione": conferimento.orario,
            "orario_raccolta": conferimento.orario_raccolta,
            "nota": conferimento.note,
            "straordinario": conferimento.straordinario,
        }


class SensoreZona(_SensoreBase):
    """La zona di raccolta, come la chiama il gestore.

    A Padova e' il nome del calendario cartaceo, per esempio "Calendario Padova
    Q6 2026": e' l'unico punto in cui l'API dichiara la zona, e serve a
    controllare di aver configurato l'indirizzo giusto.
    """

    _attr_translation_key = "zona"
    _attr_entity_registry_enabled_default = False
    # Non descrive la raccolta, descrive la CONFIGURAZIONE: serve a controllare
    # di aver preso l'indirizzo giusto. Sta nella scheda Diagnostica, che e' il
    # posto che Home Assistant tiene per le entita' di questo genere.
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: RifiutologoCoordinator) -> None:
        """Costruisce il sensore."""
        super().__init__(coordinator, "zona")

    @property
    def native_value(self) -> str | None:
        """Nome della zona dichiarata dal gestore."""
        if (calendario := self.coordinator.data) is None:
            return None
        zona = calendario.zona
        return zona[:LUNGHEZZA_MASSIMA_STATO] if zona else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Il PDF del calendario cartaceo e l'eventuale nota del gestore."""
        calendario = self.coordinator.data
        if calendario is None:
            return {}
        return {
            "pdf": next(
                (a.url for a in calendario.allegati if a.url is not None), None
            ),
            "allegati": [a.nome for a in calendario.allegati],
            "nota": calendario.nota or None,
        }
