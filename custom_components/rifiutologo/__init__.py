"""Integrazione Il Rifiutologo (Gruppo Hera) per Home Assistant.

Calendario della raccolta porta a porta per i 181 comuni serviti dal Gruppo Hera
e dalle sue societa' territoriali, fra cui AcegasApsAmga (Padova e Trieste).

Progetto della comunita', non ufficiale e non affiliato al Gruppo Hera.
"""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import RifiutologoConfigEntry, RifiutologoCoordinator

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CALENDAR,
    Platform.SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: RifiutologoConfigEntry) -> bool:
    """Avvia un indirizzo configurato."""
    coordinator = RifiutologoCoordinator(hass, entry)
    # Se il gestore non risponde al primo scarico, questa solleva da sola
    # ConfigEntryNotReady e Home Assistant riprovera' piu' tardi.
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: RifiutologoConfigEntry
) -> bool:
    """Scarica un indirizzo."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
