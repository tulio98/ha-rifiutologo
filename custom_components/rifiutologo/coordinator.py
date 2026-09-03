"""Coordinamento dello scarico: una sola chiamata al gestore per tutte le entita'."""

from __future__ import annotations

from datetime import date, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import Calendario, RifiutologoClient, RifiutologoError
from .const import (
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

_LOGGER = logging.getLogger(__name__)

type RifiutologoConfigEntry = ConfigEntry[RifiutologoCoordinator]


class RifiutologoCoordinator(DataUpdateCoordinator[Calendario]):
    """Tiene aggiornato il calendario di un indirizzo."""

    config_entry: RifiutologoConfigEntry

    def __init__(self, hass: HomeAssistant, entry: RifiutologoConfigEntry) -> None:
        """Prepara il coordinator sulla sessione HTTP condivisa di Home Assistant."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
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
        self._riallineamento_tentato = False

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
        """Indirizzo leggibile, per titoli e attributi."""
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

    # --- ciclo di vita ---------------------------------------------------------

    async def _async_setup(self) -> None:
        """Predispone il risveglio di mezzanotte, una sola volta."""
        # I dati non cambiano a mezzanotte, ma "stasera" si sposta di un giorno:
        # senza questo, il sensore dell'esposizione resterebbe fermo a ieri fino
        # allo scarico successivo, che puo' essere fra dodici ore.
        self.config_entry.async_on_unload(
            async_track_time_change(
                self.hass, self._alla_mezzanotte, hour=0, minute=0, second=10
            )
        )

    @callback
    def _alla_mezzanotte(self, adesso: object) -> None:
        """Rinfresca le entita' senza richiamare il gestore."""
        _LOGGER.debug("Mezzanotte: ricalcolo le entita' di %s", self.indirizzo)
        self.async_update_listeners()

    async def _async_update_data(self) -> Calendario:
        """Scarica il calendario dell'indirizzo configurato."""
        comune_id, via_id, civico_id = self._identificativi
        try:
            calendario = await self.client.calendario(
                comune_id,
                via_id,
                civico_id,
                da=self.oggi,
                giorni=self.giorni_da_mostrare,
            )
            if not calendario.giorni and not self._riallineamento_tentato:
                self._riallineamento_tentato = True
                if await self._riallinea():
                    comune_id, via_id, civico_id = self._identificativi
                    calendario = await self.client.calendario(
                        comune_id,
                        via_id,
                        civico_id,
                        da=self.oggi,
                        giorni=self.giorni_da_mostrare,
                    )
        except RifiutologoError as errore:
            raise UpdateFailed(str(errore)) from errore

        if not calendario.giorni:
            # Non e' un errore: circa un indirizzo su tre, a Padova, e' servito da
            # cassonetti stradali e non ha alcun calendario. Va detto una volta,
            # non a ogni scarico.
            _LOGGER.log(
                logging.INFO if self.data is None else logging.DEBUG,
                "%s non ha raccolta porta a porta: il calendario e' vuoto",
                self.indirizzo,
            )
        return calendario

    async def _riallinea(self) -> bool:
        """Ricalcola gli id partendo dai nomi salvati.

        Serve se il gestore rinumera il proprio database: i nomi restano, gli id
        no. Ritorna True se la terna e' cambiata, cioe' se vale la pena riprovare.
        """
        dati = self.config_entry.data
        attuali = (dati[CONF_COMUNE_ID], dati[CONF_VIA_ID], dati[CONF_CIVICO_ID])
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
            _LOGGER.debug("Riallineamento non riuscito: %s", errore)
            return False

        nuovi = (comune.id, via.id, civico.id)
        if nuovi == attuali:
            return False

        _LOGGER.warning(
            "Il gestore ha cambiato gli identificativi di %s: %s diventa %s. "
            "Uso i nuovi per questa sessione; se il problema si ripete, "
            "riconfigura l'integrazione",
            self.indirizzo,
            attuali,
            nuovi,
        )
        self._id_riallineati = nuovi
        return True
