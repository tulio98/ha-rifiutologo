"""Test della configurazione guidata."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rifiutologo.api import BASE_URL, Via
from custom_components.rifiutologo.config_flow import _trova
from custom_components.rifiutologo.const import (
    CONF_CALENDARI_PER_FRAZIONE,
    CONF_CIVICO_NUMERO,
    CONF_COMUNE_NOME,
    CONF_EVENTI_CON_ORARIO,
    CONF_GIORNI_DA_MOSTRARE,
    CONF_VIA_NOME,
    DOMAIN,
)
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import (
    CIVICO_ID,
    CIVICO_SCELTO,
    COMUNE_ID,
    COMUNE_SCELTO,
    VIA_ID,
    VIA_SCELTA,
    carica,
    registra,
)


@pytest.fixture(autouse=True)
def _carica_integrazione(enable_custom_integrations: None) -> None:
    """Ogni test di questo file passa dal loader di Home Assistant."""


async def _fino_al_civico(
    hass: HomeAssistant,
    *,
    source: str = SOURCE_USER,
    atteso: str | None = "civico",
    **kwargs,
):
    """Porta il flusso fino al terzo passo.

    Con `atteso=None` non pretende di esserci arrivato: serve ai test in cui il
    flusso deve deviare, per esempio quando la via non ha civici.
    """
    risultato = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": source, **kwargs}
    )
    assert risultato["type"] is FlowResultType.FORM
    assert risultato["step_id"] == "user"

    risultato = await hass.config_entries.flow.async_configure(
        risultato["flow_id"], {"comune": COMUNE_SCELTO}
    )
    assert risultato["step_id"] == "via"

    risultato = await hass.config_entries.flow.async_configure(
        risultato["flow_id"], {"via": VIA_SCELTA}
    )
    if atteso is not None:
        assert risultato["step_id"] == atteso
    return risultato


async def test_flusso_completo(hass: HomeAssistant, gestore) -> None:
    """Tre tendine e la voce e' creata, col titolo giusto."""
    risultato = await _fino_al_civico(hass)
    risultato = await hass.config_entries.flow.async_configure(
        risultato["flow_id"], {"civico": CIVICO_SCELTO}
    )
    await hass.async_block_till_done()

    assert risultato["type"] is FlowResultType.CREATE_ENTRY
    assert risultato["title"] == "VIA BERNARDO TREVISAN 8, Padova"
    assert risultato["data"][CONF_COMUNE_NOME] == "Padova"
    assert risultato["data"][CONF_VIA_NOME] == "VIA BERNARDO TREVISAN"
    # Il civico resta una stringa: esistono "1/A", "1/SNC", "2/2".
    assert risultato["data"][CONF_CIVICO_NUMERO] == "8"
    assert risultato["result"].unique_id == f"{COMUNE_ID}-{VIA_ID}-{CIVICO_ID}"


async def test_le_tendine_sono_piene(hass: HomeAssistant, gestore) -> None:
    """Ogni passo offre le voci vere del gestore, e si possono cercare."""
    risultato = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    selettore = risultato["data_schema"].schema["comune"]
    valori = [o["value"] for o in selettore.config["options"]]
    # Il valore e' il testo che si legge, non l'id: e' cio' che il campo
    # mostra dopo la scelta, e un id li' dentro non direbbe niente a nessuno.
    assert COMUNE_SCELTO in valori
    assert str(COMUNE_ID) not in valori
    # `custom_value` non serve ad accettare valori inventati - quelli li
    # respinge il flusso, e c'e' un test apposta piu' sotto - ma e' il campo da
    # cui Home Assistant decide se disegnare una casella di ricerca o un menu'
    # da scorrere. Con 2200 vie la differenza e' tutto.
    assert selettore.config["custom_value"] is True
    # Ordine alfabetico, non quello del gestore.
    etichette = [o["label"] for o in selettore.config["options"]]
    assert etichette == sorted(etichette)


@pytest.mark.parametrize(
    ("scritto", "atteso"),
    [
        ("Padova", "Padova"),
        ("padova", "minuscolo: il nome e' quello lo stesso"),
        ("  Padova  ", "spazi intorno"),
        ("Padova (PD)", "l'etichetta con la provincia"),
    ],
)
async def test_il_comune_si_puo_anche_scrivere(
    hass: HomeAssistant, gestore, scritto: str, atteso: str
) -> None:
    """Confermare il testo senza cliccare un suggerimento deve funzionare.

    La casella di ricerca lascia premere invio su cio' che si e' digitato, e
    allora al flusso arriva il nome invece dell'id. Rifiutare un nome scritto
    giusto sarebbe una pedanteria che l'utente leggerebbe come un difetto.
    """
    risultato = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    risultato = await hass.config_entries.flow.async_configure(
        risultato["flow_id"], {"comune": scritto}
    )
    assert risultato["type"] is FlowResultType.FORM, atteso
    assert risultato["step_id"] == "via", atteso


# Il campo del modulo si chiama come il passo, tranne al primo: li' il passo e'
# "user" perche' lo vuole Home Assistant, ma il campo e' "comune".
CAMPO_DEL_PASSO = {"user": "comune", "via": "via", "civico": "civico"}


@pytest.mark.parametrize(
    ("passo", "scritto", "errore"),
    [
        ("user", "Vattelapesca", "comune_sconosciuto"),
        ("via", "VIA CHE NON ESISTE", "via_sconosciuta"),
        ("civico", "999/Z", "civico_sconosciuto"),
    ],
)
async def test_un_valore_inventato_lo_dice(
    hass: HomeAssistant, gestore, passo: str, scritto: str, errore: str
) -> None:
    """Il campo e' cercabile, non libero: cio' che non esiste va respinto.

    E va respinto DICENDOLO. Prima questo ramo non era raggiungibile e il
    modulo si ripresentava muto: con la casella di ricerca ci si arriva
    scrivendo qualunque cosa e premendo invio, e restare zitti sarebbe il modo
    piu' sicuro di far credere che l'integrazione sia rotta.
    """
    risultato = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    if passo != "user":
        risultato = await hass.config_entries.flow.async_configure(
            risultato["flow_id"], {"comune": COMUNE_SCELTO}
        )
    if passo == "civico":
        risultato = await hass.config_entries.flow.async_configure(
            risultato["flow_id"], {"via": VIA_SCELTA}
        )

    risultato = await hass.config_entries.flow.async_configure(
        risultato["flow_id"], {CAMPO_DEL_PASSO[passo]: scritto}
    )
    assert risultato["type"] is FlowResultType.FORM
    assert risultato["step_id"] == passo, "si resta dove si era"
    assert risultato["errors"] == {"base": errore}


async def test_la_via_scritta_per_esteso_vale(hass: HomeAssistant, gestore) -> None:
    """Anche la via, non solo il comune: stesso patto su tutti e tre i passi."""
    risultato = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    risultato = await hass.config_entries.flow.async_configure(
        risultato["flow_id"], {"comune": COMUNE_SCELTO}
    )
    risultato = await hass.config_entries.flow.async_configure(
        risultato["flow_id"], {"via": "via bernardo trevisan"}
    )
    assert risultato["step_id"] == "civico"

    # E il civico, che e' una stringa e non un intero.
    risultato = await hass.config_entries.flow.async_configure(
        risultato["flow_id"], {"civico": "8"}
    )
    assert risultato["type"] is FlowResultType.CREATE_ENTRY
    assert risultato["data"][CONF_CIVICO_NUMERO] == "8"


async def test_tutte_le_tendine_sono_cercabili(hass: HomeAssistant, gestore) -> None:
    """Non serve a niente cercare il comune se poi le 2200 vie si scorrono."""
    risultato = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    for campo, avanti in (("comune", COMUNE_SCELTO), ("via", VIA_SCELTA)):
        assert risultato["data_schema"].schema[campo].config["custom_value"] is True
        risultato = await hass.config_entries.flow.async_configure(
            risultato["flow_id"], {campo: avanti}
        )
    assert risultato["data_schema"].schema["civico"].config["custom_value"] is True


async def test_indirizzo_senza_porta_a_porta(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Un indirizzo a cassonetti lo dice subito, invece di creare entita' mute."""
    registra(aioclient_mock, calendario="calendario_vuoto", allegati="allegati_vuoti")

    risultato = await _fino_al_civico(hass)
    risultato = await hass.config_entries.flow.async_configure(
        risultato["flow_id"], {"civico": CIVICO_SCELTO}
    )

    assert risultato["type"] is FlowResultType.FORM
    assert risultato["step_id"] == "civico"
    assert risultato["errors"] == {"base": "nessun_pap"}


async def test_gestore_irraggiungibile(hass: HomeAssistant, aioclient_mock) -> None:
    """Se il backend non risponde, il flusso si ferma con un messaggio chiaro."""
    aioclient_mock.get(f"{BASE_URL}/getComuni.php", status=500)
    risultato = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert risultato["type"] is FlowResultType.ABORT
    assert risultato["reason"] == "cannot_connect"


async def test_indirizzo_gia_configurato(
    hass: HomeAssistant, gestore, voce: MockConfigEntry
) -> None:
    """Lo stesso indirizzo non si configura due volte."""
    voce.add_to_hass(hass)

    risultato = await _fino_al_civico(hass)
    risultato = await hass.config_entries.flow.async_configure(
        risultato["flow_id"], {"civico": CIVICO_SCELTO}
    )
    assert risultato["type"] is FlowResultType.ABORT
    assert risultato["reason"] == "already_configured"


async def test_riconfigura(hass: HomeAssistant, gestore, voce: MockConfigEntry) -> None:
    """Si puo' cambiare indirizzo senza perdere la voce e la sua cronologia."""
    voce.add_to_hass(hass)
    assert await hass.config_entries.async_setup(voce.entry_id)
    await hass.async_block_till_done()

    risultato = await _fino_al_civico(
        hass, source=SOURCE_RECONFIGURE, entry_id=voce.entry_id
    )
    # Il civico "1" della stessa via, invece dell'8 di partenza.
    risultato = await hass.config_entries.flow.async_configure(
        risultato["flow_id"], {"civico": "1"}
    )
    await hass.async_block_till_done()

    assert risultato["type"] is FlowResultType.ABORT
    assert risultato["reason"] == "reconfigure_successful"
    assert voce.data[CONF_CIVICO_NUMERO] == "1"
    assert voce.title == "VIA BERNARDO TREVISAN 1, Padova"
    assert voce.unique_id == f"{COMUNE_ID}-{VIA_ID}-1328838"


async def test_opzioni(hass: HomeAssistant, gestore, voce: MockConfigEntry) -> None:
    """Le opzioni si salvano e ricaricano la voce da sole."""
    voce.add_to_hass(hass)
    assert await hass.config_entries.async_setup(voce.entry_id)
    await hass.async_block_till_done()

    risultato = await hass.config_entries.options.async_init(voce.entry_id)
    assert risultato["step_id"] == "init"

    risultato = await hass.config_entries.options.async_configure(
        risultato["flow_id"],
        {
            CONF_EVENTI_CON_ORARIO: False,
            CONF_CALENDARI_PER_FRAZIONE: True,
            CONF_GIORNI_DA_MOSTRARE: 90,
        },
    )
    await hass.async_block_till_done()

    assert risultato["type"] is FlowResultType.CREATE_ENTRY
    assert voce.options[CONF_EVENTI_CON_ORARIO] is False
    assert voce.options[CONF_CALENDARI_PER_FRAZIONE] is True
    # Il selettore numerico restituisce un float: deve arrivare intero.
    assert voce.options[CONF_GIORNI_DA_MOSTRARE] == 90
    assert isinstance(voce.options[CONF_GIORNI_DA_MOSTRARE], int)


async def test_via_senza_civici_non_e_un_guasto_di_rete(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Una via che il gestore non associa a nessun civico non deve uccidere il flusso.

    Prima si abortiva con `cannot_connect`, cioe' dando la colpa alla rete per un
    dato che semplicemente manca, e l'utente doveva ricominciare da capo.
    """
    aioclient_mock.get(f"{BASE_URL}/getComuni.php", json=carica("comuni"))
    aioclient_mock.get(f"{BASE_URL}/getIndirizzi.php", json=carica("indirizzi"))
    aioclient_mock.get(f"{BASE_URL}/getNumeriCivici.php", json=[])

    risultato = await _fino_al_civico(hass, atteso=None)

    # Si torna a scegliere la via, spiegando perche'.
    assert risultato["type"] is FlowResultType.FORM
    assert risultato["step_id"] == "via"
    assert risultato["errors"] == {"base": "via_senza_civici"}
    # E la tendina e' ancora piena: si sceglie un'altra via e si prosegue.
    assert risultato["data_schema"].schema["via"].config["options"]


async def test_comune_senza_vie(hass: HomeAssistant, aioclient_mock) -> None:
    """Un comune senza vie riporta al primo passo, non a un abort."""
    aioclient_mock.get(f"{BASE_URL}/getComuni.php", json=carica("comuni"))
    aioclient_mock.get(f"{BASE_URL}/getIndirizzi.php", json=[])

    risultato = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    risultato = await hass.config_entries.flow.async_configure(
        risultato["flow_id"], {"comune": COMUNE_SCELTO}
    )
    assert risultato["type"] is FlowResultType.FORM
    assert risultato["step_id"] == "user"
    assert risultato["errors"] == {"base": "comune_senza_vie"}


async def test_rete_giu_resta_un_abort(hass: HomeAssistant, aioclient_mock) -> None:
    """Il vero errore di rete deve continuare ad abortire, non a far riprovare."""
    aioclient_mock.get(f"{BASE_URL}/getComuni.php", json=carica("comuni"))
    aioclient_mock.get(f"{BASE_URL}/getIndirizzi.php", json=carica("indirizzi"))
    aioclient_mock.get(f"{BASE_URL}/getNumeriCivici.php", status=503)

    risultato = await _fino_al_civico(hass, atteso=None)
    assert risultato["type"] is FlowResultType.ABORT
    assert risultato["reason"] == "cannot_connect"


def test_trova_non_pesca_niente_con_una_stringa_vuota() -> None:
    """Il contratto: un valore vuoto non combacia con niente, mai.

    Si prova la funzione da sola e non attraverso il flusso, perche' oggi dal
    flusso non ci si arriva: il parser scarta le voci senza nome, quindi non
    esiste un elemento con cui una stringa vuota possa combaciare. Qui se ne
    costruisce uno a mano - che e' l'unico modo di dire davvero che cosa deve
    succedere se un giorno il gestore mandasse un nome bianco.
    """
    vie = [Via(id=1, nome=""), Via(id=2, nome="VIA VERA")]

    def nomi(via: Via) -> tuple[str, ...]:
        return (via.nome,)

    assert _trova(vie, "", nomi) is None
    assert _trova(vie, "   ", nomi) is None
    # E quello vero si trova lo stesso, comunque lo si scriva.
    assert _trova(vie, "VIA VERA", nomi).id == 2
    assert _trova(vie, "  via vera  ", nomi).id == 2


async def test_il_valore_di_ogni_voce_e_il_testo_che_si_legge(
    hass: HomeAssistant, gestore
) -> None:
    """Il campo, dopo la scelta, mostra il VALORE grezzo dell'opzione.

    Non e' una nostra svista: `ha-picker-field.ts` disegna
    `<span slot="headline">${this.value}</span>` quando nessuno gli passa un
    `valueRenderer`, e il selettore di Home Assistant non gliene passa uno. Con
    l'id del gestore dentro al valore, chi sceglieva "Padova" si ritrovava
    scritto "372" nella casella.

    Quindi l'invariante e' questo, su tutti e tre i passi: valore == etichetta.
    """
    risultato = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    for campo, avanti in (
        ("comune", COMUNE_SCELTO),
        ("via", VIA_SCELTA),
        ("civico", CIVICO_SCELTO),
    ):
        opzioni = risultato["data_schema"].schema[campo].config["options"]
        assert opzioni, campo
        for voce in opzioni:
            assert voce["value"] == voce["label"], (
                f"{campo}: la casella mostrerebbe {voce['value']!r} "
                f"invece di {voce['label']!r}"
            )
            assert not voce["value"].isdigit() or campo == "civico", (
                f"{campo}: {voce['value']!r} e' un numero nudo"
            )
        risultato = await hass.config_entries.flow.async_configure(
            risultato["flow_id"], {campo: avanti}
        )

    assert risultato["type"] is FlowResultType.CREATE_ENTRY
    # E la voce salvata conserva comunque gli ID veri, che sono quelli che
    # servono a chiamare il gestore: a cambiare e' solo cio' che viaggia nel
    # modulo.
    assert risultato["result"].unique_id == f"{COMUNE_ID}-{VIA_ID}-{CIVICO_ID}"
