"""Il binary sensor che risponde alla domanda: stasera devo esporre qualcosa?"""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import RifiutologoConfigEntry, RifiutologoCoordinator
from .entity import RifiutologoEntity, attributi_giorno


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RifiutologoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Crea il binary sensor dell'indirizzo."""
    async_add_entities([BinarioEsporreStasera(entry.runtime_data)])


class BinarioEsporreStasera(RifiutologoEntity, BinarySensorEntity):
    """Acceso nei giorni in cui il gestore prevede un'esposizione.

    Attenzione al significato: la data che il gestore pubblica e' la sera in cui
    si mette fuori il sacco, non il mattino in cui passa il camion. Quindi questo
    sensore e' acceso per tutto il giorno dell'ESPOSIZIONE, e si spegne a
    mezzanotte, quando il mezzo deve ancora passare.
    """

    _attr_translation_key = "esporre_stasera"

    def __init__(self, coordinator: RifiutologoCoordinator) -> None:
        """Costruisce il binary sensor."""
        super().__init__(coordinator, "esporre_stasera")

    @property
    def is_on(self) -> bool | None:
        """Vero se stasera c'e' qualcosa da esporre."""
        if (calendario := self.coordinator.data) is None:
            return None
        return calendario.del_giorno(self.coordinator.oggi) is not None

    @property
    def icon(self) -> str:
        """Bidone pieno o vuoto, a colpo d'occhio."""
        return "mdi:trash-can" if self.is_on else "mdi:trash-can-outline"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Che cosa va esposto, con orari e colori."""
        calendario = self.coordinator.data
        giorno = (
            calendario.del_giorno(self.coordinator.oggi) if calendario else None
        )
        return attributi_giorno(giorno, self.coordinator.oggi)
