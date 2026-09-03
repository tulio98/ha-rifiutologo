"""Test del coordinator: errori, e il riallineamento degli identificativi."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.rifiutologo.api import BASE_URL
from custom_components.rifiutologo.const import (
    CONF_CIVICO_ID,
    DOMAIN,
    UPDATE_INTERVAL_HOURS,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import CIVICO_ID, DATI, carica, registra

ROMA = ZoneInfo("Europe/Rome")
SERA_DI_RACCOLTA = datetime(2026, 9, 3, 18, 0, tzinfo=ROMA)


@pytest.fixture(autouse=True)
def _carica_integrazione(enable_custom_integrations: None) -> None:
    """Ogni test di questo file passa dal loader di Home Assistant."""


def _binario(hass: HomeAssistant, voce: MockConfigEntry):
    """Lo stato del binary sensor dell'esposizione."""
    registro = er.async_get(hass)
    entity_id = registro.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{voce.entry_id}_esporre_stasera"
    )
    return hass.states.get(entity_id)


async def test_riallineamento_degli_identificativi(
    hass: HomeAssistant, aioclient_mock, freezer
) -> None:
    """Se il gestore rinumera, l'indirizzo si ritrova per nome.

    La voce di configurazione porta un id di civico ormai vecchio. Il primo
    scarico torna vuoto; il coordinator risolve di nuovo comune, via e civico
    partendo dai NOMI, trova l'id nuovo e riprova.
    """
    freezer.move_to(SERA_DI_RACCOLTA)

    # L'id vecchio non da' calendario, quello nuovo si'.
    aioclient_mock.get(
        f"{BASE_URL}/getCalendarioPap.php",
        params={"idCivico": "999999"},
        json=carica("calendario_vuoto"),
    )
    aioclient_mock.get(
        f"{BASE_URL}/getCalendarioPap.php",
        params={"idCivico": str(CIVICO_ID)},
        json=carica("calendario"),
    )
    aioclient_mock.get(f"{BASE_URL}/getComuni.php", json=carica("comuni"))
    aioclient_mock.get(f"{BASE_URL}/getIndirizzi.php", json=carica("indirizzi"))
    aioclient_mock.get(f"{BASE_URL}/getNumeriCivici.php", json=carica("civici"))
    aioclient_mock.get(f"{BASE_URL}/getAllegatiPap.php", json=carica("allegati"))

    voce = MockConfigEntry(
        domain=DOMAIN,
        title="VIA BERNARDO TREVISAN 8, Padova",
        data={**DATI, CONF_CIVICO_ID: 999999},
        unique_id="372-26863-999999",
    )
    await hass.config.async_set_time_zone("Europe/Rome")
    voce.add_to_hass(hass)
    assert await hass.config_entries.async_setup(voce.entry_id)
    await hass.async_block_till_done()

    assert voce.state is ConfigEntryState.LOADED
    assert _binario(hass, voce).state == STATE_ON

    # Il riallineamento vale per la sessione e non riscrive la configurazione:
    # cosi' non puo' innescare ricariche a catena.
    assert voce.data[CONF_CIVICO_ID] == 999999


async def test_riallineamento_una_volta_sola(
    hass: HomeAssistant, aioclient_mock, freezer
) -> None:
    """Un indirizzo senza PAP non fa ripartire il riallineamento a ogni giro."""
    freezer.move_to(SERA_DI_RACCOLTA)
    registra(aioclient_mock, calendario="calendario_vuoto", allegati="allegati_vuoti")

    voce = MockConfigEntry(
        domain=DOMAIN, title="prova", data=DATI, unique_id="372-26863-1328844"
    )
    await hass.config.async_set_time_zone("Europe/Rome")
    voce.add_to_hass(hass)
    assert await hass.config_entries.async_setup(voce.entry_id)
    await hass.async_block_till_done()

    def quante(endpoint: str) -> int:
        return sum(1 for c in aioclient_mock.mock_calls if endpoint in str(c[1]))

    # Al primo scarico il riallineamento viene tentato: tre chiamate in piu'.
    assert quante("getComuni.php") == 1

    freezer.tick(timedelta(hours=UPDATE_INTERVAL_HOURS + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert quante("getCalendarioPap.php") >= 2
    assert quante("getComuni.php") == 1, "il riallineamento si tenta una volta sola"


async def test_gestore_giu_rende_indisponibili(
    hass: HomeAssistant, aioclient_mock, voce: MockConfigEntry, freezer
) -> None:
    """Se il gestore cade dopo l'avvio, le entita' diventano indisponibili."""
    freezer.move_to(SERA_DI_RACCOLTA)
    registra(aioclient_mock)
    await hass.config.async_set_time_zone("Europe/Rome")
    voce.add_to_hass(hass)
    assert await hass.config_entries.async_setup(voce.entry_id)
    await hass.async_block_till_done()
    assert _binario(hass, voce).state == STATE_ON

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE_URL}/getCalendarioPap.php", status=500)

    freezer.tick(timedelta(hours=UPDATE_INTERVAL_HOURS + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert _binario(hass, voce).state == STATE_UNAVAILABLE
