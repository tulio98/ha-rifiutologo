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
    agenda,
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
    assert prossima_raccolta(calendario, alle_due) is sette


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


@pytest.mark.parametrize(
    ("orario", "atteso"),
    [
        ("dalle 20:00", 20 * 60),
        ("Dalle 20:00 in poi", 20 * 60),
        ("  dalle 20:00", 20 * 60),
        ("entro le 04:00", None),
        # Il controllo e' sul PREFISSO, non sulla presenza della parola: un
        # termine che nomina un'apertura resta un termine.
        ("entro le 04:00, dalle 20:00 del giorno prima", None),
        ("consegna dalle 20:00", None),
        ("", None),
        (None, None),
    ],
)
def test_dalle_e_unapertura_entro_e_un_termine(
    orario: str | None, atteso: int | None
) -> None:
    """Con inizio uguale a fine e' il TESTO del gestore a dire che cosa sia.

    Censiti sul backend: 1382 conferimenti "dalle HH:MM" (un'apertura) e 5836
    "entro le HH:MM" (un termine). Trattarli tutti come termini faceva dire al
    sensore mezzanotte invece delle 20:00.
    """
    ora = "20:00" if atteso is not None else "04:00"
    conferimento = api.Conferimento(
        frazione="x",
        macroprodotto_id=1,
        colore=None,
        ora_inizio=ora,
        ora_fine=ora,
        orario=orario,
        orario_raccolta=None,
        straordinario=False,
        note=None,
    )
    assert conferimento.apertura_dichiarata == atteso


def test_giorno_senza_conferimenti_non_solleva() -> None:
    """`GiornoRaccolta` e' pubblica: un giorno vuoto non deve far esplodere max()."""
    vuoto = api.GiornoRaccolta(giorno=date(2026, 9, 3), conferimenti=())
    assert vuoto.chiusura_minuti == 24 * 60
    assert vuoto.apertura_minuti is None


async def test_nessuna_fascia_morta_a_modena() -> None:
    """Dove la finestra chiude prima di mezzanotte le due nozioni non si contraddicono.

    Modena espone "dalle 00:00 alle 07:00": dalle 07:00 a mezzanotte la raccolta
    di oggi e' chiusa. Prima, `prossima_raccolta` ragionava per data e diceva
    "oggi, fra zero giorni" mentre il sensore dell'esposizione era gia' spento.
    """
    calendario = _calendario("calendario_modena")
    primo = calendario.giorni[0]
    assert primo.chiusura_minuti == 7 * 60, "la finestra chiude alle 07:00"

    prima = istante(primo.giorno, 3 * 60)  # le 03:00, finestra aperta
    assert giorno_in_corso(calendario, prima) is primo
    assert prossima_raccolta(calendario, prima) is primo

    dopo = istante(primo.giorno, 10 * 60)  # le 10:00, finestra chiusa
    in_corso = giorno_in_corso(calendario, dopo)
    prossima = prossima_raccolta(calendario, dopo)
    assert in_corso is not primo
    assert prossima is not primo, "non puo' dire 'oggi' con la finestra gia' chiusa"
    assert in_corso is prossima, "le due non si contraddicono"


async def test_solo_aperti_a_gradara() -> None:
    """In una sera con due finestre, quella scaduta non va piu' elencata.

    Gradara: Carta "dalle 20:00 alle 23:00", Organico "dalle 20:00 alle 06:00".
    """
    calendario = _calendario("calendario_gradara")
    # La sera che interessa e' quella con due finestre DIVERSE, non due frazioni:
    # i nomi cambiano di settimana in settimana, la forma no.
    sera = next(
        g
        for g in calendario.giorni
        if len({c.fine_minuti_effettiva for c in g.conferimenti}) > 1
    )
    breve = min(c.fine_minuti_effettiva for c in sera.conferimenti)
    lunga = max(c.fine_minuti_effettiva for c in sera.conferimenti)
    assert breve == 23 * 60, "una chiude alle 23:00"
    assert lunga == 30 * 60, "l'altra alle 06:00 del giorno dopo"
    superstite = next(
        c.frazione for c in sera.conferimenti if c.fine_minuti_effettiva == lunga
    )

    assert solo_aperti(sera, istante(sera.giorno, 22 * 60)) is sera, (
        "prima delle 23:00 ci sono entrambe"
    )

    rimaste = solo_aperti(sera, istante(sera.giorno, 24 * 60 + 30))
    assert rimaste is not None
    assert rimaste.frazioni == [superstite], "quella delle 23:00 e' scaduta"

    assert solo_aperti(sera, istante(sera.giorno, 31 * 60)) is None, (
        "dopo le 06:00 non c'e' piu' niente da esporre"
    )


async def test_il_confine_conosce_ogni_singola_scadenza() -> None:
    """Il risveglio deve cadere quando scade UNA frazione, non solo l'ultima.

    A Gradara l'Indifferenziato chiude alle 23:00 e l'Organico alle 06:00 del
    giorno dopo. Prima, il confine piu' vicino era la mezzanotte: per un'ora lo
    stato pubblicato continuava a dire di esporre una frazione gia' scaduta.
    """
    calendario = _calendario("calendario_gradara")
    sera = next(
        g
        for g in calendario.giorni
        if len({c.fine_minuti_effettiva for c in g.conferimenti}) > 1
    )
    alle_22 = istante(sera.giorno, 22 * 60)
    confine = prossimo_confine(calendario, alle_22)
    assert confine == istante(sera.giorno, 23 * 60, fold=1), (
        f"il confine e' {confine}, ma alle 23:00 scade una frazione"
    )
    # E il confine successivo e' la mezzanotte, che cambia la data di oggi.
    dopo = prossimo_confine(calendario, istante(sera.giorno, 23 * 60 + 1))
    assert dopo == istante(sera.giorno, 24 * 60)


async def test_scadenza_e_chiusura_usano_lo_stesso_metro() -> None:
    """La chiusura del giorno e' la piu' tarda fra le scadenze delle sue frazioni.

    Se le due si calcolassero in due posti diversi tornerebbero a divergere, ed
    e' esattamente cosi' che la frazione scaduta restava esposta.
    """
    for nome in ("calendario", "calendario_gradara", "calendario_faenza"):
        calendario = _calendario(nome)
        for giorno in calendario.giorni:
            attesa = max(scadenza(giorno, c) for c in giorno.conferimenti)
            assert chiusura(giorno) == attesa, nome


# --- l'agenda della settimana --------------------------------------------------

TUTTI_I_COMUNI = (
    "calendario",
    "calendario_bologna",
    "calendario_faenza",
    "calendario_modena",
    "calendario_gradara",
)


@pytest.mark.parametrize(
    ("nome", "quando", "atteso", "perche"),
    [
        (
            "calendario",
            datetime(2026, 9, 3, 18, 0, tzinfo=ROMA),
            ["2026-09-03", "2026-09-06", "2026-09-08", "2026-09-09"],
            "Padova: la finestra copre dal 3 al 9 compresi",
        ),
        (
            "calendario",
            datetime(2026, 9, 3, 23, 0, tzinfo=ROMA),
            ["2026-09-03", "2026-09-06", "2026-09-08", "2026-09-09"],
            "alle 23:00 la sera di oggi e' ancora aperta, l'elenco non cambia",
        ),
        (
            "calendario",
            datetime(2026, 9, 4, 0, 30, tzinfo=ROMA),
            ["2026-09-06", "2026-09-08", "2026-09-09", "2026-09-10"],
            "passata la mezzanotte il 3 e' chiuso e in fondo entra il 10",
        ),
        (
            "calendario_modena",
            datetime(2026, 9, 3, 12, 0, tzinfo=ROMA),
            ["2026-09-04", "2026-09-05", "2026-09-07", "2026-09-08", "2026-09-09"],
            "Modena espone dalle 00:00 alle 07:00: a mezzogiorno oggi e' gia' andato",
        ),
        (
            "calendario_bologna",
            datetime(2026, 9, 4, 2, 0, tzinfo=ROMA),
            [
                "2026-09-03",
                "2026-09-06",
                "2026-09-07",
                "2026-09-08",
                "2026-09-09",
                "2026-09-10",
            ],
            "Bologna chiude alle 06:00: alle due di notte la sera di IERI e' in cima",
        ),
        (
            "calendario_faenza",
            datetime(2026, 9, 3, 18, 0, tzinfo=ROMA),
            ["2026-09-03", "2026-09-05", "2026-09-07", "2026-09-08"],
            "Faenza dichiara un termine, non una finestra: vale fino a mezzanotte",
        ),
    ],
)
async def test_agenda_della_settimana(
    nome: str, quando: datetime, atteso: list[str], perche: str
) -> None:
    """Sette giorni, con le regole della finestra e non con quelle del calendario."""
    calendario = _calendario(nome)
    giorni = agenda(calendario, quando, 7)
    assert [g.giorno.isoformat() for g in giorni] == atteso, perche


async def test_agenda_tiene_solo_le_frazioni_ancora_aperte() -> None:
    """A Gradara, fra le 23:00 e le 06:00, della sera resta solo l'Organico.

    E' lo stesso taglio che fa il sensore di stasera: se l'agenda non lo
    facesse, il riepilogo della settimana direbbe di esporre una frazione che
    il sensore ha gia' tolto dall'elenco.
    """
    calendario = _calendario("calendario_gradara")
    giorni = agenda(calendario, datetime(2026, 9, 8, 23, 30, tzinfo=ROMA), 7)
    assert [g.giorno.isoformat() for g in giorni] == [
        "2026-09-08",
        "2026-09-09",
        "2026-09-10",
        "2026-09-11",
    ]
    assert giorni[0].frazioni == ["Organico"], "l'Indifferenziato e' scaduto alle 23:00"
    assert len(calendario.del_giorno(date(2026, 9, 8)).conferimenti) == 2, (
        "il calendario di partenza non e' stato toccato"
    )


@pytest.mark.parametrize("nome", TUTTI_I_COMUNI)
async def test_agenda_non_puo_contraddire_gli_altri(nome: str) -> None:
    """La prima voce dell'agenda e' `giorno_in_corso`, ora per ora, ovunque.

    E' l'invariante che tiene insieme le due entita': il riepilogo della
    settimana e il sensore di stasera guardano lo stesso elenco, e la prima
    sera dell'uno deve essere la sera dell'altro. Qui si controlla ogni ora di
    dieci giorni, su tutti e cinque i modi in cui i comuni scrivono l'orario.
    """
    calendario = _calendario(nome)
    inizio = datetime(2026, 9, 2, 0, 0, tzinfo=ROMA)
    for ora in range(10 * 24):
        adesso = inizio + timedelta(hours=ora)
        giorni = agenda(calendario, adesso, 7)
        in_corso = giorno_in_corso(calendario, adesso)

        if giorni:
            assert in_corso is not None, (
                f"{nome} {adesso}: agenda piena, niente in corso"
            )
            assert giorni[0].giorno == in_corso.giorno, f"{nome} {adesso}"
            assert giorni[0].frazioni == solo_aperti(in_corso, adesso).frazioni, (
                f"{nome} {adesso}: le frazioni della prima sera non coincidono"
            )
        else:
            # Vuota solo per un motivo: non c'e' niente di aperto dentro
            # la finestra. Mai perche' l'ha saltato.
            oltre = adesso.date() + timedelta(days=6)
            assert in_corso is None or in_corso.giorno > oltre, (
                f"{nome} {adesso}: agenda vuota ma c'e' una sera aperta in finestra"
            )

        # E la prossima raccolta, quando cade in finestra, e' la prima voce
        # dell'agenda che non sta nel passato.
        prossima = prossima_raccolta(calendario, adesso)
        da_oggi = [g for g in giorni if g.giorno >= adesso.date()]
        if da_oggi:
            assert prossima is not None and prossima.giorno == da_oggi[0].giorno, (
                f"{nome} {adesso}"
            )


@pytest.mark.parametrize("nome", TUTTI_I_COMUNI)
async def test_agenda_e_ordinata_e_senza_doppioni(nome: str) -> None:
    """Un elenco che salta indietro o ripete una data non si puo' disegnare."""
    calendario = _calendario(nome)
    giorni = agenda(calendario, datetime(2026, 9, 3, 12, 0, tzinfo=ROMA), 7)
    date_ = [g.giorno for g in giorni]
    assert date_ == sorted(date_)
    assert len(date_) == len(set(date_))


async def test_agenda_senza_dati_e_senza_finestra() -> None:
    """Senza calendario, o con una finestra vuota di giorni, la lista e' vuota."""
    calendario = _calendario("calendario")
    quando = datetime(2026, 9, 3, 18, 0, tzinfo=ROMA)
    assert agenda(None, quando, 7) == []
    assert agenda(calendario, quando, 0) == []
    assert agenda(calendario, quando, -1) == []
    assert agenda(api.Calendario(nota="", giorni=(), allegati=()), quando, 7) == []
    assert [g.giorno.isoformat() for g in agenda(calendario, quando, 1)] == [
        "2026-09-03"
    ], "un giorno solo e' oggi e basta"

    # Zero giorni non e' "oggi", e' nessun giorno - e va detto esplicitamente.
    # Senza il guardiano il limite cadrebbe IERI, e a Bologna alle due di notte
    # una finestra vuota pescherebbe la sera di ieri ancora aperta: l'unico
    # posto in cui la differenza si vede.
    bologna = _calendario("calendario_bologna")
    notte = datetime(2026, 9, 4, 2, 0, tzinfo=ROMA)
    assert [g.giorno.isoformat() for g in agenda(bologna, notte, 1)] == [
        "2026-09-03"
    ], "anche in una finestra di un giorno la sera di ieri aperta c'e'"
    assert agenda(bologna, notte, 0) == []


async def test_agenda_di_un_anno_arriva_in_fondo() -> None:
    """Con una finestra larga l'agenda e' tutto il calendario ancora da fare."""
    calendario = _calendario("calendario")
    quando = datetime(2026, 9, 3, 18, 0, tzinfo=ROMA)
    giorni = agenda(calendario, quando, 365)
    assert len(giorni) == len(calendario.giorni), "nessuna sera e' andata persa"
