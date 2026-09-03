"""Coordinamento dello scarico: una sola chiamata al gestore per tutte le entita'."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import Calendario, GiornoRaccolta, RifiutologoClient, RifiutologoError
from .const import (
    CADENZA_RIALLINEAMENTO,
    CONF_CIVICO_ID,
    CONF_CIVICO_NUMERO,
    CONF_COMUNE_ID,
    CONF_COMUNE_NOME,
    CONF_GIORNI_DA_MOSTRARE,
    CONF_VIA_ID,
    CONF_VIA_NOME,
    DEFAULT_GIORNI_DA_MOSTRARE,
    DOMAIN,
    UPDATE_INTERVAL_HOURS,
)
from .orari import giorno_in_corso, prossima_raccolta, prossimo_confine

_LOGGER = logging.getLogger(__name__)

type RifiutologoConfigEntry = ConfigEntry[RifiutologoCoordinator]


class RifiutologoCoordinator(DataUpdateCoordinator[Calendario]):
    """Tiene aggiornato il calendario di un indirizzo."""

    config_entry: RifiutologoConfigEntry

    def __init__(self, hass: HomeAssistant, entry: RifiutologoConfigEntry) -> None:
        """Prepara il coordinator sulla sessione HTTP condivisa di Home Assistant."""
        # Il nome finisce nei log a ogni scarico, e i log finiscono nelle
        # segnalazioni: qui ci va il comune e un troncone dell'entry_id, mai via
        # e civico. E' la stessa regola che segue la diagnostica.
        self._etichetta = f"{entry.data[CONF_COMUNE_NOME]} ({entry.entry_id[:7]})"

        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {self._etichetta}",
            update_interval=timedelta(hours=UPDATE_INTERVAL_HOURS),
            # Il calendario di un anno e' un oggetto immutabile e confrontabile:
            # senza questo, ogni scarico riscriverebbe lo stato di tutte le
            # entita' anche quando non e' cambiato nulla.
            always_update=False,
        )
        self.client = RifiutologoClient(async_get_clientsession(hass))

        # Gli id del gestore non sono garantiti stabili nel tempo. Se un giorno
        # cambiassero, il calendario tornerebbe vuoto senza dire niente: qui si
        # tiene una risoluzione alternativa fatta per nome, valida per la sessione.
        self._id_riallineati: tuple[int, int, int] | None = None
        self._scarichi_vuoti = 0
        self._gia_avvisato = False

        self._disdici_risveglio: CALLBACK_TYPE | None = None

    # --- lettura della configurazione -----------------------------------------

    @property
    def comune_nome(self) -> str:
        """Nome del comune scelto."""
        return self.config_entry.data[CONF_COMUNE_NOME]

    @property
    def via_nome(self) -> str:
        """Nome della via, come lo scrive il gestore (tutto maiuscolo)."""
        return self.config_entry.data[CONF_VIA_NOME]

    @property
    def civico_numero(self) -> str:
        """Numero civico, che e' una stringa e non un intero."""
        return self.config_entry.data[CONF_CIVICO_NUMERO]

    @property
    def indirizzo(self) -> str:
        """Indirizzo leggibile, per il nome del dispositivo e per gli attributi."""
        return f"{self.via_nome} {self.civico_numero}, {self.comune_nome}"

    @property
    def giorni_da_mostrare(self) -> int:
        """Ampiezza dell'orizzonte da chiedere al gestore."""
        return self.config_entry.options.get(
            CONF_GIORNI_DA_MOSTRARE, DEFAULT_GIORNI_DA_MOSTRARE
        )

    @property
    def _identificativi(self) -> tuple[int, int, int]:
        """La terna comune/via/civico in uso in questo momento."""
        if self._id_riallineati is not None:
            return self._id_riallineati
        dati = self.config_entry.data
        return (dati[CONF_COMUNE_ID], dati[CONF_VIA_ID], dati[CONF_CIVICO_ID])

    @property
    def oggi(self) -> date:
        """La data di oggi nel fuso orario di Home Assistant."""
        return dt_util.now().date()

    @property
    def attuale(self) -> GiornoRaccolta | None:
        """Che cosa si puo' ancora esporre adesso.

        Dove la finestra scavalca la mezzanotte puo' essere la sera di IERI, ed
        e' giusto: alle due di notte a Bologna il sacco va ancora messo fuori.
        """
        return giorno_in_corso(self.data, dt_util.now())

    @property
    def prossima(self) -> GiornoRaccolta | None:
        """La prossima raccolta, da oggi in avanti.

        Deliberatamente diversa da `attuale`: un sensore che si chiama "prossima
        raccolta" non puo' rispondere ieri, nemmeno nelle ore in cui la finestra
        di ieri e' ancora aperta.
        """
        return prossima_raccolta(self.data, self.oggi)

    # --- risveglio ai confini della giornata -----------------------------------

    async def _async_setup(self) -> None:
        """Fa in modo che il risveglio programmato non sopravviva alla voce."""
        self.config_entry.async_on_unload(self._annulla_risveglio)

    @callback
    def _annulla_risveglio(self) -> None:
        """Disdice il risveglio in sospeso, se c'e'."""
        if self._disdici_risveglio is not None:
            self._disdici_risveglio()
            self._disdici_risveglio = None

    @callback
    def _programma_risveglio(self, calendario: Calendario | None) -> None:
        """Programma il ricalcolo al prossimo confine di giornata."""
        self._annulla_risveglio()
        adesso = dt_util.now()
        # Un confine gia' passato - orologio riportato indietro, o un dato
        # vecchio - darebbe un ritardo negativo: il callback rientrerebbe subito
        # e si riprogrammerebbe sullo stesso istante, girando a vuoto senza
        # freno. Il pavimento costa una riga.
        quando = max(
            prossimo_confine(calendario, adesso), adesso + timedelta(seconds=1)
        )
        self._disdici_risveglio = async_track_point_in_time(
            self.hass, self._al_confine, quando
        )
        _LOGGER.debug("%s: prossimo ricalcolo alle %s", self._etichetta, quando)

    @callback
    def _al_confine(self, adesso: datetime) -> None:
        """Ricalcola le entita' senza richiamare il gestore, e si riprogramma.

        A mezzanotte cambia la data di oggi; alla chiusura della finestra la
        raccolta di stasera passa il testimone alla successiva. In nessuno dei
        due casi e' arrivato un dato nuovo, quindi non si disturba il gestore.
        """
        self.async_update_listeners()
        self._programma_risveglio(self.data)

    # --- scarico ---------------------------------------------------------------

    async def _scarica(self) -> Calendario:
        """Un giro secco sul gestore con gli identificativi in uso."""
        comune_id, via_id, civico_id = self._identificativi
        return await self.client.calendario(
            comune_id,
            via_id,
            civico_id,
            da=self.oggi,
            giorni=self.giorni_da_mostrare,
        )

    async def _async_update_data(self) -> Calendario:
        """Scarica il calendario dell'indirizzo configurato."""
        try:
            calendario = await self._scarica()
        except RifiutologoError as errore:
            raise UpdateFailed(str(errore)) from errore

        if calendario.giorni:
            # Il contatore conta i vuoti CONSECUTIVI: senza questo azzeramento
            # un vuoto isolato sfaserebbe la cadenza per tutta la sessione, e la
            # rete di sicurezza arriverebbe con giorni di ritardo.
            self._scarichi_vuoti = 0
            self._gia_avvisato = False
        else:
            calendario = await self._forse_riallinea(calendario)

        self._programma_risveglio(calendario)
        return calendario

    async def _forse_riallinea(self, vuoto: Calendario) -> Calendario:
        """Di fronte a un calendario vuoto, prova a ritrovare l'indirizzo per nome.

        Un calendario vuoto ha tre cause diverse e indistinguibili dalla
        risposta: l'indirizzo non ha il porta a porta (il caso normale, e non e'
        un guasto), gli identificativi non valgono piu', oppure il backend ha
        cambiato forma. Si tenta ogni tanto e non una volta sola: se il primo
        tentativo lo brucia un indirizzo senza porta a porta, il giorno in cui
        il gestore rinumera davvero la rete di sicurezza deve esserci ancora.
        """
        self._scarichi_vuoti += 1
        if (self._scarichi_vuoti - 1) % CADENZA_RIALLINEAMENTO:
            self._avvisa_se_muto()
            return vuoto

        precedenti = self._id_riallineati
        try:
            if not await self._riallinea():
                self._avvisa_se_muto()
                return vuoto
            nuovo = await self._scarica()
        except RifiutologoError as errore:
            # La rete di sicurezza e' un di piu'. Se inciampa lei, si tiene il
            # risultato valido che si ha gia' in mano: renderebbe l'integrazione
            # meno affidabile di quanto sarebbe senza. E si torna alla terna di
            # prima, che quella nuova non e' mai stata confermata.
            _LOGGER.debug("%s: riallineamento interrotto: %s", self._etichetta, errore)
            self._id_riallineati = precedenti
            self._avvisa_se_muto()
            return vuoto

        if nuovo.giorni:
            self._scarichi_vuoti = 0
            self._gia_avvisato = False
            # L'avviso si da' QUI, non appena si trova una terna diversa: prima
            # di questo punto nessuno l'aveva ancora provata.
            _LOGGER.warning(
                "%s: il gestore ha cambiato gli identificativi di questo "
                "indirizzo. Li ho ricalcolati partendo dal nome e il calendario "
                "e' tornato. Vale per questa sessione: se il problema si ripete, "
                "riconfigura l'integrazione",
                self._etichetta,
            )
            return nuovo

        # Gli identificativi nuovi non hanno risolto niente: si torna indietro
        # invece di trascinarli per tutta la sessione.
        _LOGGER.debug(
            "%s: gli identificativi ricalcolati danno un calendario vuoto lo stesso",
            self._etichetta,
        )
        self._id_riallineati = precedenti
        self._avvisa_se_muto()
        return vuoto

    @callback
    def _avvisa_se_muto(self) -> None:
        """Spiega una volta sola perche' le entita' non hanno niente da dire."""
        if self._gia_avvisato:
            return
        self._gia_avvisato = True
        _LOGGER.info(
            "%s: il gestore non pubblica alcun calendario per questo indirizzo. "
            "Non e' un guasto: succede agli indirizzi serviti da cassonetti "
            "stradali o da isole ecologiche, che a Padova sono circa uno su tre",
            self._etichetta,
        )

    async def _riallinea(self) -> bool:
        """Ricalcola gli id partendo dai nomi salvati.

        Serve se il gestore rinumera il proprio database: i nomi restano, gli id
        no. Ritorna True se la terna e' cambiata, cioe' se vale la pena riprovare.
        """
        attuali = self._identificativi
        try:
            comuni = await self.client.comuni()
            comune = next(
                (c for c in comuni if c.nome.casefold() == self.comune_nome.casefold()),
                None,
            )
            if comune is None:
                return False

            vie = await self.client.vie(comune.id)
            via = next(
                (v for v in vie if v.nome.casefold() == self.via_nome.casefold()), None
            )
            if via is None:
                return False

            civici = await self.client.civici(comune.id, via.id)
            civico = next((c for c in civici if c.numero == self.civico_numero), None)
            if civico is None:
                return False
        except RifiutologoError as errore:
            _LOGGER.debug(
                "%s: riallineamento non riuscito: %s", self._etichetta, errore
            )
            return False

        nuovi = (comune.id, via.id, civico.id)
        if nuovi == attuali:
            return False

        # Non si stampano le terne: via_id e civico_id sono due dei quattro
        # campi che la diagnostica oscura, e questa riga finisce nei log che le
        # segnalazioni allegano.
        cambiati = [
            nome
            for nome, prima, dopo in zip(
                ("comune", "via", "civico"), attuali, nuovi, strict=True
            )
            if prima != dopo
        ]
        _LOGGER.debug(
            "%s: identificativi ricalcolati per nome, cambia %s",
            self._etichetta,
            ", ".join(cambiati),
        )
        self._id_riallineati = nuovi
        return True
