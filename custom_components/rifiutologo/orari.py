"""La finestra di esposizione, e il confine fra una sera e la successiva.

Sta in un modulo a se' perche' e' la nozione da cui dipendono tutti: il
calendario per costruire gli eventi, i sensori per dire che cosa tocca stasera,
il coordinator per sapere quando risvegliare le entita'. Definirla due volte
vorrebbe dire vederle dissentire.

Il fatto da cui discende tutto: la data che il gestore pubblica e' la sera in
cui si ESPONE, e la finestra puo' scavalcare la mezzanotte. A Bologna si espone
"dalle 20:00 alle 06:00": fino alle sei del mattino dopo il sacco va ancora
messo fuori, e finche' quella finestra e' aperta la sera non e' finita.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from homeassistant.util import dt as dt_util

from .api import Calendario, GiornoRaccolta


def istante(giorno: date, minuti: int) -> datetime:
    """L'istante locale a `minuti` dalla mezzanotte di `giorno`.

    Si passa per l'ora di parete invece di sommare un timedelta perche' nei due
    giorni del cambio d'ora una somma sposterebbe l'orario di un'ora. E i minuti
    oltre 1440 finiscono nei giorni successivi: e' cosi' che si rappresentano
    sia il "24:00" di Padova sia la chiusura alle 06:00 del mattino dopo di
    Bologna.
    """
    giorni_avanti, resto = divmod(minuti, 24 * 60)
    ore, minuti_residui = divmod(resto, 60)
    return datetime.combine(
        giorno + timedelta(days=giorni_avanti),
        time(hour=ore, minute=minuti_residui),
        tzinfo=dt_util.get_default_time_zone(),
    )


def apertura(giorno: GiornoRaccolta) -> datetime:
    """Quando si apre l'esposizione di quella sera.

    Se il gestore non dichiara un orario si ripiega sulla mezzanotte del giorno,
    che e' il modo onesto di dire "quel giorno" senza inventare un'ora.
    """
    minuti = giorno.apertura_minuti
    return istante(giorno.giorno, minuti if minuti is not None else 0)


def chiusura(giorno: GiornoRaccolta) -> datetime:
    """Quando quella sera finisce davvero.

    E' la fine dell'ultima finestra dichiarata, che puo' cadere il giorno dopo.
    Senza finestre dichiarate e' la mezzanotte.
    """
    return istante(giorno.giorno, giorno.chiusura_minuti)


def giorno_in_corso(
    calendario: Calendario | None, adesso: datetime
) -> GiornoRaccolta | None:
    """La raccolta di cui ci si deve ancora occupare.

    E' la prima la cui finestra non e' ancora chiusa: quella di stasera finche'
    c'e' tempo per esporre, e subito dopo la successiva. Un solo concetto, da
    cui discendono sia "che cosa espongo stasera" sia "quando tocca di nuovo".
    """
    if calendario is None:
        return None
    for giorno in calendario.giorni:
        if chiusura(giorno) > adesso:
            return giorno
    return None


def prossimo_confine(calendario: Calendario | None, adesso: datetime) -> datetime:
    """Il primo momento in cui le entita' vanno ricalcolate.

    Due cose spostano il significato di "stasera" senza che arrivi un dato
    nuovo: la mezzanotte, che cambia la data di oggi, e la chiusura della
    finestra in corso, che passa il testimone alla raccolta successiva. Si
    prende la piu' vicina delle due.
    """
    confini = [dt_util.start_of_local_day(adesso) + timedelta(days=1)]
    if (giorno := giorno_in_corso(calendario, adesso)) is not None:
        confini.append(chiusura(giorno))
    return min(confini)
