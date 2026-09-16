"""Client asincrono per il backend del servizio Il Rifiutologo (Gruppo Hera).

Gli endpoint sono quelli che il sito https://www.ilrifiutologo.it dichiara in
chiaro nel proprio sorgente. Sono in sola lettura, in GET, senza autenticazione
e senza chiave. Nessuno di essi e' documentato ufficialmente: la forma delle
risposte qui sotto e' stata verificata sul campo e il parsing e' volutamente
tollerante, perche' puo' cambiare senza preavviso.

Un fatto che vale la pena ripetere perche' cambia il senso di tutto: la data che
il backend restituisce NON e' il giorno in cui passa il camion, e' la sera in cui
si espone. A Padova `orario` dice "dalle 20:00 alle 24:00" e `orarioRaccolta`
dice "dalle 05:00 del giorno successivo".
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, time
import json
import logging
import re
import socket
from typing import Any, Final
from urllib.parse import quote

import aiohttp

_LOGGER = logging.getLogger(__name__)

BASE_URL: Final = "https://webapp-ambiente.gruppohera.it/rifiutologo/rifiutologoweb"
"""Radice degli endpoint JSON."""

ALLEGATI_BASE_URL: Final = "https://webapp-ambiente.gruppohera.it/"
"""Radice da cui si scaricano i PDF: e' l'unica che serve il file vero.

Le altre tre plausibili (con /rifiutologo/, con /rifiutologoweb/, e il sito
ilrifiutologo.it) rispondono 200 con una pagina HTML, cioe' un 404 travestito.
"""

REQUEST_TIMEOUT: Final = 30
USER_AGENT: Final = "ha-rifiutologo (+https://github.com/tulio98/ha-rifiutologo)"

_ORA_RE: Final = re.compile(r"^\s*(\d{1,2})[:.](\d{2})\s*$")

ORA_MASSIMA: Final = 24
"""Il gestore scrive "24:00", che e' la mezzanotte del giorno dopo."""

MINUTO_MASSIMO: Final = 59
MINUTI_IN_UN_GIORNO: Final = 24 * 60

# Un esadecimale della forma "ABC", che vale "AABBCC" come nel CSS...
CIFRE_COLORE_CORTO: Final = 3
# ...e la forma lunga, l'unica che Home Assistant accetta: il suo
# validatore `cv.color_hex` vuole esattamente ^#[0-9A-F]{6}$.
CIFRE_COLORE: Final = 6
LUNGHEZZA_DATA_ISO: Final = 10


class RifiutologoError(Exception):
    """Errore generico del client."""


class RifiutologoConnectionError(RifiutologoError):
    """Il backend non risponde, o risponde qualcosa che non e' JSON."""


class RifiutologoNotFoundError(RifiutologoError):
    """Comune, via o civico non presenti nel database del gestore."""


@dataclass(frozen=True, slots=True)
class Comune:
    """Un comune servito dal Rifiutologo."""

    id: int
    nome: str
    provincia: str

    @property
    def etichetta(self) -> str:
        """Nome da mostrare a tendina."""
        return f"{self.nome} ({self.provincia})" if self.provincia else self.nome


@dataclass(frozen=True, slots=True)
class Via:
    """Una via di un comune. Il backend le scrive tutte in maiuscolo."""

    id: int
    nome: str


@dataclass(frozen=True, slots=True)
class Civico:
    """Un numero civico. E' una stringa: esistono "1/A", "1/SNC", "2/2"."""

    id: int
    numero: str


@dataclass(frozen=True, slots=True)
class Allegato:
    """Il calendario cartaceo in PDF, il cui nome contiene la zona di raccolta.

    A Padova il `nome` e' della forma "Calendario Padova Q6 2026": e' l'unico
    posto in cui l'API dichiara a quale zona appartiene un indirizzo.
    """

    id: int | None
    nome: str
    url: str | None


@dataclass(frozen=True, slots=True)
class Conferimento:
    """Una frazione da esporre in una certa sera."""

    frazione: str
    macroprodotto_id: int | None
    colore: str | None
    ora_inizio: str | None
    ora_fine: str | None
    orario: str | None
    orario_raccolta: str | None
    straordinario: bool
    note: str | None

    @property
    def apertura_dichiarata(self) -> int | None:
        """L'ora in cui si puo' COMINCIARE a esporre, se il gestore la dichiara.

        Con una finestra vera e' il suo inizio. Quando oraInizio e oraFine
        coincidono il numero da solo non basta a dire che cosa significhi, e a
        dirlo e' il testo del gestore: "dalle 20:00" e' un'apertura, "entro le
        04:00" e' un termine. Censiti sul backend il 3 settembre 2026: 1382
        conferimenti della prima forma, 5836 della seconda.

        Se il testo non dice ne' l'una ne' l'altra cosa si ammette di non
        sapere, invece di indovinare.
        """
        if self.inizio_minuti is None:
            return None
        if self.fine_minuti_effettiva is not None:
            return self.inizio_minuti
        testo = (self.orario or "").strip().casefold()
        return self.inizio_minuti if testo.startswith("dalle") else None

    @property
    def chiave(self) -> str:
        """Identificatore stabile della frazione, per costruire gli UID."""
        if self.macroprodotto_id is not None:
            return str(self.macroprodotto_id)
        return slug(self.frazione)

    @property
    def fine_minuti_effettiva(self) -> int | None:
        """Chiusura in minuti, oltre le 24 ore se la finestra scavalca la mezzanotte.

        Ritorna None quando il gestore NON dichiara una finestra, e cioe' quando
        oraInizio e oraFine coincidono. In quel caso e' il campo testuale
        `orario` a dire che cosa intende: a Faenza "entro le 04:00", che e' una
        scadenza, altrove "dalle 20:00", che e' un'apertura senza chiusura.
        Fabbricare una durata di 24 ore sarebbe peggio che non darne nessuna.

        Verificato sul backend il 3 settembre 2026: Padova 20:00->24:00 (finestra
        regolare), Bologna 20:00->06:00 (scavalca), Faenza 04:00->04:00 (scadenza).
        """
        inizio, fine = self.inizio_minuti, self.fine_minuti
        if inizio is None or fine is None:
            return None
        if fine < inizio:
            fine += MINUTI_IN_UN_GIORNO
        # Il confronto va fatto DOPO aver normalizzato: "24:00" -> "00:00" da'
        # 1440 e 0, che normalizzati coincidono. Senza questo si costruirebbe un
        # evento di calendario di durata zero.
        return fine if fine > inizio else None

    @property
    def inizio_minuti(self) -> int | None:
        """Minuti dalla mezzanotte dell'inizio esposizione, se dichiarato."""
        return _minuti(self.ora_inizio)

    @property
    def fine_minuti(self) -> int | None:
        """Minuti dalla mezzanotte della fine esposizione, se dichiarata.

        Puo' valere 1440: il backend scrive "24:00", che e' la mezzanotte del
        giorno dopo e non un orario valido per `datetime.time`.
        """
        return _minuti(self.ora_fine)


@dataclass(frozen=True, slots=True)
class GiornoRaccolta:
    """Una sera di esposizione, con tutte le frazioni previste."""

    giorno: date
    conferimenti: tuple[Conferimento, ...]

    @property
    def apertura_minuti(self) -> int | None:
        """Il piu' presto fra gli inizi di esposizione dichiarati, se ce n'e' uno.

        Si prende il minimo e non il primo della lista: l'ordine con cui il
        gestore elenca i conferimenti non e' garantito, e in una sera con piu'
        frazioni la finestra utile e' quella che si apre prima.

        Si contano solo le aperture DICHIARATE: dove inizio e fine coincidono e
        il gestore scrive "entro le 04:00" quell'ora e' un termine, e spacciarla
        per l'inizio direbbe a chi legge di cominciare quando invece e' tardi.
        Dove pero' scrive "dalle 20:00" e' un'apertura a tutti gli effetti, e va
        contata.
        """
        inizi = [
            c.apertura_dichiarata
            for c in self.conferimenti
            if c.apertura_dichiarata is not None
        ]
        return min(inizi) if inizi else None

    @property
    def chiusura_minuti(self) -> int:
        """Minuti dalla mezzanotte in cui l'ultima finestra della sera si chiude.

        Puo' superare i 1440 quando la finestra scavalca la mezzanotte.

        I conferimenti che non dichiarano una finestra contano come mezzanotte,
        non come zero: altrimenti una sera con "entro le 04:00" (nessuna
        finestra) piu' "dalle 20:00 alle 22:00" chiuderebbe alle 22:00, cioe'
        una frazione in piu' ACCORCEREBBE la sera invece di allungarla.
        """
        return (
            max(
                (
                    c.fine_minuti_effettiva
                    if c.fine_minuti_effettiva is not None
                    else MINUTI_IN_UN_GIORNO
                )
                for c in self.conferimenti
            )
            if self.conferimenti
            else MINUTI_IN_UN_GIORNO
        )

    @property
    def orari_per_frazione(self) -> dict[str, str]:
        """Orario di esposizione dichiarato, frazione per frazione.

        Le frazioni di una stessa sera non hanno per forza lo stesso orario:
        promuovere il primo conferimento a rappresentante del giorno sarebbe
        una semplificazione che ogni tanto mente.
        """
        return {c.frazione: c.orario for c in self.conferimenti if c.orario is not None}

    @property
    def note_per_frazione(self) -> dict[str, str]:
        """Nota del gestore, frazione per frazione.

        Anche questa non si puo' schiacciare: su un giorno con piu' frazioni
        capita spesso che la nota appartenga a una sola.

        La chiave e' il nome della frazione: nella rara sera in cui la stessa
        frazione compare due volte vince la PRIMA nota, come faceva l'attributo
        scalare prima che questa mappa esistesse.
        """
        note: dict[str, str] = {}
        for c in self.conferimenti:
            if c.note is not None:
                note.setdefault(c.frazione, c.note)
        return note

    @property
    def orari_raccolta_per_frazione(self) -> dict[str, str]:
        """Orario di raccolta dichiarato, frazione per frazione."""
        return {
            c.frazione: c.orario_raccolta
            for c in self.conferimenti
            if c.orario_raccolta is not None
        }

    @property
    def frazioni(self) -> list[str]:
        """Nomi delle frazioni, senza ripetizioni, nell'ordine dell'API."""
        visti: dict[str, None] = {}
        for c in self.conferimenti:
            visti.setdefault(c.frazione, None)
        return list(visti)


@dataclass(frozen=True, slots=True)
class Calendario:
    """Il calendario completo di un indirizzo."""

    nota: str
    giorni: tuple[GiornoRaccolta, ...]
    allegati: tuple[Allegato, ...]

    @property
    def zona(self) -> str | None:
        """Nome della zona di raccolta, se il gestore lo dichiara."""
        return self.allegati[0].nome if self.allegati else None

    @property
    def frazioni(self) -> dict[str, str | None]:
        """Frazioni presenti nel calendario, ciascuna col suo colore ufficiale.

        L'ordine e' quello di prima comparsa, cioe' quello del gestore. Il colore
        e' il primo non nullo incontrato: e' stabile fra comuni diversi, mentre
        gli id dei macroprodotti no.
        """
        trovate: dict[str, str | None] = {}
        for giorno in self.giorni:
            for conferimento in giorno.conferimenti:
                if trovate.get(conferimento.frazione) is None:
                    trovate[conferimento.frazione] = conferimento.colore
        return trovate

    @property
    def chiavi_frazione(self) -> dict[str, str]:
        """Chiave stabile per ogni frazione, con cui costruire gli unique_id.

        E' l'id del macroprodotto quando il gestore lo dichiara: non dipende
        dall'ordine in cui le frazioni compaiono nel calendario, che cambia da
        solo mentre la finestra dei giorni scorre, e sopravvive a un cambio di
        etichetta. Lo slug del nome resta come ripiego.
        """
        chiavi: dict[str, str] = {}
        for giorno in self.giorni:
            for conferimento in giorno.conferimenti:
                chiavi.setdefault(conferimento.frazione, conferimento.chiave)
        return chiavi

    def del_giorno(self, giorno: date) -> GiornoRaccolta | None:
        """La raccolta di un giorno preciso, se c'e'."""
        for g in self.giorni:
            if g.giorno == giorno:
                return g
        return None

    def prossimi(self, da: date) -> list[GiornoRaccolta]:
        """I giorni di raccolta da `da` compreso in poi, in ordine."""
        return [g for g in self.giorni if g.giorno >= da]


def slug(testo: str) -> str:
    """Riduce un nome a qualcosa di usabile dentro un unique_id.

    Sta qui e non in calendar.py perche' lo usano entrambi: la chiave di
    ripiego di un conferimento senza id e quella di un'entita' calendario.
    """
    return re.sub(r"[^a-z0-9]+", "_", testo.casefold()).strip("_") or "frazione"


def _minuti(valore: str | None) -> int | None:
    """Converte "20:00" in 1200. Ritorna None se il formato non e' quello."""
    if not valore:
        return None
    if (m := _ORA_RE.match(valore)) is None:
        return None
    ore, minuti = int(m.group(1)), int(m.group(2))
    if not 0 <= ore <= ORA_MASSIMA or not 0 <= minuti <= MINUTO_MASSIMO:
        return None
    totale = ore * 60 + minuti
    return totale if totale <= MINUTI_IN_UN_GIORNO else None


def _colore(grezzo: Any) -> str | None:
    """Normalizza "701100" in "#701100". Scarta tutto cio' che non e' un esadecimale.

    La forma corta di tre cifre viene RADDOPPIATA, "ABC" -> "AABBCC", che e' la
    stessa espansione del CSS e non un'invenzione. Serve perche' a valle il
    colore lo valida Home Assistant con `cv.color_hex`, il cui schema e'
    `^#[0-9A-F]{6}$` (helpers/config_validation.py): un "#ABC" non lo passa, e
    `CalendarEntity.get_initial_entity_options` in quel caso ritorna None senza
    dire niente - cioe' il colore ufficiale del gestore sparirebbe dal
    calendario in silenzio.

    Oggi Hera manda sempre sei cifre (verificato su tutte e cinque le fixture),
    quindi e' un difetto latente e non un caso vivo: costa una riga chiuderlo.
    """
    if not isinstance(grezzo, str):
        return None
    pulito = grezzo.strip().lstrip("#")
    if len(pulito) not in (CIFRE_COLORE_CORTO, CIFRE_COLORE) or not all(
        c in "0123456789abcdefABCDEF" for c in pulito
    ):
        return None
    if len(pulito) == CIFRE_COLORE_CORTO:
        pulito = "".join(c * 2 for c in pulito)
    return f"#{pulito.upper()}"


def _data(grezzo: Any) -> date | None:
    """Estrae la data da "2026-09-03T00:00:00+00:00".

    Si prendono i primi dieci caratteri di proposito: il backend marca tutto come
    UTC ma intende una data locale, e convertire il fuso sposterebbe i giorni.
    """
    if not isinstance(grezzo, str) or len(grezzo) < LUNGHEZZA_DATA_ISO:
        return None
    try:
        return date.fromisoformat(grezzo[:LUNGHEZZA_DATA_ISO])
    except ValueError:
        return None


def _intero(grezzo: Any) -> int | None:
    """Converte in intero un valore che l'API manda ora come numero ora come stringa."""
    if isinstance(grezzo, bool):
        return None
    if isinstance(grezzo, int):
        return grezzo
    if isinstance(grezzo, str) and grezzo.strip().lstrip("-").isdigit():
        return int(grezzo)
    return None


def _testo(grezzo: Any) -> str | None:
    """Ritorna una stringa non vuota, oppure None."""
    if not isinstance(grezzo, str):
        return None
    pulito = grezzo.strip()
    return pulito or None


class RifiutologoClient:
    """Accesso ai cinque endpoint del backend."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Inizializza il client sulla sessione condivisa di Home Assistant."""
        self._session = session

    async def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        """Esegue una GET e ritorna il JSON decodificato."""
        url = f"{BASE_URL}/{endpoint}"
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                risposta = await self._session.get(
                    url, params=params, headers={"User-Agent": USER_AGENT}
                )
                risposta.raise_for_status()
                # Il backend dichiara text/html anche quando risponde JSON, quindi
                # si legge il testo e si decodifica a mano invece di usare .json().
                testo = await risposta.text()
        except UnicodeDecodeError as err:
            # Un corpo mal codificato o troncato: e' un guasto della risposta,
            # non un errore di programmazione, e deve entrare nella gerarchia
            # degli errori del client come tutti gli altri.
            raise RifiutologoConnectionError(
                f"{endpoint} ha risposto un corpo non decodificabile: {err}"
            ) from err
        except TimeoutError as err:
            raise RifiutologoConnectionError(
                f"Il backend non ha risposto entro {REQUEST_TIMEOUT} s ({endpoint})"
            ) from err
        except (aiohttp.ClientError, socket.gaierror) as err:
            raise RifiutologoConnectionError(
                f"Errore di rete verso {endpoint}: {err}"
            ) from err

        try:
            return json.loads(testo)
        except ValueError as err:
            raise RifiutologoConnectionError(
                f"{endpoint} non ha risposto JSON "
                f"(primi 120 caratteri: {testo[:120]!r})"
            ) from err

    async def comuni(self) -> list[Comune]:
        """Tutti i comuni serviti."""
        grezzo = await self._get("getComuni.php")
        if not isinstance(grezzo, list):
            raise RifiutologoConnectionError("getComuni.php non ha risposto una lista")

        comuni: list[Comune] = []
        for voce in grezzo:
            if not isinstance(voce, dict):
                continue
            identificativo = _intero(voce.get("id"))
            nome = _testo(voce.get("name"))
            if identificativo is None or nome is None:
                continue
            comuni.append(
                Comune(
                    id=identificativo,
                    nome=nome,
                    provincia=_testo(voce.get("provincia")) or "",
                )
            )
        if not comuni:
            raise RifiutologoConnectionError(
                "getComuni.php ha risposto un elenco vuoto"
            )
        return comuni

    async def vie(self, comune_id: int) -> list[Via]:
        """Le vie di un comune. A Padova sono 2200."""
        grezzo = await self._get("getIndirizzi.php", {"idComune": comune_id})
        if not isinstance(grezzo, list):
            raise RifiutologoConnectionError(
                "getIndirizzi.php non ha risposto una lista"
            )

        vie: list[Via] = []
        for voce in grezzo:
            if not isinstance(voce, dict):
                continue
            identificativo = _intero(voce.get("id"))
            nome = _testo(voce.get("indirizzo"))
            if identificativo is None or nome is None:
                continue
            vie.append(Via(id=identificativo, nome=nome))
        if not vie:
            raise RifiutologoNotFoundError(f"Nessuna via per il comune {comune_id}")
        return vie

    async def civici(self, comune_id: int, via_id: int) -> list[Civico]:
        """I numeri civici di una via."""
        grezzo = await self._get(
            "getNumeriCivici.php", {"idComune": comune_id, "idIndirizzo": via_id}
        )
        if not isinstance(grezzo, list):
            raise RifiutologoConnectionError(
                "getNumeriCivici.php non ha risposto una lista"
            )

        civici: list[Civico] = []
        for voce in grezzo:
            if not isinstance(voce, dict):
                continue
            identificativo = _intero(voce.get("id"))
            numero = _testo(voce.get("numeroCivico"))
            if identificativo is None or numero is None:
                continue
            civici.append(Civico(id=identificativo, numero=numero))
        if not civici:
            raise RifiutologoNotFoundError(f"Nessun civico per la via {via_id}")
        return civici

    async def allegati(
        self, comune_id: int, via_id: int, civico_id: int
    ) -> list[Allegato]:
        """I PDF del calendario cartaceo. Lista vuota se l'indirizzo non ha il PAP."""
        grezzo = await self._get(
            "getAllegatiPap.php",
            {
                "idComune": comune_id,
                "idIndirizzo": via_id,
                "idCivico": civico_id,
                "isBusiness": 0,
            },
        )
        if not isinstance(grezzo, list):
            return []

        allegati: list[Allegato] = []
        for voce in grezzo:
            if not isinstance(voce, dict):
                continue
            nome = _testo(voce.get("nome"))
            if nome is None:
                continue
            percorso = _testo(voce.get("path"))
            allegati.append(
                Allegato(
                    id=_intero(voce.get("id")),
                    nome=nome,
                    # I nomi dei file contengono spazi e parentesi in molti
                    # comuni: senza codifica l'URL non e' valido.
                    url=f"{ALLEGATI_BASE_URL}{quote(percorso.lstrip('/'), safe='/')}"
                    if percorso
                    else None,
                )
            )
        return allegati

    async def calendario(
        self,
        comune_id: int,
        via_id: int,
        civico_id: int,
        *,
        da: date,
        giorni: int,
    ) -> Calendario:
        """Il calendario di un indirizzo a partire da `da`, per `giorni` giorni.

        Non solleva se non c'e' raccolta porta a porta: ritorna un calendario con
        zero giorni. Distinguere i due casi tocca a chi chiama.
        """
        grezzo = await self._get(
            "getCalendarioPap.php",
            {
                "idComune": comune_id,
                "idIndirizzo": via_id,
                "idCivico": civico_id,
                "isBusiness": 0,
                "idCategoriaAzienda": 0,
                "date": datetime.combine(da, time.min).strftime("%Y-%m-%dT%H:%M:%S"),
                "giorniDaMostrare": giorni,
            },
        )
        if not isinstance(grezzo, dict):
            raise RifiutologoConnectionError(
                "getCalendarioPap.php non ha risposto un oggetto"
            )

        giorni_raccolta: list[GiornoRaccolta] = []
        for voce in grezzo.get("calendario") or []:
            if not isinstance(voce, dict):
                continue
            giorno = _data(voce.get("data"))
            if giorno is None:
                continue
            conferimenti = tuple(
                c
                for c in (
                    _conferimento(v)
                    for v in voce.get("conferimenti") or []
                    if isinstance(v, dict)
                )
                if c is not None
            )
            if conferimenti:
                giorni_raccolta.append(
                    GiornoRaccolta(giorno=giorno, conferimenti=conferimenti)
                )

        giorni_raccolta.sort(key=lambda g: g.giorno)

        try:
            allegati = await self.allegati(comune_id, via_id, civico_id)
        except RifiutologoError as errore:
            # Gli allegati sono un di piu': il calendario e' gia' in mano e non
            # deve cadere per una chiamata accessoria.
            _LOGGER.debug("getAllegatiPap.php non ha risposto: %s", errore)
            allegati = []

        return Calendario(
            nota=_testo(grezzo.get("notaPap")) or "",
            giorni=tuple(giorni_raccolta),
            allegati=tuple(allegati),
        )


def _conferimento(voce: dict[str, Any]) -> Conferimento | None:
    """Costruisce un Conferimento da una voce grezza, o None se inutilizzabile."""
    macroprodotto = voce.get("macroprodotto")
    if not isinstance(macroprodotto, dict):
        return None
    frazione = _testo(macroprodotto.get("descrizione"))
    if frazione is None:
        return None

    pittogramma = macroprodotto.get("pittogramma")
    colore = (
        _colore(pittogramma.get("colore")) if isinstance(pittogramma, dict) else None
    )

    return Conferimento(
        frazione=frazione,
        macroprodotto_id=_intero(macroprodotto.get("id")),
        colore=colore,
        ora_inizio=_testo(voce.get("oraInizio")),
        ora_fine=_testo(voce.get("oraFine")),
        orario=_testo(voce.get("orario")),
        orario_raccolta=_testo(voce.get("orarioRaccolta")),
        straordinario=_intero(voce.get("straordinario")) not in (None, 0),
        note=_testo(voce.get("note")),
    )
