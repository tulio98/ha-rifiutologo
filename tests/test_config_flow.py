"""Test della configurazione guidata."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rifiutologo.api import BASE_URL
from custom_components.rifiutologo.const import (
    CONF_CALENDARI_PER_FRAZIONE,
    CONF_CIVICO_NUMERO,
    CONF_COMUNE_NOME,
    CONF_EVENTI_CON_ORARIO,
    CONF_GIORNI_DA_MOSTRARE,
    CONF_VIA_NOME,
    DOMAIN,
)
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import CIVICO_ID, COMUNE_ID, VIA_ID, registra


@pytest.fixture(autouse=True)
def _carica_integrazione(enable_custom_integrations: None) -> None:
    """Ogni test di questo file passa dal loader di Home Assistant."""


async def _fino_al_civico(hass: HomeAssistant, *, source: str = SOURCE_USER, **kwargs):
    """Porta il flusso fino al terzo passo."""
    risultato = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": source, **kwargs}
    )
    assert risultato["type"] is FlowResultType.FORM
    assert risultato["step_id"] == "user"

    risultato = await hass.config_entries.flow.async_configure(
        risultato["flow_id"], {"comune": str(COMUNE_ID)}
    )
    assert risultato["step_id"] == "via"

    risultato = await hass.config_entries.flow.async_configure(
        risultato["flow_id"], {"via": str(VIA_ID)}
    )
    assert risultato["step_id"] == "civico"
    return risultato


async def test_flusso_completo(hass: HomeAssistant, gestore) -> None:
    """Tre tendine e la voce e' creata, col titolo giusto."""
    risultato = await _fino_al_civico(hass)
    risultato = await hass.config_entries.flow.async_configure(
        risultato["flow_id"], {"civico": str(CIVICO_ID)}
    )
    await hass.async_block_till_done()

    assert risultato["type"] is FlowResultType.CREATE_ENTRY
    assert risultato["title"] == "VIA BERNARDO TREVISAN 8, Padova"
    assert risultato["data"][CONF_COMUNE_NOME] == "Padova"
    assert risultato["data"][CONF_VIA_NOME] == "VIA BERNARDO TREVISAN"
    # Il civico resta una stringa: esistono "1/A", "1/SNC", "2/2".
    assert risultato["data"][CONF_CIVICO_NUMERO] == "8"
    assert risultato["result"].unique_id == f"{COMUNE_ID}-{VIA_ID}-{CIVICO_ID}"


async def test_le_tendine_sono_piene(hass: HomeAssistant, gestore) -> None:
    """Ogni passo offre le voci vere del gestore, non un campo libero."""
    risultato = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    selettore = risultato["data_schema"].schema["comune"]
    valori = [o["value"] for o in selettore.config["options"]]
    assert str(COMUNE_ID) in valori
    assert selettore.config["custom_value"] is False
    # Ordine alfabetico, non quello del gestore.
    etichette = [o["label"] for o in selettore.config["options"]]
    assert etichette == sorted(etichette)


async def test_indirizzo_senza_porta_a_porta(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Un indirizzo a cassonetti lo dice subito, invece di creare entita' mute."""
    registra(aioclient_mock, calendario="calendario_vuoto", allegati="allegati_vuoti")

    risultato = await _fino_al_civico(hass)
    risultato = await hass.config_entries.flow.async_configure(
        risultato["flow_id"], {"civico": str(CIVICO_ID)}
    )

    assert risultato["type"] is FlowResultType.FORM
    assert risultato["step_id"] == "civico"
    assert risultato["errors"] == {"base": "nessun_pap"}


async def test_gestore_irraggiungibile(hass: HomeAssistant, aioclient_mock) -> None:
    """Se il backend non risponde, il flusso si ferma con un messaggio chiaro."""
    aioclient_mock.get(f"{BASE_URL}/getComuni.php", status=500)
    risultato = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert risultato["type"] is FlowResultType.ABORT
    assert risultato["reason"] == "cannot_connect"


async def test_indirizzo_gia_configurato(
    hass: HomeAssistant, gestore, voce: MockConfigEntry
) -> None:
    """Lo stesso indirizzo non si configura due volte."""
    voce.add_to_hass(hass)

    risultato = await _fino_al_civico(hass)
    risultato = await hass.config_entries.flow.async_configure(
        risultato["flow_id"], {"civico": str(CIVICO_ID)}
    )
    assert risultato["type"] is FlowResultType.ABORT
    assert risultato["reason"] == "already_configured"


async def test_riconfigura(hass: HomeAssistant, gestore, voce: MockConfigEntry) -> None:
    """Si puo' cambiare indirizzo senza perdere la voce e la sua cronologia."""
    voce.add_to_hass(hass)
    assert await hass.config_entries.async_setup(voce.entry_id)
    await hass.async_block_till_done()

    risultato = await _fino_al_civico(
        hass, source=SOURCE_RECONFIGURE, entry_id=voce.entry_id
    )
    # Il civico "1" della stessa via, che nelle fixture ha id 1328838.
    risultato = await hass.config_entries.flow.async_configure(
        risultato["flow_id"], {"civico": "1328838"}
    )
    await hass.async_block_till_done()

    assert risultato["type"] is FlowResultType.ABORT
    assert risultato["reason"] == "reconfigure_successful"
    assert voce.data[CONF_CIVICO_NUMERO] == "1"
    assert voce.title == "VIA BERNARDO TREVISAN 1, Padova"
    assert voce.unique_id == f"{COMUNE_ID}-{VIA_ID}-1328838"


async def test_opzioni(hass: HomeAssistant, gestore, voce: MockConfigEntry) -> None:
    """Le opzioni si salvano e ricaricano la voce da sole."""
    voce.add_to_hass(hass)
    assert await hass.config_entries.async_setup(voce.entry_id)
    await hass.async_block_till_done()

    risultato = await hass.config_entries.options.async_init(voce.entry_id)
    assert risultato["step_id"] == "init"

    risultato = await hass.config_entries.options.async_configure(
        risultato["flow_id"],
        {
            CONF_EVENTI_CON_ORARIO: False,
            CONF_CALENDARI_PER_FRAZIONE: True,
            CONF_GIORNI_DA_MOSTRARE: 90,
        },
    )
    await hass.async_block_till_done()

    assert risultato["type"] is FlowResultType.CREATE_ENTRY
    assert voce.options[CONF_EVENTI_CON_ORARIO] is False
    assert voce.options[CONF_CALENDARI_PER_FRAZIONE] is True
    # Il selettore numerico restituisce un float: deve arrivare intero.
    assert voce.options[CONF_GIORNI_DA_MOSTRARE] == 90
    assert isinstance(voce.options[CONF_GIORNI_DA_MOSTRARE], int)
