"""Test dell'avvio e delle entita', con il tempo congelato."""

from __future__ import annotations

import dataclasses
from datetime import date, datetime
import json
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.rifiutologo.api import BASE_URL
from custom_components.rifiutologo.const import (
    CONF_CALENDARI_PER_FRAZIONE,
    CONF_GIORNI_DA_MOSTRARE,
    CONF_SENSORI_PER_FRAZIONE,
    DOMAIN,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
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


def _settimana(hass: HomeAssistant, voce: MockConfigEntry):
    """Gli attributi della settimana, che dalla 0.6.0 stanno sul CALENDARIO.

    Ci stanno perche' un'agenda e' il mestiere di un calendario, e perche' il
    sensore che li portava - "Raccolte in settimana" - si presentava come un
    contatore e faceva credere che il numero fosse la cosa importante.
    """
    return _stato(hass, voce, "calendar", "calendario")


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
    # La prossima esposizione e' la sera del 6, non stasera.
    prossima = _stato(hass, voce, "sensor", "prossima_esposizione")
    assert datetime.fromisoformat(prossima.state).astimezone(ROMA).date() == date(
        2026, 9, 6
    )


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
    prossima = _stato(hass, voce, "sensor", "prossima_esposizione")
    assert datetime.fromisoformat(prossima.state).astimezone(ROMA).date() == date(
        2026, 9, 6
    )


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
    assert not acceso, "alle 10:00 la finestra delle 00:00-07:00 e' chiusa"

    prossima = _stato(hass, voce, "sensor", "prossima_esposizione")
    quando = datetime.fromisoformat(prossima.state).astimezone(ROMA)
    assert quando.date() > date(2026, 9, 3), (
        f"l'inizio esposizione e' {quando}, cioe' oggi, che e' gia' passato"
    )

    # E dentro la finestra le due tornano d'accordo.
    freezer.move_to(datetime(2026, 9, 3, 3, 0, tzinfo=ROMA))
    await hass.config_entries.async_reload(voce.entry_id)
    await hass.async_block_till_done()
    assert _stato(hass, voce, "binary_sensor", "esporre_stasera").state == STATE_ON


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


# --- il riepilogo della settimana --------------------------------------------


async def test_la_settimana_elenca_le_sere(
    hass: HomeAssistant, gestore, voce: MockConfigEntry, freezer
) -> None:
    """Sette giorni dal 3 al 9 settembre: quattro sere di esposizione."""
    freezer.move_to(SERA_DI_RACCOLTA)
    await _avvia(hass, voce)

    settimana = _settimana(hass, voce)
    assert settimana.attributes["da"] == "2026-09-03"
    assert settimana.attributes["a"] == "2026-09-09"

    giorni = settimana.attributes["giorni"]
    assert [g["data"] for g in giorni] == [
        "2026-09-03",
        "2026-09-06",
        "2026-09-08",
        "2026-09-09",
    ]
    assert [g["giorni_mancanti"] for g in giorni] == [0, 3, 5, 6]
    assert [g["giorno_settimana"] for g in giorni] == [4, 7, 2, 3], (
        "giovedi', domenica, martedi', mercoledi'"
    )
    assert giorni[2]["frazioni"] == ["Indifferenziato", "Organico"]
    assert giorni[0]["inizio_esposizione"] == "2026-09-03T20:00:00+02:00"
    assert giorni[0]["fine_esposizione"] == "2026-09-04T00:00:00+02:00"

    # L'ordine e' quello di prima comparsa, non alfabetico.
    assert settimana.attributes["frazioni"] == ["Organico", "Indifferenziato", "Carta"]


async def test_la_settimana_non_contraddice_stasera(
    hass: HomeAssistant, gestore, voce: MockConfigEntry, freezer
) -> None:
    """La prima sera dell'elenco e' quella che il sensore di stasera racconta."""
    freezer.move_to(datetime(2026, 9, 3, 23, 0, tzinfo=ROMA))
    await _avvia(hass, voce)

    giorni = _settimana(hass, voce).attributes["giorni"]
    stasera = _stato(hass, voce, "sensor", "esposizione_stasera")
    assert stasera.state == "Organico"
    assert giorni[0]["data"] == stasera.attributes["data"] == "2026-09-03"
    assert giorni[0]["frazioni"] == stasera.attributes["frazioni"]

    # Passata la mezzanotte la sera del 3 esce dall'elenco, e in fondo entra
    # il 10: la finestra e' scorsa di un giorno insieme al calendario.
    dopo = datetime(2026, 9, 4, 0, 30, tzinfo=ROMA)
    freezer.move_to(dopo)
    async_fire_time_changed(hass, dopo)
    await hass.async_block_till_done()

    settimana = _settimana(hass, voce)
    assert [g["data"] for g in settimana.attributes["giorni"]] == [
        "2026-09-06",
        "2026-09-08",
        "2026-09-09",
        "2026-09-10",
    ]
    assert _stato(hass, voce, "sensor", "esposizione_stasera").state == "nessuna"


async def test_la_settimana_tiene_la_sera_di_ieri_ancora_aperta(
    hass: HomeAssistant, aioclient_mock, voce: MockConfigEntry, freezer
) -> None:
    """A Bologna, alle due di notte, la sera di ieri e' ancora la prima della lista.

    E' l'unico caso in cui l'elenco comincia prima di `da`, ed e' quello giusto:
    quel sacco va ancora messo fuori.
    """
    registra(
        aioclient_mock, calendario="calendario_bologna", allegati="allegati_bologna"
    )
    freezer.move_to(datetime(2026, 9, 4, 2, 0, tzinfo=ROMA))
    await _avvia(hass, voce)

    settimana = _settimana(hass, voce)
    assert settimana.attributes["da"] == "2026-09-04"
    giorni = settimana.attributes["giorni"]
    assert giorni[0]["data"] == "2026-09-03", "la finestra di ieri chiude alle 06:00"
    assert giorni[0]["giorni_mancanti"] == 0, "non scende sotto zero"
    assert giorni[0]["fine_esposizione"] == "2026-09-04T06:00:00+02:00"
    assert _stato(hass, voce, "binary_sensor", "esporre_stasera").state == STATE_ON


async def test_la_settimana_perde_la_frazione_scaduta(
    hass: HomeAssistant, aioclient_mock, voce: MockConfigEntry, freezer
) -> None:
    """Il taglio delle frazioni scadute vale anche nel riepilogo, non solo stasera.

    A Gradara l'8 settembre l'Indifferenziato chiude alle 23:00 e l'Organico
    alle 06:00: dopo le 23:00 il riepilogo deve dire una cosa sola, come il
    sensore di stasera, e non due.
    """
    registra(
        aioclient_mock, calendario="calendario_gradara", allegati="allegati_gradara"
    )
    freezer.move_to(datetime(2026, 9, 8, 22, 0, tzinfo=ROMA))
    await _avvia(hass, voce)

    prima = _settimana(hass, voce).attributes["giorni"]
    assert prima[0]["frazioni"] == ["Indifferenziato", "Organico"]

    dopo = datetime(2026, 9, 8, 23, 30, tzinfo=ROMA)
    freezer.move_to(dopo)
    async_fire_time_changed(hass, dopo)
    await hass.async_block_till_done()

    settimana = _settimana(hass, voce)
    giorni = settimana.attributes["giorni"]
    assert giorni[0]["data"] == "2026-09-08"
    assert giorni[0]["frazioni"] == ["Organico"]
    assert set(settimana.attributes["frazioni"]) == {
        "Organico",
        "Plastica",
        "Lattine",
        "Carta",
    }, "l'Indifferenziato scaduto non compare piu' nemmeno nel riepilogo"
    stasera = _stato(hass, voce, "sensor", "esposizione_stasera")
    assert stasera.state == "Organico"


async def test_la_settimana_senza_raccolte_dice_zero(
    hass: HomeAssistant, aioclient_mock, voce: MockConfigEntry, freezer
) -> None:
    """Zero e' una risposta; `unknown` sarebbe un'altra cosa."""
    registra(aioclient_mock, calendario="calendario_vuoto", allegati="allegati_vuoti")
    freezer.move_to(SERA_DI_RACCOLTA)
    await _avvia(hass, voce)

    settimana = _settimana(hass, voce)
    assert settimana.attributes["giorni"] == []
    assert settimana.attributes["frazioni"] == []
    assert settimana.attributes["calendario"] == {}


# --- un sensore per ogni frazione --------------------------------------------


async def _avvia_con_sensori(
    hass: HomeAssistant, voce: MockConfigEntry, quando: datetime
) -> None:
    """Avvia la voce con l'opzione dei sensori per frazione accesa."""
    voce.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        voce, options={CONF_SENSORI_PER_FRAZIONE: True}
    )
    await hass.config.async_set_time_zone("Europe/Rome")
    assert await hass.config_entries.async_setup(voce.entry_id)
    await hass.async_block_till_done()


def _sensori_frazione(hass: HomeAssistant, voce: MockConfigEntry) -> list[str]:
    """Gli unique_id dei soli sensori per frazione."""
    registro = er.async_get(hass)
    return sorted(
        e.unique_id
        for e in er.async_entries_for_config_entry(registro, voce.entry_id)
        if e.domain == "sensor" and e.unique_id.startswith(f"{voce.entry_id}_frazione_")
    )


async def test_i_sensori_per_frazione_sono_spenti_di_serie(
    hass: HomeAssistant, gestore, voce: MockConfigEntry, freezer
) -> None:
    """Sei entita' in piu' non devono comparire a chi non le ha chieste."""
    freezer.move_to(SERA_DI_RACCOLTA)
    await _avvia(hass, voce)
    assert _sensori_frazione(hass, voce) == []
    # Ma i sensori fissi ci sono tutti.
    assert _stato(hass, voce, "sensor", "esposizione_stasera") is not None


async def test_un_sensore_per_ogni_frazione(
    hass: HomeAssistant, aioclient_mock, voce: MockConfigEntry, freezer
) -> None:
    """Sei frazioni a Padova, sei sensori, ciascuno con la SUA prossima data."""
    registra(aioclient_mock)
    freezer.move_to(SERA_DI_RACCOLTA)
    await _avvia_con_sensori(hass, voce, SERA_DI_RACCOLTA)

    assert len(_sensori_frazione(hass, voce)) == 6
    chiavi = coordinator_chiavi(hass, voce)

    carta = _stato(hass, voce, "sensor", f"frazione_{chiavi['Carta']}")
    assert carta.state == "2026-09-09", "la carta passa il 9, non il 3"
    assert carta.attributes["frazione"] == "Carta"
    assert carta.attributes["colore"] == "#0093D0"
    assert carta.attributes["giorni_mancanti"] == 6
    assert carta.attributes["giorno_settimana"] == 3
    assert carta.attributes["inizio_esposizione"] == "2026-09-09T20:00:00+02:00"
    assert carta.attributes["fine_esposizione"] == "2026-09-10T00:00:00+02:00"
    assert carta.attributes["orario_esposizione"] == "dalle 20:00 alle 24:00"
    assert carta.attributes["prossime"] == ["2026-09-09"]

    organico = _stato(hass, voce, "sensor", f"frazione_{chiavi['Organico']}")
    assert organico.state == "2026-09-03", "stasera"
    assert organico.attributes["giorni_mancanti"] == 0
    assert organico.attributes["prossime"] == [
        "2026-09-03",
        "2026-09-06",
        "2026-09-08",
        "2026-09-10",
        "2026-09-13",
    ], "cinque date e non di piu'"


async def test_il_sensore_di_frazione_non_guarda_indietro(
    hass: HomeAssistant, aioclient_mock, voce: MockConfigEntry, freezer
) -> None:
    """Un sensore `date` che pubblica ieri e' un sensore che mente.

    A Bologna alle due di notte la sera di ieri e' ancora esponibile - e infatti
    "Raccolta stasera" e' acceso - ma la prossima DATA e' quella dopo.
    """
    registra(
        aioclient_mock, calendario="calendario_bologna", allegati="allegati_bologna"
    )
    notte = datetime(2026, 9, 4, 2, 0, tzinfo=ROMA)
    freezer.move_to(notte)
    await _avvia_con_sensori(hass, voce, notte)

    chiavi = coordinator_chiavi(hass, voce)
    organico = _stato(hass, voce, "sensor", f"frazione_{chiavi['Organico']}")
    assert organico.state == "2026-09-06"
    assert _stato(hass, voce, "binary_sensor", "esporre_stasera").state == STATE_ON
    assert (
        _stato(hass, voce, "binary_sensor", "esporre_stasera").attributes["data"]
        == "2026-09-03"
    ), "le due entita' rispondono a due domande diverse"


async def test_spegnere_i_sensori_per_frazione_li_toglie_dal_registro(
    hass: HomeAssistant, aioclient_mock, voce: MockConfigEntry, freezer
) -> None:
    """Senza la pulizia resterebbero per sempre "non disponibili".

    E non deve portarsi via i sensori fissi, che stanno nella stessa
    piattaforma e si distinguono solo dal prefisso dell'unique_id.
    """
    registra(aioclient_mock)
    freezer.move_to(SERA_DI_RACCOLTA)
    await _avvia_con_sensori(hass, voce, SERA_DI_RACCOLTA)
    assert len(_sensori_frazione(hass, voce)) == 6

    risultato = await hass.config_entries.options.async_init(voce.entry_id)
    await hass.config_entries.options.async_configure(
        risultato["flow_id"],
        {
            CONF_CALENDARI_PER_FRAZIONE: False,
            CONF_SENSORI_PER_FRAZIONE: False,
            CONF_GIORNI_DA_MOSTRARE: 365,
        },
    )
    await hass.async_block_till_done()

    assert _sensori_frazione(hass, voce) == []

    # Si guarda il REGISTRO e non gli stati: "Zona di raccolta" e' disattivata
    # di serie, quindi e' registrata ma non ha stato, e cercarne uno direbbe
    # "cancellata" di un'entita' che sta benissimo dov'e'.
    registro = er.async_get(hass)
    rimasti = {
        e.unique_id
        for e in er.async_entries_for_config_entry(registro, voce.entry_id)
        if e.domain == "sensor"
    }
    for chiave in (
        "esposizione_stasera",
        "prossima_esposizione",
        "zona",
    ):
        assert f"{voce.entry_id}_{chiave}" in rimasti, (
            f"la pulizia si e' portata via {chiave}"
        )


# --- il calendario dice se si puo' esporre ADESSO ----------------------------


async def test_il_calendario_e_stasera_non_dicono_la_stessa_cosa(
    hass: HomeAssistant, gestore, voce: MockConfigEntry, freezer
) -> None:
    """Alle 18:00 tocca stasera, ma il sacco fuori adesso e' fuori regolamento.

    Sono le due domande che prima si confondevano perche' entrambe le righe
    dicevano "Acceso": il calendario risponde a "posso esporre ADESSO", il
    binario a "stasera tocca, e sono ancora in tempo".
    """
    freezer.move_to(SERA_DI_RACCOLTA)
    await _avvia(hass, voce)

    assert _stato(hass, voce, "binary_sensor", "esporre_stasera").state == STATE_ON
    calendario = _stato(hass, voce, "calendar", "calendario")
    assert calendario.state == STATE_OFF, "l'esposizione comincia alle 20:00"

    # Alle 20:00 si apre, e allora dicono la stessa cosa.
    apre = datetime(2026, 9, 3, 20, 0, tzinfo=ROMA)
    freezer.move_to(apre)
    async_fire_time_changed(hass, apre)
    await hass.async_block_till_done()

    calendario = _stato(hass, voce, "calendar", "calendario")
    assert calendario.state == STATE_ON
    assert calendario.attributes["message"] == "Organico"
    assert _stato(hass, voce, "binary_sensor", "esporre_stasera").state == STATE_ON

    # A mezzanotte si chiudono tutte e due.
    chiude = datetime(2026, 9, 4, 0, 1, tzinfo=ROMA)
    freezer.move_to(chiude)
    async_fire_time_changed(hass, chiude)
    await hass.async_block_till_done()

    assert _stato(hass, voce, "calendar", "calendario").state == STATE_OFF
    assert _stato(hass, voce, "binary_sensor", "esporre_stasera").state == STATE_OFF


async def test_il_calendario_si_apre_da_solo_senza_richiamare_il_gestore(
    hass: HomeAssistant, gestore, voce: MockConfigEntry, freezer
) -> None:
    """Il risveglio all'apertura c'e' gia': va solo verificato che ci sia."""
    prima = datetime(2026, 9, 3, 19, 59, tzinfo=ROMA)
    freezer.move_to(prima)
    await _avvia(hass, voce)
    scarichi = sum(1 for c in gestore.mock_calls if "getCalendarioPap.php" in str(c[1]))
    assert _stato(hass, voce, "calendar", "calendario").state == STATE_OFF

    apre = datetime(2026, 9, 3, 20, 0, tzinfo=ROMA)
    freezer.move_to(apre)
    async_fire_time_changed(hass, apre)
    await hass.async_block_till_done()

    assert _stato(hass, voce, "calendar", "calendario").state == STATE_ON
    dopo = sum(1 for c in gestore.mock_calls if "getCalendarioPap.php" in str(c[1]))
    assert dopo == scarichi, "un confine di giornata non e' un dato nuovo"


async def test_un_termine_vale_da_mezzanotte(
    hass: HomeAssistant, aioclient_mock, voce: MockConfigEntry, freezer
) -> None:
    """A Faenza "entro le 04:00" non e' un'apertura: si puo' esporre tutto il giorno."""
    registra(aioclient_mock, calendario="calendario_faenza", allegati="allegati_faenza")
    mattina = datetime(2026, 9, 3, 9, 0, tzinfo=ROMA)
    freezer.move_to(mattina)
    await _avvia(hass, voce)

    calendario = _stato(hass, voce, "calendar", "calendario")
    assert calendario.state == STATE_ON, "nessun'ora prima della quale sia vietato"
    assert calendario.attributes["message"] == "Indifferenziato"
    assert calendario.attributes["all_day"] is True, "un termine non e' una durata"


async def test_bologna_e_ancora_aperta_alle_due_di_notte(
    hass: HomeAssistant, aioclient_mock, voce: MockConfigEntry, freezer
) -> None:
    """Dove scavalca la mezzanotte, alle due si puo' ancora uscire davvero."""
    registra(
        aioclient_mock, calendario="calendario_bologna", allegati="allegati_bologna"
    )
    notte = datetime(2026, 9, 4, 2, 0, tzinfo=ROMA)
    freezer.move_to(notte)
    await _avvia(hass, voce)

    calendario = _stato(hass, voce, "calendar", "calendario")
    assert calendario.state == STATE_ON
    assert calendario.attributes["start_time"] == "2026-09-03 20:00:00", (
        "l'evento in corso e' quello di ieri sera"
    )

    # Alle sette e' finita.
    mattina = datetime(2026, 9, 4, 7, 0, tzinfo=ROMA)
    freezer.move_to(mattina)
    async_fire_time_changed(hass, mattina)
    await hass.async_block_till_done()
    assert _stato(hass, voce, "calendar", "calendario").state == STATE_OFF


async def test_frazione_fuori_orizzonte_non_inventa_una_data(
    hass: HomeAssistant, aioclient_mock, voce: MockConfigEntry, freezer
) -> None:
    """Se nell'orizzonte quella frazione non ricompare, lo stato e' sconosciuto.

    Non e' un caso di laboratorio: a Padova fra due raccolte del vetro passano
    fino a 35 giorni, e chi accorcia l'orizzonte a 30 si trova esattamente qui.
    L'entita' resta - la frazione esiste, il gestore la nomina - ma la data no.
    """
    registra(aioclient_mock)
    # Il 21 settembre, nelle fixture, la carta e' passata il 9 e non torna.
    tardi = datetime(2026, 9, 21, 18, 0, tzinfo=ROMA)
    freezer.move_to(tardi)
    await _avvia_con_sensori(hass, voce, tardi)

    chiavi = coordinator_chiavi(hass, voce)
    carta = _stato(hass, voce, "sensor", f"frazione_{chiavi['Carta']}")
    assert carta.state == STATE_UNKNOWN
    assert carta.attributes["prossime"] == []
    assert carta.attributes["giorni_mancanti"] is None
    assert carta.attributes["inizio_esposizione"] is None
    assert carta.attributes["straordinario"] is False
    # Il nome e il colore restano: descrivono la frazione, non la data.
    assert carta.attributes["frazione"] == "Carta"
    assert carta.attributes["colore"] == "#0093D0"

    # E l'organico, che invece torna, ha la sua data.
    organico = _stato(hass, voce, "sensor", f"frazione_{chiavi['Organico']}")
    assert organico.state == "2026-09-22"


async def test_la_frazione_scaduta_oggi_non_e_la_prossima(
    hass: HomeAssistant, aioclient_mock, voce: MockConfigEntry, freezer
) -> None:
    """A Modena si espone dalle 00:00 alle 07:00: a mezzogiorno oggi e' andato.

    E' il caso in cui la data da sola non basta: il giorno e' ancora quello di
    oggi, ma la finestra si e' chiusa cinque ore fa. Senza il controllo sulla
    scadenza il sensore indicherebbe una sera gia' persa.
    """
    registra(aioclient_mock, calendario="calendario_modena", allegati="allegati_modena")
    mezzogiorno = datetime(2026, 9, 4, 12, 0, tzinfo=ROMA)
    freezer.move_to(mezzogiorno)
    await _avvia_con_sensori(hass, voce, mezzogiorno)

    chiavi = coordinator_chiavi(hass, voce)
    organico = _stato(hass, voce, "sensor", f"frazione_{chiavi['Organico']}")
    assert organico.state == "2026-09-07", (
        "l'organico del 4 si esponeva entro le 07:00: a mezzogiorno e' passato"
    )
    assert organico.attributes["prossime"][0] == "2026-09-07"
    # E prima delle sette invece e' ancora quella di oggi.
    assert _stato(hass, voce, "binary_sensor", "esporre_stasera").state == STATE_OFF


async def test_la_pulizia_tocca_solo_le_entita_per_frazione(
    hass: HomeAssistant, aioclient_mock, voce: MockConfigEntry, freezer
) -> None:
    """Si guarda CHE COSA rimuove, non che cosa resta alla fine.

    Alla fine le due cose non si distinguono, e non per un difetto del test:
    Home Assistant conserva le voci rimosse e ne restituisce nome, icona e area
    appena lo stesso unique_id ricompare, quindi un sensore fisso cancellato e
    subito ricreato torna identico. Verificato su questo codice, cancellando di
    proposito tutti i sensori: il nome scelto a mano era ancora li'.

    Quindi una pulizia che allarga il tiro non lascia tracce nello stato finale,
    e l'unico modo di accorgersene e' guardarla mentre lavora. Il danno vero lo
    farebbe su un'entita' che NON ricompare - una frazione stagionale fuori
    stagione - e quella non c'e' modo di ricrearla per accorgersene dopo.
    """
    registra(aioclient_mock)
    freezer.move_to(SERA_DI_RACCOLTA)
    await _avvia_con_sensori(hass, voce, SERA_DI_RACCOLTA)

    registro = er.async_get(hass)
    attesi = {
        e.entity_id
        for e in er.async_entries_for_config_entry(registro, voce.entry_id)
        if e.unique_id.startswith(f"{voce.entry_id}_frazione_")
    }
    assert len(attesi) == 6

    rimossi: list[str] = []
    originale = er.EntityRegistry.async_remove

    def _sorveglia(self: er.EntityRegistry, entity_id: str) -> None:
        rimossi.append(entity_id)
        originale(self, entity_id)

    with patch.object(er.EntityRegistry, "async_remove", _sorveglia):
        risultato = await hass.config_entries.options.async_init(voce.entry_id)
        await hass.config_entries.options.async_configure(
            risultato["flow_id"],
            {
                CONF_CALENDARI_PER_FRAZIONE: False,
                CONF_SENSORI_PER_FRAZIONE: False,
                CONF_GIORNI_DA_MOSTRARE: 365,
            },
        )
        await hass.async_block_till_done()

    assert set(rimossi) == attesi, "la pulizia ha allargato il tiro"
    assert _sensori_frazione(hass, voce) == []


async def test_la_pulizia_resta_dentro_la_propria_piattaforma(
    hass: HomeAssistant, aioclient_mock, voce: MockConfigEntry, freezer
) -> None:
    """Il prefisso da solo non basta: i due domini possono sceglierlo uguale.

    Oggi sensori e calendari usano prefissi diversi, quindi il controllo sul
    dominio non ha occasione di servire. E' proprio per questo che va provato
    qui: il giorno in cui una piattaforma nuova scegliesse lo stesso prefisso,
    senza quel controllo si porterebbe via le entita' dell'altra e nessun test
    se ne accorgerebbe.
    """
    registra(aioclient_mock)
    freezer.move_to(SERA_DI_RACCOLTA)
    voce.add_to_hass(hass)

    # Un'entita' di un ALTRO dominio che condivide il prefisso dei sensori.
    registro = er.async_get(hass)
    intruso = registro.async_get_or_create(
        "calendar",
        DOMAIN,
        f"{voce.entry_id}_frazione_finta",
        config_entry=voce,
        suggested_object_id="intruso",
    )

    # I sensori per frazione sono spenti: la pulizia gira.
    await hass.config.async_set_time_zone("Europe/Rome")
    assert await hass.config_entries.async_setup(voce.entry_id)
    await hass.async_block_till_done()

    assert registro.async_get(intruso.entity_id) is not None, (
        "la pulizia dei sensori si e' portata via un calendario"
    )


# --- il calendario che si legge a occhio -------------------------------------


async def _lingua(hass: HomeAssistant, codice: str) -> None:
    """Imposta la lingua di Home Assistant, che decide i nomi dei giorni."""
    await hass.config.async_update(language=codice)


async def test_il_calendario_della_settimana_si_legge(
    hass: HomeAssistant, gestore, voce: MockConfigEntry, freezer
) -> None:
    """Un dizionario piatto giorno -> frazioni, che e' la forma che si legge.

    E' la risposta alla lamentela vera: aprendo l'entita' si vedeva "4" e un
    blocco di YAML. Home Assistant rende un attributo che contiene dizionari
    come un blocco YAML e una lista di stringhe come una riga sola di virgole:
    il dizionario piatto e' l'unica forma che venga fuori a righe.
    """
    await _lingua(hass, "it")
    freezer.move_to(SERA_DI_RACCOLTA)
    await _avvia(hass, voce)

    settimana = _settimana(hass, voce)
    calendario = settimana.attributes["calendario"]

    assert calendario == {
        "gio 03/09": "Organico",
        "dom 06/09": "Organico",
        "mar 08/09": "Indifferenziato, Organico",
        "mer 09/09": "Carta",
    }
    # L'ordine e' quello del calendario, non quello di un dizionario qualunque:
    # chi lo legge lo legge dall'alto.
    assert list(calendario) == [
        "gio 03/09",
        "dom 06/09",
        "mar 08/09",
        "mer 09/09",
    ]


async def test_il_calendario_non_puo_dissentire_dall_elenco(
    hass: HomeAssistant, gestore, voce: MockConfigEntry, freezer
) -> None:
    """Due forme della stessa settimana: devono raccontare la stessa cosa.

    `calendario` e' per gli occhi, `giorni` per i template. Se divergessero,
    l'utente leggerebbe una settimana e la sua automazione ne userebbe un'altra.
    """
    await _lingua(hass, "it")
    freezer.move_to(SERA_DI_RACCOLTA)
    await _avvia(hass, voce)

    settimana = _settimana(hass, voce)
    calendario = settimana.attributes["calendario"]
    giorni = settimana.attributes["giorni"]

    assert len(calendario) == len(giorni)
    for etichetta, frazioni in zip(calendario, giorni, strict=True):
        assert calendario[etichetta] == ", ".join(frazioni["frazioni"])
        # E l'etichetta contiene davvero il giorno di quella sera.
        assert etichetta.endswith(
            datetime.fromisoformat(frazioni["data"]).strftime("%d/%m")
        )


@pytest.mark.parametrize(
    "caso",
    [
        # italiano; solo la parte prima del trattino sceglie la lingua;
        # inglese e la sua variante; e una lingua che non parliamo, che
        # ripiega sull'inglese come fa Home Assistant con ogni testo mancante.
        ("it", "gio 03/09"),
        ("it-IT", "gio 03/09"),
        ("en", "Thu 03/09"),
        ("en-GB", "Thu 03/09"),
        ("de", "Thu 03/09"),
    ],
)
async def test_i_nomi_dei_giorni_seguono_la_lingua_di_home_assistant(
    hass: HomeAssistant, gestore, voce: MockConfigEntry, freezer, caso: tuple[str, str]
) -> None:
    """Il nome del giorno lo decide chi guarda, non chi ha scritto il codice."""
    lingua, atteso = caso
    await _lingua(hass, lingua)
    freezer.move_to(SERA_DI_RACCOLTA)
    await _avvia(hass, voce)

    calendario = _settimana(hass, voce).attributes["calendario"]
    assert next(iter(calendario)) == atteso, lingua


async def test_il_calendario_di_una_settimana_vuota_e_vuoto(
    hass: HomeAssistant, aioclient_mock, voce: MockConfigEntry, freezer
) -> None:
    """Nessuna raccolta: un dizionario vuoto, non una riga che finge."""
    registra(aioclient_mock, calendario="calendario_vuoto", allegati="allegati_vuoti")
    await _lingua(hass, "it")
    freezer.move_to(SERA_DI_RACCOLTA)
    await _avvia(hass, voce)

    settimana = _settimana(hass, voce)
    assert settimana.attributes["calendario"] == {}
    assert settimana.state == STATE_OFF, "e nessun evento in corso"


async def test_il_calendario_scorre_con_la_mezzanotte(
    hass: HomeAssistant, gestore, voce: MockConfigEntry, freezer
) -> None:
    """Passata la mezzanotte la sera di ieri esce e in fondo ne entra un'altra."""
    await _lingua(hass, "it")
    freezer.move_to(datetime(2026, 9, 3, 23, 0, tzinfo=ROMA))
    await _avvia(hass, voce)
    assert "gio 03/09" in _settimana(hass, voce).attributes["calendario"]

    dopo = datetime(2026, 9, 4, 0, 30, tzinfo=ROMA)
    freezer.move_to(dopo)
    async_fire_time_changed(hass, dopo)
    await hass.async_block_till_done()

    calendario = _settimana(hass, voce).attributes["calendario"]
    assert list(calendario) == [
        "dom 06/09",
        "mar 08/09",
        "mer 09/09",
        "gio 10/09",
    ], "il 3 e' uscito, il 10 e' entrato"


async def test_il_calendario_mostra_solo_le_frazioni_ancora_aperte(
    hass: HomeAssistant, aioclient_mock, voce: MockConfigEntry, freezer
) -> None:
    """Se una frazione e' scaduta non deve comparire nemmeno nel calendario.

    A Gradara l'8 settembre l'Indifferenziato chiude alle 23:00 e l'Organico
    alle 06:00: dopo le 23:00 la riga deve dire una cosa sola.
    """
    registra(
        aioclient_mock, calendario="calendario_gradara", allegati="allegati_gradara"
    )
    await _lingua(hass, "it")
    freezer.move_to(datetime(2026, 9, 8, 22, 0, tzinfo=ROMA))
    await _avvia(hass, voce)
    assert (
        _settimana(hass, voce).attributes["calendario"]["mar 08/09"]
        == "Indifferenziato, Organico"
    )

    dopo = datetime(2026, 9, 8, 23, 30, tzinfo=ROMA)
    freezer.move_to(dopo)
    async_fire_time_changed(hass, dopo)
    await hass.async_block_till_done()

    calendario = _settimana(hass, voce).attributes["calendario"]
    assert calendario["mar 08/09"] == "Organico"


async def test_il_colore_ufficiale_arriva_fino_al_registro(
    hass: HomeAssistant, aioclient_mock, voce: MockConfigEntry, freezer
) -> None:
    """Il colore non serve a niente se non esce dall'integrazione.

    E' il canale che colora le righe della card `calendar`: `_attr_initial_color`
    viene letto UNA volta alla creazione dell'entita', validato da Home Assistant
    con `cv.color_hex` e scritto nelle opzioni del registro. Se la validazione lo
    respinge - come faceva con un esadecimale a tre cifre - il colore sparisce
    senza un errore, e finora nessun test guardava qui.
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
    chiavi = coordinator_chiavi(hass, voce)
    attesi = {
        "Organico": "#701100",
        "Indifferenziato": "#7C7C81",
        "Carta": "#0093D0",
        "Imballaggi in vetro": "#15A53F",
    }
    for frazione, colore in attesi.items():
        entity_id = registro.async_get_entity_id(
            "calendar", DOMAIN, f"{voce.entry_id}_calendario_{chiavi[frazione]}"
        )
        assert entity_id is not None, frazione
        opzioni = registro.async_get(entity_id).options
        assert opzioni == {"calendar": {"color": colore}}, (
            f"{frazione}: il colore non e' arrivato al registro ({opzioni})"
        )


# --- la migrazione: le entita' ritirate ---------------------------------------


async def test_le_entita_ritirate_spariscono_dal_registro(
    hass: HomeAssistant, gestore, voce: MockConfigEntry, freezer
) -> None:
    """Chi aggiorna non deve ritrovarsi quattro righe grigie per sempre.

    Home Assistant ripulisce il registro da solo soltanto quando si rimuove
    l'intera voce: un'entita' che l'integrazione smette di creare resta li', in
    stato "non disponibile", cioe' peggio del disordine che si voleva togliere.

    E si guarda che la pulizia NON prenda `prossima_esposizione`, che comincia
    con le stesse nove lettere di `prossima_raccolta`: con un confronto per
    prefisso - che e' come funziona la pulizia dei sensori per frazione - si
    porterebbe via una delle entita' che restano.
    """
    freezer.move_to(SERA_DI_RACCOLTA)
    voce.add_to_hass(hass)

    # Le quattro di prima, come le avrebbe lasciate una versione precedente.
    registro = er.async_get(hass)
    ritirate = {}
    for dominio, chiave in (
        ("binary_sensor", "finestra_aperta"),
        ("sensor", "prossima_raccolta"),
        ("sensor", "giorni_alla_prossima"),
        ("sensor", "settimana"),
    ):
        voce_registro = registro.async_get_or_create(
            dominio,
            DOMAIN,
            f"{voce.entry_id}_{chiave}",
            config_entry=voce,
            suggested_object_id=f"vecchia_{chiave}",
        )
        ritirate[chiave] = voce_registro.entity_id

    await hass.config.async_set_time_zone("Europe/Rome")
    assert await hass.config_entries.async_setup(voce.entry_id)
    await hass.async_block_till_done()

    for chiave, entity_id in ritirate.items():
        assert registro.async_get(entity_id) is None, f"{chiave} e' rimasta"

    # E le entita' di oggi ci sono tutte, compresa quella col nome che assomiglia.
    for dominio, chiave in (
        ("calendar", "calendario"),
        ("binary_sensor", "esporre_stasera"),
        ("sensor", "esposizione_stasera"),
        ("sensor", "prossima_esposizione"),
    ):
        assert (
            registro.async_get_entity_id(dominio, DOMAIN, f"{voce.entry_id}_{chiave}")
            is not None
        ), f"la pulizia si e' portata via {chiave}"


async def test_la_pulizia_delle_ritirate_e_idempotente(
    hass: HomeAssistant, gestore, voce: MockConfigEntry, freezer
) -> None:
    """Dal secondo avvio non c'e' piu' niente da togliere, e non deve rompersi."""
    freezer.move_to(SERA_DI_RACCOLTA)
    await _avvia(hass, voce)
    registro = er.async_get(hass)
    prima = {
        e.entity_id for e in er.async_entries_for_config_entry(registro, voce.entry_id)
    }

    await hass.config_entries.async_reload(voce.entry_id)
    await hass.async_block_till_done()

    dopo = {
        e.entity_id for e in er.async_entries_for_config_entry(registro, voce.entry_id)
    }
    assert dopo == prima
