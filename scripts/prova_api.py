#!/usr/bin/env python3
"""Banco di prova del client, contro l'API vera, senza Home Assistant.

    python3 scripts/prova_api.py Padova "VIA BERNARDO TREVISAN" 8
    python3 scripts/prova_api.py Padova "VIA BERNARDO TREVISAN" 8 --anonimo

Serve a rispondere alla domanda che viene prima di tutte: questo indirizzo ha
davvero la raccolta porta a porta? Circa un indirizzo su tre, a Padova, non ce
l'ha, e in quel caso nessuna integrazione potra' mostrare un calendario.

Con `--anonimo` l'uscita non contiene ne' la via ne' il civico ne' i loro
identificativi, nemmeno quando l'indirizzo non viene trovato e il programma
ripete cio' che hai scritto. Restano il comune e la zona di raccolta, che
servono a capire di quale calendario si sta parlando: e' la forma da allegare
a una segnalazione.

Serve solo aiohttp. Il client viene caricato per percorso, non come parte del
package, proprio per non tirarsi dietro Home Assistant.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, timedelta
import importlib.util
import pathlib
import sys

import aiohttp

RADICE = pathlib.Path(__file__).resolve().parents[1]
_PERCORSO_API = RADICE / "custom_components" / "rifiutologo" / "api.py"

_specifica = importlib.util.spec_from_file_location("rifiutologo_api", _PERCORSO_API)
if _specifica is None or _specifica.loader is None:  # pragma: no cover
    raise SystemExit(f"non trovo il client in {_PERCORSO_API}")
api = importlib.util.module_from_spec(_specifica)
# Va registrato PRIMA di eseguirlo: @dataclass risale a sys.modules per
# risolvere le annotazioni, e senza questa riga muore con un AttributeError
# che non dice niente.
sys.modules["rifiutologo_api"] = api
_specifica.loader.exec_module(api)


def _tipo_finestra(conferimento) -> str:
    """Dice che genere di orario dichiara il gestore per quella frazione."""
    inizio, fine = conferimento.inizio_minuti, conferimento.fine_minuti
    if inizio is None or fine is None:
        return "nessun orario"
    if fine == inizio:
        return "scadenza o apertura (inizio == fine)"
    if fine < inizio:
        return "finestra che scavalca la mezzanotte"
    return "finestra regolare"


async def principale(
    comune_cercato: str, via_cercata: str, civico_cercato: str, *, anonimo: bool
) -> int:
    """Risolve l'indirizzo e stampa il calendario."""

    def riservato(testo: str) -> str:
        """Nasconde cio' che non deve finire in una segnalazione."""
        return "(nascosto)" if anonimo else testo

    async with aiohttp.ClientSession() as sessione:
        client = api.RifiutologoClient(sessione)

        comuni = await client.comuni()
        print(f"comuni serviti: {len(comuni)}")
        comune = next(
            (c for c in comuni if c.nome.casefold() == comune_cercato.casefold()), None
        )
        if comune is None:
            simili = [
                c.nome for c in comuni if comune_cercato.casefold() in c.nome.casefold()
            ]
            print(f"comune '{comune_cercato}' non trovato. Forse: {simili[:10]}")
            return 1
        print(f"comune: {comune.nome} ({comune.provincia}) id={comune.id}")

        vie = await client.vie(comune.id)
        print(f"vie: {len(vie)}")
        via = next(
            (v for v in vie if v.nome.casefold() == via_cercata.casefold()), None
        )
        if via is None:
            # Anche qui passa da `riservato`: e' il caso in cui si apre una
            # segnalazione, e cio' che l'utente ha digitato E' la sua via.
            simili = [
                v.nome for v in vie if via_cercata.casefold() in v.nome.casefold()
            ]
            print(
                f"via '{riservato(via_cercata)}' non trovata. "
                f"Forse: {riservato(str(simili[:10]))}"
            )
            return 1
        print(f"via: {riservato(via.nome)} id={riservato(str(via.id))}")

        civici = await client.civici(comune.id, via.id)
        civico = next((c for c in civici if c.numero == civico_cercato), None)
        if civico is None:
            # L'elenco dei civici di una via e' altrettanto parlante del civico
            # stesso: con `--anonimo` non esce nessuno dei due.
            print(
                f"civico '{riservato(civico_cercato)}' non trovato. Disponibili: "
                f"{riservato(str([c.numero for c in civici][:30]))}"
            )
            return 1
        print(f"civico: {riservato(civico.numero)} id={riservato(str(civico.id))}")

        oggi = date.today()
        calendario = await client.calendario(
            comune.id, via.id, civico.id, da=oggi, giorni=365
        )

        print(f"\nzona: {calendario.zona or 'non dichiarata'}")
        if calendario.allegati and calendario.allegati[0].url:
            print(f"PDF:  {calendario.allegati[0].url}")
        if calendario.nota:
            print(f"nota: {calendario.nota}")

        if not calendario.giorni:
            print(
                "\nNESSUNA RACCOLTA PORTA A PORTA per questo indirizzo.\n"
                "L'indirizzo esiste ma e' servito da cassonetti stradali o isole "
                "ecologiche: il calendario e' vuoto e non e' un errore."
            )
            return 2

        _stampa_calendario(calendario, oggi)
        return 0


def _stampa_calendario(calendario, oggi: date) -> None:
    """Stampa frazioni, orari dichiarati e prossime esposizioni."""
    print(f"\ngiorni di raccolta nei prossimi 365 giorni: {len(calendario.giorni)}")

    frazioni: dict[str, tuple[int, str | None]] = {}
    for giorno in calendario.giorni:
        for conferimento in giorno.conferimenti:
            conteggio, colore = frazioni.get(conferimento.frazione, (0, None))
            frazioni[conferimento.frazione] = (
                conteggio + 1,
                colore or conferimento.colore,
            )
    print("\nfrazioni:")
    for nome, (conteggio, colore) in sorted(frazioni.items(), key=lambda kv: -kv[1][0]):
        print(f"  {nome:28s} {conteggio:4d} volte   colore {colore or '-'}")

    print("\norari dichiarati dal gestore:")
    visti: set[tuple[str | None, str | None, str | None]] = set()
    for giorno in calendario.giorni:
        for conferimento in giorno.conferimenti:
            chiave = (
                conferimento.ora_inizio,
                conferimento.ora_fine,
                conferimento.orario,
            )
            if chiave in visti:
                continue
            visti.add(chiave)
            print(
                f"  {conferimento.ora_inizio or '--:--'} -> "
                f"{conferimento.ora_fine or '--:--'}  "
                f"[{_tipo_finestra(conferimento)}]  {conferimento.orario or ''}"
            )

    print("\nprossime 8 esposizioni:")
    for giorno in calendario.prossimi(oggi)[:8]:
        quando = giorno.giorno - oggi
        etichetta = (
            "STASERA"
            if quando == timedelta(0)
            else "domani"
            if quando == timedelta(days=1)
            else f"fra {quando.days} giorni"
        )
        print(
            f"  {giorno.giorno.isoformat()} ({etichetta:14s}) "
            f"{', '.join(giorno.frazioni)}"
        )


def main() -> int:
    """Legge gli argomenti e lancia la prova."""
    analizzatore = argparse.ArgumentParser(
        description="Prova un indirizzo contro il backend del Rifiutologo."
    )
    analizzatore.add_argument("comune")
    analizzatore.add_argument("via")
    analizzatore.add_argument("civico")
    analizzatore.add_argument(
        "--anonimo",
        action="store_true",
        help="non stampare via, civico e identificativi: da usare nelle segnalazioni",
    )
    argomenti = analizzatore.parse_args()

    try:
        return asyncio.run(
            principale(
                argomenti.comune,
                argomenti.via,
                argomenti.civico,
                anonimo=argomenti.anonimo,
            )
        )
    except api.RifiutologoError as errore:
        print(f"errore: {errore}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
