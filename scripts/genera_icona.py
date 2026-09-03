#!/usr/bin/env python3
"""Genera l'icona dell'integrazione.

    python3 scripts/genera_icona.py

Non e' un logo del gestore e non ne imita nessuno: e' una griglia con i colori
che il gestore stesso pubblica per le frazioni, in `pittogramma.colore`, sotto
due anelli che suggeriscono un calendario. Rigenerarla e' un comando; se vuoi
un'altra icona, sostituisci i due PNG o cambia questo script.

Serve Pillow: pip install Pillow
"""

from __future__ import annotations

import pathlib

from PIL import Image, ImageDraw

# I colori veri, cosi' come li restituisce il backend per Padova.
COLORI = [
    "#701100",  # Organico
    "#0093D0",  # Carta
    "#15A53F",  # Imballaggi in vetro
    "#FDB913",  # Lattine e imballaggi in plastica
    "#7C7C81",  # Indifferenziato
    "#E9E4DC",  # la sesta cella: neutra, per non ripetere un colore
]
FONDO = "#1B1D22"
ANELLI = "#E9E4DC"

DESTINAZIONE = (
    pathlib.Path(__file__).resolve().parents[1]
    / "custom_components"
    / "rifiutologo"
    / "brand"
)


def disegna(lato: int) -> Image.Image:
    """Disegna l'icona a un lato dato, lavorando a 4x per i bordi morbidi."""
    scala = 4
    dim = lato * scala
    immagine = Image.new("RGBA", (dim, dim), (0, 0, 0, 0))
    disegno = ImageDraw.Draw(immagine)

    disegno.rounded_rectangle(
        [0, 0, dim - 1, dim - 1], radius=int(dim * 0.22), fill=FONDO
    )

    # I due anelli della rilegatura, in alto.
    raggio = int(dim * 0.035)
    for frazione in (0.34, 0.66):
        centro_x = int(dim * frazione)
        centro_y = int(dim * 0.145)
        disegno.ellipse(
            [
                centro_x - raggio,
                centro_y - raggio,
                centro_x + raggio,
                centro_y + raggio,
            ],
            fill=ANELLI,
        )

    # La griglia 3x2 delle frazioni.
    margine = dim * 0.16
    alto = dim * 0.27
    gioco = dim * 0.045
    larghezza_cella = (dim - 2 * margine - 2 * gioco) / 3
    altezza_cella = (dim - alto - margine - gioco) / 2

    for indice, colore in enumerate(COLORI):
        colonna, riga = indice % 3, indice // 3
        x = margine + colonna * (larghezza_cella + gioco)
        y = alto + riga * (altezza_cella + gioco)
        disegno.rounded_rectangle(
            [x, y, x + larghezza_cella, y + altezza_cella],
            radius=int(larghezza_cella * 0.22),
            fill=colore,
        )

    return immagine.resize((lato, lato), Image.LANCZOS)


def main() -> None:
    """Scrive icon.png e icon@2x.png."""
    DESTINAZIONE.mkdir(parents=True, exist_ok=True)
    for lato, nome in ((256, "icon.png"), (512, "icon@2x.png")):
        percorso = DESTINAZIONE / nome
        disegna(lato).save(percorso, "PNG", optimize=True)
        print(f"{percorso.name}: {lato}x{lato}, {percorso.stat().st_size} byte")


if __name__ == "__main__":
    main()
