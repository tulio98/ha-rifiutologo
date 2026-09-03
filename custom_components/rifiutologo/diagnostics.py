"""Diagnostica: quello che serve a capire un problema, senza l'indirizzo di casa."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_CIVICO_ID, CONF_CIVICO_NUMERO, CONF_VIA_ID, CONF_VIA_NOME
from .coordinator import RifiutologoConfigEntry

# Il comune non si nasconde: senza quello una segnalazione e' inutile. Via e
# civico si', perche' insieme sono l'indirizzo di casa di chi segnala.
DA_NASCONDERE = {CONF_VIA_ID, CONF_VIA_NOME, CONF_CIVICO_ID, CONF_CIVICO_NUMERO}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: RifiutologoConfigEntry
) -> dict[str, Any]:
    """Raccoglie la diagnostica di un indirizzo."""
    coordinator = entry.runtime_data
    calendario = coordinator.data

    return {
        "configurazione": async_redact_data(dict(entry.data), DA_NASCONDERE),
        "opzioni": dict(entry.options),
        "aggiornamento_riuscito": coordinator.last_update_success,
        "calendario": {
            "zona": calendario.zona if calendario else None,
            "nota": calendario.nota if calendario else None,
            "giorni": len(calendario.giorni) if calendario else 0,
            "frazioni": calendario.frazioni if calendario else {},
            "primo_giorno": (
                calendario.giorni[0].giorno.isoformat()
                if calendario and calendario.giorni
                else None
            ),
            "ultimo_giorno": (
                calendario.giorni[-1].giorno.isoformat()
                if calendario and calendario.giorni
                else None
            ),
            "esempio": (
                {
                    "giorno": calendario.giorni[0].giorno.isoformat(),
                    "conferimenti": [
                        {
                            "frazione": c.frazione,
                            "colore": c.colore,
                            "ora_inizio": c.ora_inizio,
                            "ora_fine": c.ora_fine,
                            "orario": c.orario,
                            "orario_raccolta": c.orario_raccolta,
                            "straordinario": c.straordinario,
                        }
                        for c in calendario.giorni[0].conferimenti
                    ],
                }
                if calendario and calendario.giorni
                else None
            ),
        },
    }
