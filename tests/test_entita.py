"""Test dell'avvio e delle entita', con il tempo congelato."""

from __future__ import annotations

import dataclasses
from datetime import date, datetime
import json
from zoneinfo import ZoneInfo

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.rifiutologo.api import BASE_URL
from custom_components.rifiutologo.const import (
    CONF_CALENDARI_PER_FRAZIONE,
    CONF_EVENTI_CON_ORARIO,
    CONF_GIORNI_DA_MOSTRARE,
    DOMAIN,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import carica, registra

ROMA = ZoneInfo("Europe/Rome")
# Il primo giorno delle fixture: Organico, esposizione dalle 20:00 alle 24:00.
SERA_DI_RACCOLTA = datetime(2026, 9, 3, 18, 0, tzinfo=ROMA)


@pytest.fixture(autouse=True)
def _carica_integrazione(enable_custom_integrations: None) -> None:
    """Ogni test di questo file passa dal loader di Home Assistant."""


async def _avvia(hass: HomeAssistant, voce: MockConfigEntry) -> None:
    """Mette in funzione la voce di configurazione."""
    await hass.config.async_set_time_zone("Europe/Rome")
    voce.add_to_hass(hass)
    assert await hass.config_entries.async_setup(voce.entry_id)
    await hass.async_block_till_done()


def coordinator_chiavi(hass: HomeAssistant, voce: MockConfigEntry) -> dict[str, str]:
    """La mappa frazione -> chiave stabile, come la vede il coordinator."""
    return voce.runtime_data.data.chiavi_frazione


def _stato(hass: HomeAssistant, voce: MockConfigEntry, piattaforma: str, chiave: str):
    """Ritrova lo stato di un'entita' partendo dal suo unique_id."""
    registro = er.async_get(hass)
    entity_id = registro.async_get_entity_id(
        piattaforma, DOMAIN, f"{voce.entry_id}_{chiave}"
    )
    assert entity_id is not None, f"entita' {piattaforma}/{chiave} non creata"
    return hass.states.get(entity_id)


async def test_avvio_e_spegnimento(
    hass: HomeAssistant, gestore, voce: MockConfigEntry, freezer
) -> None:
    """La voce si avvia, crea il dispositivo, e si scarica pulita."""
    freezer.move_to(SERA_DI_RACCOLTA)
    await _avvia(hass, voce)
    assert voce.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(voce.entry_id)
    await hass.async_block_till_done()
    assert voce.state is ConfigEntryState.NOT_LOADED


async def test_sera_con_raccolta(
    hass: HomeAssistant, gestore, voce: MockConfigEntry, freezer
) -> None:
    """Nella sera del 3 settembre 2026 va esposto l'organico."""
    freezer.move_to(SERA_DI_RACCOLTA)
    await _avvia(hass, voce)

    binario = _stato(hass, voce, "binary_sensor", "esporre_stasera")
    assert binario.state == STATE_ON
    assert binario.attributes["frazioni"] == ["Organico"]
    assert binario.attributes["colori"] == {"Organico": "#701100"}
    assert binario.attributes["orario_esposizione"] == "dalle 20:00 alle 24:00"
    assert binario.attributes["orario_raccolta"] == "dalle 05:00 del giorno successivo"
    assert binario.attributes["giorni_mancanti"] == 0

    assert _stato(hass, voce, "sensor", "esposizione_stasera").state == "Organico"
    assert _stato(hass, voce, "sensor", "prossima_raccolta").state == "2026-09-03"
    assert _stato(hass, voce, "sensor", "giorni_alla_prossima").state == "0"

    # device_class timestamp: lo stato e' l'istante in UTC, ma sono le 20:00 a Roma.
    prossima = _stato(hass, voce, "sensor", "prossima_esposizione")
    assert datetime.fromisoformat(prossima.state).astimezone(ROMA) == datetime(
        2026, 9, 3, 20, 0, tzinfo=ROMA
    )


async def test_sera_senza_raccolta(
    hass: HomeAssistant, gestore, voce: MockConfigEntry, freezer
) -> None:
    """Il 4 settembre non si espone niente: la prossima e' il 6."""
    freezer.move_to(datetime(2026, 9, 4, 18, 0, tzinfo=ROMA))
    await _avvia(hass, voce)

    assert _stato(hass, voce, "binary_sensor", "esporre_stasera").state == STATE_OFF
    assert _stato(hass, voce, "sensor", "esposizione_stasera").state == "nessuna"
    assert _stato(hass, voce, "sensor", "prossima_raccolta").state == "2026-09-06"
    assert _stato(hass, voce, "sensor", "giorni_alla_prossima").state == "2"


async def test_le_entita_si_spostano_a_mezzanotte(
    hass: HomeAssistant, gestore, voce: MockConfigEntry, freezer
) -> None:
    """A mezzanotte "stasera" cambia significato, senza richiamare il gestore."""
    freezer.move_to(datetime(2026, 9, 3, 23, 0, tzinfo=ROMA))
    await _avvia(hass, voce)
    assert _stato(hass, voce, "binary_sensor", "esporre_stasera").state == STATE_ON

    chiamate_prima = len(gestore.mock_calls)

    freezer.move_to(datetime(2026, 9, 4, 0, 1, tzinfo=ROMA))
    async_fire_time_changed(hass, datetime(2026, 9, 4, 0, 1, tzinfo=ROMA))
    await hass.async_block_till_done()

    assert _stato(hass, voce, "binary_sensor", "esporre_stasera").state == STATE_OFF
    assert len(gestore.mock_calls) == chiamate_prima, (
        "il risveglio di mezzanotte non deve interrogare il gestore"
    )


async def test_zona_e_pdf(
    hass: HomeAssistant, gestore, voce: MockConfigEntry, freezer
) -> None:
    """Il sensore della zona e' disattivato di serie ma sa il fatto suo."""
    freezer.move_to(SERA_DI_RACCOLTA)
    await _avvia(hass, voce)

    registro = er.async_get(hass)
    entity_id = registro.async_get_entity_id("sensor", DOMAIN, f"{voce.entry_id}_zona")
    voce_registro = registro.async_get(entity_id)
    assert voce_registro.disabled_by is er.RegistryEntryDisabler.INTEGRATION

    registro.async_update_entity(entity_id, disabled_by=None)
    await hass.config_entries.async_reload(voce.entry_id)
    await hass.async_block_till_done()

    zona = hass.states.get(entity_id)
    assert zona.state == "Calendario Padova Q6 2026"
    assert zona.attributes["pdf"].endswith("Q6_Padova_2026_dr_calendario.pdf")


async def test_calendario_con_orario(
    hass: HomeAssistant, gestore, voce: MockConfigEntry, freezer
) -> None:
    """Gli eventi coprono la finestra di esposizione dichiarata dal gestore."""
    freezer.move_to(SERA_DI_RACCOLTA)
    await _avvia(hass, voce)

    stato = _stato(hass, voce, "calendar", "calendario")
    assert stato.state == STATE_OFF  # alle 18:00 la finestra non e' ancora aperta
    assert stato.attributes["message"] == "Organico"
    assert stato.attributes["all_day"] is False
    assert stato.attributes["start_time"] == "2026-09-03 20:00:00"
    assert stato.attributes["end_time"] == "2026-09-04 00:00:00"

    eventi = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": stato.entity_id,
            "start_date_time": datetime(2026, 9, 3, 0, 0, tzinfo=ROMA),
            "duration": {"days": 7},
        },
        blocking=True,
        return_response=True,
    )
    riepilogo = [e["summary"] for e in eventi[stato.entity_id]["events"]]
    # 3 set Organico, 6 Organico, 8 Indifferenziato + Organico, 9 Carta.
    # Nella stessa sera l'ordine e' alfabetico.
    assert riepilogo == [
        "Organico",
        "Organico",
        "Indifferenziato",
        "Organico",
        "Carta",
    ]


async def test_calendario_giornaliero(
    hass: HomeAssistant, aioclient_mock, voce: MockConfigEntry, freezer
) -> None:
    """Spegnendo l'opzione, gli eventi tornano giornalieri."""
    registra(aioclient_mock)
    freezer.move_to(SERA_DI_RACCOLTA)
    voce.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        voce, options={CONF_EVENTI_CON_ORARIO: False}
    )
    await hass.config.async_set_time_zone("Europe/Rome")
    assert await hass.config_entries.async_setup(voce.entry_id)
    await hass.async_block_till_done()

    stato = _stato(hass, voce, "calendar", "calendario")
    assert stato.attributes["all_day"] is True
    assert stato.attributes["start_time"] == "2026-09-03 00:00:00"


async def test_calendari_per_frazione(
    hass: HomeAssistant, aioclient_mock, voce: MockConfigEntry, freezer
) -> None:
    """Un calendario per frazione, ciascuno col colore ufficiale del gestore."""
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
    calendari = [
        e
        for e in er.async_entries_for_config_entry(registro, voce.entry_id)
        if e.domain == "calendar"
    ]
    # Quello complessivo piu' uno per ogni frazione presente nelle fixture.
    assert len(calendari) > 1
    # Le chiavi sono gli id dei macroprodotti, non lo slug del nome: non
    # dipendono dall'ordine in cui il gestore elenca le frazioni.
    chiavi = coordinator_chiavi(hass, voce)
    assert set(chiavi) >= {"Organico", "Imballaggi in vetro"}
    unici = {e.unique_id for e in calendari}
    for frazione in ("Organico", "Imballaggi in vetro"):
        assert f"{voce.entry_id}_calendario_{chiavi[frazione]}" in unici

    vetro = _stato(
        hass, voce, "calendar", f"calendario_{chiavi['Imballaggi in vetro']}"
    )
    assert vetro.attributes["message"] == "Imballaggi in vetro"


async def test_gestore_giu_allo_avvio(
    hass: HomeAssistant, aioclient_mock, voce: MockConfigEntry
) -> None:
    """Se il gestore non risponde all'avvio, la voce va in ritentativo."""
    aioclient_mock.get(f"{BASE_URL}/getCalendarioPap.php", status=503)
    voce.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(voce.entry_id)
    await hass.async_block_till_done()
    assert voce.state is ConfigEntryState.SETUP_RETRY


async def test_bologna_resta_acceso_dopo_la_mezzanotte(
    hass: HomeAssistant, aioclient_mock, voce: MockConfigEntry, freezer
) -> None:
    """Dove la finestra scavalca la mezzanotte, la sera non finisce a mezzanotte.

    A Bologna si espone "dalle 20:00 alle 06:00": alle due di notte c'e' ancora
    tempo, e il sensore deve dirlo. Prima della correzione si spegneva alle 24:00
    e il calendario mostrava un evento giornaliero al posto della finestra.
    """
    registra(
        aioclient_mock, calendario="calendario_bologna", allegati="allegati_bologna"
    )
    freezer.move_to(datetime(2026, 9, 3, 21, 0, tzinfo=ROMA))
    await _avvia(hass, voce)

    assert _stato(hass, voce, "binary_sensor", "esporre_stasera").state == STATE_ON
    calendario = _stato(hass, voce, "calendar", "calendario")
    assert calendario.attributes["all_day"] is False
    assert calendario.attributes["start_time"] == "2026-09-03 20:00:00"
    assert calendario.attributes["end_time"] == "2026-09-04 06:00:00"

    # Le due di notte: la data e' cambiata, la finestra no.
    dopo_mezzanotte = datetime(2026, 9, 4, 2, 0, tzinfo=ROMA)
    freezer.move_to(dopo_mezzanotte)
    async_fire_time_changed(hass, dopo_mezzanotte)
    await hass.async_block_till_done()

    binario = _stato(hass, voce, "binary_sensor", "esporre_stasera")
    assert binario.state == STATE_ON, "la finestra e' ancora aperta"
    assert binario.attributes["data"] == "2026-09-03"
    # Non scende sotto zero: la risposta giusta e' "adesso", non "meno un giorno".
    assert binario.attributes["giorni_mancanti"] == 0

    # Le sette: la finestra si e' chiusa, si guarda avanti.
    mattina = datetime(2026, 9, 4, 7, 0, tzinfo=ROMA)
    freezer.move_to(mattina)
    async_fire_time_changed(hass, mattina)
    await hass.async_block_till_done()

    assert _stato(hass, voce, "binary_sensor", "esporre_stasera").state == STATE_OFF
    assert _stato(hass, voce, "sensor", "prossima_raccolta").state == "2026-09-06"


async def test_faenza_scadenza_resta_giornaliera(
    hass: HomeAssistant, aioclient_mock, voce: MockConfigEntry, freezer
) -> None:
    """A Faenza il gestore dichiara una scadenza, non una finestra."""
    registra(aioclient_mock, calendario="calendario_faenza", allegati="allegati_faenza")
    freezer.move_to(datetime(2026, 9, 3, 18, 0, tzinfo=ROMA))
    await _avvia(hass, voce)

    calendario = _stato(hass, voce, "calendar", "calendario")
    assert calendario.attributes["all_day"] is True
    binario = _stato(hass, voce, "binary_sensor", "esporre_stasera")
    assert binario.state == STATE_ON
    # La frase esatta del gestore resta a disposizione: e' l'unica cosa vera.
    assert binario.attributes["orario_esposizione"] == "entro le 04:00"


async def test_orari_diversi_per_frazione(
    hass: HomeAssistant, aioclient_mock, voce: MockConfigEntry, freezer
) -> None:
    """Con orari diversi fra le frazioni, lo scalare tace e la mappa parla."""
    grezzo = carica("calendario")
    giorno = grezzo["calendario"][0]
    secondo = json.loads(json.dumps(giorno["conferimenti"][0]))
    secondo["macroprodotto"] = {
        "id": 68,
        "descrizione": "Carta",
        "pittogramma": {"nomeFile": "x", "colore": "0093D0"},
    }
    secondo["oraInizio"] = "18:00"
    secondo["orario"] = "dalle 18:00 alle 24:00"
    giorno["conferimenti"].append(secondo)

    registra(aioclient_mock)
    aioclient_mock.clear_requests()
    registra(aioclient_mock)
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE_URL}/getComuni.php", json=carica("comuni"))
    aioclient_mock.get(f"{BASE_URL}/getIndirizzi.php", json=carica("indirizzi"))
    aioclient_mock.get(f"{BASE_URL}/getNumeriCivici.php", json=carica("civici"))
    aioclient_mock.get(f"{BASE_URL}/getCalendarioPap.php", json=grezzo)
    aioclient_mock.get(f"{BASE_URL}/getAllegatiPap.php", json=carica("allegati"))

    freezer.move_to(datetime(2026, 9, 3, 18, 0, tzinfo=ROMA))
    await _avvia(hass, voce)

    binario = _stato(hass, voce, "binary_sensor", "esporre_stasera")
    assert set(binario.attributes["frazioni"]) == {"Organico", "Carta"}
    # Non concordano: lo scalare sarebbe una mezza verita'.
    assert binario.attributes["orario_esposizione"] is None
    assert binario.attributes["orari_esposizione"] == {
        "Organico": "dalle 20:00 alle 24:00",
        "Carta": "dalle 18:00 alle 24:00",
    }
    # Il sensore dell'istante prende il piu' presto, non il primo della lista.
    prossima = _stato(hass, voce, "sensor", "prossima_esposizione")
    assert datetime.fromisoformat(prossima.state).astimezone(ROMA).hour == 18


async def test_calendari_per_frazione_spariscono_dal_registro(
    hass: HomeAssistant, aioclient_mock, voce: MockConfigEntry, freezer
) -> None:
    """Spegnendo l'opzione dal flusso vero, le entita' non restano morte nel registro.

    Si passa dal flusso opzioni e non da async_update_entry proprio perche' il
    ricaricamento della voce fa parte di cio' che si vuole verificare: e'
    OptionsFlowWithReload a innescarlo, ed e' li' che scatta la pulizia.
    """
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

    def calendari() -> list[str]:
        return sorted(
            e.unique_id
            for e in er.async_entries_for_config_entry(registro, voce.entry_id)
            if e.domain == "calendar"
        )

    assert len(calendari()) == 7, "il complessivo piu' le sei frazioni di Padova"

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

    assert calendari() == [f"{voce.entry_id}_calendario"]
    # E nessuna resta appesa nello stato macchina.
    assert not [
        s for s in hass.states.async_all("calendar") if s.state == STATE_UNAVAILABLE
    ]


async def test_prossima_raccolta_non_mostra_mai_ieri(
    hass: HomeAssistant, aioclient_mock, voce: MockConfigEntry, freezer
) -> None:
    """Le due domande hanno due risposte, e nessuna delle due e' una data passata.

    A Bologna il 6 e il 7 settembre sono consecutivi e la finestra del 6 chiude
    alle 06:00 del 7. Alle due di notte: si espone ancora la roba di ieri, ma la
    prossima raccolta e' quella di oggi.
    """
    registra(
        aioclient_mock, calendario="calendario_bologna", allegati="allegati_bologna"
    )
    freezer.move_to(datetime(2026, 9, 7, 2, 0, tzinfo=ROMA))
    await _avvia(hass, voce)

    binario = _stato(hass, voce, "binary_sensor", "esporre_stasera")
    assert binario.state == STATE_ON
    assert binario.attributes["data"] == "2026-09-06", "la finestra di ieri e' aperta"

    prossima = _stato(hass, voce, "sensor", "prossima_raccolta")
    assert prossima.state == "2026-09-07", "la prossima raccolta non puo' essere ieri"
    assert _stato(hass, voce, "sensor", "giorni_alla_prossima").state == "0"

    istante = _stato(hass, voce, "sensor", "prossima_esposizione")
    quando = datetime.fromisoformat(istante.state).astimezone(ROMA)
    assert quando.date() == date(2026, 9, 7)
    assert quando.hour == 20


async def test_le_frazioni_assenti_non_vengono_cancellate(
    hass: HomeAssistant, aioclient_mock, voce: MockConfigEntry, freezer
) -> None:
    """Un calendario temporaneamente vuoto non deve distruggere le entita'.

    E' il caso che il coordinator stesso definisce normale, e prima portava via
    le sei entita' per frazione insieme al nome scelto a mano dall'utente.
    """
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

    def calendari() -> set[str]:
        return {
            e.unique_id
            for e in er.async_entries_for_config_entry(registro, voce.entry_id)
            if e.domain == "calendar"
        }

    prima = calendari()
    assert len(prima) == 7

    # L'utente rinomina un'entita': e' la cosa che si perderebbe.
    chiavi = coordinator_chiavi(hass, voce)
    carta = registro.async_get_entity_id(
        "calendar", DOMAIN, f"{voce.entry_id}_calendario_{chiavi['Carta']}"
    )
    registro.async_update_entity(carta, name="La carta di casa")

    # Il gestore smette di rispondere col calendario, e Home Assistant riparte.
    aioclient_mock.clear_requests()
    registra(aioclient_mock, calendario="calendario_vuoto", allegati="allegati_vuoti")
    await hass.config_entries.async_reload(voce.entry_id)
    await hass.async_block_till_done()

    assert calendari() == prima, "nessuna entita' va cancellata"
    assert registro.async_get(carta).name == "La carta di casa"


async def test_frazioni_che_collidono_restano_due_entita(
    hass: HomeAssistant, aioclient_mock, voce: MockConfigEntry, freezer
) -> None:
    """Due nomi che danno lo stesso slug non devono far sparire un'entita'."""
    grezzo = carica("calendario")
    giorno = grezzo["calendario"][0]
    gemello = json.loads(json.dumps(giorno["conferimenti"][0]))
    # "Carta e cartone" e "Carta-e-cartone" danno lo stesso slug.
    giorno["conferimenti"][0]["macroprodotto"]["descrizione"] = "Carta e cartone"
    gemello["macroprodotto"] = {
        "id": 99,
        "descrizione": "Carta-e-cartone",
        "pittogramma": {"nomeFile": "x", "colore": "0093D0"},
    }
    giorno["conferimenti"].append(gemello)

    aioclient_mock.get(f"{BASE_URL}/getComuni.php", json=carica("comuni"))
    aioclient_mock.get(f"{BASE_URL}/getIndirizzi.php", json=carica("indirizzi"))
    aioclient_mock.get(f"{BASE_URL}/getNumeriCivici.php", json=carica("civici"))
    aioclient_mock.get(f"{BASE_URL}/getCalendarioPap.php", json=grezzo)
    aioclient_mock.get(f"{BASE_URL}/getAllegatiPap.php", json=carica("allegati"))

    freezer.move_to(SERA_DI_RACCOLTA)
    voce.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        voce, options={CONF_CALENDARI_PER_FRAZIONE: True}
    )
    await hass.config.async_set_time_zone("Europe/Rome")
    assert await hass.config_entries.async_setup(voce.entry_id)
    await hass.async_block_till_done()

    registro = er.async_get(hass)
    chiavi = {
        e.unique_id
        for e in er.async_entries_for_config_entry(registro, voce.entry_id)
        if e.domain == "calendar"
    }
    # Le due frazioni che condividono la chiave stabile ne ottengono comunque
    # due diverse: nessuna delle due sparisce, che era il difetto.
    per_frazione = [c for c in chiavi if c != f"{voce.entry_id}_calendario"]
    assert len(per_frazione) == len(set(per_frazione))
    nomi = {
        s.attributes.get("friendly_name", "") for s in hass.states.async_all("calendar")
    }
    assert any("Carta e cartone" in n for n in nomi)
    assert any("Carta-e-cartone" in n for n in nomi)


async def test_niente_fascia_morta_a_modena(
    hass: HomeAssistant, aioclient_mock, voce: MockConfigEntry, freezer
) -> None:
    """Due entita' dello stesso dispositivo non devono contraddirsi.

    Modena espone "dalle 00:00 alle 07:00". Dalle 07:00 a mezzanotte - 17 ore su
    24 - il sensore dell'esposizione e' spento; prima, «giorni alla prossima»
    diceva 0 lo stesso, perche' ragionava per data e non per finestra.
    """
    registra(aioclient_mock, calendario="calendario_modena", allegati="allegati_modena")
    freezer.move_to(datetime(2026, 9, 3, 10, 0, tzinfo=ROMA))
    await _avvia(hass, voce)

    acceso = _stato(hass, voce, "binary_sensor", "esporre_stasera").state == STATE_ON
    giorni = int(_stato(hass, voce, "sensor", "giorni_alla_prossima").state)
    assert not acceso, "alle 10:00 la finestra delle 00:00-07:00 e' chiusa"
    assert giorni > 0, "e allora non puo' dire che la prossima e' oggi"

    prossima = _stato(hass, voce, "sensor", "prossima_raccolta").state
    assert prossima > "2026-09-03", f"prossima raccolta e' {prossima}, cioe' oggi"

    # E dentro la finestra le due tornano d'accordo.
    freezer.move_to(datetime(2026, 9, 3, 3, 0, tzinfo=ROMA))
    await hass.config_entries.async_reload(voce.entry_id)
    await hass.async_block_till_done()
    assert _stato(hass, voce, "binary_sensor", "esporre_stasera").state == STATE_ON
    assert _stato(hass, voce, "sensor", "giorni_alla_prossima").state == "0"


async def test_gradara_smette_di_elencare_la_frazione_scaduta(
    hass: HomeAssistant, aioclient_mock, voce: MockConfigEntry, freezer
) -> None:
    """In una sera con due finestre, quella scaduta sparisce dall'elenco.

    Gradara: una frazione chiude alle 23:00, l'altra alle 06:00 del giorno dopo.
    """
    registra(
        aioclient_mock, calendario="calendario_gradara", allegati="allegati_gradara"
    )
    # L'8 settembre e' la sera con due finestre diverse: Indifferenziato fino
    # alle 23:00, Organico fino alle 06:00 del giorno dopo.
    freezer.move_to(datetime(2026, 9, 8, 22, 0, tzinfo=ROMA))
    await _avvia(hass, voce)

    binario = _stato(hass, voce, "binary_sensor", "esporre_stasera")
    entrambe = set(binario.attributes["frazioni"])
    assert entrambe == {"Indifferenziato", "Organico"}

    # Passata la mezzanotte: chi chiudeva alle 23:00 non e' piu' esponibile.
    dopo = datetime(2026, 9, 9, 0, 30, tzinfo=ROMA)
    freezer.move_to(dopo)
    async_fire_time_changed(hass, dopo)
    await hass.async_block_till_done()

    binario = _stato(hass, voce, "binary_sensor", "esporre_stasera")
    assert binario.state == STATE_ON, "una finestra e' ancora aperta"
    rimaste = set(binario.attributes["frazioni"])
    assert rimaste == {"Organico"}, (
        f"l'Indifferenziato e' scaduto alle 23:00: {rimaste}"
    )
    # E l'orario elencato e' solo quello di chi e' rimasto.
    assert set(binario.attributes["orari_esposizione"]) == rimaste
    testo = _stato(hass, voce, "sensor", "esposizione_stasera").state
    assert set(testo.split(", ")) == rimaste


async def test_la_frazione_scaduta_sparisce_all_ora_giusta(
    hass: HomeAssistant, aioclient_mock, voce: MockConfigEntry, freezer
) -> None:
    """Non basta che il calcolo sia giusto: qualcuno deve ricalcolare a quell'ora.

    A Gradara l'Indifferenziato chiude alle 23:00. Il risveglio era programmato
    a mezzanotte, quindi fra le 23:00 e le 00:00 lo stato PUBBLICATO diceva
    ancora di esporlo, contraddicendo il proprio attributo orari_esposizione.
    """
    registra(
        aioclient_mock, calendario="calendario_gradara", allegati="allegati_gradara"
    )
    freezer.move_to(datetime(2026, 9, 8, 22, 0, tzinfo=ROMA))
    await _avvia(hass, voce)

    binario = _stato(hass, voce, "binary_sensor", "esporre_stasera")
    assert set(binario.attributes["frazioni"]) == {"Indifferenziato", "Organico"}

    # Le 23:30: la mezzanotte non e' ancora arrivata, ma una frazione e' scaduta.
    alle_23_30 = datetime(2026, 9, 8, 23, 30, tzinfo=ROMA)
    freezer.move_to(alle_23_30)
    async_fire_time_changed(hass, alle_23_30)
    await hass.async_block_till_done()

    binario = _stato(hass, voce, "binary_sensor", "esporre_stasera")
    assert binario.attributes["frazioni"] == ["Organico"], (
        "lo stato pubblicato non e' stato ricalcolato alla scadenza delle 23:00"
    )
    assert _stato(hass, voce, "sensor", "esposizione_stasera").state == "Organico"


async def test_le_chiavi_non_dipendono_dall_ordine_dell_api(
    hass: HomeAssistant, aioclient_mock, voce: MockConfigEntry, freezer
) -> None:
    """Due frazioni che collidono non devono scambiarsi identita' fra due avvii.

    Quando il gestore non dichiara l'id del macroprodotto la chiave ripiega
    sullo slug del nome, e due nomi che differiscono solo nella punteggiatura
    danno lo stesso slug. Il discriminante che li separa deve dipendere dal
    NOME e non dall'ordine in cui l'API li elenca: altrimenti al riavvio
    successivo la stessa entita' - con il nome che l'utente le ha dato e le
    automazioni che la citano - si ritrova gli eventi dell'altra frazione.
    """

    def payload(invertito: bool) -> dict:
        grezzo = carica("calendario")
        giorno = grezzo["calendario"][0]
        base = json.loads(json.dumps(giorno["conferimenti"][0]))
        gemelli = []
        for nome in ("Pannolini/Pannoloni", "Pannolini - Pannoloni"):
            copia = json.loads(json.dumps(base))
            # Senza id, la chiave ripiega sullo slug: i due collidono.
            copia["macroprodotto"] = {
                "id": None,
                "descrizione": nome,
                "pittogramma": {"nomeFile": "x", "colore": "701100"},
            }
            gemelli.append(copia)
        if invertito:
            gemelli.reverse()
        giorno["conferimenti"] = gemelli
        return grezzo

    def registra_con(grezzo: dict) -> None:
        aioclient_mock.clear_requests()
        aioclient_mock.get(f"{BASE_URL}/getComuni.php", json=carica("comuni"))
        aioclient_mock.get(f"{BASE_URL}/getIndirizzi.php", json=carica("indirizzi"))
        aioclient_mock.get(f"{BASE_URL}/getNumeriCivici.php", json=carica("civici"))
        aioclient_mock.get(f"{BASE_URL}/getCalendarioPap.php", json=grezzo)
        aioclient_mock.get(f"{BASE_URL}/getAllegatiPap.php", json=carica("allegati"))

    registra_con(payload(invertito=False))
    freezer.move_to(SERA_DI_RACCOLTA)
    voce.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        voce, options={CONF_CALENDARI_PER_FRAZIONE: True}
    )
    await hass.config.async_set_time_zone("Europe/Rome")
    assert await hass.config_entries.async_setup(voce.entry_id)
    await hass.async_block_till_done()

    registro = er.async_get(hass)

    def mappa() -> dict[str, str]:
        """unique_id -> nome della frazione servita da quell'entita'."""
        fuori: dict[str, str] = {}
        for e in er.async_entries_for_config_entry(registro, voce.entry_id):
            if e.domain != "calendar" or not e.unique_id.startswith(
                f"{voce.entry_id}_calendario_"
            ):
                continue
            stato = hass.states.get(e.entity_id)
            nome = stato.attributes["message"]
            # Solo le due gemelle: le altre frazioni della fixture non c'entrano.
            if "Pannol" in nome:
                fuori[e.unique_id] = nome
        return fuori

    prima = mappa()
    assert len(prima) == 2, f"una delle due frazioni e' sparita: {prima}"
    assert set(prima.values()) == {"Pannolini/Pannoloni", "Pannolini - Pannoloni"}

    # Stesso insieme, ordine invertito dall'API: le identita' devono reggere.
    registra_con(payload(invertito=True))
    await hass.config_entries.async_reload(voce.entry_id)
    await hass.async_block_till_done()

    assert mappa() == prima, "le due entita' si sono scambiate identita'"


async def test_niente_entita_orfane_mentre_la_voce_si_scarica(
    hass: HomeAssistant, aioclient_mock, voce: MockConfigEntry, freezer
) -> None:
    """Un aggiornamento che arriva durante lo scaricamento non deve creare entita'.

    Nei sorgenti di Home Assistant lo stato passa a UNLOAD_IN_PROGRESS PRIMA che
    le piattaforme vengano smontate, e le callback di async_on_unload girano
    dopo: in quella finestra un flag registrato li' arriverebbe sempre tardi, ed
    e' per questo che la guardia guarda lo STATO della voce.
    """
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

    def quanti() -> int:
        return len(
            [
                e
                for e in er.async_entries_for_config_entry(registro, voce.entry_id)
                if e.domain == "calendar"
            ]
        )

    prima = quanti()
    coordinator = voce.runtime_data

    # Una frazione nuova arriva mentre la voce si sta smontando.
    calendario = coordinator.data
    giorno = calendario.giorni[0]
    inedita = dataclasses.replace(
        giorno.conferimenti[0], frazione="Sfalci e potature", macroprodotto_id=777
    )
    con_inedita = dataclasses.replace(
        calendario,
        giorni=(
            dataclasses.replace(giorno, conferimenti=(*giorno.conferimenti, inedita)),
            *calendario.giorni[1:],
        ),
    )

    voce.mock_state(hass, ConfigEntryState.UNLOAD_IN_PROGRESS)
    coordinator.async_set_updated_data(con_inedita)
    await hass.async_block_till_done()

    assert quanti() == prima, "creata un'entita' mentre la voce si scaricava"

    # E a voce di nuovo carica la stessa frazione nasce, come deve.
    voce.mock_state(hass, ConfigEntryState.LOADED)
    coordinator.async_set_updated_data(con_inedita)
    await hass.async_block_till_done()
    assert quanti() == prima + 1
