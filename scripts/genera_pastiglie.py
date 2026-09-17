#!/usr/bin/env python3
"""Genera le pastiglie di colore che il README mostra accanto ai codici.

    python3 scripts/genera_pastiglie.py

GitHub disegna un pallino accanto a `#701100` **solo** dentro issue, pull
request e discussioni: nei file, README compreso, quel codice resta testo (lo
si vede chiedendo a /markdown la resa in `mode=markdown` invece che in
`mode=gfm`). E le immagini `data:` vengono ripulite via. Quindi il quadratino
deve essere un file vero, dentro il repository.

Scrive un PNG per ogni colore citato nel README, in `docs/colori/<ESADECIMALE>.png`:
nessuna dipendenza, il PNG e' scritto a mano con `zlib`, che e' di serie.
"""

from __future__ import annotations

import pathlib
import re
import struct
import zlib

RADICE = pathlib.Path(__file__).resolve().parents[1]
CARTELLA = RADICE / "docs" / "colori"

LATO = 16
BORDO = "#808080"  # un grigio di mezzo: si vede sia sul tema chiaro sia sullo scuro


def _rgb(esadecimale: str) -> tuple[int, int, int]:
    grezzo = esadecimale.lstrip("#")
    return (
        int(grezzo[0:2], 16),
        int(grezzo[2:4], 16),
        int(grezzo[4:6], 16),
    )


def _pezzo(tipo: bytes, dati: bytes) -> bytes:
    return (
        struct.pack(">I", len(dati))
        + tipo
        + dati
        + struct.pack(">I", zlib.crc32(tipo + dati) & 0xFFFFFFFF)
    )


def pastiglia(esadecimale: str, lato: int = LATO) -> bytes:
    """Un quadrato pieno del colore chiesto, con un bordo di un pixel."""
    dentro = _rgb(esadecimale)
    bordo = _rgb(BORDO)
    righe = b""
    for y in range(lato):
        riga = b"\x00"  # filtro 0: la riga e' scritta cosi' com'e'
        for x in range(lato):
            orlo = y in (0, lato - 1) or x in (0, lato - 1)
            riga += bytes(bordo if orlo else dentro)
        righe += riga
    return (
        b"\x89PNG\r\n\x1a\n"
        + _pezzo(b"IHDR", struct.pack(">IIBBBBB", lato, lato, 8, 2, 0, 0, 0))
        + _pezzo(b"IDAT", zlib.compress(righe, 9))
        + _pezzo(b"IEND", b"")
    )


def colori_del_readme() -> list[str]:
    """I colori che il README nomina: la lista non si tiene a mano."""
    testo = (RADICE / "README.md").read_text(encoding="utf-8")
    return sorted(set(re.findall(r"docs/colori/([0-9A-F]{6})\.png", testo)))


def main() -> None:
    """Riscrive tutte le pastiglie che il README nomina."""
    CARTELLA.mkdir(parents=True, exist_ok=True)
    for esadecimale in colori_del_readme():
        percorso = CARTELLA / f"{esadecimale}.png"
        percorso.write_bytes(pastiglia(esadecimale))
        print(f"{percorso.relative_to(RADICE)}  #{esadecimale}")


if __name__ == "__main__":
    main()
