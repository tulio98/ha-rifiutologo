#!/usr/bin/env python3
"""Banco di prova del client, contro l'API vera, senza Home Assistant.

    python3 scripts/prova_api.py Padova "VIA BERNARDO TREVISAN" 8

Serve a rispondere alla domanda che viene prima di tutte: questo indirizzo ha
davvero la raccolta porta a porta? Circa un indirizzo su tre, a Padova, non ce
l'ha, e in quel caso nessuna integrazione potra' mostrare un calendario.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from pathlib import Path
import sys

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components"))

from rifiutologo.api import RifiutologoClient, RifiutologoError


async def principale(comune_cercato: str, via_cercata: str, civico_cercato: str) -> int:
    """Risolve l'indirizzo e stampa il calendario."""
    async with aiohttp.ClientSession() as sessione:
        client = RifiutologoClient(sessione)

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
            simili = [
                v.nome for v in vie if via_cercata.casefold() in v.nome.casefold()
            ]
            print(f"via '{via_cercata}' non trovata. Forse: {simili[:10]}")
            return 1
        print(f"via: {via.nome} id={via.id}")

        civici = await client.civici(comune.id, via.id)
        civico = next((c for c in civici if c.numero == civico_cercato), None)
        if civico is None:
            print(
                f"civico '{civico_cercato}' non trovato. Disponibili: "
                f"{[c.numero for c in civici][:30]}"
            )
            return 1
        print(f"civico: {civico.numero} id={civico.id}")

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
        for nome, (conteggio, colore) in sorted(
            frazioni.items(), key=lambda kv: -kv[1][0]
        ):
            print(f"  {nome:28s} {conteggio:4d} volte   colore {colore or '-'}")

        print("\nprossime 8 esposizioni:")
        for giorno in calendario.prossimi(oggi)[:8]:
            primo = giorno.conferimenti[0]
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
            print(
                f"      esposizione {primo.orario or '-'} | "
                f"raccolta {primo.orario_raccolta or '-'}"
            )
        return 0


ARGOMENTI_ATTESI = 4

if __name__ == "__main__":
    if len(sys.argv) != ARGOMENTI_ATTESI:
        print(__doc__)
        raise SystemExit(64)
    try:
        raise SystemExit(asyncio.run(principale(sys.argv[1], sys.argv[2], sys.argv[3])))
    except RifiutologoError as errore:
        print(f"errore: {errore}")
        raise SystemExit(1) from errore
