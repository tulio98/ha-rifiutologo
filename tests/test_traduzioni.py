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
    # `\s*` perche' la chiave d'errore si scrive in due modi: passata al passo
    # successivo - errore="..." - oppure assegnata a una variabile locale
    # quando il modulo si ripresenta da solo - errore = "...". Senza gli spazi
    # il secondo caso non veniva visto, e un testo mancante li' non si sarebbe
    # notato.
    usate |= set(re.findall(r'errore\s*=\s*"(\w+)"', sorgente))
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


def _testi_piani(nodo: dict, prefisso: str = "") -> list[tuple[str, str]]:
    """Tutte le stringhe di un file di traduzione, col loro percorso."""
    fuori: list[tuple[str, str]] = []
    for chiave, valore in nodo.items():
        if isinstance(valore, dict):
            fuori += _testi_piani(valore, prefisso + chiave + ".")
        elif isinstance(valore, str):
            fuori.append((prefisso + chiave, valore))
    return fuori


# Le parole tronche che in italiano vogliono l'accento, non l'apostrofo. Il
# confine a destra e' `(?!\w)` e non `\b`: dopo l'apostrofo c'e' uno spazio o un
# segno, e li' `\b` non combacia - cosi' "e' servito" viene preso e "l'elenco"
# no, che e' esattamente la distinzione che serve.
TRONCHE = re.compile(
    r"\b(?:e|gia|piu|puo|perche|cosi|pero|li|societa|entita|citta|qualita"
    r"|sara|finche|poiche|verra|meta)'(?!\w)"
)


def test_l_italiano_ha_gli_accenti() -> None:
    """I testi che l'utente legge non si scrivono con l'apostrofo al posto dell'accento.

    Nel codice e nei commenti l'apostrofo si usa di proposito, per tenere i
    sorgenti in ASCII puro. Ma questi non sono commenti: sono le frasi che
    compaiono dentro Home Assistant, e li' "e' servito" e' semplicemente
    scritto male.
    """
    sbagliati = [
        (chiave, valore)
        for chiave, valore in _testi_piani(_testi("translations/it.json"))
        if TRONCHE.search(valore)
    ]
    assert not sbagliati, "\n".join(
        f"{c}: {TRONCHE.search(v).group()} in «{v[:70]}»" for c, v in sbagliati
    )
