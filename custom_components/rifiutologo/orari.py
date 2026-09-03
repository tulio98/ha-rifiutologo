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

import dataclasses
from datetime import date, datetime, time, timedelta

from homeassistant.util import dt as dt_util

from .api import MINUTI_IN_UN_GIORNO, Calendario, GiornoRaccolta


def istante(giorno: date, minuti: int, *, fold: int = 0) -> datetime:
    """L'istante locale a `minuti` dalla mezzanotte di `giorno`.

    I minuti oltre 1440 finiscono nei giorni successivi: e' cosi' che si
    rappresentano sia il "24:00" di Padova sia la chiusura alle 06:00 del
    mattino dopo di Bologna.

    Si costruisce l'ora di parete e non si somma un timedelta soltanto perche'
    e' piu' esplicito - non perche' la somma sbagli: su un datetime aware
    l'aritmetica e' gia' di parete, e nei giorni del cambio d'ora i due modi
    danno lo stesso risultato (verificato sul 25 ottobre 2026).

    Nella notte in cui l'ora torna indietro un'ora di parete capita due volte.
    `fold` sceglie quale delle due: 0 la prima, 1 la seconda. Le chiusure usano
    la seconda, cosi' nel dubbio la finestra resta aperta piu' a lungo invece di
    chiudersi in anticipo. Oggi nessun comune censito chiude fra le 02:00 e le
    03:00, quindi e' una precauzione e non il rimedio a un caso vivo.
    """
    giorni_avanti, resto = divmod(minuti, 24 * 60)
    ore, minuti_residui = divmod(resto, 60)
    return datetime.combine(
        giorno + timedelta(days=giorni_avanti),
        time(hour=ore, minute=minuti_residui),
        tzinfo=dt_util.get_default_time_zone(),
    ).replace(fold=fold)


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
    return istante(giorno.giorno, giorno.chiusura_minuti, fold=1)


def solo_aperti(
    giorno: GiornoRaccolta | None, adesso: datetime
) -> GiornoRaccolta | None:
    """La stessa sera, con le sole frazioni ancora esponibili.

    Serve perche' la chiusura del GIORNO e' il massimo fra le frazioni, e in una
    sera con finestre diverse quella che chiude prima resterebbe elencata come
    "da esporre adesso" anche dopo essere scaduta: a Gradara l'Indifferenziato
    chiude alle 23:00 e l'Organico alle 06:00, e fra le due il sensore diceva di
    esporre entrambi contraddicendo il proprio attributo orari_esposizione.

    Ritorna None se non e' rimasto niente da esporre.
    """
    if giorno is None:
        return None
    aperti = tuple(
        c
        for c in giorno.conferimenti
        if istante(
            giorno.giorno,
            c.fine_minuti_effettiva
            if c.fine_minuti_effettiva is not None
            else MINUTI_IN_UN_GIORNO,
            fold=1,
        )
        > adesso
    )
    if not aperti:
        return None
    if len(aperti) == len(giorno.conferimenti):
        return giorno
    return dataclasses.replace(giorno, conferimenti=aperti)


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
    calendario: Calendario | None, adesso: datetime
) -> GiornoRaccolta | None:
    """La prossima raccolta di cui occuparsi. Non cade mai nel passato.

    Servono ENTRAMBE le condizioni, e ciascuna chiude un difetto diverso:

    - la finestra non ancora chiusa. Senza, nei comuni che chiudono prima di
      mezzanotte - Modena espone dalle 00:00 alle 07:00, Casalecchio dalle 18:00
      alle 20:00 - per gran parte della giornata questa direbbe "oggi, fra zero
      giorni" mentre il sensore dell'esposizione e' gia' spento da ore: due
      entita' dello stesso dispositivo che si contraddicono.
    - la data non passata. Senza, dove la finestra scavalca la mezzanotte
      risponderebbe ieri, e un sensore che si chiama "prossima raccolta" con
      device_class DATE non puo' pubblicare una data passata.
    """
    if calendario is None:
        return None
    oggi = adesso.date()
    for giorno in calendario.giorni:
        if giorno.giorno >= oggi and chiusura(giorno) > adesso:
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
