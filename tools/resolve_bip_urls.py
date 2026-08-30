# -*- coding: utf-8 -*-
"""Mapuje podmioty z data/bip_jst.json na REALNE adresy stron BIP.

Slug z API gov.pl (/gmina-...) to trasa wewnętrznej wyszukiwarki, więc dla
każdego podmiotu pytamy DuckDuckGo o „"<name>" BIP" i przyjmujemy pierwszy
wynik, w którego adresie występuje fragment „bip" (typowe domeny: bip.xxx.pl,
xxx.bip.gov.pl, xxx.pl/bip). Wyniki trafiają do data/bip_jst_urls.json
(mapowanie slug -> url). Narzędzie jest idempotentne: istniejące wpisy są
pomijane, więc można je uruchamiać wielokrotnie aż do pokrycia całości.

Użycie:  python tools/resolve_bip_urls.py [--limit N] [--force]
"""
import json
import os
import re
import sys
import time

from ddgs import DDGS

HERE = os.path.dirname(os.path.abspath(__file__))
REG = os.path.join(HERE, "..", "data", "bip_jst.json")
OUT = os.path.join(HERE, "..", "data", "bip_jst_urls.json")

SKIP_HOSTS = re.compile(
    r"(wikipedia\.|facebook\.|youtube\.|instagram\.|linkedin\.|twitter\.|x\.com|"
    r"google\.|gov\.pl/web/bip/spis|aplikacje\.gov\.pl)", re.I)

BAD_URL = {"https://www.gov.pl", "http://www.gov.pl", "https://gov.pl"}


def normalize(url: str) -> str:
    url = (url or "").strip()
    if not url.startswith("http"):
        url = "https://" + url
    return url.rstrip("/")


def looks_like_bip(url: str) -> bool:
    if not url or url in BAD_URL or SKIP_HOSTS.search(url):
        return False
    # akceptuj tylko adresy, w których faktycznie występuje "bip"
    return bool(re.search(r"(^|\.)bip[.-]|/bip(/|$)|bip\.gov\.pl", url, re.I))


def main() -> None:
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 0
    force = "--force" in sys.argv

    registry = json.load(open(REG, encoding="utf-8"))
    try:
        mapping = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        mapping = {}

    todo = [r for r in registry
            if force or r["slug"] not in mapping or not mapping[r["slug"]]]
    if limit:
        todo = todo[:limit]
    print(f"registry={len(registry)} resolved={sum(1 for v in mapping.values() if v)} "
          f"todo={len(todo)}", flush=True)

    found = 0
    with DDGS() as ddgs:
        for i, r in enumerate(todo, 1):
            name = r["name"]
            query = f'"{name}" BIP'
            url = ""
            try:
                for res in ddgs.text(query, region="pl-pl", max_results=5):
                    cand = normalize(res.get("href") or res.get("url") or "")
                    if looks_like_bip(cand):
                        url = cand
                        break
            except Exception as exc:
                print(f"[{i}] ERR {name}: {exc}", flush=True)
                time.sleep(3)
                continue
            mapping[r["slug"]] = url
            if url:
                found += 1
            if i % 25 == 0:
                print(f"[{i}/{len(todo)}] found_so_far={found}", flush=True)
                json.dump(mapping, open(OUT, "w", encoding="utf-8"),
                          ensure_ascii=False, indent=0)
            time.sleep(1.5)

    json.dump(mapping, open(OUT, "w", encoding="utf-8"),
              ensure_ascii=False, indent=0)
    resolved = sum(1 for v in mapping.values() if v)
    print(f"DONE resolved={resolved}/{len(registry)} new={found}", flush=True)


if __name__ == "__main__":
    main()
