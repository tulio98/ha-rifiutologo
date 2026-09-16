"""Il binary sensor che risponde a una sola domanda: stasera tocca o no.

E' il si'/no di "Da esporre stasera", ed e' il mattone delle automazioni: un
trigger booleano non si puo' sostituire con un confronto sullo stato testuale
dell'altra, perche' in una sera con orari diversi quel testo cambia a meta'
serata - a Gradara alle 23:00 - e un trigger `not_to: "nessuna"` manderebbe una
seconda notifica.

Resta ACCESA di serie proprio per questo, anche se ripete un'informazione che
un'altra entita' gia' porta: e' la prima cosa che si copia dal README, e
spegnerla vorrebbe dire consegnare un esempio che non funziona finche' non si
trova l'interruttore. Il doppione che infastidiva non era questo - era la
seconda riga che diceva "Acceso" senza far capire quale fosse quale, e quella
non c'e' piu'.
"""

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
