"""Test della diagnostica: deve essere utile senza rivelare dove abiti."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rifiutologo.diagnostics import async_get_config_entry_diagnostics
from homeassistant.core import HomeAssistant

ROMA = ZoneInfo("Europe/Rome")


@pytest.fixture(autouse=True)
def _carica_integrazione(enable_custom_integrations: None) -> None:
    """Questo test avvia l'integrazione."""


async def test_diagnostica(
    hass: HomeAssistant, gestore, voce: MockConfigEntry, freezer
) -> None:
    """La diagnostica dice tutto il necessario, ma non via e civico."""
    freezer.move_to(datetime(2026, 9, 3, 18, 0, tzinfo=ROMA))
    await hass.config.async_set_time_zone("Europe/Rome")
    voce.add_to_hass(hass)
    assert await hass.config_entries.async_setup(voce.entry_id)
    await hass.async_block_till_done()

    dati = await async_get_config_entry_diagnostics(hass, voce)

    # Il comune resta in chiaro: senza, una segnalazione non serve a niente.
    assert dati["configurazione"]["comune_nome"] == "Padova"
    assert dati["configurazione"]["comune_id"] == 372
    # Via e civico no: insieme sono l'indirizzo di casa.
    assert dati["configurazione"]["via_nome"] == "**REDACTED**"
    assert dati["configurazione"]["via_id"] == "**REDACTED**"
    assert dati["configurazione"]["civico_numero"] == "**REDACTED**"
    assert dati["configurazione"]["civico_id"] == "**REDACTED**"

    testo = str(dati)
    assert "TREVISAN" not in testo
    assert "26863" not in testo

    assert dati["aggiornamento_riuscito"] is True
    assert dati["calendario"]["zona"] == "Calendario Padova Q6 2026"
    assert dati["calendario"]["giorni"] == 12
    assert dati["calendario"]["frazioni"]["Organico"] == "#701100"
    assert dati["calendario"]["esempio"]["conferimenti"][0]["ora_inizio"] == "20:00"
