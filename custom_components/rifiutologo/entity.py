"""Base comune a tutte le entita' e costruzione degli attributi condivisi."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .api import GiornoRaccolta
from .const import ATTRIBUTION, DOMAIN, MANUFACTURER
from .coordinator import RifiutologoCoordinator

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


def istante(giorno: date, minuti: int) -> datetime:
    """Costruisce l'istante locale a `minuti` dalla mezzanotte di `giorno`.

    Si passa per l'ora di parete e non per una somma di timedelta perche' nei due
    giorni del cambio d'ora una somma sposterebbe l'orario di un'ora. E si
    gestisce il caso "24:00", che il gestore usa e che non e' un orario valido:
    sono 1440 minuti, cioe' la mezzanotte del giorno dopo.
    """
    giorni_avanti, resto = divmod(minuti, 24 * 60)
    ore, minuti_residui = divmod(resto, 60)
    return datetime.combine(
        giorno + timedelta(days=giorni_avanti),
        time(hour=ore, minute=minuti_residui),
        tzinfo=dt_util.get_default_time_zone(),
    )


def attributi_giorno(giorno: GiornoRaccolta | None, oggi: date) -> dict[str, Any]:
    """Attributi comuni che descrivono una sera di esposizione."""
    if giorno is None:
        return {
            "frazioni": [],
            "colori": {},
            "data": None,
            "giorni_mancanti": None,
            "orario_esposizione": None,
            "orario_raccolta": None,
            "straordinario": False,
            "note": None,
        }

    primo = giorno.conferimenti[0]
    return {
        "frazioni": giorno.frazioni,
        "colori": {
            c.frazione: c.colore for c in giorno.conferimenti if c.colore is not None
        },
        "data": giorno.giorno.isoformat(),
        "giorni_mancanti": (giorno.giorno - oggi).days,
        # Il gestore dichiara la finestra in cui si ESPONE, non quella in cui
        # passa il camion: sono due cose diverse e vanno tenute distinte.
        "orario_esposizione": primo.orario,
        "orario_raccolta": primo.orario_raccolta,
        "straordinario": any(c.straordinario for c in giorno.conferimenti),
        "note": next((c.note for c in giorno.conferimenti if c.note), None),
    }
