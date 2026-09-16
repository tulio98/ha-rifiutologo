"""Gli istanti ESATTI dei confini, e le mappe che governano gli unique_id.

Nati da un banco mutazionale: si introduce un difetto per volta nel codice e si
guarda se la suite se ne accorge. Ogni test qui dentro uccide una mutazione che
prima passava indenne - per lo piu' della forma `>` al posto di `>=`, che e' il
modo in cui questo progetto ha gia' sbagliato due volte.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.rifiutologo.api import (
    Calendario,
    Conferimento,
    GiornoRaccolta,
    slug,
)
from custom_components.rifiutologo.calendar import costruisci_eventi
from custom_components.rifiutologo.orari import (
    apertura,
    chiusura,
    giorno_in_corso,
    istante,
    prossima_raccolta,
    prossimo_confine,
    scadenza,
    solo_aperti,
)
from homeassistant.core import HomeAssistant

ROMA = ZoneInfo("Europe/Rome")


@pytest.fixture(autouse=True)
async def _fuso_italiano(hass: HomeAssistant) -> None:
    """`istante` legge il fuso di Home Assistant: qui e' quello di casa."""
    await hass.config.async_set_time_zone("Europe/Rome")


def conf(  # noqa: PLR0913
    fr: str = "Carta",
    i: str | None = None,
    f: str | None = None,
    orario: str | None = None,
    *,
    note: str | None = None,
    mid: int | None = None,
    colore: str | None = None,
) -> Conferimento:
    """Un conferimento minimo, per costruire a mano le sere che servono."""
    return Conferimento(
        frazione=fr,
        macroprodotto_id=mid,
        colore=colore,
        ora_inizio=i,
        ora_fine=f,
        orario=orario,
        orario_raccolta=None,
        straordinario=False,
        note=note,
    )


# --- M01 / M12: l'ora che capita due volte ------------------------------------


def test_la_chiusura_prende_la_seconda_delle_due_ore_ambigue() -> None:
    """25 ottobre 2026: le 02:30 capitano due volte, la finestra usa la seconda."""
    giorno = GiornoRaccolta(
        giorno=date(2026, 10, 24), conferimenti=(conf(i="20:00", f="02:30"),)
    )
    fine = scadenza(giorno, giorno.conferimenti[0])
    assert fine.fold == 1
    assert fine.utcoffset() == timedelta(hours=1), "ha chiuso un'ora in anticipo"


def test_istante_apre_alla_prima_delle_due_ore_ambigue() -> None:
    """L'apertura usa la PRIMA: nel dubbio la finestra e' piu' larga."""
    assert istante(date(2026, 10, 25), 150).utcoffset() == timedelta(hours=2)


# --- M02: una sera senza conferimenti -----------------------------------------


def test_chiusura_di_una_sera_senza_conferimenti() -> None:
    """Non deve esplodere: senza frazioni la sera finisce a mezzanotte."""
    vuota = GiornoRaccolta(giorno=date(2026, 9, 10), conferimenti=())
    assert chiusura(vuota) == datetime(2026, 9, 11, 0, 0, tzinfo=ROMA)


# --- M04 / M05 / M06 / M07 / M08: gli istanti esatti ---------------------------


def _padova(giorno: date) -> GiornoRaccolta:
    return GiornoRaccolta(
        giorno=giorno,
        conferimenti=(conf(i="20:00", f="24:00", orario="dalle 20:00 alle 24:00"),),
    )


def test_alle_24_in_punto_non_si_espone_piu() -> None:
    """La finestra e' semiaperta: l'istante di chiusura e' gia' fuori."""
    giorno = _padova(date(2026, 9, 10))
    mezzanotte = datetime(2026, 9, 11, 0, 0, tzinfo=ROMA)
    assert solo_aperti(giorno, mezzanotte) is None


def test_giorno_in_corso_lascia_la_sera_all_istante_esatto() -> None:
    """Alla mezzanotte in punto la sera precedente e' finita, non ancora in corso."""
    giorno = _padova(date(2026, 9, 10))
    dopo = _padova(date(2026, 9, 12))
    cal = Calendario(nota="", giorni=(giorno, dopo), allegati=())
    mezzanotte = datetime(2026, 9, 11, 0, 0, tzinfo=ROMA)
    assert giorno_in_corso(cal, mezzanotte) is dopo


def test_prossima_raccolta_scarta_la_sera_che_chiude_adesso() -> None:
    """Modena chiude alle 07:00 dello stesso giorno: alle 07:00 in punto e' finita."""
    modena = GiornoRaccolta(
        giorno=date(2026, 9, 12),
        conferimenti=(conf(i="00:00", f="07:00", orario="dalle 00:00 alle 07:00"),),
    )
    dopo = GiornoRaccolta(
        giorno=date(2026, 9, 15),
        conferimenti=(conf(i="00:00", f="07:00", orario="dalle 00:00 alle 07:00"),),
    )
    cal = Calendario(nota="", giorni=(modena, dopo), allegati=())
    alle7 = datetime(2026, 9, 12, 7, 0, tzinfo=ROMA)
    assert prossima_raccolta(cal, alle7) is dopo


def test_il_confine_non_e_mai_l_istante_in_cui_lo_si_chiede() -> None:
    """Alle 23:00 in punto la scadenza appena passata non e' piu' un confine."""
    grad = GiornoRaccolta(
        giorno=date(2026, 9, 12),
        conferimenti=(
            conf("Indifferenziato", "20:00", "23:00", "dalle 20:00 alle 23:00"),
            conf("Organico", "20:00", "06:00", "dalle 20:00 alle 06:00"),
        ),
    )
    cal = Calendario(nota="", giorni=(grad,), allegati=())
    alle23 = datetime(2026, 9, 12, 23, 0, tzinfo=ROMA)
    confine = prossimo_confine(cal, alle23)
    assert confine > alle23
    assert confine == datetime(2026, 9, 13, 0, 0, tzinfo=ROMA)


def test_all_apertura_esatta_il_confine_va_avanti() -> None:
    """Alle 20:00 in punto l'apertura e' avvenuta: non e' piu' un confine futuro."""
    cal = Calendario(nota="", giorni=(_padova(date(2026, 9, 10)),), allegati=())
    alle20 = datetime(2026, 9, 10, 20, 0, tzinfo=ROMA)
    assert prossimo_confine(cal, alle20) > alle20


# --- M14 / M15 / M16: lo slug --------------------------------------------------


@pytest.mark.parametrize(
    ("nome", "atteso"),
    [
        ("Carta", "carta"),
        ("CARTA E CARTONE", "carta_e_cartone"),
        ("Verde (sfalci)", "verde_sfalci"),
        ("* * *", "frazione"),
    ],
)
def test_slug(nome: str, atteso: str) -> None:
    """Minuscolo, senza underscore ai bordi, e mai vuoto."""
    assert slug(nome) == atteso


def test_la_chiave_di_ripiego_e_lo_slug() -> None:
    """Senza id del macroprodotto la chiave e' lo slug del nome."""
    assert conf("Carta e Cartone").chiave == "carta_e_cartone"


# --- M19: la finestra vera vale anche senza il testo "dalle" -------------------


@pytest.mark.parametrize("testo", [None, "20:00 - 24:00", "Esposizione serale"])
def test_una_finestra_vera_apre_anche_senza_la_parola_dalle(testo: str | None) -> None:
    """Il testo serve SOLO quando inizio e fine coincidono."""
    giorno = GiornoRaccolta(
        giorno=date(2026, 9, 10),
        conferimenti=(conf(i="20:00", f="24:00", orario=testo),),
    )
    assert giorno.apertura_minuti == 1200
    assert apertura(giorno) == datetime(2026, 9, 10, 20, 0, tzinfo=ROMA)


# --- M22 / M23 / M24: le mappe per frazione ------------------------------------


def test_la_nota_che_vince_e_la_prima() -> None:
    """Con due conferimenti della stessa frazione vince la prima nota."""
    giorno = GiornoRaccolta(
        giorno=date(2026, 9, 10),
        conferimenti=(conf(note="prima"), conf(note="seconda")),
    )
    assert giorno.note_per_frazione == {"Carta": "prima"}


def test_la_chiave_di_una_frazione_non_cambia_a_meta_calendario() -> None:
    """Un giorno il gestore dichiara l'id, un altro no: vince l'id, che e' stabile."""
    cal = Calendario(
        nota="",
        giorni=(
            GiornoRaccolta(giorno=date(2026, 9, 10), conferimenti=(conf(mid=7),)),
            GiornoRaccolta(giorno=date(2026, 9, 11), conferimenti=(conf(mid=None),)),
        ),
        allegati=(),
    )
    assert cal.chiavi_frazione == {"Carta": "7"}


def test_il_colore_e_il_primo_non_nullo() -> None:
    """La prima comparsa puo' non avere il pittogramma: si cerca avanti."""
    cal = Calendario(
        nota="",
        giorni=(
            GiornoRaccolta(giorno=date(2026, 9, 10), conferimenti=(conf(colore=None),)),
            GiornoRaccolta(
                giorno=date(2026, 9, 11), conferimenti=(conf(colore="#FF0000"),)
            ),
        ),
        allegati=(),
    )
    assert cal.frazioni == {"Carta": "#FF0000"}


# --- M47: l'ordine degli eventi a parita' di inizio ----------------------------


def test_gli_eventi_dello_stesso_giorno_sono_in_ordine_alfabetico() -> None:
    """Senza il summary nella chiave l'ordine sarebbe quello, mutevole, dell'API."""
    cal = Calendario(
        nota="",
        giorni=(
            GiornoRaccolta(
                giorno=date(2026, 9, 10),
                conferimenti=(conf("Vetro", mid=1), conf("Carta", mid=2)),
            ),
        ),
        allegati=(),
    )
    eventi = costruisci_eventi(cal, indirizzo="x", prefisso_uid="e")
    assert [e.summary for e in eventi] == ["Carta", "Vetro"]
