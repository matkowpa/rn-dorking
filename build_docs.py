# -*- coding: utf-8 -*-
"""Buduje dane dla frontendu GitHub Pages (docs/data/).

- kopiuje pliki dzienne data/dnia/<data>.json do docs/data/<data>.json
- tworzy docs/data/index.json (lista dni z liczbą ofert, malejąco)
- tworzy docs/data/all.json (wszystkie oferty - wyszukiwanie globalne,
  najbliższe terminy)
- tworzy docs/nabory.ics (kalendarz iCalendar aktywnych terminów naborów)
"""

import glob
import hashlib
import json
import logging
import os
from datetime import date, timedelta

logger = logging.getLogger(__name__)
DOCS_DATA = os.path.join("docs", "data")


def _read(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _ics_escape(text: str) -> str:
    """Escapuje tekst wg RFC 5545 (przecinki, średniki, nowe linie)."""
    return (text.replace("\\", "\\\\")
                .replace(";", "\\;")
                .replace(",", "\\,")
                .replace("\n", "\\n"))


def build_ics(offers: list[dict], today: str | None = None) -> str:
    """Buduje kalendarz iCalendar (RFC 5545) z AKTYWNYCH ofert (termin >= dziś).

    UID = SHA1 z URL-a oferty (stabilny między buildami - kalendarz poprawnie
    aktualizuje istniejące wpisy zamiast duplikować). Zwraca treść pliku ICS.
    """
    today = today or date.today().isoformat()
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//rn-dorking//nabory rad nadzorczych//PL",
        "CALSCALE:GREGORIAN",
        "X-WR-CALNAME:Nabory - rady nadzorcze",
    ]
    for o in offers:
        termin = o.get("termin_skladania_ofert", "")
        if not termin or termin < today:
            continue  # bez terminu lub archiwalne - pomijamy
        uid = hashlib.sha1(o.get("url", "").encode("utf-8")).hexdigest()
        summary = _ics_escape(o.get("podmiot") or "(bez nazwy)")
        description = _ics_escape(
            f"{o.get('podsumowanie', '')}\n{o.get('url', '')}")
        # DTEND w iCalendar jest wyłączny - termin składania = koniec dnia,
        # więc wpis trwa do następnego dnia
        end = (date.fromisoformat(termin) + timedelta(days=1)).isoformat()
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}@rn-dorking",
            f"DTSTAMP:{today.replace('-', '')}T000000Z",
            f"DTSTART;VALUE=DATE:{termin.replace('-', '')}",
            f"DTEND;VALUE=DATE:{end.replace('-', '')}",
            f"SUMMARY:{summary}",
            f"DESCRIPTION:{description}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def build() -> None:
    days: list[dict] = []
    all_offers: list[dict] = []

    for path in sorted(glob.glob(os.path.join("data", "dnia", "*.json"))):
        payload = _read(path)
        run_date = payload.get("date") or os.path.basename(path)[:-5]
        offers = payload.get("offers", [])
        stats = payload.get("stats", {})
        entry = {
            "date": run_date,
            "count": len(offers),
            "stats": {
                "raw_results": stats.get("raw_results", 0),
                "after_filter": stats.get("after_filter", 0),
                "offers_added": stats.get("offers_added", 0),
            },
        }
        days.append(entry)
        all_offers.extend(offers)
        _write(os.path.join(DOCS_DATA, f"{run_date}.json"), payload)

    days.sort(key=lambda d: d["date"], reverse=True)
    _write(os.path.join(DOCS_DATA, "index.json"), days)
    _write(os.path.join(DOCS_DATA, "all.json"), all_offers)

    # Kalendarz iCalendar z aktywnych terminów (link na stronie głównej)
    ics_path = os.path.join("docs", "nabory.ics")
    os.makedirs("docs", exist_ok=True)
    tmp = ics_path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(build_ics(all_offers))
    os.replace(tmp, ics_path)
    logger.info("build_docs: %s dni, %s ofert łącznie", len(days), len(all_offers))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=__import__("sys").stdout)
    build()
