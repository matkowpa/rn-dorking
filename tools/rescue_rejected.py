#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ratunek zagubionych ogłoszeń (Etap 2, naprawa danych).

Przepuszcza przez potok ogłoszenia, które stary prefiltr odrzucił fałszywie
(fraza "kurs" łapiąca "konkurs", "egzamin" w wymaganiach). Nowy filtr je
przepuszcza; LLM ekstrahuje pola; wyniki dopisują się do oferty.json i
plików dnia, a build_docs.py odbudowuje docs/data dla strony.

Tryby:
  --list           tylko wypisz kandydatów (bez LLM, bez zapisu)
  --apply          przepuść przez LLM i zapisz (wymaga LLM_API_KEY w .env)
  --dry-run        jak --apply, ale bez zapisu (podgląd ekstrakcji)

Wykorzystuje moduły projektu: heuristics, content_fetcher, llm_parser, storage.
"""

import argparse
import json
import os
import sys
import time
from datetime import date

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from heuristics import prefilter_reject
from content_fetcher import fetch_content
from llm_parser import extract_fields, filter_is_announcement
from storage import Storage

ODRZUCONE_GLOB = "data/dnia/odrzucone-*.json"


def znajdz_zagubione() -> list[dict]:
    """Odrzucone, które NOWY prefiltr przepuszcza + wyglądają na realny nabór."""
    import glob
    out = []
    seen = set()
    for path in sorted(glob.glob(ODRZUCONE_GLOB)):
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        for x in d.get("rejected", []):
            t = x.get("title") or x.get("tytul") or ""
            s = x.get("snippet") or ""
            u = x.get("url") or ""
            if not u or u in seen:
                continue
            seen.add(u)
            rej, _ = prefilter_reject(t, s, u)
            if rej:
                continue  # nowy filtr nadal odrzuca - pomijamy
            tl = t.lower()
            is_rn = ("rady nadzorczej" in tl or "rada nadzorcza" in tl or
                     "członek rady" in tl or "członków rady" in tl or
                     "członka rady" in tl)
            is_nabor = any(k in tl for k in ("nabór", "naborze", "naboru", "ogłoszenie", "postępowanie kwalifikacyjne"))
            if is_rn and is_nabor:
                out.append({
                    "title": t, "url": u,
                    "odrzucono_dnia": path.split("odrzucone-")[1].replace(".json", ""),
                })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Ratunek zagubionych ogłoszeń")
    ap.add_argument("--list", action="store_true", help="tylko lista kandydatów")
    ap.add_argument("--apply", action="store_true", help="LLM ekstrakcja + zapis")
    ap.add_argument("--dry-run", action="store_true", help="LLM ekstrakcja bez zapisu")
    args = ap.parse_args()

    kandydaci = znajdz_zagubione()
    print(f"Kandydatów do ratunku: {len(kandydaci)}\n")

    if args.list or not (args.apply or args.dry_run):
        for k in kandydaci:
            print(f"[{k['odrzucono_dnia']}] {k['title'][:80]}")
            print(f"    {k['url']}")
        return 0

    # --- tryb apply/dry-run: wymaga .env z LLM_* ---
    try:
        config.validate()
    except ValueError as e:
        print(f"BLAD: {e}\n(Utwórz .env z LLM_API_KEY/LLM_BASE_URL/LLM_MODEL)", file=sys.stderr)
        return 1

    from storage import Storage
    storage = Storage()
    added, skipped, failed = 0, 0, 0

    for i, k in enumerate(kandydaci, 1):
        url = k["url"]
        print(f"[{i}/{len(kandydaci)}] {k['title'][:70]}")
        if not storage.is_new(url):
            print("    już w historii - pomijam")
            skipped += 1
            continue
        text, _ = fetch_content(url)
        if not text:
            print("    brak treści (strona nieosiągalna) - pomijam")
            failed += 1
            time.sleep(0.5)
            continue
        try:
            czy_nabor, uzasadnienie = filter_is_announcement(k["title"], text[:2000], url)
        except Exception as e:
            print(f"    LLM filter błąd: {e}")
            failed += 1
            continue
        if not czy_nabor:
            print(f"    LLM odrzuca: {uzasadnienie[:80]}")
            skipped += 1
            time.sleep(0.5)
            continue
        offer = extract_fields(text, url)
        if not offer:
            print("    ekstrakcja bez rezultatu")
            failed += 1
            time.sleep(0.5)
            continue
        offer.setdefault("url", url)
        offer.setdefault("znaleziono_dnia", date.today().isoformat())
        if args.dry_run:
            print(f"    [DRY] podmiot={offer.get('podmiot','')[:50]} termin={offer.get('termin_skladania_ofert','')}")
        else:
            if storage.is_new(url):
                storage.add_offer(offer)
                print(f"    DODANO: {offer.get('podmiot','')[:50]} termin={offer.get('termin_skladania_ofert','')}")
                added += 1
            else:
                skipped += 1
        time.sleep(1)

    if args.apply and added:
        storage.save()
        print(f"\nZapisano oferty.json + stan.json (dodano {added})")
        print("Uruchom teraz: python build_docs.py  (odbudowa docs/data dla strony)")

    print(f"\nPODSUMOWANIE: dodano={added} pominięto={skipped} błędy={failed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
