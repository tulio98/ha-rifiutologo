"""Configurazione guidata: comune, via e civico si scelgono a tendina.

L'API lavora per indirizzo, mai per zona: il turno di raccolta e il codice zona
(a Padova per esempio "Q6 2026") sono una conseguenza del civico, non un dato
da chiedere all'utente. Per questo qui non si chiede nessuna zona.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.util import dt as dt_util

from .api import Civico, Comune, RifiutologoClient, RifiutologoError, Via
from .const import (
    CONF_CALENDARI_PER_FRAZIONE,
    CONF_CIVICO_ID,
    CONF_CIVICO_NUMERO,
    CONF_COMUNE_ID,
    CONF_COMUNE_NOME,
    CONF_EVENTI_CON_ORARIO,
    CONF_GIORNI_DA_MOSTRARE,
    CONF_VIA_ID,
    CONF_VIA_NOME,
    DEFAULT_CALENDARI_PER_FRAZIONE,
    DEFAULT_EVENTI_CON_ORARIO,
    DEFAULT_GIORNI_DA_MOSTRARE,
    DOMAIN,
    MAX_GIORNI_DA_MOSTRARE,
    MIN_GIORNI_DA_MOSTRARE,
)

CAMPO_COMUNE = "comune"
CAMPO_VIA = "via"
CAMPO_CIVICO = "civico"

# Basta un mese per capire se un indirizzo ha il porta a porta: la verifica in
# fondo al flusso non deve far aspettare l'utente piu' del necessario.
GIORNI_DI_VERIFICA = 40


class RifiutologoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Tre passi, ciascuno alimentato dall'elenco vero del gestore."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        """Prepara lo stato che attraversa i tre passi."""
        self._comuni: list[Comune] = []
        self._vie: list[Via] = []
        self._civici: list[Civico] = []
        self._comune: Comune | None = None
        self._via: Via | None = None

    @property
    def _client(self) -> RifiutologoClient:
        """Client sulla sessione HTTP condivisa."""
        return RifiutologoClient(async_get_clientsession(self.hass))

    # --- passo 1: il comune ----------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Sceglie il comune fra i 181 serviti."""
        if not self._comuni:
            try:
                self._comuni = await self._client.comuni()
            except RifiutologoError:
                return self.async_abort(reason="cannot_connect")

        if user_input is not None:
            scelto = _trova(self._comuni, user_input[CAMPO_COMUNE], lambda c: c.id)
            if scelto is not None:
                self._comune = scelto
                self._vie = []
                return await self.async_step_via()

        opzioni = [
            SelectOptionDict(value=str(c.id), label=c.etichetta)
            for c in sorted(self._comuni, key=lambda c: c.nome)
        ]
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CAMPO_COMUNE): _tendina(opzioni)},
            ),
        )

    # --- passo 2: la via -------------------------------------------------------

    async def async_step_via(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Sceglie la via. A Padova sono 2200: la tendina si puo' filtrare."""
        assert self._comune is not None

        if not self._vie:
            try:
                self._vie = await self._client.vie(self._comune.id)
            except RifiutologoError:
                return self.async_abort(reason="cannot_connect")

        if user_input is not None:
            scelta = _trova(self._vie, user_input[CAMPO_VIA], lambda v: v.id)
            if scelta is not None:
                self._via = scelta
                self._civici = []
                return await self.async_step_civico()

        opzioni = [
            SelectOptionDict(value=str(v.id), label=v.nome)
            for v in sorted(self._vie, key=lambda v: v.nome)
        ]
        return self.async_show_form(
            step_id="via",
            data_schema=vol.Schema({vol.Required(CAMPO_VIA): _tendina(opzioni)}),
            description_placeholders={"comune": self._comune.nome},
        )

    # --- passo 3: il civico, e la verifica -------------------------------------

    async def async_step_civico(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Sceglie il civico e verifica che quell'indirizzo abbia il porta a porta."""
        assert self._comune is not None
        assert self._via is not None

        errori: dict[str, str] = {}

        if not self._civici:
            try:
                self._civici = await self._client.civici(self._comune.id, self._via.id)
            except RifiutologoError:
                return self.async_abort(reason="cannot_connect")

        if user_input is not None:
            civico = _trova(self._civici, user_input[CAMPO_CIVICO], lambda c: c.id)
            if civico is not None:
                try:
                    calendario = await self._client.calendario(
                        self._comune.id,
                        self._via.id,
                        civico.id,
                        da=dt_util.now().date(),
                        giorni=GIORNI_DI_VERIFICA,
                    )
                except RifiutologoError:
                    errori["base"] = "cannot_connect"
                else:
                    if not calendario.giorni:
                        # Non e' un guasto: a Padova circa un indirizzo su tre e'
                        # servito da cassonetti stradali. Meglio dirlo adesso che
                        # lasciare l'utente con entita' mute per sempre.
                        errori["base"] = "nessun_pap"
                    else:
                        return await self._concludi(civico)

        opzioni = [
            SelectOptionDict(value=str(c.id), label=c.numero) for c in self._civici
        ]
        return self.async_show_form(
            step_id="civico",
            data_schema=vol.Schema({vol.Required(CAMPO_CIVICO): _tendina(opzioni)}),
            errors=errori,
            description_placeholders={"via": self._via.nome},
        )

    async def _concludi(self, civico: Civico) -> ConfigFlowResult:
        """Crea la voce, oppure aggiorna quella esistente se si sta riconfigurando."""
        assert self._comune is not None
        assert self._via is not None

        identificativo = f"{self._comune.id}-{self._via.id}-{civico.id}"
        titolo = f"{self._via.nome} {civico.numero}, {self._comune.nome}"
        dati = {
            CONF_COMUNE_ID: self._comune.id,
            CONF_COMUNE_NOME: self._comune.nome,
            CONF_VIA_ID: self._via.id,
            CONF_VIA_NOME: self._via.nome,
            CONF_CIVICO_ID: civico.id,
            CONF_CIVICO_NUMERO: civico.numero,
        }

        await self.async_set_unique_id(identificativo)

        if self.source == SOURCE_RECONFIGURE:
            voce = self._get_reconfigure_entry()
            # Cambiare indirizzo e' lecito riconfigurando; finire sopra a un
            # indirizzo gia' configurato altrove no.
            for altra in self._async_current_entries():
                if (
                    altra.entry_id != voce.entry_id
                    and altra.unique_id == identificativo
                ):
                    return self.async_abort(reason="already_configured")
            return self.async_update_reload_and_abort(
                voce, unique_id=identificativo, title=titolo, data=dati
            )

        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=titolo, data=dati)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Permette di cambiare indirizzo senza rifare tutto da capo."""
        return await self.async_step_user()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Espone le opzioni."""
        return RifiutologoOptionsFlow()


class RifiutologoOptionsFlow(OptionsFlowWithReload):
    """Opzioni. La classe ricarica da sola la voce quando cambiano."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Mostra e salva le opzioni."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_EVENTI_CON_ORARIO: user_input[CONF_EVENTI_CON_ORARIO],
                    CONF_CALENDARI_PER_FRAZIONE: user_input[
                        CONF_CALENDARI_PER_FRAZIONE
                    ],
                    CONF_GIORNI_DA_MOSTRARE: int(user_input[CONF_GIORNI_DA_MOSTRARE]),
                }
            )

        attuali = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_EVENTI_CON_ORARIO,
                        default=attuali.get(
                            CONF_EVENTI_CON_ORARIO, DEFAULT_EVENTI_CON_ORARIO
                        ),
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_CALENDARI_PER_FRAZIONE,
                        default=attuali.get(
                            CONF_CALENDARI_PER_FRAZIONE,
                            DEFAULT_CALENDARI_PER_FRAZIONE,
                        ),
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_GIORNI_DA_MOSTRARE,
                        default=attuali.get(
                            CONF_GIORNI_DA_MOSTRARE, DEFAULT_GIORNI_DA_MOSTRARE
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_GIORNI_DA_MOSTRARE,
                            max=MAX_GIORNI_DA_MOSTRARE,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )


def _tendina(opzioni: list[SelectOptionDict]) -> SelectSelector:
    """Una tendina ricercabile, senza valori liberi."""
    return SelectSelector(
        SelectSelectorConfig(
            options=opzioni,
            mode=SelectSelectorMode.DROPDOWN,
            custom_value=False,
            sort=False,
        )
    )


def _trova[T](elementi: list[T], valore: str, chiave: Any) -> T | None:
    """Ritrova un elemento dall'id serializzato come stringa dalla tendina."""
    for elemento in elementi:
        if str(chiave(elemento)) == valore:
            return elemento
    return None
