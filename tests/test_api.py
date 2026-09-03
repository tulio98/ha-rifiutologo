"""Test del client e del parsing delle risposte del gestore."""

from __future__ import annotations

from datetime import date

import pytest

from custom_components.rifiutologo.api import (
    BASE_URL,
    RifiutologoClient,
    RifiutologoConnectionError,
    RifiutologoNotFoundError,
    _colore,
    _data,
    _intero,
    _minuti,
    _testo,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .conftest import CIVICO_ID, COMUNE_ID, VIA_ID, carica, registra


@pytest.mark.parametrize(
    ("grezzo", "atteso"),
    [
        ("20:00", 1200),
        ("24:00", 1440),
        ("05:00", 300),
        ("0:00", 0),
        ("20.30", 1230),
        ("25:00", None),
        ("20:99", None),
        ("", None),
        (None, None),
        ("mezzanotte", None),
    ],
)
def test_minuti(grezzo: str | None, atteso: int | None) -> None:
    """L'orario del gestore diventa minuti, e "24:00" vale 1440."""
    assert _minuti(grezzo) == atteso


@pytest.mark.parametrize(
    ("grezzo", "atteso"),
    [
        ("701100", "#701100"),
        ("#0093d0", "#0093D0"),
        ("abc", "#ABC"),
        ("zzzzzz", None),
        ("70110", None),
        (None, None),
        (123, None),
    ],
)
def test_colore(grezzo: object, atteso: str | None) -> None:
    """Il colore del pittogramma viene normalizzato, o scartato."""
    assert _colore(grezzo) == atteso


def test_data_ignora_il_fuso() -> None:
    """La data si prende dai primi dieci caratteri, senza convertire il fuso.

    Il backend marca tutto come UTC ma intende una data locale: convertire
    sposterebbe i giorni indietro di uno.
    """
    assert _data("2026-09-03T00:00:00+00:00") == date(2026, 9, 3)
    assert _data("2026-01-01T00:00:00+00:00") == date(2026, 1, 1)
    assert _data("non una data") is None
    assert _data(None) is None


@pytest.mark.parametrize(
    ("grezzo", "atteso"),
    [(5, 5), ("5", 5), ("-3", -3), (True, None), ("cinque", None), (None, None)],
)
def test_intero(grezzo: object, atteso: int | None) -> None:
    """L'API manda gli interi ora come numero ora come stringa."""
    assert _intero(grezzo) == atteso


def test_testo() -> None:
    """Le stringhe vuote valgono quanto l'assenza."""
    assert _testo("  ciao  ") == "ciao"
    assert _testo("   ") is None
    assert _testo(None) is None


async def test_calendario_completo(hass: HomeAssistant, gestore) -> None:
    """Il calendario si legge tutto: giorni, frazioni, colori, orari, zona."""
    client = RifiutologoClient(async_get_clientsession(hass))
    calendario = await client.calendario(
        COMUNE_ID, VIA_ID, CIVICO_ID, da=date(2026, 9, 3), giorni=40
    )

    assert len(calendario.giorni) == 12
    assert calendario.giorni[0].giorno == date(2026, 9, 3)
    assert calendario.giorni == tuple(sorted(calendario.giorni, key=lambda g: g.giorno))

    assert calendario.frazioni["Organico"] == "#701100"
    assert calendario.frazioni["Imballaggi in vetro"] == "#15A53F"

    primo = calendario.giorni[0].conferimenti[0]
    assert primo.frazione == "Organico"
    assert primo.inizio_minuti == 1200
    assert primo.fine_minuti == 1440
    assert primo.orario == "dalle 20:00 alle 24:00"
    assert primo.orario_raccolta == "dalle 05:00 del giorno successivo"
    assert primo.straordinario is False

    assert calendario.zona == "Calendario Padova Q6 2026"
    assert calendario.allegati[0].url == (
        "https://webapp-ambiente.gruppohera.it/"
        "assets/uploads/pap/od/Q6_Padova_2026_dr_calendario.pdf"
    )


async def test_indirizzo_senza_porta_a_porta(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Un indirizzo senza PAP da' zero giorni, e non e' un errore."""
    registra(aioclient_mock, calendario="calendario_vuoto", allegati="allegati_vuoti")
    client = RifiutologoClient(async_get_clientsession(hass))
    calendario = await client.calendario(
        COMUNE_ID, VIA_ID, CIVICO_ID, da=date(2026, 9, 3), giorni=40
    )
    assert calendario.giorni == ()
    assert calendario.zona is None


async def test_comuni_e_ricerche(hass: HomeAssistant, gestore) -> None:
    """Comuni, vie e civici arrivano tipizzati."""
    client = RifiutologoClient(async_get_clientsession(hass))

    comuni = await client.comuni()
    padova = next(c for c in comuni if c.nome == "Padova")
    assert padova.id == COMUNE_ID
    assert padova.etichetta == "Padova (PD)"

    vie = await client.vie(COMUNE_ID)
    assert any(v.id == VIA_ID and v.nome == "VIA BERNARDO TREVISAN" for v in vie)

    civici = await client.civici(COMUNE_ID, VIA_ID)
    assert any(c.id == CIVICO_ID and c.numero == "8" for c in civici)
    # I civici sono stringhe, mai interi: esistono "1/A", "1/SNC", "2/2".
    assert all(isinstance(c.numero, str) for c in civici)


async def test_risposta_non_json(hass: HomeAssistant, aioclient_mock) -> None:
    """Se il backend risponde HTML, si alza un errore di connessione."""
    aioclient_mock.get(f"{BASE_URL}/getComuni.php", text="<html>manutenzione</html>")
    client = RifiutologoClient(async_get_clientsession(hass))
    with pytest.raises(RifiutologoConnectionError):
        await client.comuni()


async def test_elenco_vuoto(hass: HomeAssistant, aioclient_mock) -> None:
    """Un elenco di vie vuoto e' un "non trovato", non un successo silenzioso."""
    aioclient_mock.get(f"{BASE_URL}/getIndirizzi.php", json=[])
    client = RifiutologoClient(async_get_clientsession(hass))
    with pytest.raises(RifiutologoNotFoundError):
        await client.vie(COMUNE_ID)


async def test_voci_malformate_vengono_saltate(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Una voce senza id o senza nome si salta, non fa cadere tutto."""
    aioclient_mock.get(
        f"{BASE_URL}/getComuni.php",
        json=[
            {"id": 1, "name": "Buono", "provincia": "PD"},
            {"id": None, "name": "Senza id"},
            {"id": 2},
            "nemmeno un oggetto",
            {"id": 3, "name": "Anche questo", "provincia": ""},
        ],
    )
    client = RifiutologoClient(async_get_clientsession(hass))
    comuni = await client.comuni()
    assert [c.nome for c in comuni] == ["Buono", "Anche questo"]
    assert comuni[1].etichetta == "Anche questo"


async def test_url_del_pdf_codificato(hass: HomeAssistant, aioclient_mock) -> None:
    """I nomi dei PDF hanno spazi e parentesi: senza codifica l'URL non e' valido.

    Quello di Bologna e' un caso vero: "PAP calendario BOLOGNA Famiglia e Azienda
    (Santo Stefano Collina).pdf".
    """
    registra(
        aioclient_mock, calendario="calendario_bologna", allegati="allegati_bologna"
    )
    client = RifiutologoClient(async_get_clientsession(hass))
    calendario = await client.calendario(
        COMUNE_ID, VIA_ID, CIVICO_ID, da=date(2026, 9, 3), giorni=30
    )

    url = calendario.allegati[0].url
    assert url is not None
    assert " " not in url
    assert "%20" in url
    assert "%28" in url and "%29" in url, "le parentesi vanno codificate"
    # La struttura dell'URL non deve essere stata rovinata dalla codifica.
    assert url.startswith("https://webapp-ambiente.gruppohera.it/assets/uploads/")
    assert url.endswith(".pdf")


async def test_gli_allegati_non_portano_giu_il_calendario(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Il calendario e' il dato principale: non cade per una chiamata accessoria."""
    aioclient_mock.get(f"{BASE_URL}/getCalendarioPap.php", json=carica("calendario"))
    aioclient_mock.get(f"{BASE_URL}/getAllegatiPap.php", status=500)

    client = RifiutologoClient(async_get_clientsession(hass))
    calendario = await client.calendario(
        COMUNE_ID, VIA_ID, CIVICO_ID, da=date(2026, 9, 3), giorni=30
    )

    assert len(calendario.giorni) == 12, "il calendario e' arrivato ed e' intero"
    assert calendario.allegati == ()
    assert calendario.zona is None


async def test_finestre_dei_tre_comuni(hass: HomeAssistant, aioclient_mock) -> None:
    """Il client legge i tre modi in cui il gestore dichiara un orario."""
    attesi = {
        "calendario": ("20:00", "24:00", 1440),
        "calendario_bologna": ("20:00", "06:00", 1800),
        "calendario_faenza": ("04:00", "04:00", None),
    }
    for nome, (inizio, fine, effettiva) in attesi.items():
        aioclient_mock.clear_requests()
        registra(aioclient_mock, calendario=nome, allegati="allegati_vuoti")
        client = RifiutologoClient(async_get_clientsession(hass))
        calendario = await client.calendario(
            COMUNE_ID, VIA_ID, CIVICO_ID, da=date(2026, 9, 3), giorni=30
        )
        conferimento = calendario.giorni[0].conferimenti[0]
        assert conferimento.ora_inizio == inizio, nome
        assert conferimento.ora_fine == fine, nome
        assert conferimento.fine_minuti_effettiva == effettiva, nome
