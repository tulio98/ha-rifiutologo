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
    voce.add_to_hass(hass)
    assert await hass.config_entries.async_setup(voce.entry_id)
    await hass.async_block_till_done()

    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{voce.entry_id}_settimana"
    )
    assert entity_id is not None

    blocco = next(b for b in _blocchi("yaml") if "raccolte_in_settimana" in b)
    contenuto = yaml.safe_load(blocco)["content"].replace(
        "sensor.CAMBIAMI_raccolte_in_settimana", entity_id
    )
    reso = Template(contenuto, hass).async_render(parse_result=False)

    assert "Da qui a domenica: 4 sere" in reso
    assert "**gio 03**" in reso, f"il giorno non e' stato reso:\n{reso}"
    assert "**dom 06**" in reso
    assert "Indifferenziato, Organico" in reso
    assert "Undefined" not in reso, f"un attributo non esiste piu':\n{reso}"
