"""Il calendario della raccolta.

Sempre un calendario complessivo con tutte le frazioni; se richiesto dalle
opzioni, anche un calendario per frazione, ciascuno col colore ufficiale che il
gestore pubblica in `pittogramma.colore`.
"""

from __future__ import annotations

import datetime as dt
import re

from homeassistant.components.calendar import (
    DOMAIN as DOMINIO_CALENDARIO,
    CalendarEntity,
    CalendarEvent,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import Calendario, Conferimento
from .const import (
    CONF_CALENDARI_PER_FRAZIONE,
    CONF_EVENTI_CON_ORARIO,
    DEFAULT_CALENDARI_PER_FRAZIONE,
    DEFAULT_EVENTI_CON_ORARIO,
    icona_per_frazione,
)
from .coordinator import RifiutologoConfigEntry, RifiutologoCoordinator
from .entity import RifiutologoEntity
from .orari import istante


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RifiutologoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Crea il calendario complessivo e, se chiesto, quelli per frazione."""
    coordinator = entry.runtime_data
    per_frazione = entry.options.get(
        CONF_CALENDARI_PER_FRAZIONE, DEFAULT_CALENDARI_PER_FRAZIONE
    )
    frazioni_create: set[str] = set()

    @callback
    def _frazioni_mancanti() -> list[CalendarEntity]:
        """Le entita' per frazione che ancora non esistono."""
        if not per_frazione or coordinator.data is None:
            return []
        nuove: list[CalendarEntity] = []
        for frazione, colore in coordinator.data.frazioni.items():
            if frazione in frazioni_create:
                continue
            frazioni_create.add(frazione)
            nuove.append(CalendarioFrazione(coordinator, frazione, colore))
        return nuove

    async_add_entities([CalendarioRaccolta(coordinator), *_frazioni_mancanti()])
    _ripulisci_registro(hass, entry, frazioni_create)

    @callback
    def _al_dato_nuovo() -> None:
        """Una frazione stagionale puo' comparire mesi dopo la configurazione.

        Gli sfalci a primavera, per esempio: senza questo l'entita' nascerebbe
        solo al riavvio successivo di Home Assistant.
        """
        if nuove := _frazioni_mancanti():
            async_add_entities(nuove)

    entry.async_on_unload(coordinator.async_add_listener(_al_dato_nuovo))


@callback
def _ripulisci_registro(
    hass: HomeAssistant, entry: RifiutologoConfigEntry, frazioni: set[str]
) -> None:
    """Toglie dal registro i calendari per frazione che non servono piu'.

    Senza questo, spegnendo l'opzione le entita' resterebbero per sempre nel
    registro in stato "unavailable": Home Assistant le ripulisce da sola solo
    quando si rimuove l'intera voce di configurazione.
    """
    registro = er.async_get(hass)
    prefisso = f"{entry.entry_id}_calendario_"
    attesi = {f"{prefisso}{_chiave(frazione)}" for frazione in frazioni}

    for voce in er.async_entries_for_config_entry(registro, entry.entry_id):
        if (
            voce.domain == DOMINIO_CALENDARIO
            and voce.unique_id.startswith(prefisso)
            and voce.unique_id not in attesi
        ):
            registro.async_remove(voce.entity_id)


class _CalendarioBase(RifiutologoEntity, CalendarEntity):
    """Parte comune ai due tipi di calendario."""

    _frazione: str | None = None

    def __init__(self, coordinator: RifiutologoCoordinator, chiave: str) -> None:
        """Prepara la memoria degli eventi gia' costruiti."""
        super().__init__(coordinator, chiave)
        self._memoria: list[CalendarEvent] | None = None

    @property
    def _con_orario(self) -> bool:
        """Se costruire eventi con orario invece che giornalieri."""
        return self.coordinator.config_entry.options.get(
            CONF_EVENTI_CON_ORARIO, DEFAULT_EVENTI_CON_ORARIO
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Butta via gli eventi memorizzati: il calendario e' cambiato."""
        self._memoria = None
        super()._handle_coordinator_update()

    def _eventi(self) -> list[CalendarEvent]:
        """Gli eventi noti, costruiti una volta per scarico e non a ogni lettura.

        Home Assistant legge lo stato di un'entita' calendario piu' volte per
        ogni scrittura, e un anno di calendario sono qualche centinaio di
        eventi: ricostruirli ogni volta si paga senza motivo.
        """
        if self._memoria is None:
            calendario = self.coordinator.data
            self._memoria = (
                []
                if calendario is None
                else costruisci_eventi(
                    calendario,
                    con_orario=self._con_orario,
                    indirizzo=self.coordinator.indirizzo,
                    prefisso_uid=self.coordinator.config_entry.entry_id,
                    solo_frazione=self._frazione,
                )
            )
        return self._memoria

    @property
    def event(self) -> CalendarEvent | None:
        """Il prossimo evento, o quello in corso."""
        adesso = dt_util.now()
        for evento in self._eventi():
            if evento.end_datetime_local > adesso:
                return evento
        return None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: dt.datetime,
        end_date: dt.datetime,
    ) -> list[CalendarEvent]:
        """Gli eventi che ricadono nell'intervallo richiesto."""
        return [
            evento
            for evento in self._eventi()
            if evento.start_datetime_local < end_date
            and evento.end_datetime_local > start_date
        ]


class CalendarioRaccolta(_CalendarioBase):
    """Tutte le frazioni insieme."""

    _attr_translation_key = "raccolta"

    def __init__(self, coordinator: RifiutologoCoordinator) -> None:
        """Costruisce il calendario complessivo."""
        super().__init__(coordinator, "calendario")


class CalendarioFrazione(_CalendarioBase):
    """Una sola frazione, col colore che le da' il gestore."""

    def __init__(
        self, coordinator: RifiutologoCoordinator, frazione: str, colore: str | None
    ) -> None:
        """Costruisce il calendario di una frazione."""
        super().__init__(coordinator, f"calendario_{_chiave(frazione)}")
        self._frazione = frazione
        self._attr_name = frazione
        self._attr_icon = icona_per_frazione(frazione)
        if colore is not None:
            # Home Assistant colora l'entita' calendar da 2026.6 in poi; sulle
            # versioni precedenti l'attributo resta li' senza fare danni.
            self._attr_initial_color = colore


def costruisci_eventi(
    calendario: Calendario,
    *,
    con_orario: bool,
    indirizzo: str,
    prefisso_uid: str,
    solo_frazione: str | None = None,
) -> list[CalendarEvent]:
    """Trasforma il calendario del gestore in eventi di Home Assistant.

    Con `con_orario` l'evento copre la finestra di ESPOSIZIONE dichiarata dal
    gestore, che e' la cosa che serve davvero per farsi avvisare in tempo: a
    Padova dalle 20:00 alle 24:00, a Bologna dalle 20:00 alle 06:00 del mattino
    dopo.

    Restano giornalieri due casi, e per lo stesso motivo: il gestore non
    dichiara nessuna finestra. Succede quando mancano gli orari, e quando
    oraInizio coincide con oraFine, che a Faenza vuol dire "entro le 04:00" e
    altrove "dalle 20:00" - una scadenza o un'apertura, non una durata. In
    entrambi i casi la frase esatta del gestore finisce nella descrizione
    dell'evento, che e' meglio di una durata inventata.
    """
    eventi: list[CalendarEvent] = []

    for giorno in calendario.giorni:
        for conferimento in giorno.conferimenti:
            if solo_frazione is not None and conferimento.frazione != solo_frazione:
                continue

            inizio_minuti = conferimento.inizio_minuti
            fine_minuti = conferimento.fine_minuti_effettiva
            inizio: dt.date | dt.datetime
            fine: dt.date | dt.datetime

            if con_orario and inizio_minuti is not None and fine_minuti is not None:
                inizio = istante(giorno.giorno, inizio_minuti)
                fine = istante(giorno.giorno, fine_minuti)
            else:
                # Evento giornaliero: start ed end devono essere entrambi date,
                # mai un misto di date e datetime, o la validazione respinge.
                inizio = giorno.giorno
                fine = giorno.giorno + dt.timedelta(days=1)

            eventi.append(
                CalendarEvent(
                    start=inizio,
                    end=fine,
                    summary=conferimento.frazione,
                    description=_descrizione(conferimento),
                    location=indirizzo,
                    uid=(
                        f"{prefisso_uid}-{giorno.giorno.isoformat()}"
                        f"-{conferimento.chiave}"
                    ),
                )
            )

    eventi.sort(key=lambda e: (e.start_datetime_local, e.summary))
    return eventi


def _descrizione(conferimento: Conferimento) -> str | None:
    """Testo che spiega quando esporre e quando passa il mezzo."""
    pezzi: list[str] = []
    if conferimento.orario:
        pezzi.append(f"Esposizione {conferimento.orario}.")
    if conferimento.orario_raccolta:
        pezzi.append(f"Raccolta {conferimento.orario_raccolta}.")
    if conferimento.straordinario:
        pezzi.append("Raccolta straordinaria.")
    if conferimento.note:
        pezzi.append(conferimento.note)
    return " ".join(pezzi) or None


def _chiave(frazione: str) -> str:
    """Rende un nome di frazione utilizzabile come parte di unique_id."""
    return re.sub(r"[^a-z0-9]+", "_", frazione.casefold()).strip("_") or "frazione"
