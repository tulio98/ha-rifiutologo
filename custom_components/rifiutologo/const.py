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
CONF_GIORNI_DA_MOSTRARE: Final = "giorni_da_mostrare"

DEFAULT_EVENTI_CON_ORARIO: Final = True
DEFAULT_CALENDARI_PER_FRAZIONE: Final = False
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
