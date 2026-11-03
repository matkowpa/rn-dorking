# -*- coding: utf-8 -*-
"""Mapuje podmioty z rejestru BIP na REALNE adresy stron BIP.

Dwa źródła wejściowe:
- `data/bip_jst.json` - rejestr podmiotów z API gov.pl. Slug z API
  (/gmina-...) to trasa wewnętrznej wyszukiwarki portalu, nie BIP, więc dla
  każdego podmiotu szukamy realnego adresu.
- `data/gminy_teryt.json` - pełna lista 2479 gmin (TERC GUS). Wpisy nie mają
  adresu, więc rejestr JST dopisuje je jako `teryt-<TERC>`; tutaj szukamy dla
  nich BIP-u po nazwie + powiecie (bez tego 2346 gmin nigdy nie jest
  skanowanych, co daje 2,6% pokrycia).

Walidacja kandydata (bez tego mapowanie łapie złe gminy o tej samej nazwie):
pobieramy stronę i wymagamy kodu 200 ORAZ nazwy podmiotu w treści/URL-u.
Dodatkowo zapisujemy, czy strona ma dział ogłoszeń (diagnostyka pokrycia).

Wyszukiwarka: Brave, gdy jest `BRAVE_API_KEY` (produkcja, ~1 zapytanie/s),
inaczej DuckDuckGo. Wyniki trafiają do `data/bip_jst_urls.json`
(slug -> url). Narzędzie jest idempotentne i wznawialne: istniejące wpisy są
pomijane, można je uruchamiać partiami (`--limit`).

Użycie:
    python tools/resolve_bip_urls.py                  # brakujące wpisy gov.pl
    python tools/resolve_bip_urls.py --teryt-only     # tylko gminy z TERYT
    python tools/resolve_bip_urls.py --limit 400      # partia (quota Brave)
    python tools/resolve_bip_urls.py --dry-run        # raport bez zapisu
"""

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from urllib.parse import urlparse

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)

REG = os.path.join(ROOT, "data", "bip_jst.json")
TERYT = os.path.join(ROOT, "data", "gminy_teryt.json")
OUT = os.path.join(ROOT, "data", "bip_jst_urls.json")

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) rn-dorking/3.1"}

SKIP_HOSTS = re.compile(
    r"(wikipedia\.|facebook\.|youtube\.|instagram\.|linkedin\.|twitter\.|x\.com|"
    r"google\.|aplikacje\.gov\.pl)", re.I)

# Portal gov.pl: strona podmiotu, nie BIP (skanowanie jej daje zero ogłoszeń).
PORTAL_RE = re.compile(r"^https?://(www\.)?gov\.pl(/|$)", re.I)

BAD_URL = {"https://www.gov.pl", "http://www.gov.pl", "https://gov.pl"}

SECTION_RE = re.compile(
    r"nab[oó]r|ogłoszen|ogloszen|konkurs|kandydat", re.I)

# Strony pokontrolne RIO i podobne wymieniają wiele podmiotów w treści.
CONTROL_PAGE_RE = re.compile(
    r"wystąpienie pokontrolne|wystapienie pokontrolne|protok[oó]ł kontroli|"
    r"regionalna izba obrachunkowa", re.I)


def normalize(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if not url.startswith("http"):
        url = "https://" + url
    return url.rstrip("/")


def looks_like_bip(url: str) -> bool:
    """Czy adres wygląda na stronę BIP (a nie portal, agregator, artykuł)."""
    if not url or url in BAD_URL or SKIP_HOSTS.search(url):
        return False
    if PORTAL_RE.search(url):
        return False
    host = urlparse(url).netloc.lower()
    path = urlparse(url).path.lower()
    if host in ("bip.gov.pl", "www.bip.gov.pl"):   # portal, nie strona podmiotu
        return False
    if host.startswith("bip.") or ".bip." in host or "bip-" in host:
        return True
    if host.startswith("bip") and "." in host:      # bip.gogolin.pl
        return True
    return "/bip" in path                            # leczna.pl/bip


def name_key(text: str) -> str:
    """Klucz porównania nazw: bez prefiksu urzędowego, bez diakrytyków."""
    s = (text or "").strip().lower().replace("ł", "l")
    s = "".join(c for c in unicodedata.normalize("NFKD", s)
                if not unicodedata.combining(c))
    s = re.sub(r"^(urząd miasta i gminy|urząd gminy i miasta|urząd miasta|"
               r"urząd gminy|urząd miejski|gmina|miasto)\s+", "", s)
    return re.sub(r"[^a-z0-9]+", "", s)


def validate(url: str, name: str, timeout: int = 12) -> tuple[bool, str]:
    """Czy strona pod adresem to BIP TEGO podmiotu. Zwraca (ok, szczegół)."""
    key = name_key(name)
    if not key:
        return False, "brak nazwy"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=(6, timeout))
    except requests.exceptions.SSLError:
        try:
            import urllib3
            urllib3.disable_warnings()
            resp = requests.get(url, headers=HEADERS, timeout=(6, timeout), verify=False)
        except Exception as exc:
            return False, f"błąd SSL: {type(exc).__name__}"
    except Exception as exc:
        return False, f"błąd pobrania: {type(exc).__name__}"
    if resp.status_code != 200:
        return False, f"HTTP {resp.status_code}"
    text = resp.text or ""
    # Nazwa musi być w TREŚCI strony - sam URL nie wystarcza: dwie gminy o tej
    # samej nazwie (miasto i gmina wiejska) mają domeny z tym samym rdzeniem.
    if key not in name_key(text[:1500]):
        return False, "nazwa podmiotu nie występuje na stronie"
    # Współdzielone portale (np. riokatowice.bip.net.pl) wymieniają w treści
    # wiele gmin - ich strony kontrolne nie są BIP-em podmiotu.
    title = ""
    match = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    if match:
        title = re.sub(r"\s+", " ", match.group(1))
    if CONTROL_PAGE_RE.search(title) and "izba obrachunkowa" not in name_key(name):
        return False, f"strona kontroli, nie BIP podmiotu ({title[:60]})"
    section = "sekcja ogłoszeń: tak" if SECTION_RE.search(text) else "sekcja ogłoszeń: nie"
    return True, f"200, {section}"


def _search_ddg(query: str, limit: int = 6) -> list[str]:
    from ddgs import DDGS
    with DDGS() as ddgs:
        out = []
        for res in ddgs.text(query, region="pl-pl", max_results=limit):
            url = normalize(res.get("href") or res.get("url") or "")
            if url:
                out.append(url)
        return out


def _search_brave(query: str, limit: int = 6) -> list[str]:
    key = os.getenv("BRAVE_API_KEY", "").strip()
    if not key:
        return []
    resp = requests.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": limit, "country": "pl",
                "search_lang": "pl"},
        headers={"Accept": "application/json", "X-Subscription-Token": key},
        timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"Brave HTTP {resp.status_code}")
    data = resp.json()
    return [normalize(item.get("url", ""))
            for item in (data.get("web", {}) or {}).get("results", [])]


def search(query: str, limit: int = 6) -> list[str]:
    """Brave, gdy jest klucz; w przeciwnym razie DuckDuckGo."""
    if os.getenv("BRAVE_API_KEY", "").strip():
        return _search_brave(query, limit)
    return _search_ddg(query, limit)


def build_todo(registry: list, teryt: list, mapping: dict,
               teryt_only: bool = False, force: bool = False) -> list[dict]:
    """Lista podmiotów bez realnego adresu BIP.

    Wpisy gov.pl: slug z API. Gminy z TERYT: slug `teryt-<TERC>` (zgodnie z
    tym, jak rejestr dopisuje je w direct_sources._load_jst_registry).
    """
    todo = []
    if not teryt_only:
        for r in registry:
            if not r.get("slug"):
                continue
            if not force and mapping.get(r["slug"]):
                continue
            todo.append({"slug": r["slug"], "name": r.get("name", ""),
                         "hint": "", "kind": r.get("kind", "")})
    for g in teryt:
        slug = f"teryt-{g['teryt']}"
        if not force and mapping.get(slug):
            continue
        hint = " ".join(x for x in (g.get("powiat", ""), g.get("voivodeship", "")) if x)
        name = (("Miasto " if g.get("gmina_type") == "1" else "Gmina ") + g["name"])
        todo.append({"slug": slug, "name": name, "hint": hint,
                     "kind": "gmina-teryt"})
    return todo


def query_for(entry: dict) -> str:
    base = entry["name"]
    if entry.get("kind") == "gmina-teryt":
        base = re.sub(r"^(Gmina|Miasto)\s+", "", base)
    if entry.get("hint"):
        return f'"{base}" BIP {entry["hint"]}'
    return f'"{base}" BIP'


def resolve(entry: dict) -> tuple[str, str]:
    """Szuka i waliduje adres BIP dla jednego podmiotu. Zwraca (url, opis)."""
    try:
        candidates = search(query_for(entry), limit=6)
    except Exception as exc:
        return "", f"błąd wyszukiwarki: {type(exc).__name__}: {str(exc)[:80]}"
    kept = [u for u in candidates if looks_like_bip(u)]
    detail = "brak kandydata w wynikach"
    for url in kept[:3]:
        ok, detail = validate(url, entry["name"])
        if ok:
            return url, detail
    if kept:
        return "", f"brak walidacji ({detail})"
    return "", detail


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="ile podmiotów w tej partii")
    ap.add_argument("--teryt-only", action="store_true", help="tylko gminy z TERYT")
    ap.add_argument("--force", action="store_true", help="nadpisz istniejące wpisy")
    ap.add_argument("--dry-run", action="store_true", help="nie zapisuj mapowania")
    ap.add_argument("--delay", type=float, default=0.0,
                    help="przerwa między zapytaniami (domyślnie 1.2 s Brave / 1.6 s DDG)")
    args = ap.parse_args(argv)

    registry = json.load(open(REG, encoding="utf-8"))
    try:
        teryt = json.load(open(TERYT, encoding="utf-8"))
    except FileNotFoundError:
        teryt = []
    try:
        mapping = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        mapping = {}

    todo = build_todo(registry, teryt, mapping,
                      teryt_only=args.teryt_only, force=args.force)
    if args.limit:
        todo = todo[:args.limit]
    backend = "Brave" if os.getenv("BRAVE_API_KEY", "").strip() else "DuckDuckGo"
    delay = args.delay or (1.2 if backend == "Brave" else 1.6)
    print(f"registry={len(registry)} teryt={len(teryt)} "
          f"resolved={sum(1 for v in mapping.values() if v)} "
          f"todo={len(todo)} backend={backend}", flush=True)

    found = 0
    for i, entry in enumerate(todo, 1):
        url, detail = resolve(entry)
        mapping[entry["slug"]] = url
        if url:
            found += 1
        print(f"[{i}/{len(todo)}] {'OK ' if url else '-- '} {entry['name'][:38]:38} "
              f"| {detail} | {url[:70]}", flush=True)
        if i % 25 == 0 and not args.dry_run:
            _write(mapping)
        time.sleep(delay)

    if not args.dry_run:
        _write(mapping)
    resolved = sum(1 for v in mapping.values() if v)
    print(f"DONE resolved={resolved} new={found} "
          f"(na {len(todo)} sprawdzonych)", flush=True)
    return 0


def _write(mapping: dict) -> None:
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=0)
    os.replace(tmp, OUT)


if __name__ == "__main__":
    sys.exit(main())
