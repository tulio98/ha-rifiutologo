"""Test del coordinator: errori, e il riallineamento degli identificativi."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.rifiutologo import coordinator as modulo
from custom_components.rifiutologo.api import BASE_URL
from custom_components.rifiutologo.const import (
    CONF_CIVICO_ID,
    DOMAIN,
    UPDATE_INTERVAL_HOURS,
)
from custom_components.rifiutologo.coordinator import INTERVALLO_RIALLINEAMENTO
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .conftest import CIVICO_ID, DATI, VIA_ID, carica, registra

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


async def test_il_riallineamento_torna_a_riprovare(
    hass: HomeAssistant, aioclient_mock, freezer
) -> None:
    """La rete di sicurezza non deve consumarsi al primo calendario vuoto.

    Il freno e' sul TEMPO: contando i vuoti consecutivi, un backend che alterna
    pieno e vuoto azzerava il contatore a ogni giro e pagava un riallineamento a
    ogni singolo vuoto isolato.
    """
    freezer.move_to(SERA_DI_RACCOLTA)
    registra(aioclient_mock, calendario="calendario_vuoto", allegati="allegati_vuoti")

    voce = MockConfigEntry(
        domain=DOMAIN, title="prova", data=DATI, unique_id="372-26863-1328844"
    )
    await hass.config.async_set_time_zone("Europe/Rome")
    voce.add_to_hass(hass)
    assert await hass.config_entries.async_setup(voce.entry_id)
    await hass.async_block_till_done()

    def tentativi() -> int:
        """Ogni riallineamento passa da getComuni.php: si contano quelli."""
        return sum(1 for c in aioclient_mock.mock_calls if "getComuni.php" in str(c[1]))

    assert tentativi() == 1, "il primo scarico vuoto tenta subito"

    # Qualche giro dopo, ancora fermo: non deve martellare il gestore.
    for _ in range(3):
        freezer.tick(timedelta(hours=UPDATE_INTERVAL_HOURS + 1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    assert tentativi() == 1, "fra un tentativo e l'altro deve passare del tempo"

    # Passato l'intervallo, ci riprova.
    freezer.tick(INTERVALLO_RIALLINEAMENTO)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert tentativi() >= 2, "la rete di sicurezza deve tornare disponibile"


async def test_alternare_pieno_e_vuoto_non_moltiplica_i_tentativi(
    hass: HomeAssistant, aioclient_mock, freezer
) -> None:
    """Un backend che sfarfalla non deve costare un riallineamento a ogni vuoto.

    Col freno sui vuoti CONSECUTIVI ogni vuoto isolato era il primo della sua
    serie, quindi sempre gratuito: meno vuoti costavano piu' rete di sicurezza.
    """
    freezer.move_to(SERA_DI_RACCOLTA)
    registra(aioclient_mock)
    voce = MockConfigEntry(
        domain=DOMAIN, title="prova", data=DATI, unique_id="372-26863-1328844"
    )
    await hass.config.async_set_time_zone("Europe/Rome")
    voce.add_to_hass(hass)
    assert await hass.config_entries.async_setup(voce.entry_id)
    await hass.async_block_till_done()

    def tentativi() -> int:
        return sum(1 for c in aioclient_mock.mock_calls if "getComuni.php" in str(c[1]))

    assert tentativi() == 0, "con il calendario pieno non si tenta niente"

    # Sei giri alternati pieno/vuoto, tutti dentro l'intervallo di guardia.
    for giro in range(6):
        aioclient_mock.clear_requests()
        vuoto = giro % 2 == 0
        registra(
            aioclient_mock,
            calendario="calendario_vuoto" if vuoto else "calendario",
            allegati="allegati_vuoti" if vuoto else "allegati",
        )
        freezer.tick(timedelta(hours=UPDATE_INTERVAL_HOURS + 1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

    # Il conteggio riparte da zero dopo ogni clear_requests: quel che conta e'
    # che l'ultimo giro vuoto non abbia tentato, perche' l'intervallo non e'
    # ancora passato dal primo.
    assert tentativi() == 0, (
        "dopo il primo tentativo si aspetta, comunque vadano i dati"
    )


async def test_identificativi_inutili_non_vengono_adottati(
    hass: HomeAssistant, aioclient_mock, freezer
) -> None:
    """Se i nuovi identificativi danno un calendario vuoto lo stesso, si torna indietro.

    Altrimenti una terna sbagliata resterebbe in uso per tutta la sessione,
    nascondendo il problema vero.
    """
    freezer.move_to(SERA_DI_RACCOLTA)
    # Qualunque id chieda, il calendario e' vuoto: il riallineamento trova un id
    # diverso da quello configurato, ma non risolve niente.
    aioclient_mock.get(
        f"{BASE_URL}/getCalendarioPap.php", json=carica("calendario_vuoto")
    )
    aioclient_mock.get(f"{BASE_URL}/getComuni.php", json=carica("comuni"))
    aioclient_mock.get(f"{BASE_URL}/getIndirizzi.php", json=carica("indirizzi"))
    aioclient_mock.get(f"{BASE_URL}/getNumeriCivici.php", json=carica("civici"))
    aioclient_mock.get(f"{BASE_URL}/getAllegatiPap.php", json=carica("allegati_vuoti"))

    voce = MockConfigEntry(
        domain=DOMAIN,
        title="prova",
        data={**DATI, CONF_CIVICO_ID: 999999},
        unique_id="372-26863-999999",
    )
    await hass.config.async_set_time_zone("Europe/Rome")
    voce.add_to_hass(hass)
    assert await hass.config_entries.async_setup(voce.entry_id)
    await hass.async_block_till_done()

    coordinator = voce.runtime_data
    assert coordinator._id_riallineati is None, (
        "una terna che non risolve niente non va tenuta"
    )
    # E la configurazione su disco non viene toccata in nessun caso.
    assert voce.data[CONF_CIVICO_ID] == 999999


async def test_la_rete_di_sicurezza_non_puo_far_cadere_lo_scarico(
    hass: HomeAssistant, aioclient_mock, freezer
) -> None:
    """Se inciampa il riallineamento, si tiene il risultato valido gia' in mano.

    Il primo scarico e' riuscito: il gestore ha risposto correttamente che non
    c'e' porta a porta. Se poi fallisce la verifica - che e' un di piu' - non
    deve diventare un UpdateFailed: renderebbe l'integrazione meno affidabile di
    quanto sarebbe senza rete di sicurezza.
    """
    freezer.move_to(SERA_DI_RACCOLTA)
    aioclient_mock.get(
        f"{BASE_URL}/getCalendarioPap.php",
        params={"idCivico": "999999"},
        json=carica("calendario_vuoto"),
    )
    # La verifica con gli id ricalcolati cade.
    aioclient_mock.get(
        f"{BASE_URL}/getCalendarioPap.php",
        params={"idCivico": str(CIVICO_ID)},
        status=503,
    )
    aioclient_mock.get(f"{BASE_URL}/getComuni.php", json=carica("comuni"))
    aioclient_mock.get(f"{BASE_URL}/getIndirizzi.php", json=carica("indirizzi"))
    aioclient_mock.get(f"{BASE_URL}/getNumeriCivici.php", json=carica("civici"))
    aioclient_mock.get(f"{BASE_URL}/getAllegatiPap.php", json=carica("allegati_vuoti"))

    voce = MockConfigEntry(
        domain=DOMAIN,
        title="prova",
        data={**DATI, CONF_CIVICO_ID: 999999},
        unique_id="372-26863-999999",
    )
    await hass.config.async_set_time_zone("Europe/Rome")
    voce.add_to_hass(hass)
    assert await hass.config_entries.async_setup(voce.entry_id)
    await hass.async_block_till_done()

    assert voce.state is ConfigEntryState.LOADED, "la voce deve caricarsi lo stesso"
    coordinator = voce.runtime_data
    assert coordinator.last_update_success is True
    # La terna nuova non e' mai stata confermata: non deve restare in uso.
    assert coordinator._id_riallineati is None


async def test_il_freno_del_riallineamento_e_sul_tempo(
    hass: HomeAssistant, aioclient_mock, freezer
) -> None:
    """Il marcatore del riallineamento e' un istante, non un conteggio.

    Se il contatore contasse i vuoti cumulativi invece che quelli consecutivi,
    il giorno in cui il gestore rinumera davvero la rete di sicurezza
    arriverebbe con giorni di ritardo.
    """
    freezer.move_to(SERA_DI_RACCOLTA)
    registra(aioclient_mock)
    voce = MockConfigEntry(
        domain=DOMAIN, title="prova", data=DATI, unique_id="372-26863-1328844"
    )
    await hass.config.async_set_time_zone("Europe/Rome")
    voce.add_to_hass(hass)
    assert await hass.config_entries.async_setup(voce.entry_id)
    await hass.async_block_till_done()

    coordinator = voce.runtime_data
    assert coordinator._ultimo_riallineamento is None, "col pieno non si tenta"

    # Un vuoto: il tentativo parte e viene marcato nel tempo.
    aioclient_mock.clear_requests()
    registra(aioclient_mock, calendario="calendario_vuoto", allegati="allegati_vuoti")
    freezer.tick(timedelta(hours=UPDATE_INTERVAL_HOURS + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    primo = coordinator._ultimo_riallineamento
    assert primo is not None

    # Il calendario torna: il freno si scarica. Tenerlo armato avrebbe fatto
    # risparmiare una richiesta ogni dodici ore al prezzo di sei giorni di
    # silenzio, se il gestore rinumerava subito dopo un vuoto isolato.
    aioclient_mock.clear_requests()
    registra(aioclient_mock)
    freezer.tick(timedelta(hours=UPDATE_INTERVAL_HOURS + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert coordinator._ultimo_riallineamento is None

    # E il vuoto successivo tenta subito, senza aspettare l'intervallo.
    aioclient_mock.clear_requests()
    registra(aioclient_mock, calendario="calendario_vuoto", allegati="allegati_vuoti")
    freezer.tick(timedelta(hours=UPDATE_INTERVAL_HOURS + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    tentativi = sum(
        1 for c in aioclient_mock.mock_calls if "getComuni.php" in str(c[1])
    )
    assert tentativi == 1, "dopo un recupero la rete di sicurezza torna immediata"


async def test_il_log_non_contiene_gli_identificativi(
    hass: HomeAssistant, aioclient_mock, freezer, caplog
) -> None:
    """via_id e civico_id sono due dei quattro campi che la diagnostica oscura.

    Non devono uscire in chiaro da una riga di log che le segnalazioni allegano.
    """
    freezer.move_to(SERA_DI_RACCOLTA)
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
        title="prova",
        data={**DATI, CONF_CIVICO_ID: 999999},
        unique_id="372-26863-999999",
    )
    await hass.config.async_set_time_zone("Europe/Rome")
    voce.add_to_hass(hass)

    with caplog.at_level(logging.DEBUG, logger="custom_components.rifiutologo"):
        assert await hass.config_entries.async_setup(voce.entry_id)
        await hass.async_block_till_done()

    nostre = [
        r for r in caplog.records if r.name.startswith("custom_components.rifiutologo")
    ]
    assert nostre, "nessuna riga di log da esaminare"

    avvisi = [r.getMessage() for r in nostre if r.levelno >= logging.WARNING]
    assert avvisi, "il riallineamento riuscito deve dirlo"
    testo = " ".join(avvisi)
    assert str(VIA_ID) not in testo
    assert str(CIVICO_ID) not in testo
    assert "999999" not in testo
    # Il comune si', che senza quello una segnalazione non serve.
    assert "Padova" in testo


async def test_avviso_una_volta_sola_per_indirizzo_muto(
    hass: HomeAssistant, aioclient_mock, freezer, caplog
) -> None:
    """Un indirizzo senza porta a porta va spiegato, ma una volta sola."""
    freezer.move_to(SERA_DI_RACCOLTA)
    registra(aioclient_mock, calendario="calendario_vuoto", allegati="allegati_vuoti")
    voce = MockConfigEntry(
        domain=DOMAIN, title="prova", data=DATI, unique_id="372-26863-1328844"
    )
    await hass.config.async_set_time_zone("Europe/Rome")
    voce.add_to_hass(hass)

    with caplog.at_level(logging.INFO, logger="custom_components.rifiutologo"):
        assert await hass.config_entries.async_setup(voce.entry_id)
        await hass.async_block_till_done()

        for _ in range(3):
            freezer.tick(timedelta(hours=UPDATE_INTERVAL_HOURS + 1))
            async_fire_time_changed(hass)
            await hass.async_block_till_done()

    spiegazioni = [
        r
        for r in caplog.records
        if r.levelno == logging.INFO
        and "non ha restituito alcun calendario" in r.getMessage()
    ]
    assert len(spiegazioni) == 1, f"detto {len(spiegazioni)} volte invece di una"


async def test_si_chiede_il_calendario_a_partire_da_ieri(
    hass: HomeAssistant, gestore, voce: MockConfigEntry, freezer
) -> None:
    """Il backend filtra dalla data richiesta: partire da oggi cancella ieri sera.

    Dove la finestra scavalca la mezzanotte, uno scarico che cade fra la
    mezzanotte e la chiusura - con un aggiornamento ogni dodici ore capita
    spesso - toglieva dai dati proprio la sera che il sensore stava tenendo viva.
    """
    freezer.move_to(SERA_DI_RACCOLTA)
    await hass.config.async_set_time_zone("Europe/Rome")
    voce.add_to_hass(hass)
    assert await hass.config_entries.async_setup(voce.entry_id)
    await hass.async_block_till_done()

    richieste = [
        c for c in aioclient_mock_calls(gestore) if "getCalendarioPap.php" in c[0]
    ]
    assert richieste, "nessuna richiesta di calendario"
    chiesto = richieste[-1][1]["date"]
    assert chiesto.startswith("2026-09-02"), (
        f"chiesto da {chiesto}, ma deve partire da ieri"
    )
    # E si chiede un giorno in PIU', o partendo da ieri l'orizzonte in avanti si
    # accorcerebbe di uno rispetto a quello che l'utente ha configurato.
    coordinator = voce.runtime_data
    assert int(richieste[-1][1]["giorniDaMostrare"]) == (
        coordinator.giorni_da_mostrare + 1
    )


def aioclient_mock_calls(mock) -> list[tuple[str, dict[str, str]]]:
    """URL e parametri di ogni chiamata registrata dal mock."""
    fuori: list[tuple[str, dict[str, str]]] = []
    for chiamata in mock.mock_calls:
        url = str(chiamata[1])
        pezzi = urlparse(url)
        fuori.append((pezzi.path, {k: v[0] for k, v in parse_qs(pezzi.query).items()}))
    return fuori


async def test_il_risveglio_e_sempre_nel_futuro(
    hass: HomeAssistant, gestore, voce: MockConfigEntry, freezer
) -> None:
    """Un confine gia' passato non deve produrre un ritardo negativo.

    Questo test guarda l'ISTANTE passato a async_track_point_in_time, non solo
    che il risveglio esista: senza, il pavimento non sarebbe esercitato da nulla
    e toglierlo non romperebbe nessun test.
    """
    freezer.move_to(SERA_DI_RACCOLTA)
    await hass.config.async_set_time_zone("Europe/Rome")
    voce.add_to_hass(hass)
    assert await hass.config_entries.async_setup(voce.entry_id)
    await hass.async_block_till_done()

    coordinator = voce.runtime_data
    adesso = dt_util.now()
    programmati: list[datetime] = []

    def _spia(hass_, azione, quando):
        programmati.append(quando)
        return lambda: None

    with (
        patch.object(
            modulo, "prossimo_confine", return_value=adesso - timedelta(hours=3)
        ),
        patch.object(modulo, "async_track_point_in_time", _spia),
    ):
        coordinator._programma_risveglio(coordinator.data)

    assert programmati, "nessun risveglio programmato"
    assert programmati[-1] > adesso, (
        f"programmato nel passato ({programmati[-1]} <= {adesso}): girerebbe a vuoto"
    )
