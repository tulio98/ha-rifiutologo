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

`agenda` e' la prima delle due allungata: non una sera ma tutte quelle di una
finestra di giorni, con lo stesso metro, cosi' il riepilogo della settimana non
puo' dire una cosa diversa dal sensore di stasera.
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime, time, timedelta

from homeassistant.util import dt as dt_util

from .api import MINUTI_IN_UN_GIORNO, Calendario, Conferimento, GiornoRaccolta


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


def scadenza(giorno: GiornoRaccolta, conferimento: Conferimento) -> datetime:
    """Quando QUELLA frazione smette di essere esponibile.

    E' il metro unico: lo usano `solo_aperti` per togliere dall'elenco cio' che
    e' scaduto, `chiusura` per sapere quando finisce la sera, e `prossimo_confine`
    per sapere quando risvegliare le entita'. Tenerlo in un posto solo e' l'unico
    modo perche' i tre non divergano - ed erano gia' divergiti una volta: la
    frazione scadeva alle 23:00 e il risveglio era programmato a mezzanotte,
    quindi per un'ora lo stato pubblicato diceva ancora di esporla.

    Senza finestra dichiarata la scadenza e' la mezzanotte. Non si prova a
    dedurla dal testo: "entro le 04:00" e' un termine che il gestore riferisce a
    un momento che non sappiamo collocare, e sbagliarlo vorrebbe dire dire a
    qualcuno di non esporre quando invece deve.
    """
    minuti = conferimento.fine_minuti_effettiva
    return istante(
        giorno.giorno,
        minuti if minuti is not None else MINUTI_IN_UN_GIORNO,
        fold=1,
    )


def apertura_conferimento(
    giorno: GiornoRaccolta, conferimento: Conferimento
) -> datetime:
    """Quando QUELLA frazione comincia a potersi esporre.

    E' la simmetrica di `scadenza`, e come quella sta in un posto solo perche'
    la usano in tre: il binary sensor della finestra, il sensore della singola
    frazione e `prossimo_confine` per sapere quando risvegliare le entita'.

    Senza un'apertura dichiarata e' la mezzanotte del giorno. Non si prova a
    dedurla: "entro le 04:00" e' un TERMINE, e prenderlo per un inizio direbbe
    a chi legge di cominciare alle quattro del mattino quando invece a
    quell'ora e' gia' tardi. Il discernimento fra le due forme lo fa
    `Conferimento.apertura_dichiarata`, sul testo del gestore.
    """
    minuti = conferimento.apertura_dichiarata
    return istante(giorno.giorno, minuti if minuti is not None else 0)


def in_finestra(
    giorno: GiornoRaccolta, conferimento: Conferimento, adesso: datetime
) -> bool:
    """Vero se quella frazione si puo' mettere fuori proprio adesso.

    Due condizioni, e sono diverse da quelle di `solo_aperti`: li' basta non
    essere scaduti, qui bisogna anche essere gia' cominciati.
    """
    return (
        apertura_conferimento(giorno, conferimento)
        <= adesso
        < scadenza(giorno, conferimento)
    )


def solo_in_finestra(
    giorno: GiornoRaccolta | None, adesso: datetime
) -> GiornoRaccolta | None:
    """La stessa sera, con le sole frazioni esponibili IN QUESTO MOMENTO.

    Fratello di `solo_aperti`, e la differenza e' tutta qui: `solo_aperti`
    toglie cio' che e' scaduto e risponde alla domanda "che cosa tocca oggi",
    questa toglie anche cio' che non e' ancora cominciato e risponde a "che
    cosa posso portare fuori adesso". Alle sei di sera del giorno della carta
    la prima dice "Carta" e la seconda dice niente, ed e' giusto cosi'.
    """
    if giorno is None:
        return None
    dentro = tuple(c for c in giorno.conferimenti if in_finestra(giorno, c, adesso))
    if not dentro:
        return None
    if len(dentro) == len(giorno.conferimenti):
        return giorno
    return dataclasses.replace(giorno, conferimenti=dentro)


def apertura(giorno: GiornoRaccolta) -> datetime:
    """Quando si apre l'esposizione di quella sera.

    Se nessun conferimento dichiara una finestra si ripiega sulla mezzanotte del
    giorno, che e' il modo onesto di dire "quel giorno" senza inventare un'ora.
    """
    minuti = giorno.apertura_minuti
    return istante(giorno.giorno, minuti if minuti is not None else 0)


def chiusura(giorno: GiornoRaccolta) -> datetime:
    """Quando quella sera finisce davvero.

    E' la piu' tarda fra le scadenze delle sue frazioni, che puo' cadere il
    giorno dopo. Senza finestre dichiarate e' la mezzanotte.
    """
    if not giorno.conferimenti:
        return istante(giorno.giorno, MINUTI_IN_UN_GIORNO, fold=1)
    return max(scadenza(giorno, c) for c in giorno.conferimenti)


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
    aperti = tuple(c for c in giorno.conferimenti if scadenza(giorno, c) > adesso)
    if not aperti:
        return None
    if len(aperti) == len(giorno.conferimenti):
        return giorno
    return dataclasses.replace(giorno, conferimenti=aperti)


def agenda(
    calendario: Calendario | None, adesso: datetime, giorni: int
) -> list[GiornoRaccolta]:
    """Le sere ancora da fare, da adesso fino alla fine di una finestra di `giorni`.

    E' l'elenco che risponde a "che cosa esco a mettere fuori questa settimana",
    e non inventa regole nuove: usa le stesse degli altri.

    - La finestra copre `giorni` date a partire da OGGI, l'ultima compresa.
    - Una sera gia' chiusa non c'e' piu', anche se e' quella di oggi.
    - Una sera ancora aperta c'e' anche se e' quella di IERI - dove la finestra
      scavalca la mezzanotte quel sacco va ancora messo fuori. E' l'unico motivo
      per cui la lista puo' cominciare prima di oggi.
    - Di ogni sera restano le sole frazioni non scadute, esattamente come nel
      sensore di stasera.

    Quando la lista non e' vuota il suo primo elemento e' `giorno_in_corso`, con
    le sole frazioni ancora aperte: il filtro e' lo stesso, perche' `solo_aperti`
    ritorna None esattamente quando `chiusura` e' gia' passata. Se il primo
    giorno non chiuso cade oltre la finestra, la lista e' vuota.
    """
    if calendario is None or giorni < 1:
        return []
    limite = adesso.date() + timedelta(days=giorni - 1)
    return [
        aperto
        for giorno in calendario.giorni
        if giorno.giorno <= limite
        and (aperto := solo_aperti(giorno, adesso)) is not None
    ]


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
      risponderebbe ieri, e un sensore per frazione con device_class DATE non
      puo' pubblicare una data passata.
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
    raccolta; l'apertura di OGNI SINGOLA frazione, che accende cio' che si puo'
    portare fuori - e che puo' cadere fra giorni, non stasera; e la scadenza di
    OGNI SINGOLA frazione, perche' in una sera con finestre diverse ognuna
    compare e sparisce per conto suo. Si prende la piu' vicina.

    Per frazione e non per giorno, da entrambi i lati. Le scadenze comprendono
    gia' la chiusura del giorno, che e' la piu' tarda fra loro; le aperture
    comprendono gia' `apertura`, che e' la piu' presto fra quelle dichiarate.

    Dal lato delle scadenze la differenza e' misurata su un caso vivo: a
    Gradara una frazione chiude alle 23:00 e l'altra alle 06:00, e fermarsi al
    giorno teneva la prima nell'elenco per un'ora dopo la scadenza. Dal lato
    delle aperture no: fra i cinque comuni censiti non esiste una sera con due
    aperture diverse, e finche' e' cosi' il minimo basterebbe. Costa una riga
    tenerle tutte, e il giorno in cui una comparisse nessuno starebbe a
    ricontrollare questo file.
    """
    confini = [dt_util.start_of_local_day(adesso) + timedelta(days=1)]

    if (giorno := giorno_in_corso(calendario, adesso)) is not None:
        for conferimento in giorno.conferimenti:
            for momento in (
                scadenza(giorno, conferimento),
                apertura_conferimento(giorno, conferimento),
            ):
                if momento > adesso:
                    confini.append(momento)

    return min(confini)
