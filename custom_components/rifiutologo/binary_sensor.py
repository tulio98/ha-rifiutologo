"""I due binary sensor, e la differenza fra loro non e' una sfumatura.

"Raccolta stasera" dice che OGGI tocca e che si e' ancora in tempo: si accende
a mezzanotte e si spegne quando l'ultima finestra si chiude. Serve a decidere
se stasera bisogna ricordarsi di qualcosa.

"Finestra di esposizione aperta" dice che si puo' uscire ADESSO: si accende
all'ora dichiarata dal gestore - a Padova le 19:00 o le 20:00 secondo la zona -
e non un minuto prima. Serve a far partire l'avviso nel momento giusto senza
ricalcolare l'orario in un template.
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
from .orari import giorno_in_corso, solo_aperti, solo_in_finestra


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RifiutologoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Crea i binary sensor dell'indirizzo."""
    coordinator = entry.runtime_data
    async_add_entities(
        [BinarioEsporreStasera(coordinator), BinarioFinestraAperta(coordinator)]
    )


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


class BinarioFinestraAperta(RifiutologoEntity, BinarySensorEntity):
    """Acceso solo DENTRO la finestra dichiarata dal gestore.

    Fratello minore di quello sopra, e la differenza sta tutta nell'apertura:
    quello e' acceso da mezzanotte, questo dalle 19:00 o dalle 20:00, cioe'
    dall'ora che il gestore scrive. Alle sei di sera del giorno della carta il
    primo dice si' e questo dice no, ed e' la risposta giusta: il sacco fuori a
    quell'ora e' fuori regolamento.

    Dove il gestore NON dichiara un'apertura - "entro le 04:00" e' un termine,
    non un inizio - la finestra vale da mezzanotte, perche' in quel caso non
    c'e' nessun'ora prima della quale sia vietato.
    """

    _attr_translation_key = "finestra_aperta"

    def __init__(self, coordinator: RifiutologoCoordinator) -> None:
        """Costruisce il binary sensor."""
        super().__init__(coordinator, "finestra_aperta")

    @property
    def _giorno(self) -> GiornoRaccolta | None:
        """Le frazioni che si possono portare fuori proprio adesso.

        Non serve escludere le sere future: di una sera che deve ancora venire
        nemmeno l'apertura e' passata, e `solo_in_finestra` la scarta da se'.
        """
        adesso = dt_util.now()
        return solo_in_finestra(giorno_in_corso(self.coordinator.data, adesso), adesso)

    @property
    def is_on(self) -> bool | None:
        """Vero se in questo momento c'e' qualcosa che si puo' mettere fuori."""
        if self.coordinator.data is None:
            return None
        return self._giorno is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Che cosa si puo' esporre adesso, con orari e colori."""
        return attributi_giorno(self._giorno, self.coordinator.oggi)
