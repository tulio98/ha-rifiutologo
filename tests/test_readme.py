"""Test del README: le promesse che fa devono essere vere.

Un README e' la prima cosa che la gente legge e l'ultima che qualcuno verifica.
Qui gli esempi passano dal validatore VERO di Home Assistant, e le affermazioni
sulle entita' e sugli attributi vengono confrontate con il codice.
"""

from __future__ import annotations

from datetime import datetime
import json
import pathlib
import re
import struct
import zlib
from zoneinfo import ZoneInfo

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import yaml

from custom_components.rifiutologo.const import DOMAIN
from homeassistant.components.automation import config as validazione_automazioni
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.template import Template

RADICE = pathlib.Path(__file__).resolve().parents[1]
README = (RADICE / "README.md").read_text(encoding="utf-8")


def _blocchi(linguaggio: str) -> list[str]:
    """I blocchi di codice del README, per linguaggio."""
    return re.findall(rf"```{linguaggio}\n(.*?)```", README, re.DOTALL)


@pytest.fixture(autouse=True)
def _carica_integrazione(enable_custom_integrations: None) -> None:
    """Serve a caricare le piattaforme referenziate dagli esempi."""


def test_ci_sono_esempi_da_verificare() -> None:
    """Se l'estrazione smette di trovare blocchi, il resto dei test mente."""
    assert len(_blocchi("yaml")) >= 4


async def test_le_automazioni_sono_valide(hass: HomeAssistant) -> None:
    """Ogni automazione del README deve passare il validatore di Home Assistant.

    E' il controllo che avrebbe evitato di pubblicare una condizione `state` con
    `above:`, che Home Assistant rifiuta.
    """
    trovate = 0
    for blocco in _blocchi("yaml"):
        contenuto = yaml.safe_load(blocco)
        if not isinstance(contenuto, dict) or "automation" not in contenuto:
            continue
        for indice, automazione in enumerate(contenuto["automation"]):
            trovate += 1
            validata = await validazione_automazioni.async_validate_config_item(
                hass, f"automation {indice}", automazione
            )
            assert validata is not None, (
                f"Home Assistant rifiuta l'automazione '{automazione.get('alias')}'"
            )
    assert trovate >= 3, "le automazioni del README non vengono trovate"


async def test_le_card_sono_yaml_valido() -> None:
    """Le card devono almeno essere YAML ben formato con un tipo."""
    for blocco in _blocchi("yaml"):
        contenuto = yaml.safe_load(blocco)
        if isinstance(contenuto, dict) and "type" in contenuto:
            assert contenuto["type"]
            return
    pytest.fail("nessuna card trovata nel README")


def _stringhe(nodo: object) -> list[str]:
    """Tutte le stringhe dentro una struttura YAML, a qualsiasi profondita'."""
    if isinstance(nodo, str):
        return [nodo]
    if isinstance(nodo, dict):
        return [t for v in nodo.values() for t in _stringhe(v)]
    if isinstance(nodo, list):
        return [t for v in nodo for t in _stringhe(v)]
    return []


async def test_i_template_del_readme_compilano(hass: HomeAssistant) -> None:
    """Un template rotto nel README si scopre solo quando lo incolla qualcuno.

    Si valida il template INTERO, non i frammenti: un `{% if %}` da solo non e'
    valido, e spezzarlo darebbe un errore che non esiste.
    """
    trovati = 0
    for blocco in _blocchi("yaml"):
        for testo in _stringhe(yaml.safe_load(blocco)):
            if "{{" not in testo and "{%" not in testo:
                continue
            trovati += 1
            Template(testo, hass).ensure_valid()
    assert trovati >= 4, "i template del README non vengono trovati"


def test_la_card_markdown_conserva_gli_a_capo() -> None:
    """Con `>-` il markdown finisce tutto su una riga e i titoli non si vedono."""
    for blocco in _blocchi("yaml"):
        if "type: markdown" in blocco:
            assert "content: |-" in blocco, "serve uno scalare literal, non `>-`"
            return
    pytest.fail("nessuna card markdown nel README")


def test_i_comuni_citati_sono_veri() -> None:
    """Il README non deve promettere comuni che il gestore non serve.

    L'elenco di confronto e' la fixture, che e' una risposta vera di getComuni.
    Qui si controllano i nomi della tabella "Chi e' coperto".
    """
    fixture = json.loads(
        (RADICE / "tests" / "fixtures" / "comuni.json").read_text(encoding="utf-8")
    )
    noti = {c["name"] for c in fixture}

    # Della tabella si controllano solo i nomi presenti nella fixture ridotta:
    # gli altri sono verificati contro l'API viva, non qui.
    citati = set(re.findall(r"\b(Padova|Bologna|Faenza|Trieste|Abano Terme)\b", README))
    assert citati, "il controllo non sta leggendo la tabella"
    assert citati <= noti, f"comuni citati ma inesistenti: {citati - noti}"

    # E i tre che NON esistono non devono comparire come promessa. "Forlì" va
    # cercato da solo: dentro "Forlì-Cesena" e' il nome della provincia, che il
    # gestore serve davvero (Cesena, Cesenatico, Gambettola...).
    for inesistente, schema in (
        ("Forlì", r"\bForlì\b(?!-)"),
        ("Fano", r"\bFano\b"),
        ("Selvazzano Dentro", r"\bSelvazzano Dentro\b"),
    ):
        for riga in README.splitlines():
            if re.search(schema, riga):
                assert "non ci sono" in riga, (
                    f"{inesistente} non e' servito dal gestore: va detto, non promesso"
                )


def test_le_entita_promesse_esistono() -> None:
    """Ogni entita' nominata nella tabella deve esistere davvero nel codice."""
    testi = json.loads(
        (
            RADICE / "custom_components" / "rifiutologo" / "translations" / "it.json"
        ).read_text(encoding="utf-8")
    )
    nomi = {
        voce["name"]
        for piattaforma in testi["entity"].values()
        for voce in piattaforma.values()
    }
    for nome in nomi:
        assert f"**{nome}**" in README, f"l'entita' «{nome}» non e' documentata"


def test_gli_attributi_promessi_esistono() -> None:
    """La tabella degli attributi deve corrispondere a quello che il codice produce."""
    sorgente = (RADICE / "custom_components" / "rifiutologo" / "entity.py").read_text(
        encoding="utf-8"
    )
    prodotti = set(re.findall(r'^\s{8}"(\w+)":', sorgente, re.M))
    assert prodotti, "il controllo non sta leggendo attributi_giorno"
    for attributo in prodotti:
        assert f"`{attributo}`" in README, f"attributo non documentato: {attributo}"


async def test_la_card_della_settimana_si_disegna(
    hass: HomeAssistant, gestore, voce: MockConfigEntry, freezer
) -> None:
    """Il template della settimana va RESO con dati veri, non solo compilato.

    `ensure_valid` dice che la sintassi sta in piedi; non dice che
    `giorno_settimana` esista davvero fra gli attributi. Se un attributo cambia
    nome, la card del README diventa una tabella di vuoti e nessun altro
    controllo se ne accorge.
    """
    freezer.move_to(datetime(2026, 9, 3, 18, 0, tzinfo=ZoneInfo("Europe/Rome")))
    await hass.config.async_set_time_zone("Europe/Rome")
    # Il README e' in italiano, e le etichette dei giorni seguono la lingua di
    # Home Assistant: senza questa riga il controllo girerebbe in inglese e
    # direbbe che la card e' rotta quando invece e' giusta.
    await hass.config.async_update(language="it")
    voce.add_to_hass(hass)
    assert await hass.config_entries.async_setup(voce.entry_id)
    await hass.async_block_till_done()

    entity_id = er.async_get(hass).async_get_entity_id(
        "calendar", DOMAIN, f"{voce.entry_id}_calendario"
    )
    assert entity_id is not None

    blocco = next(
        b for b in _blocchi("yaml") if "type: markdown" in b and "'calendario'" in b
    )
    contenuto = yaml.safe_load(blocco)["content"].replace(
        "calendar.CAMBIAMI_calendario_esposizioni", entity_id
    )
    reso = Template(contenuto, hass).async_render(parse_result=False)

    assert "Questa settimana" in reso
    assert "**gio 03/09**" in reso, f"il giorno non e' stato reso:\n{reso}"
    assert "**dom 06/09**" in reso
    assert "Indifferenziato, Organico" in reso
    assert "Undefined" not in reso, f"un attributo non esiste piu':\n{reso}"


def _decodifica_png(grezzo: bytes) -> tuple[int, int, list[list[tuple[int, ...]]]]:
    """Un lettore PNG scritto da capo, per non verificare il generatore con se stesso.

    Regge tutti e cinque i filtri di riga, anche se il generatore usa solo lo
    zero: se un domani scrivesse i PNG in un altro modo, questo li leggerebbe
    lo stesso, e il test resterebbe un controllo vero.
    """
    assert grezzo[:8] == b"\x89PNG\r\n\x1a\n", "non e' un PNG"
    intestazione = b""
    compressi = b""
    i = 8
    while i < len(grezzo):
        (lunghezza,) = struct.unpack(">I", grezzo[i : i + 4])
        tipo = grezzo[i + 4 : i + 8]
        corpo = grezzo[i + 8 : i + 8 + lunghezza]
        (firma,) = struct.unpack(">I", grezzo[i + 8 + lunghezza : i + 12 + lunghezza])
        assert zlib.crc32(tipo + corpo) & 0xFFFFFFFF == firma, f"CRC rotto in {tipo!r}"
        if tipo == b"IHDR":
            intestazione = corpo
        elif tipo == b"IDAT":
            compressi += corpo
        i += 12 + lunghezza

    larghezza, altezza, profondita, colore, _, _, intreccio = struct.unpack(
        ">IIBBBBB", intestazione
    )
    assert (profondita, colore, intreccio) == (8, 2, 0), (
        "atteso RGB a 8 bit, non intrecciato"
    )

    canali = 3
    passo = larghezza * canali
    crudo = zlib.decompress(compressi)
    precedente = bytearray(passo)
    pixel: list[list[tuple[int, ...]]] = []
    letti = 0
    for _ in range(altezza):
        filtro = crudo[letti]
        letti += 1
        riga = bytearray(crudo[letti : letti + passo])
        letti += passo
        for x in range(passo):
            a = riga[x - canali] if x >= canali else 0
            b = precedente[x]
            c = precedente[x - canali] if x >= canali else 0
            if filtro == 0:
                aggiunta = 0
            elif filtro == 1:
                aggiunta = a
            elif filtro == 2:
                aggiunta = b
            elif filtro == 3:
                aggiunta = (a + b) // 2
            elif filtro == 4:
                da, db, dc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                aggiunta = a if (da <= db and da <= dc) else (b if db <= dc else c)
            else:
                raise AssertionError(f"filtro sconosciuto: {filtro}")
            riga[x] = (riga[x] + aggiunta) & 0xFF
        pixel.append([tuple(riga[x : x + canali]) for x in range(0, passo, canali)])
        precedente = riga
    return larghezza, altezza, pixel


def test_la_tabella_dei_colori_dice_il_vero() -> None:
    """I colori del README sono quelli del gestore, non scelti da noi.

    Il confronto e' con la fixture, che e' una risposta vera del backend per
    l'indirizzo di prova: ogni riga della tabella deve ritrovarsi li'.
    """
    fixture = json.loads(
        (RADICE / "tests" / "fixtures" / "calendario.json").read_text(encoding="utf-8")
    )
    veri: dict[str, str] = {}

    def cammina(nodo: object) -> None:
        if isinstance(nodo, dict):
            # La frazione e' `macroprodotto.descrizione`, e il colore sta nel
            # pittogramma dello stesso nodo: cosi' li legge anche api.py.
            pittogramma = nodo.get("pittogramma")
            if isinstance(pittogramma, dict) and nodo.get("descrizione"):
                veri[str(nodo["descrizione"])] = str(pittogramma["colore"]).upper()
            for valore in nodo.values():
                cammina(valore)
        elif isinstance(nodo, list):
            for valore in nodo:
                cammina(valore)

    cammina(fixture)
    assert veri, "la fixture non ha piu' i pittogrammi: non si sta guardando niente"

    righe = re.findall(
        r"^\| ([^|]+?) \| !\[\]\(docs/colori/([0-9A-F]{6})\.png\) `#([0-9A-F]{6})` \|$",
        README,
        re.M,
    )
    assert len(righe) == len(veri), (
        f"la tabella ha {len(righe)} frazioni, il gestore ne da {len(veri)}"
    )
    for frazione, pastiglia, codice in righe:
        assert pastiglia == codice, (
            f"{frazione}: il quadratino mostra #{pastiglia} ma il codice dice #{codice}"
        )
        assert veri.get(frazione) == codice, (
            f"{frazione}: il README dice #{codice}, il gestore #{veri.get(frazione)}"
        )


def test_ogni_pastiglia_e_davvero_di_quel_colore() -> None:
    """Il quadratino accanto al codice deve essere proprio quel colore.

    GitHub disegna il pallino accanto a `#701100` solo dentro issue e pull
    request, non nei file: nel README il quadratino e' un PNG vero, e un PNG
    vero puo' sbagliare colore in silenzio.
    """
    codici = sorted(set(re.findall(r"docs/colori/([0-9A-F]{6})\.png", README)))
    assert codici, "il README non mostra piu' nessuna pastiglia"

    for codice in codici:
        percorso = RADICE / "docs" / "colori" / f"{codice}.png"
        assert percorso.is_file(), f"il README mostra {percorso.name}, che non esiste"
        larghezza, altezza, pixel = _decodifica_png(percorso.read_bytes())
        atteso = (int(codice[0:2], 16), int(codice[2:4], 16), int(codice[4:6], 16))
        dentro = {
            pixel[y][x] for y in range(1, altezza - 1) for x in range(1, larghezza - 1)
        }
        assert dentro == {atteso}, f"{percorso.name} non e' #{codice} ma {dentro}"


def test_le_immagini_del_readme_esistono() -> None:
    """Un'immagine rotta nel README si vede solo su GitHub, e troppo tardi."""
    percorsi = [
        p
        for p in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", README)
        if not p.startswith(("http://", "https://"))
    ]
    assert percorsi, "il README non ha piu' immagini locali"
    mancanti = [p for p in percorsi if not (RADICE / p).is_file()]
    assert not mancanti, f"immagini citate ma assenti: {mancanti}"
