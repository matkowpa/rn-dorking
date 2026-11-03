# -*- coding: utf-8 -*-
"""Buduje rejestr SEKCJI ogłoszeń na stronach BIP (`data/bip_sections.json`).

Dlaczego: strona główna BIP-u to zwykle "dane podstawowe" + menu podmiotowe, a
ogłoszenia o naborach leżą w dziale typu "Nabory"/"Ogłoszenia o naborze".
Dotychczasowy skan brał stronę główną i dwie podstrony wybrane po wzorcu URL,
co w praktyce trafiało w "aktualności" (tam nie ma naborów) - stąd zero
kandydatów z JST przez 66 dni.

Jak wybieramy sekcję: po TEKŚCIE kotwicy ("nabór", "nabory", "konkurs",
"ogłoszenia o naborze"), a nie po adresie - systemy BIP mają różne schematy
URL. Kandydat jest przyjmowany, gdy po pobraniu ma co najmniej jeden wpis
(kotwica z tymi samymi słowami albo adres wyglądający na ogłoszenie).
Zapisywany jest kandydat z największą liczbą wpisów.

Użycie:
    python tools/discover_sections.py                 # brakujące wpisy
    python tools/discover_sections.py --limit 200     # partia
    python tools/discover_sections.py --refresh       # przebadaj ponownie
    python tools/discover_sections.py --dry-run       # raport bez zapisu
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import date
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)

import direct_sources as ds  # noqa: E402

OUT = os.path.join(ROOT, "data", "bip_sections.json")

# Kotwice sekcji ogłoszeń. "praca" bywa zbyt szeroka, więc jej nie ma.
SECTION_TEXT_RE = re.compile(
    r"nab[oó]r|naboru|nabory|konkurs|ogłoszen\w*\s+o\s+naborz|ogloszen\w*\s+o\s+naborz",
    re.I)
# Sekcje, które wyglądają podobnie, ale nie mają naborów na stanowiska:
# dotacje, zlecanie zadań publicznych, przetargi.
NOT_RECRUITMENT_RE = re.compile(
    r"konkurs\w*\s+ofert|zada[nń]\s+publiczn|dotacj|przetarg|zam[oó]wien", re.I)
NABOR_RE = re.compile(r"nab[oó]r|naboru|nabory", re.I)

MAX_CANDIDATES = 4          # ile sekcji testować na podmiot


def _candidates(soup, base_url: str) -> list[tuple[str, str]]:
    """(tekst, url) linków-sekcji na tej samej domenie, bez duplikatów."""
    base_host = urlparse(base_url).netloc.lower()
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        if not text or len(text) > 80 or not SECTION_TEXT_RE.search(text):
            continue
        if NOT_RECRUITMENT_RE.search(text):
            continue
        url = urljoin(base_url, a["href"].strip())
        if not url.startswith("http"):
            continue
        if urlparse(url).netloc.lower() != base_host:
            continue
        if url.rstrip("/") == base_url.rstrip("/") or url in seen:
            continue
        seen.add(url)
        out.append((text, url))
    return out


def _count_items(html: str) -> int:
    """Ile wpisów (ogłoszeń) jest na stronie sekcji."""
    soup = BeautifulSoup(html, "html.parser")
    n = 0
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        if SECTION_TEXT_RE.search(text) or ds.looks_like_notice_url(
                urljoin("https://x/", a["href"].strip())):
            n += 1
    return n


def discover_section(url: str) -> dict | None:
    """Znajduje sekcję ogłoszeń dla podmiotu. Zwraca wpis rejestru lub None.

    Wymagamy tylko tej samej domeny co strona główna: sprawdzanie nazwy
    podmiotu w treści sekcji odrzucało prawdziwe trafienia (np. BIP Mińska
    Mazowieckiego nie powtarza nazwy w nagłówku działu). Adres podmiotu
    waliduje już resolver (tools/resolve_bip_urls.py), więc tutaj ufamy domenie.
    """
    html = ds._fetch_html(url)
    if not html:
        return None
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return None
    best, best_score = None, (-1, -1)
    for text, cand_url in _candidates(soup, url)[:MAX_CANDIDATES]:
        sub_html = ds._fetch_html(cand_url)
        if not sub_html:
            continue
        items = _count_items(sub_html)
        if not items:
            continue
        # Sekcja z "nabór" w nazwie jest więcej warta niż ogólne "konkursy".
        score = (1 if NABOR_RE.search(text) else 0, items)
        if best is None or score > best_score:
            best = {"url": cand_url, "items": items, "label": text[:80]}
            best_score = score
    if not best:
        return None
    best["checked"] = date.today().isoformat()
    return best


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--delay", type=float, default=0.4)
    args = ap.parse_args(argv)

    registry = ds._load_jst_registry()
    urls_map = ds._load_jst_urls()
    for e in registry:
        real = urls_map.get(e.get("slug", ""))
        if real:
            e["url"] = real
    pool = [e for e in registry
            if e.get("url") and e["url"].rstrip("/") not in ds.BAD_URLS
            and not ds.is_portal_url(e["url"])]

    try:
        sections = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        sections = {}

    todo = [e for e in pool
            if args.refresh or not (sections.get(e.get("slug")) or {}).get("url")]
    if args.limit:
        todo = todo[:args.limit]
    print(f"pula={len(pool)} z-sekcją={len(sections)} todo={len(todo)}", flush=True)

    found = 0
    for i, entry in enumerate(todo, 1):
        result = discover_section(entry["url"])
        if result:
            found += 1
            sections[entry.get("slug") or entry["url"]] = result
            label = f"{result['label']} ({result['items']} poz.)"
        else:
            label = "-"
        print(f"[{i}/{len(todo)}] {'SEK' if result else ' --'} {entry['name'][:36]:36} | {label}",
              flush=True)
        if i % 20 == 0 and not args.dry_run:
            _write(sections)
        time.sleep(args.delay)

    if not args.dry_run:
        _write(sections)
    with_items = sum(1 for v in sections.values() if v.get("url"))
    print(f"DONE sekcje={with_items} nowe={found} (na {len(todo)} sprawdzonych)", flush=True)
    return 0


def _write(sections: dict) -> None:
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sections, f, ensure_ascii=False, indent=0, sort_keys=True)
    os.replace(tmp, OUT)


if __name__ == "__main__":
    sys.exit(main())
