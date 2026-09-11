"""Dettagli di comportamento che il banco mutazionale ha trovato scoperti.

Ogni test qui dentro uccide una mutazione che prima passava indenne: la cache
degli eventi che non si invalida, l'avviso che non arriva, il calendario
complessivo cancellato per sbaglio dalla pulizia del registro.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta
import logging
from zoneinfo import ZoneInfo

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.rifiutologo.api import (
    BASE_URL,
    RifiutologoClient,
    RifiutologoConnectionError,
)
from custom_components.rifiutologo.const import (
    CONF_CALENDARI_PER_FRAZIONE,
    CONF_EVENTI_CON_ORARIO,
    CONF_GIORNI_DA_MOSTRARE,
    DOMAIN,
    UPDATE_INTERVAL_HOURS,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .conftest import CIVICO_ID, DATI, carica, registra

ROMA = ZoneInfo("Europe/Rome")
SERA_DI_RACCOLTA = datetime(2026, 9, 3, 18, 0, tzinfo=ROMA)


@pytest.fixture(autouse=True)
def _carica_integrazione(enable_custom_integrations: None) -> None:
    """Ogni test di questo file passa dal loader di Home Assistant."""


def _stato(hass: HomeAssistant, voce: MockConfigEntry, piattaforma: str, chiave: str):
    registro = er.async_get(hass)
    entity_id = registro.async_get_entity_id(
        piattaforma, DOMAIN, f"{voce.entry_id}_{chiave}"
    )
    assert entity_id is not None, f"entita' {piattaforma}/{chiave} non creata"
    return hass.states.get(entity_id)


async def _avvia(hass: HomeAssistant, voce: MockConfigEntry) -> None:
    await hass.config.async_set_time_zone("Europe/Rome")
    voce.add_to_hass(hass)
    assert await hass.config_entries.async_setup(voce.entry_id)
    await hass.async_block_till_done()


# --- M27: un corpo che non si decodifica --------------------------------------


async def test_corpo_non_decodificabile_e_un_errore_del_client(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Deve entrare nella gerarchia del client, non uscire come UnicodeDecodeError."""
    aioclient_mock.get(
        f"{BASE_URL}/getComuni.php",
        exc=UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
    )
    client = RifiutologoClient(async_get_clientsession(hass))
    with pytest.raises(RifiutologoConnectionError):
        await client.comuni()


# --- M29 / M30 / M32: chi avvisa l'utente, e quando ---------------------------


def _spiegazioni(caplog) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.levelno == logging.INFO
        and "non ha restituito alcun calendario" in r.getMessage()
    ]


async def test_il_primo_calendario_vuoto_si_spiega_subito(
    hass: HomeAssistant, aioclient_mock, freezer, caplog
) -> None:
    """Non al giro dopo: chi installa deve capire subito perche' e' tutto muto."""
    freezer.move_to(SERA_DI_RACCOLTA)
    registra(aioclient_mock, calendario="calendario_vuoto", allegati="allegati_vuoti")
    voce = MockConfigEntry(
        domain=DOMAIN, title="prova", data=DATI, unique_id="372-26863-1328844"
    )
    with caplog.at_level(logging.INFO, logger="custom_components.rifiutologo"):
        await _avvia(hass, voce)
    assert len(_spiegazioni(caplog)) == 1


async def test_avviso_anche_quando_gli_id_ricalcolati_non_risolvono(
    hass: HomeAssistant, aioclient_mock, freezer, caplog
) -> None:
    """La terna nuova e' stata provata ed e' vuota lo stesso: va detto lo stesso."""
    freezer.move_to(SERA_DI_RACCOLTA)
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
        data={**DATI, "civico_id": 999999},
        unique_id="372-26863-999999",
    )
    with caplog.at_level(logging.INFO, logger="custom_components.rifiutologo"):
        await _avvia(hass, voce)
    assert len(_spiegazioni(caplog)) == 1


async def test_avviso_anche_se_la_rete_di_sicurezza_e_caduta_al_primo_giro(
    hass: HomeAssistant, aioclient_mock, freezer, caplog
) -> None:
    """Se il primo giro cade per la rete, la spiegazione arriva comunque.

    Al secondo giro il freno e' armato, e l'unico posto rimasto per spiegare
    perche' le entita' sono mute e' il ramo del freno.
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
        status=503,
    )
    aioclient_mock.get(f"{BASE_URL}/getComuni.php", json=carica("comuni"))
    aioclient_mock.get(f"{BASE_URL}/getIndirizzi.php", json=carica("indirizzi"))
    aioclient_mock.get(f"{BASE_URL}/getNumeriCivici.php", json=carica("civici"))
    aioclient_mock.get(f"{BASE_URL}/getAllegatiPap.php", json=carica("allegati_vuoti"))
    voce = MockConfigEntry(
        domain=DOMAIN,
        title="prova",
        data={**DATI, "civico_id": 999999},
        unique_id="372-26863-999999",
    )
    with caplog.at_level(logging.INFO, logger="custom_components.rifiutologo"):
        await _avvia(hass, voce)
        assert _spiegazioni(caplog) == [], "il primo giro e' caduto, non si sa ancora"
        freezer.tick(timedelta(hours=UPDATE_INTERVAL_HOURS + 1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    assert len(_spiegazioni(caplog)) == 1


# --- M43: una terna invariata non e' un riallineamento ------------------------


async def test_terna_invariata_non_costa_un_secondo_scarico(
    hass: HomeAssistant, aioclient_mock, freezer
) -> None:
    """Se i nomi danno gli stessi id non c'e' niente da riprovare."""
    freezer.move_to(SERA_DI_RACCOLTA)
    registra(aioclient_mock, calendario="calendario_vuoto", allegati="allegati_vuoti")
    voce = MockConfigEntry(
        domain=DOMAIN, title="prova", data=DATI, unique_id="372-26863-1328844"
    )
    await _avvia(hass, voce)
    scarichi = sum(
        1 for c in aioclient_mock.mock_calls if "getCalendarioPap.php" in str(c[1])
    )
    assert scarichi == 1, "la terna e' la stessa: il secondo scarico e' sprecato"
    assert voce.runtime_data._id_riallineati is None


# --- M40: uno scarico identico non deve riscrivere lo stato -------------------


async def test_uno_scarico_identico_non_riscrive_lo_stato(
    hass: HomeAssistant, gestore, voce: MockConfigEntry, freezer
) -> None:
    """always_update=False: un calendario immutato non tocca le entita'."""
    freezer.move_to(SERA_DI_RACCOLTA)
    await _avvia(hass, voce)
    prima = _stato(hass, voce, "sensor", "esposizione_stasera").last_updated

    # Il coordinator si richiama a mano, con l'orologio fermo. Saltare avanti
    # dodici ore misurerebbe due cose insieme: `always_update`, che e' quella in
    # esame, e i confini di giornata, che in dodici ore si attraversano per
    # forza - e alle sette del mattino dopo il sensore vale davvero "nessuna",
    # quindi riscriverlo li' e' giusto, non un difetto. Prima questo test
    # passava solo finche' il risveglio programmato non faceva in tempo a
    # scattare, ed e' bastata un'entita' in piu' per rovesciarlo.
    # Il conteggio vero e' questo, e non `last_updated`: Home Assistant scarta
    # da solo una riscrittura identica, quindi la data di aggiornamento non
    # cambia nemmeno con `always_update=True` e non puo' accorgersi di niente.
    # Qui si guarda piu' a monte, se le entita' sono state AVVISATE.
    avvisi = 0

    @callback
    def _conta() -> None:
        nonlocal avvisi
        avvisi += 1

    disdici = voce.runtime_data.async_add_listener(_conta)
    await voce.runtime_data.async_refresh()
    await hass.async_block_till_done()
    disdici()

    assert voce.runtime_data.last_update_success, "il secondo scarico e' andato"
    assert avvisi == 0, "calendario identico: nessuna entita' andava avvisata"
    assert _stato(hass, voce, "sensor", "esposizione_stasera").last_updated == prima


# --- M35: la pulizia non deve portarsi via il calendario complessivo ----------


async def test_il_calendario_complessivo_sopravvive_alla_pulizia(
    hass: HomeAssistant, aioclient_mock, voce: MockConfigEntry, freezer
) -> None:
    """Spegnendo i calendari per frazione, il complessivo tiene nome ed entity_id."""
    registra(aioclient_mock)
    freezer.move_to(SERA_DI_RACCOLTA)
    voce.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        voce, options={CONF_CALENDARI_PER_FRAZIONE: True}
    )
    await hass.config.async_set_time_zone("Europe/Rome")
    assert await hass.config_entries.async_setup(voce.entry_id)
    await hass.async_block_till_done()

    registro = er.async_get(hass)
    complessivo = registro.async_get_entity_id(
        "calendar", DOMAIN, f"{voce.entry_id}_calendario"
    )
    rimossi: list[str] = []

    @callback
    def _spia(evento) -> None:
        if (
            evento.data["action"] == "remove"
            and evento.data["entity_id"] == complessivo
        ):
            rimossi.append(evento.data["entity_id"])

    hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, _spia)

    risultato = await hass.config_entries.options.async_init(voce.entry_id)
    await hass.config_entries.options.async_configure(
        risultato["flow_id"],
        {
            CONF_EVENTI_CON_ORARIO: True,
            CONF_CALENDARI_PER_FRAZIONE: False,
            CONF_GIORNI_DA_MOSTRARE: 365,
        },
    )
    await hass.async_block_till_done()

    assert rimossi == [], (
        "la pulizia dei calendari per frazione si e' portata via anche il "
        f"complessivo: {rimossi}"
    )


# --- M45 / M46: i bordi degli eventi ------------------------------------------


async def test_l_evento_finito_all_istante_non_e_piu_quello_in_corso(
    hass: HomeAssistant, gestore, voce: MockConfigEntry, freezer
) -> None:
    """Alle 00:00 del 4 settembre l'evento del 3 e' finito: si passa al prossimo."""
    freezer.move_to(datetime(2026, 9, 4, 0, 0, tzinfo=ROMA))
    await _avvia(hass, voce)
    stato = _stato(hass, voce, "calendar", "calendario")
    assert stato.attributes["start_time"] == "2026-09-06 20:00:00"


async def test_get_events_esclude_gli_eventi_che_toccano_il_bordo(
    hass: HomeAssistant, gestore, voce: MockConfigEntry, freezer
) -> None:
    """L'intervallo richiesto e' semiaperto.

    Un evento che finisce esattamente all'inizio della finestra non ci ricade
    dentro.
    """
    freezer.move_to(SERA_DI_RACCOLTA)
    await _avvia(hass, voce)
    stato = _stato(hass, voce, "calendar", "calendario")

    eventi = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": stato.entity_id,
            # L'evento del 3 settembre finisce esattamente qui.
            "start_date_time": datetime(2026, 9, 4, 0, 0, tzinfo=ROMA),
            "end_date_time": datetime(2026, 9, 6, 20, 0, tzinfo=ROMA),
        },
        blocking=True,
        return_response=True,
    )
    assert eventi[stato.entity_id]["events"] == []


# --- M49: gli eventi memorizzati vanno buttati a ogni dato nuovo --------------


async def test_gli_eventi_si_ricostruiscono_dopo_un_dato_nuovo(
    hass: HomeAssistant, aioclient_mock, voce: MockConfigEntry, freezer
) -> None:
    """La memoria degli eventi e' una cache: un calendario nuovo la invalida."""
    freezer.move_to(SERA_DI_RACCOLTA)
    registra(aioclient_mock)
    await _avvia(hass, voce)
    stato = _stato(hass, voce, "calendar", "calendario")
    assert stato.attributes["message"] == "Organico"

    nuovo = copy.deepcopy(carica("calendario"))
    for voce_giorno in nuovo["calendario"]:
        for c in voce_giorno["conferimenti"]:
            c["macroprodotto"]["descrizione"] = "Sfalci"
    aioclient_mock.clear_requests()
    registra(aioclient_mock)
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE_URL}/getComuni.php", json=carica("comuni"))
    aioclient_mock.get(f"{BASE_URL}/getIndirizzi.php", json=carica("indirizzi"))
    aioclient_mock.get(f"{BASE_URL}/getNumeriCivici.php", json=carica("civici"))
    aioclient_mock.get(f"{BASE_URL}/getCalendarioPap.php", json=nuovo)
    aioclient_mock.get(f"{BASE_URL}/getAllegatiPap.php", json=carica("allegati"))

    freezer.tick(timedelta(hours=UPDATE_INTERVAL_HOURS + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert (
        _stato(hass, voce, "calendar", "calendario").attributes["message"] == "Sfalci"
    )


# --- M54 / M55: lo stato non puo' superare i 255 caratteri --------------------


async def test_lo_stato_dei_sensori_resta_dentro_i_255_caratteri(
    hass: HomeAssistant, aioclient_mock, voce: MockConfigEntry, freezer
) -> None:
    """Home Assistant rifiuta uno stato piu' lungo: l'entita' diventerebbe muta."""
    freezer.move_to(SERA_DI_RACCOLTA)
    lungo = "Frazione con un nome assurdamente lungo " * 10
    calendario = copy.deepcopy(carica("calendario"))
    for voce_giorno in calendario["calendario"]:
        for c in voce_giorno["conferimenti"]:
            c["macroprodotto"]["descrizione"] = lungo
    allegati = [{"id": 1, "nome": lungo, "path": "assets/uploads/x.pdf"}]

    aioclient_mock.get(f"{BASE_URL}/getComuni.php", json=carica("comuni"))
    aioclient_mock.get(f"{BASE_URL}/getIndirizzi.php", json=carica("indirizzi"))
    aioclient_mock.get(f"{BASE_URL}/getNumeriCivici.php", json=carica("civici"))
    aioclient_mock.get(f"{BASE_URL}/getCalendarioPap.php", json=calendario)
    aioclient_mock.get(f"{BASE_URL}/getAllegatiPap.php", json=allegati)

    registro = er.async_get(hass)
    voce.add_to_hass(hass)
    await hass.config.async_set_time_zone("Europe/Rome")
    assert await hass.config_entries.async_setup(voce.entry_id)
    await hass.async_block_till_done()
    registro.async_update_entity(
        registro.async_get_entity_id("sensor", DOMAIN, f"{voce.entry_id}_zona"),
        disabled_by=None,
    )
    await hass.config_entries.async_reload(voce.entry_id)
    await hass.async_block_till_done()

    esposizione = _stato(hass, voce, "sensor", "esposizione_stasera").state
    zona = _stato(hass, voce, "sensor", "zona").state
    # Uno stato troppo lungo Home Assistant lo rifiuta, e l'entita' resta muta.
    assert esposizione.startswith("Frazione con un nome"), esposizione
    assert len(esposizione) <= 255
    assert zona.startswith("Frazione con un nome"), zona
    assert len(zona) <= 255
