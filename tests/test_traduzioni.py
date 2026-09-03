"""Test dei file di traduzione: una chiave mancante non da' errore, mostra la chiave.

E' il genere di difetto che non si vede mai in sviluppo e che l'utente incontra
sempre, perche' capita solo sui rami di errore.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

RADICE = (
    pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "rifiutologo"
)
FILE_TESTI = ("strings.json", "translations/en.json", "translations/it.json")


def _testi(nome: str) -> dict:
    """Legge uno dei file di traduzione."""
    return json.loads((RADICE / nome).read_text(encoding="utf-8"))


def _chiavi(albero: dict, prefisso: str = "") -> set[str]:
    """Tutte le chiavi annidate, con il loro percorso."""
    trovate: set[str] = set()
    for chiave, valore in albero.items():
        trovate.add(prefisso + chiave)
        if isinstance(valore, dict):
            trovate |= _chiavi(valore, prefisso + chiave + ".")
    return trovate


@pytest.mark.parametrize("nome", FILE_TESTI)
def test_errori_e_abort_hanno_un_testo(nome: str) -> None:
    """Ogni errore e ogni abort che il codice puo' produrre deve avere un testo."""
    sorgente = (RADICE / "config_flow.py").read_text(encoding="utf-8")

    usate = set(re.findall(r'"base"\]?\s*[:=]\s*"(\w+)"', sorgente))
    usate |= set(re.findall(r'errore="(\w+)"', sorgente))
    aborti = set(re.findall(r'async_abort\(reason="(\w+)"\)', sorgente))
    # Questi due li produce Home Assistant per conto suo, ma il testo lo mette
    # l'integrazione: per una custom non c'e' nessun testo di serie.
    aborti |= {"already_configured", "reconfigure_successful"}

    testi = _testi(nome)
    assert usate, "il controllo non sta leggendo niente: regex da rivedere"
    assert not usate - set(testi["config"]["error"]), "errori senza testo"
    assert not aborti - set(testi["config"]["abort"]), "abort senza testo"
    assert not set(testi["config"]["error"]) - usate, "testi di errore mai usati"


def test_le_tre_lingue_hanno_le_stesse_chiavi() -> None:
    """Un testo che esiste in una lingua sola e' un buco che si vede solo li'."""
    riferimento = _chiavi(_testi("translations/en.json"))
    for nome in FILE_TESTI:
        assert _chiavi(_testi(nome)) == riferimento, f"{nome} non e' allineato"


def test_le_entita_hanno_tutte_un_nome() -> None:
    """Ogni translation_key usata dal codice deve avere un nome tradotto."""
    usate: set[str] = set()
    for sorgente in RADICE.glob("*.py"):
        testo = sorgente.read_text(encoding="utf-8")
        piattaforma = sorgente.stem
        for chiave in re.findall(r'_attr_translation_key = "(\w+)"', testo):
            usate.add(f"{piattaforma}.{chiave}")

    for nome in FILE_TESTI:
        entita = _testi(nome)["entity"]
        presenti = {
            f"{piattaforma}.{chiave}"
            for piattaforma, voci in entita.items()
            for chiave in voci
        }
        assert usate == presenti, f"{nome}: {usate ^ presenti}"


def test_le_icone_corrispondono_a_entita_vere() -> None:
    """Una voce di icons.json per un'entita' inesistente non si accorge nessuno."""
    icone = json.loads((RADICE / "icons.json").read_text(encoding="utf-8"))["entity"]
    nomi = _testi("translations/it.json")["entity"]
    for piattaforma, voci in icone.items():
        assert set(voci) <= set(nomi.get(piattaforma, {})), (
            f"icons.json dichiara {piattaforma} inesistenti"
        )
