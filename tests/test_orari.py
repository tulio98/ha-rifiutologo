"""Test della finestra di esposizione: e' la nozione da cui dipendono tutti.

I dati sono quelli veri di tre comuni che il gestore tratta in tre modi diversi:
Padova dichiara una finestra regolare (20:00 -> 24:00), Bologna una che scavalca
la mezzanotte (20:00 -> 06:00), Faenza una scadenza (04:00 -> 04:00, "entro le
04:00"). Su una sola di queste tre l'implementazione ingenua funziona.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.rifiutologo import api
from custom_components.rifiutologo.calendar import costruisci_eventi
from custom_components.rifiutologo.orari import (
    apertura,
    chiusura,
    giorno_in_corso,
    istante,
    prossima_raccolta,
    prossimo_confine,
)
from homeassistant.core import HomeAssistant

from .conftest import carica

ROMA = ZoneInfo("Europe/Rome")


@pytest.fixture(autouse=True)
async def _fuso_italiano(hass: HomeAssistant) -> None:
    """`istante` legge il fuso di Home Assistant: qui e' quello di casa."""
    await hass.config.async_set_time_zone("Europe/Rome")


def _calendario(nome: str) -> api.Calendario:
    """Costruisce un Calendario da una fixture, senza passare dalla rete."""
    grezzo = carica(nome)
    giorni = []
    for voce in grezzo["calendario"]:
        giorno = api._data(voce["data"])
        conferimenti = tuple(
            c
            for c in (api._conferimento(v) for v in voce["conferimenti"])
            if c is not None
        )
        if conferimenti:
            giorni.append(api.GiornoRaccolta(giorno=giorno, conferimenti=conferimenti))
    return api.Calendario(nota="", giorni=tuple(giorni), allegati=())


@pytest.mark.parametrize(
    ("inizio", "fine", "atteso", "perche"),
    [
        ("20:00", "24:00", 1440, "Padova: finestra regolare, il 24:00 vale 1440"),
        ("20:00", "06:00", 1800, "Bologna: scavalca, le 06:00 del giorno dopo"),
        ("04:00", "04:00", None, "Faenza: inizio uguale a fine, non e' una durata"),
        ("20:00", "00:00", 1440, "Formigine: 00:00 e' la mezzanotte successiva"),
        ("07:00", "08:30", 510, "Ferrara: finestra breve dentro il giorno"),
        (None, "06:00", None, "senza inizio non c'e' finestra"),
        ("20:00", None, None, "senza fine non c'e' finestra"),
    ],
)
def test_fine_effettiva(
    inizio: str | None, fine: str | None, atteso: int | None, perche: str
) -> None:
    """La chiusura si normalizza una volta sola, e vale per tutti."""
    conferimento = api.Conferimento(
        frazione="x",
        macroprodotto_id=1,
        colore=None,
        ora_inizio=inizio,
        ora_fine=fine,
        orario=None,
        orario_raccolta=None,
        straordinario=False,
        note=None,
    )
    assert conferimento.fine_minuti_effettiva == atteso, perche


async def test_confini_padova() -> None:
    """A Padova la sera finisce a mezzanotte."""
    calendario = _calendario("calendario")
    giorno = calendario.giorni[0]
    assert giorno.giorno == date(2026, 9, 3)
    assert apertura(giorno) == datetime(2026, 9, 3, 20, 0, tzinfo=ROMA)
    assert chiusura(giorno) == datetime(2026, 9, 4, 0, 0, tzinfo=ROMA)


async def test_confini_bologna() -> None:
    """A Bologna la sera finisce alle 06:00 del mattino dopo."""
    calendario = _calendario("calendario_bologna")
    giorno = calendario.giorni[0]
    assert apertura(giorno).hour == 20
    fine = chiusura(giorno)
    assert fine.date() == giorno.giorno + timedelta(days=1)
    assert fine.hour == 6


async def test_confini_faenza() -> None:
    """A Faenza il gestore non dichiara una durata: il confine resta la mezzanotte."""
    calendario = _calendario("calendario_faenza")
    giorno = calendario.giorni[0]
    conferimento = giorno.conferimenti[0]
    assert conferimento.orario == "entro le 04:00"
    assert conferimento.fine_minuti_effettiva is None
    assert chiusura(giorno) == istante(giorno.giorno, 24 * 60)


async def test_giorno_in_corso_scavalca_la_mezzanotte() -> None:
    """A Bologna alle due di notte si e' ancora in tempo per la sera prima."""
    calendario = _calendario("calendario_bologna")
    primo = calendario.giorni[0]
    sera = primo.giorno

    prima = datetime.combine(sera, datetime.min.time(), tzinfo=ROMA)
    assert giorno_in_corso(calendario, prima.replace(hour=21)) is primo
    # Passata la mezzanotte, ma prima delle 06:00: e' ancora quella sera.
    assert giorno_in_corso(calendario, (prima + timedelta(days=1, hours=2))) is primo
    # Dopo le 06:00 il testimone passa alla raccolta successiva.
    dopo = giorno_in_corso(calendario, prima + timedelta(days=1, hours=7))
    assert dopo is not primo


async def test_giorno_in_corso_padova() -> None:
    """A Padova il testimone passa esattamente a mezzanotte."""
    calendario = _calendario("calendario")
    primo = calendario.giorni[0]
    mezzanotte = datetime(2026, 9, 4, 0, 0, tzinfo=ROMA)
    assert giorno_in_corso(calendario, mezzanotte - timedelta(minutes=1)) is primo
    assert giorno_in_corso(calendario, mezzanotte + timedelta(minutes=1)) is not primo


async def test_prossimo_confine() -> None:
    """Il risveglio si posa sul primo fra mezzanotte e la chiusura della finestra."""
    padova = _calendario("calendario")
    # A Padova i due confini coincidono.
    assert prossimo_confine(
        padova, datetime(2026, 9, 3, 21, 0, tzinfo=ROMA)
    ) == datetime(2026, 9, 4, 0, 0, tzinfo=ROMA)

    bologna = _calendario("calendario_bologna")
    sera = bologna.giorni[0].giorno
    adesso = datetime.combine(sera, datetime.min.time(), tzinfo=ROMA) + timedelta(
        hours=21
    )
    # A Bologna la mezzanotte arriva prima della chiusura: e' lei il confine.
    assert prossimo_confine(bologna, adesso) == datetime.combine(
        sera + timedelta(days=1), datetime.min.time(), tzinfo=ROMA
    )
    # Passata la mezzanotte, il confine successivo e' la chiusura alle 06:00.
    dopo = prossimo_confine(bologna, adesso + timedelta(hours=4))
    assert dopo.hour == 6


async def test_eventi_bologna_hanno_orario() -> None:
    """A Bologna gli eventi con orario devono esistere davvero, non degradare."""
    calendario = _calendario("calendario_bologna")
    eventi = costruisci_eventi(
        calendario, con_orario=True, indirizzo="x", prefisso_uid="p"
    )
    assert eventi, "nessun evento costruito"
    assert all(not e.all_day for e in eventi), "sono degradati a giornalieri"
    primo = eventi[0]
    assert primo.start.hour == 20
    assert primo.end.hour == 6
    assert primo.end.date() == primo.start.date() + timedelta(days=1)
    assert primo.end - primo.start == timedelta(hours=10)


async def test_eventi_faenza_restano_giornalieri() -> None:
    """A Faenza non c'e' una finestra da rappresentare: l'evento resta del giorno.

    Il testo del gestore ("entro le 04:00") finisce nella descrizione: e' meglio
    di una durata di 24 ore inventata.
    """
    calendario = _calendario("calendario_faenza")
    eventi = costruisci_eventi(
        calendario, con_orario=True, indirizzo="x", prefisso_uid="p"
    )
    assert eventi
    assert all(e.all_day for e in eventi)
    assert "entro le 04:00" in eventi[0].description


async def test_eventi_padova_invariati() -> None:
    """La correzione non deve cambiare il caso che gia' funzionava."""
    calendario = _calendario("calendario")
    eventi = costruisci_eventi(
        calendario, con_orario=True, indirizzo="x", prefisso_uid="p"
    )
    primo = eventi[0]
    assert not primo.all_day
    assert primo.start == datetime(2026, 9, 3, 20, 0, tzinfo=ROMA)
    assert primo.end == datetime(2026, 9, 4, 0, 0, tzinfo=ROMA)


@pytest.mark.parametrize(
    "giorno",
    [date(2026, 10, 24), date(2026, 10, 25), date(2027, 3, 27), date(2027, 3, 28)],
)
async def test_cambio_ora(giorno: date) -> None:
    """Nei giorni del cambio d'ora la finestra resta della durata giusta."""
    inizio = istante(giorno, 20 * 60)
    fine = istante(giorno, 30 * 60)  # le 06:00 del mattino dopo
    assert inizio.hour == 20, "l'ora di parete non deve slittare"
    assert fine.hour == 6
    assert fine.date() == giorno + timedelta(days=1)


async def test_apertura_prende_il_piu_presto() -> None:
    """Con piu' frazioni nella stessa sera vale la finestra che si apre prima."""

    def conferimento(frazione: str, inizio: str) -> api.Conferimento:
        return api.Conferimento(
            frazione=frazione,
            macroprodotto_id=None,
            colore=None,
            ora_inizio=inizio,
            ora_fine="24:00",
            orario=f"dalle {inizio}",
            orario_raccolta=None,
            straordinario=False,
            note=None,
        )

    giorno = api.GiornoRaccolta(
        giorno=date(2026, 9, 3),
        # Di proposito in ordine sparso: l'API non garantisce l'ordine.
        conferimenti=(
            conferimento("Carta", "21:00"),
            conferimento("Organico", "19:00"),
        ),
    )
    assert giorno.apertura_minuti == 19 * 60
    assert apertura(giorno) == datetime(2026, 9, 3, 19, 0, tzinfo=ROMA)


async def test_prossima_raccolta_non_guarda_mai_indietro() -> None:
    """Un sensore che si chiama "prossima" non puo' rispondere ieri.

    A Bologna il 6 e il 7 settembre sono due giorni di raccolta consecutivi, e
    la finestra del 6 chiude alle 06:00 del 7. Nelle sei ore in cui i due si
    sovrappongono le due domande hanno due risposte diverse, ed e' il motivo per
    cui esistono due funzioni.
    """
    calendario = _calendario("calendario_bologna")
    sei = next(g for g in calendario.giorni if g.giorno == date(2026, 9, 6))
    sette = next(g for g in calendario.giorni if g.giorno == date(2026, 9, 7))

    alle_due = datetime(2026, 9, 7, 2, 0, tzinfo=ROMA)
    # Cosa posso ancora esporre: la roba di ieri sera, la finestra e' aperta.
    assert giorno_in_corso(calendario, alle_due) is sei
    # Qual e' la prossima raccolta: quella di oggi, non quella di ieri.
    assert prossima_raccolta(calendario, alle_due.date()) is sette


async def test_apertura_non_scambia_una_scadenza_per_un_inizio() -> None:
    """Una scadenza non e' un'apertura: dirla tale manderebbe fuori tempo."""
    scadenza = api.Conferimento(
        frazione="Indifferenziato",
        macroprodotto_id=1,
        colore=None,
        ora_inizio="04:00",
        ora_fine="04:00",
        orario="entro le 04:00",
        orario_raccolta=None,
        straordinario=False,
        note=None,
    )
    finestra = api.Conferimento(
        frazione="Plastica",
        macroprodotto_id=2,
        colore=None,
        ora_inizio="20:00",
        ora_fine="22:00",
        orario="dalle 20:00 alle 22:00",
        orario_raccolta=None,
        straordinario=False,
        note=None,
    )

    giorno = api.GiornoRaccolta(
        giorno=date(2026, 9, 8), conferimenti=(scadenza, finestra)
    )
    # Le 04:00 della scadenza non devono vincere sul minimo.
    assert giorno.apertura_minuti == 20 * 60
    assert apertura(giorno) == datetime(2026, 9, 8, 20, 0, tzinfo=ROMA)

    # Con la sola scadenza non c'e' apertura: si ripiega sulla mezzanotte.
    solo_scadenza = api.GiornoRaccolta(
        giorno=date(2026, 9, 8), conferimenti=(scadenza,)
    )
    assert solo_scadenza.apertura_minuti is None
    assert apertura(solo_scadenza) == datetime(2026, 9, 8, 0, 0, tzinfo=ROMA)


async def test_una_frazione_in_piu_non_accorcia_la_sera() -> None:
    """Chi non dichiara una finestra vale fino a mezzanotte, non fino a zero."""
    scadenza = api.Conferimento(
        frazione="Organico",
        macroprodotto_id=1,
        colore=None,
        ora_inizio="06:00",
        ora_fine="06:00",
        orario="entro le 06:00",
        orario_raccolta=None,
        straordinario=False,
        note=None,
    )
    breve = api.Conferimento(
        frazione="Plastica",
        macroprodotto_id=2,
        colore=None,
        ora_inizio="20:00",
        ora_fine="22:00",
        orario="dalle 20:00 alle 22:00",
        orario_raccolta=None,
        straordinario=False,
        note=None,
    )

    sola = api.GiornoRaccolta(giorno=date(2026, 9, 8), conferimenti=(scadenza,))
    insieme = api.GiornoRaccolta(
        giorno=date(2026, 9, 8), conferimenti=(scadenza, breve)
    )
    assert sola.chiusura_minuti == 24 * 60
    assert insieme.chiusura_minuti == 24 * 60, (
        "aggiungere una frazione non puo' accorciare la sera"
    )


@pytest.mark.parametrize(
    ("inizio", "fine"),
    [("24:00", "00:00"), ("00:00", "24:00"), ("20:00", "20:00")],
)
def test_nessuna_finestra_di_durata_zero(inizio: str, fine: str) -> None:
    """La guardia sta sui minuti normalizzati: niente eventi di durata zero."""
    conferimento = api.Conferimento(
        frazione="x",
        macroprodotto_id=1,
        colore=None,
        ora_inizio=inizio,
        ora_fine=fine,
        orario=None,
        orario_raccolta=None,
        straordinario=False,
        note=None,
    )
    effettiva = conferimento.fine_minuti_effettiva
    if effettiva is not None:
        assert effettiva > conferimento.inizio_minuti


async def test_il_confine_tiene_conto_anche_dell_apertura() -> None:
    """Le entita' vanno ricalcolate anche quando la finestra si APRE."""
    calendario = _calendario("calendario")
    # Alle 18:00 il prossimo confine sono le 20:00, non la mezzanotte.
    assert prossimo_confine(
        calendario, datetime(2026, 9, 3, 18, 0, tzinfo=ROMA)
    ) == datetime(2026, 9, 3, 20, 0, tzinfo=ROMA)
