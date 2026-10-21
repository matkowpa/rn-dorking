# -*- coding: utf-8 -*-
"""Audyt linków w bazie ofert: żywy / martwy (404) / strona-menu / treść.

Problem: Faza 0 brała za link do ogłoszenia adres z menu BIP, więc w bazie
siedzą wpisy prowadzące do strony nawigacyjnej (12 000 znaków samych nazw
działów), do 404 albo do pliku PDF (kwestionariusz) zamiast do ogłoszenia.
Bez tego nie da się powiedzieć, które oferty są realnie klikalne.

Uruchamianie:

    python tools/audit_links.py            # raport (nie zmienia bazy)
    python tools/audit_links.py --mark     # oznacza martwe/menu w oferty.json
    python tools/audit_links.py --mark --limit 10

Oznaczenia trafiają do pola `link_status`:
    "ok"      - strona ma treść ogłoszenia (albo termin w załączniku)
    "menu"    - strona nawigacyjna, bez treści ogłoszenia
    "dead"    - pobranie nieudane (404, timeout, 403)
Pole `link_checked` = data audytu.
"""

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import content_fetcher as cf  # noqa: E402
import deadline_parser as dp  # noqa: E402
from storage import Storage  # noqa: E402

logger = logging.getLogger(__name__)


def classify(url: str) -> tuple[str, str]:
    """Zwraca (status, szczegół) dla jednego URL-a.

    status: "ok" | "menu" | "dead"
    szczegół: czytelny opis (długość tekstu, znaleziony termin, kod błędu)
    """
    response = cf._fetch(url)
    if response is None:
        return "dead", "pobranie nieudane (404/403/timeout)"
    text = cf._extract_html_text(response)
    if cf._hints_offer_content(text):
        return "ok", f"treść w HTML ({len(text)} zn.)"

    # Strona bez treści w HTML - sprawdź załączniki: termin w PDF też
    # oznacza, że link prowadzi do realnego ogłoszenia.
    for link in cf._attachment_links(response.text, url):
        sub = cf._fetch(link)
        if sub is None:
            continue
        if link.lower().endswith(".pdf") or \
                "pdf" in sub.headers.get("Content-Type", "").lower():
            try:
                sub_text = cf._extract_pdf_text(sub.content)
            except Exception:
                continue
        else:
            sub_text = cf._extract_html_text(sub)
        found = dp.extract_deadline(sub_text) or dp.deadline_from_filename(link)
        if found:
            return "ok", f"termin {found} w załączniku"
    return "menu", f"strona nawigacyjna ({len(text)} zn., brak terminu)"


def audit(offers: list[dict], limit: int = 0) -> list[dict]:
    """Audytuje oferty i zwraca listę raportów (nie modyfikuje wejścia)."""
    targets = offers[:limit] if limit else offers
    reports: list[dict] = []
    for i, offer in enumerate(targets, 1):
        url = offer.get("url", "")
        status, detail = classify(url)
        logger.info("[%s/%s] %-5s %s | %s", i, len(targets), status,
                    (offer.get("podmiot") or "?")[:34], detail)
        reports.append({
            "url": url,
            "podmiot": offer.get("podmiot", ""),
            "status": status,
            "detail": detail,
        })
    return reports


def summarize(reports: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for r in reports:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Audyt linków w oferty.json")
    parser.add_argument("--mark", action="store_true",
                        help="zapisz link_status/link_checked do oferty.json")
    parser.add_argument("--limit", type=int, default=0,
                        help="zbadaj tylko N ofert (0 = wszystkie)")
    parser.add_argument("--json", help="zapisz raport do pliku JSON")
    parser.add_argument("--purge", action="store_true",
                        help="usuń oferty 'dead', a 'menu' oznacz jako nieaktualne "
                             "(wymaga --mark albo --purge; bez --dry-run zapisuje)")
    parser.add_argument("--dry-run", action="store_true",
                        help="z --purge: tylko pokaż, co zostałoby usunięte")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)

    storage = Storage()
    reports = audit(storage.offers, limit=args.limit)

    if args.mark or args.purge:
        today = date.today().isoformat()
        by_url = {r["url"]: r for r in reports}
        marked = 0
        for offer in storage.offers:
            rep = by_url.get(offer.get("url", ""))
            if not rep:
                continue
            offer["link_status"] = rep["status"]
            offer["link_checked"] = today
            marked += 1
        logger.info("Oznaczono %s ofert w oferty.json", marked)

    if args.purge:
        today = date.today().isoformat()
        dead = [o for o in storage.offers if o.get("link_status") == "dead"]
        menu = [o for o in storage.offers if o.get("link_status") == "menu"]
        print("\n=== DO USUNIĘCIA (dead) ===")
        for offer in dead:
            print(f"  - {(offer.get('podmiot') or '?')[:40]:<40} | "
                  f"{offer.get('url', '')[:55]}")
        print(f"\n=== DO OZNACZENIA (menu -> nieaktualna): {len(menu)} ===")
        for offer in menu:
            print(f"  ~ {(offer.get('podmiot') or '?')[:40]:<40} | "
                  f"{offer.get('url', '')[:55]}")

        if args.dry_run:
            logger.info("Tryb --dry-run: nic nie zapisano")
        else:
            if dead:
                dead_urls = {o.get("url", "") for o in dead}
                storage.offers = [o for o in storage.offers
                                  if o.get("url", "") not in dead_urls]
            for offer in storage.offers:
                if offer.get("link_status") == "menu":
                    offer["nieaktualna"] = True
                    offer["nieaktualna_powod"] = (
                        "link prowadzi do strony-menu, nie do ogłoszenia")
                    offer["nieaktualna_data"] = today
            storage.save()
            logger.info("Usunięto %s martwych ofert, oznaczono %s jako nieaktualne",
                        len(dead), len(menu))

    if args.json:
        Path(args.json).write_text(
            json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Raport zapisany: %s", args.json)

    counts = summarize(reports)
    print("\n=== PODSUMOWANIE ===")
    for status, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {status:<5} {count}")

    print("\n=== NIE-DZIAŁAJĄCE ===")
    for r in reports:
        if r["status"] != "ok":
            print(f"  {r['status']:<5} | {(r['podmiot'] or '?')[:34]:<34} | {r['url'][:60]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
