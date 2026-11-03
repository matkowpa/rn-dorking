# -*- coding: utf-8 -*-
"""Wydajność zapytań: ile każdy dork daje wyników, świeżych adresów i ofert.

Dane bierze z archiwum pre-filtra (`data/dnia/raw-*.json`), gdzie każdy surowy
wynik ma pole `source` (treść dorku) i `decision` (co z nim zrobił potok).

Po co: przy stałym zestawie 12 dorków 81% wsadu to `cached`/`duplicate` -
dopiero ten raport pokazuje, które zapytania dowożą NOWE adresy, a które
odgrzewają te same strony. Na tej podstawie wymienia się dorki o zerowej
wydajności (zamiast zgadywać).

Decyzje potoku:
  cached/duplicate  - adres już znany (odrzucony w TTL / widziany wcześniej)
  blocked           - medium/agregator, odsiany bez pobierania
  accepted          - oferta trafiła do bazy
  rejected/archival/empty - ocenione i odrzucone (treść, archiwum, brak treści)

Użycie:
    python tools/dork_stats.py
    python tools/dork_stats.py --days 30 --top 15
    python tools/dork_stats.py --json
"""

import argparse
import glob
import json
import os
import sys
from collections import defaultdict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RAW_GLOB = os.path.join(ROOT, "data", "dnia", "raw-*.json")

STALE = {"cached", "duplicate", "blocked", "no_url", "limit"}
EVALUATED = {"accepted", "rejected", "archival", "empty", "menu"}


def _load(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    rows = data if isinstance(data, list) else (data.get("results") or data.get("raw") or [])
    return [r for r in rows if isinstance(r, dict)]


def collect(paths: list[str]) -> dict:
    """Agreguje wpisy per dork i per dzień."""
    per_dork = defaultdict(lambda: {"total": 0, "stale": 0, "blocked": 0,
                                    "accepted": 0, "rejected": 0,
                                    "urls": set(), "fresh_urls": set()})
    per_day = defaultdict(lambda: {"total": 0, "fresh": 0, "accepted": 0})
    for path in paths:
        day = os.path.basename(path).replace("raw-", "").replace(".json", "")
        try:
            rows = _load(path)
        except Exception:
            continue
        for row in rows:
            dork = row.get("source") or "(bez źródła)"
            decision = row.get("decision") or "?"
            url = row.get("url") or ""
            d = per_dork[dork]
            d["total"] += 1
            per_day[day]["total"] += 1
            if url:
                d["urls"].add(url)
            if decision in STALE:
                d["stale"] += 1
                if decision == "blocked":
                    d["blocked"] += 1
                continue
            per_day[day]["fresh"] += 1
            if url:
                d["fresh_urls"].add(url)
            if decision == "accepted":
                d["accepted"] += 1
                per_day[day]["accepted"] += 1
            elif decision in EVALUATED:
                d["rejected"] += 1
    return {"per_dork": per_dork, "per_day": per_day}


def render(stats: dict, top: int = 20) -> str:
    rows = []
    for dork, d in stats["per_dork"].items():
        fresh = len(d["fresh_urls"])
        rows.append((d["accepted"], fresh, d["total"], dork))
    rows.sort(reverse=True)
    lines = [f"{'oferty':>6} {'nowe':>5} {'razem':>6}  dork"]
    for accepted, fresh, total, dork in rows[:top]:
        lines.append(f"{accepted:6} {fresh:5} {total:6}  {dork[:78]}")
    days = stats["per_day"]
    if days:
        lines.append("")
        lines.append(f"{'dzień':12} {'razem':>6} {'nowe':>5} {'oferty':>6}")
        for day in sorted(days):
            d = days[day]
            lines.append(f"{day:12} {d['total']:6} {d['fresh']:5} {d['accepted']:6}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=0, help="tylko ostatnie N dni")
    ap.add_argument("--top", type=int, default=20, help="ile dorków pokazać")
    ap.add_argument("--json", action="store_true", help="wynik jako JSON")
    args = ap.parse_args(argv)

    paths = sorted(glob.glob(RAW_GLOB))
    if args.days:
        paths = paths[-args.days:]
    if not paths:
        print("Brak archiwów data/dnia/raw-*.json", file=sys.stderr)
        return 1

    stats = collect(paths)
    if args.json:
        out = {dork: {k: v for k, v in d.items() if k not in ("urls", "fresh_urls")}
               for dork, d in stats["per_dork"].items()}
        print(json.dumps({"dorki": out, "dni": stats["per_day"]},
                         ensure_ascii=False, indent=1))
        return 0
    print(render(stats, top=args.top))
    return 0


if __name__ == "__main__":
    sys.exit(main())
