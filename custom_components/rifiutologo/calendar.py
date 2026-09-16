"""Il calendario della raccolta.

Sempre un calendario complessivo con tutte le frazioni; se richiesto dalle
opzioni, anche un calendario per frazione, ciascuno col colore ufficiale che il
gestore pubblica in `pittogramma.colore`.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from homeassistant.components.calendar import (
    DOMAIN as DOMINIO_CALENDARIO,
    CalendarEntity,
    CalendarEvent,
)
from homeassistant.core import HomeAssistant, callback
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
from .entity import RifiutologoEntity, attributi_settimana, collega_per_frazione
from .orari import apertura_conferimento, scadenza


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RifiutologoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Crea il calendario complessivo e, se chiesto, quelli per frazione."""
    coordinator = entry.runtime_data

    @callback
    def _costruisci(frazione: str, colore: str | None, chiave: str) -> CalendarEntity:
        return CalendarioFrazione(coordinator, frazione, colore, chiave)

    per_frazione = collega_per_frazione(
        hass,
        entry,
        attiva=entry.options.get(
            CONF_CALENDARI_PER_FRAZIONE, DEFAULT_CALENDARI_PER_FRAZIONE
        ),
        dominio=DOMINIO_CALENDARIO,
        prefisso="calendario_",
        costruttore=_costruisci,
        async_add_entities=async_add_entities,
    )
    async_add_entities([CalendarioRaccolta(coordinator), *per_frazione])


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
    """Tutte le frazioni insieme, e l'agenda della settimana negli attributi.

    E' l'entita' che risponde a due domande con lo stesso bit: "si puo'
    esporre adesso" - e' il suo stato, e dopo la riparazione di
    `costruisci_eventi` e' esattamente la finestra di esposizione - e "che cosa
    esce questa settimana", che sta negli attributi perche' un'agenda e' il
    mestiere di un calendario.
    """

    _attr_translation_key = "raccolta"

    def __init__(self, coordinator: RifiutologoCoordinator) -> None:
        """Costruisce il calendario complessivo."""
        super().__init__(coordinator, "calendario")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """La settimana: il calendario da leggere, e le sere per i template.

        Home Assistant fonde questi sopra gli attributi suoi
        (`message`, `start_time`, `all_day`...), e nessuna delle cinque chiavi
        collide con quelli.
        """
        return attributi_settimana(
            self.coordinator.data, dt_util.now(), self.hass.config.language
        )


class CalendarioFrazione(_CalendarioBase):
    """Una sola frazione, col colore che le da' il gestore."""

    def __init__(
        self,
        coordinator: RifiutologoCoordinator,
        frazione: str,
        colore: str | None,
        chiave: str,
    ) -> None:
        """Costruisce il calendario di una frazione."""
        super().__init__(coordinator, f"calendario_{chiave}")
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

    Resta giornaliero un caso solo: quando il gestore non dichiara NIENTE, ne'
    un'apertura ne' una chiusura. Allora la frase esatta del gestore finisce
    nella descrizione, che e' meglio di una durata inventata.

    Gli istanti li danno `apertura_conferimento` e `scadenza`, che sono gli
    stessi che usano i binary sensor: non si rifa' il conto qui. Prima si
    ricostruiva la finestra a mano da `inizio_minuti` e `fine_minuti_effettiva`,
    e i due metri coincidevano ovunque tranne in una forma - "dalle 20:00"
    senza chiusura, di cui il backend ha 1382 conferimenti censiti: li'
    `apertura_dichiarata` dava le 20:00 ma `fine_minuti_effettiva` dava None, e
    l'evento degenerava in giornaliero. Misurato: venti ore al giorno in cui il
    calendario diceva "c'e' un evento" mentre la finestra era ancora chiusa. Ora
    il disaccordo e' zero in tutte e cinque le forme in cui il gestore scrive
    l'orario, e non perche' lo dicono le fixture: perche' e' lo stesso conto.
    """
    eventi: list[CalendarEvent] = []

    for giorno in calendario.giorni:
        for conferimento in giorno.conferimenti:
            if solo_frazione is not None and conferimento.frazione != solo_frazione:
                continue

            inizio: dt.date | dt.datetime
            fine: dt.date | dt.datetime

            dichiarato = (
                conferimento.apertura_dichiarata is not None
                or conferimento.fine_minuti_effettiva is not None
            )
            apre = apertura_conferimento(giorno, conferimento)
            chiude = scadenza(giorno, conferimento)

            # `chiude > apre` oggi e' sempre vero quando c'e' qualcosa di
            # dichiarato, e lo e' per una garanzia che sta in un ALTRO file:
            # `apertura_dichiarata` rifiuta un inizio a "24:00", che e' l'unico
            # modo di far coincidere apertura e scadenza. La guardia resta
            # perche' la garanzia non e' locale: se un domani quella riga
            # cambiasse, senza questa qui nascerebbe un evento di durata zero,
            # e un evento di durata zero non si vede e non si spiega. Il banco
            # mutazionale la segnala come equivalente, ed e' corretto che lo
            # faccia: e' una rete, non una regola.
            if con_orario and dichiarato and chiude > apre:
                inizio, fine = apre, chiude
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
