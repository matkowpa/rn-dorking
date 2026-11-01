# -*- coding: utf-8 -*-
"""Buduje pełną listę gmin (data/gminy_teryt.json) z rejestru TERC GUS.

Źródło: plik TERC_Urzedowy.csv (stan 2026-01-01) z mirrora
https://github.com/janekolszak/poland (kopia oficjalnego TERYT GUS).
Lista zawiera 2479 gmin; rejestr BIP gov.pl (data/bip_jst.json) ma ich
mniej, bo obejmuje tylko podmioty z BIP-em na gov.pl.
"""
import csv
import io
import json
import os
import urllib.request

URL = ("https://raw.githubusercontent.com/janekolszak/poland/main/"
       "data/2026-07-22/TERC_Urzedowy.csv")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "data", "gminy_teryt.json")


def main() -> None:
    raw = urllib.request.urlopen(URL, timeout=60).read().decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(raw), delimiter=";"))
    woj = {r["WOJ"]: r["NAZWA"].title() for r in rows
           if r["WOJ"] and not r["POW"] and not r["GMI"]}
    powi = {(r["WOJ"], r["POW"]): r["NAZWA"].title() for r in rows
            if r["POW"] and not r["GMI"]}
    out = []
    for r in rows:
        if not (r["GMI"] and r["RODZ"] in ("1", "2", "3")):
            continue
        out.append({
            "teryt": r["WOJ"] + r["POW"] + r["GMI"],
            "name": r["NAZWA"],
            "type": r["NAZWA_DOD"],
            "voivodeship": woj.get(r["WOJ"], ""),
            "powiat": powi.get((r["WOJ"], r["POW"]), ""),
            "gmina_type": r["RODZ"],
        })
    assert len(out) == 2479, len(out)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=0)
    print(f"zapisano {len(out)} gmin -> {OUT}")


if __name__ == "__main__":
    main()
