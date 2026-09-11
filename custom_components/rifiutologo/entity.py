"""Base comune a tutte le entita' e attributi condivisi."""

from __future__ import annotations

from datetime import date
from typing import Any

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import GiornoRaccolta
from .const import ATTRIBUTION, DOMAIN, MANUFACTURER
from .coordinator import RifiutologoCoordinator
from .orari import apertura, chiusura

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
        # ISO: 1 e' lunedi', 7 e' domenica. Il numero e non il nome, perche' il
        # nome andrebbe scritto in una lingua sola e gli attributi non si
        # traducono; il README mostra come girarlo in italiano in tre righe.
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
