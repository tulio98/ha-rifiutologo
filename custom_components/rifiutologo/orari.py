"""La finestra di esposizione, e il confine fra una sera e la successiva.

Sta in un modulo a se' perche' e' la nozione da cui dipendono tutti: il
calendario per costruire gli eventi, i sensori per dire che cosa tocca stasera,
il coordinator per sapere quando risvegliare le entita'. Definirla due volte
vorrebbe dire vederle dissentire.

Il fatto da cui discende tutto: la data che il gestore pubblica e' la sera in
cui si ESPONE, e la finestra puo' scavalcare la mezzanotte. A Bologna si espone
"dalle 20:00 alle 06:00": fino alle sei del mattino dopo il sacco va ancora
messo fuori, e finche' quella finestra e' aperta la sera non e' finita.

Da qui nascono DUE domande diverse, che vanno tenute separate o una delle due
finisce per rispondere il passato:

- `giorno_in_corso` - che cosa si puo' ancora esporre adesso. Puo' essere ieri.
- `prossima_raccolta` - qual e' la prossima raccolta. Non guarda mai indietro.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from homeassistant.util import dt as dt_util

from .api import Calendario, GiornoRaccolta


def istante(giorno: date, minuti: int) -> datetime:
    """L'istante locale a `minuti` dalla mezzanotte di `giorno`.

    I minuti oltre 1440 finiscono nei giorni successivi: e' cosi' che si
    rappresentano sia il "24:00" di Padova sia la chiusura alle 06:00 del
    mattino dopo di Bologna.

    Si costruisce l'ora di parete e non si somma un timedelta soltanto perche'
    e' piu' esplicito - non perche' la somma sbagli: su un datetime aware
    l'aritmetica e' gia' di parete, e nei giorni del cambio d'ora i due modi
    danno lo stesso risultato (verificato sul 25 ottobre 2026).
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

    Se nessun conferimento dichiara una finestra si ripiega sulla mezzanotte del
    giorno, che e' il modo onesto di dire "quel giorno" senza inventare un'ora.
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
    """Che cosa si puo' ancora esporre adesso.

    E' la prima raccolta la cui finestra non e' ancora chiusa. Dove la finestra
    scavalca la mezzanotte questa puo' essere la sera di IERI, ed e' giusto
    cosi': alle due di notte a Bologna il sacco va ancora messo fuori.

    Serve al binary sensor e al sensore di cosa esporre. Per la domanda "quando
    tocca la prossima volta" c'e' `prossima_raccolta`, che non guarda indietro.
    """
    if calendario is None:
        return None
    for giorno in calendario.giorni:
        if chiusura(giorno) > adesso:
            return giorno
    return None


def prossima_raccolta(
    calendario: Calendario | None, oggi: date
) -> GiornoRaccolta | None:
    """La prima raccolta da oggi compreso in avanti.

    Non torna mai una data passata, ed e' proprio per questo che esiste separata
    da `giorno_in_corso`: un sensore che si chiama "prossima raccolta" non puo'
    rispondere ieri, nemmeno nelle sei ore in cui la finestra di ieri e' ancora
    aperta.
    """
    if calendario is None:
        return None
    for giorno in calendario.giorni:
        if giorno.giorno >= oggi:
            return giorno
    return None


def prossimo_confine(calendario: Calendario | None, adesso: datetime) -> datetime:
    """Il primo momento in cui le entita' vanno ricalcolate.

    Tre cose spostano il significato delle entita' senza che arrivi un dato
    nuovo: la mezzanotte, che cambia la data di oggi e quindi la prossima
    raccolta; la chiusura della finestra in corso, che passa il testimone; e
    l'apertura della prossima, che accende cio' che si puo' esporre. Si prende
    la piu' vicina delle tre.
    """
    confini = [dt_util.start_of_local_day(adesso) + timedelta(days=1)]

    if (giorno := giorno_in_corso(calendario, adesso)) is not None:
        confini.append(chiusura(giorno))
        inizio = apertura(giorno)
        if inizio > adesso:
            confini.append(inizio)

    return min(confini)
