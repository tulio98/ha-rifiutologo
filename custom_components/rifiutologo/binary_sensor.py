"""Il binary sensor che risponde a una sola domanda: adesso si espone o no."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import GiornoRaccolta
from .coordinator import RifiutologoConfigEntry, RifiutologoCoordinator
from .entity import RifiutologoEntity, attributi_giorno
from .orari import solo_aperti


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RifiutologoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Crea il binary sensor dell'indirizzo."""
    async_add_entities([BinarioEsporreStasera(entry.runtime_data)])


class BinarioEsporreStasera(RifiutologoEntity, BinarySensorEntity):
    """Acceso finche' c'e' tempo per esporre.

    Attenzione al significato: la data che il gestore pubblica e' la sera in cui
    si mette fuori il sacco, non il mattino in cui passa il camion. Il sensore
    si spegne quando la finestra di esposizione si chiude - a Padova a
    mezzanotte, a Bologna alle 06:00 del mattino dopo - e non quando cambia la
    data.
    """

    _attr_translation_key = "esporre_stasera"

    def __init__(self, coordinator: RifiutologoCoordinator) -> None:
        """Costruisce il binary sensor."""
        super().__init__(coordinator, "esporre_stasera")

    @property
    def _giorno(self) -> GiornoRaccolta | None:
        """La raccolta da esporre adesso, con le sole frazioni ancora in tempo."""
        giorno = self.coordinator.attuale
        if giorno is None or giorno.giorno > self.coordinator.oggi:
            return None
        return solo_aperti(giorno, dt_util.now())

    @property
    def is_on(self) -> bool | None:
        """Vero se c'e' qualcosa da esporre e la finestra non e' ancora chiusa."""
        if self.coordinator.data is None:
            return None
        return self._giorno is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Che cosa va esposto, con orari e colori."""
        return attributi_giorno(self._giorno, self.coordinator.oggi)
