"""Costanti dell'integrazione Il Rifiutologo."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "rifiutologo"

# --- chiavi della config entry -------------------------------------------------

CONF_COMUNE_ID: Final = "comune_id"
CONF_COMUNE_NOME: Final = "comune_nome"
CONF_VIA_ID: Final = "via_id"
CONF_VIA_NOME: Final = "via_nome"
CONF_CIVICO_ID: Final = "civico_id"
CONF_CIVICO_NUMERO: Final = "civico_numero"

# --- chiavi delle opzioni ------------------------------------------------------

CONF_EVENTI_CON_ORARIO: Final = "eventi_con_orario"
CONF_CALENDARI_PER_FRAZIONE: Final = "calendari_per_frazione"
CONF_SENSORI_PER_FRAZIONE: Final = "sensori_per_frazione"
CONF_GIORNI_DA_MOSTRARE: Final = "giorni_da_mostrare"

DEFAULT_EVENTI_CON_ORARIO: Final = True
DEFAULT_CALENDARI_PER_FRAZIONE: Final = False
# Spento di serie come i calendari: a Padova sono sei entita' in piu' per
# indirizzo, e chi non le vuole non deve ritrovarsele.
DEFAULT_SENSORI_PER_FRAZIONE: Final = False
DEFAULT_GIORNI_DA_MOSTRARE: Final = 365
MIN_GIORNI_DA_MOSTRARE: Final = 30
MAX_GIORNI_DA_MOSTRARE: Final = 365

# Quanto dura la "settimana" del sensore di riepilogo: oggi piu' i sei giorni
# seguenti. Sette e non otto perche' e' il numero che la gente ha in testa
# quando chiede "cosa esce questa settimana", e perche' e' l'ampiezza con cui
# il gestore stesso stampa il calendario cartaceo. Non e' un'opzione: chi vuole
# guardare piu' lontano ha il calendario, che arriva fino a un anno.
GIORNI_SETTIMANA: Final = 7

# Il calendario di un gestore di rifiuti cambia qualche volta l'anno: le ore sono
# l'ordine di grandezza giusto per il polling, non i minuti.
UPDATE_INTERVAL_HOURS: Final = 12

# Quante date future elencare nell'attributo `prossime` di un sensore per
# frazione. Cinque bastano a vedere il passo: a Padova il vetro passa ogni
# trenta giorni, e cinque date coprono mezzo anno senza gonfiare il database
# di Home Assistant, che archivia gli attributi a ogni cambio di stato.
PROSSIME_DA_ELENCARE: Final = 5

# Quanti intervalli di aggiornamento devono passare fra due tentativi di
# ritrovare l'indirizzo per nome, finche' il calendario resta vuoto. Con un
# aggiornamento ogni 12 ore fa una volta a settimana: abbastanza raro da non
# pesare su un indirizzo che il porta a porta non ce l'ha e non l'avra' mai
# (l'elenco delle vie di Padova sono 191 KB), abbastanza spesso da accorgersi
# entro pochi giorni se il gestore rinumera il database.
#
# Il conto riparte da zero appena il calendario torna: vedi il commento nel
# coordinator per il perche' di quello scambio.
CADENZA_RIALLINEAMENTO: Final = 14

# Abbreviazioni dei giorni, per l'attributo che si legge a occhio. Stanno qui e
# non nei file di traduzione perche' NON sono nomi di entita' ne' di attributi:
# sono VALORI, e Home Assistant traduce i valori solo quando sono presi da un
# elenco fisso dichiarato nello strings.json. Una data lo diventerebbe solo
# elencando tutti i giorni dell'anno.
#
# L'indice e' `isoweekday() - 1`: 0 e' lunedi', 6 e' domenica.
GIORNI_ABBREVIATI: Final[dict[str, tuple[str, ...]]] = {
    "it": ("lun", "mar", "mer", "gio", "ven", "sab", "dom"),
    "en": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
}

LINGUA_DI_RIPIEGO: Final = "en"
"""Con una lingua che l'integrazione non parla si ripiega sull'inglese.

E' quello che fa Home Assistant con qualunque testo non tradotto: meglio una
riga in inglese che una data nuda, e meglio l'inglese che l'italiano imposto a
chi non l'ha scelto.
"""


def giorni_abbreviati(lingua: str | None) -> tuple[str, ...]:
    """Le abbreviazioni dei giorni nella lingua di Home Assistant.

    La lingua arriva come "it", "en", ma anche come "it-IT" o "pt-BR": si guarda
    solo la parte prima del trattino, che e' quella che sceglie la lingua.
    """
    radice = (lingua or LINGUA_DI_RIPIEGO).split("-")[0].casefold()
    return GIORNI_ABBREVIATI.get(radice, GIORNI_ABBREVIATI[LINGUA_DI_RIPIEGO])


ATTRIBUTION: Final = "Dati forniti da Il Rifiutologo - Gruppo Hera"
MANUFACTURER: Final = "Gruppo Hera"

# Colori ufficiali del gestore: arrivano dall'API in `pittogramma.colore` e non
# sono cablati qui. Questa mappa serve solo a dare un'icona Material Design alle
# frazioni, ed e' costruita su sottostringhe perche' le etichette cambiano da
# comune a comune ("Carta" a Padova, "Carta e cartone" a Faenza).
ICONE_FRAZIONE: Final[tuple[tuple[str, str], ...]] = (
    ("organico", "mdi:food-apple"),
    ("umido", "mdi:food-apple"),
    ("indifferenziato", "mdi:trash-can"),
    ("secco", "mdi:trash-can"),
    ("residuo", "mdi:trash-can"),
    ("carta", "mdi:newspaper-variant-multiple"),
    ("cartone", "mdi:package-variant"),
    ("vetro", "mdi:bottle-wine"),
    ("lattine", "mdi:bottle-soda-classic"),
    ("plastica", "mdi:bottle-soda-classic"),
    ("imballaggi", "mdi:package-variant-closed"),
    ("sfalci", "mdi:leaf"),
    ("potature", "mdi:leaf"),
    ("verde", "mdi:leaf"),
    ("pannolini", "mdi:baby-carriage"),
    ("pannoloni", "mdi:baby-carriage"),
    ("tessili", "mdi:tshirt-crew"),
    ("olio", "mdi:oil"),
    ("ingombranti", "mdi:sofa"),
    ("rae", "mdi:television-classic"),
    ("pile", "mdi:battery"),
    ("farmaci", "mdi:pill"),
)

ICONA_FRAZIONE_DEFAULT: Final = "mdi:recycle"


def icona_per_frazione(frazione: str) -> str:
    """Ritorna l'icona MDI piu' adatta al nome di una frazione."""
    testo = frazione.casefold()
    for chiave, icona in ICONE_FRAZIONE:
        if chiave in testo:
            return icona
    return ICONA_FRAZIONE_DEFAULT
