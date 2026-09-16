"""Attrezzatura comune ai test."""

from __future__ import annotations

from collections.abc import Generator
import json
import pathlib
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.rifiutologo.api import BASE_URL
from custom_components.rifiutologo.const import (
    CONF_CIVICO_ID,
    CONF_CIVICO_NUMERO,
    CONF_COMUNE_ID,
    CONF_COMUNE_NOME,
    CONF_VIA_ID,
    CONF_VIA_NOME,
    DOMAIN,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

# L'indirizzo di prova e' reale e ha davvero il porta a porta: i payload delle
# fixture sono le risposte vere del gestore, ridotte nel numero di giorni.
COMUNE_ID = 372
VIA_ID = 26863
CIVICO_ID = 1328844

# Quello che la tendina MANDA quando si sceglie una voce: il testo che si legge,
# non l'id. E' il valore dell'opzione, e coincide con la sua etichetta - vedi il
# commento in `_tendina` per il perche'.
COMUNE_SCELTO = "Padova (PD)"
VIA_SCELTA = "VIA BERNARDO TREVISAN"
CIVICO_SCELTO = "8"

DATI = {
    CONF_COMUNE_ID: COMUNE_ID,
    CONF_COMUNE_NOME: "Padova",
    CONF_VIA_ID: VIA_ID,
    CONF_VIA_NOME: "VIA BERNARDO TREVISAN",
    CONF_CIVICO_ID: CIVICO_ID,
    CONF_CIVICO_NUMERO: "8",
}


def carica(nome: str):
    """Legge una fixture JSON."""
    return json.loads((FIXTURES / f"{nome}.json").read_text(encoding="utf-8"))


# `enable_custom_integrations` non e' autouse di proposito: trascinerebbe la
# fixture `hass` anche nei test sincroni di puro parsing, che non ne hanno
# bisogno. I test che avviano l'integrazione la chiedono esplicitamente.


@pytest.fixture
def gestore(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Il backend del gestore, con le risposte vere di un indirizzo di Padova."""
    registra(aioclient_mock)
    return aioclient_mock


def registra(
    mock: AiohttpClientMocker,
    *,
    calendario: str = "calendario",
    allegati: str = "allegati",
) -> None:
    """Registra i cinque endpoint."""
    mock.get(f"{BASE_URL}/getComuni.php", json=carica("comuni"))
    mock.get(f"{BASE_URL}/getIndirizzi.php", json=carica("indirizzi"))
    mock.get(f"{BASE_URL}/getNumeriCivici.php", json=carica("civici"))
    mock.get(f"{BASE_URL}/getCalendarioPap.php", json=carica(calendario))
    mock.get(f"{BASE_URL}/getAllegatiPap.php", json=carica(allegati))


@pytest.fixture
def voce() -> MockConfigEntry:
    """Una config entry gia' configurata sull'indirizzo di prova."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="VIA BERNARDO TREVISAN 8, Padova",
        data=DATI,
        unique_id=f"{COMUNE_ID}-{VIA_ID}-{CIVICO_ID}",
    )


@pytest.fixture
def niente_attesa() -> Generator[None]:
    """Evita che i test aspettino il debouncer del coordinator."""
    with patch(
        "homeassistant.helpers.update_coordinator.REQUEST_REFRESH_DEFAULT_COOLDOWN", 0
    ):
        yield
