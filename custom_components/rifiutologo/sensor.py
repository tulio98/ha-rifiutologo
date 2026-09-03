"""I sensori: cosa esporre stasera, quando tocca di nuovo, e in che zona sei."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import GiornoRaccolta
from .const import icona_per_frazione
from .coordinator import RifiutologoConfigEntry, RifiutologoCoordinator
from .entity import RifiutologoEntity, attributi_giorno
from .orari import apertura

NESSUNA = "nessuna"
LUNGHEZZA_MASSIMA_STATO = 255


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RifiutologoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Crea i sensori dell'indirizzo."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            SensoreEsposizioneStasera(coordinator),
            SensoreProssimaRaccolta(coordinator),
            SensoreProssimaEsposizione(coordinator),
            SensoreGiorniAllaProssima(coordinator),
            SensoreZona(coordinator),
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
        """
        giorno = self.coordinator.attuale
        return giorno if giorno is not None and giorno.giorno <= self._oggi else None


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


class SensoreProssimaRaccolta(_SensoreBase):
    """La data della prossima raccolta, quella in corso compresa."""

    _attr_translation_key = "prossima_raccolta"
    _attr_device_class = SensorDeviceClass.DATE

    def __init__(self, coordinator: RifiutologoCoordinator) -> None:
        """Costruisce il sensore."""
        super().__init__(coordinator, "prossima_raccolta")

    @property
    def native_value(self) -> date | None:
        """La data del prossimo giorno di esposizione."""
        giorno = self._prossimo_giorno
        return giorno.giorno if giorno else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Dettagli della prossima raccolta."""
        return attributi_giorno(self._prossimo_giorno, self._oggi)


class SensoreProssimaEsposizione(_SensoreBase):
    """L'istante in cui si apre la finestra di esposizione della prossima raccolta.

    Nella sera stessa e' gia' passato di qualche ora, e vuol dire che la
    finestra e' aperta adesso; non torna mai al giorno prima.
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


class SensoreGiorniAllaProssima(_SensoreBase):
    """Quanti giorni mancano: 0 vuol dire stasera, o finestra gia' aperta."""

    _attr_translation_key = "giorni_alla_prossima"
    _attr_native_unit_of_measurement = "d"

    def __init__(self, coordinator: RifiutologoCoordinator) -> None:
        """Costruisce il sensore."""
        super().__init__(coordinator, "giorni_alla_prossima")

    @property
    def native_value(self) -> int | None:
        """Giorni che mancano alla prossima esposizione."""
        giorno = self._prossimo_giorno
        if giorno is None:
            return None
        # Non scende sotto zero: con la finestra ancora aperta alle due di notte
        # la risposta giusta e' "adesso", non "meno un giorno".
        return max(0, (giorno.giorno - self._oggi).days)


class SensoreZona(_SensoreBase):
    """La zona di raccolta, come la chiama il gestore.

    A Padova e' il nome del calendario cartaceo, per esempio "Calendario Padova
    Q6 2026": e' l'unico punto in cui l'API dichiara la zona, e serve a
    controllare di aver configurato l'indirizzo giusto.
    """

    _attr_translation_key = "zona"
    _attr_entity_registry_enabled_default = False

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
