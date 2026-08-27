# -*- coding: utf-8 -*-
"""Klient Google Custom Search JSON API (ETAP A)."""

import logging
import sys
import time

import requests

import config

logger = logging.getLogger(__name__)

ENDPOINT = "https://www.googleapis.com/customsearch/v1"

# Zestaw 5 dorków (stały, wg specyfikacji ETAPU 2)
DORKS = [
    'inurl:bip "nabór na członków rady nadzorczej"',
    'inurl:bip "postępowanie kwalifikacyjne" "rady nadzorczej" filetype:pdf',
    'site:gov.pl "konkurs na członka rady nadzorczej"',
    '"zaproszenie do składania ofert" "rady nadzorczej" filetype:pdf',
    '"zgłoszenia kandydatów" "członka rady nadzorczej" -archiwum -protokół',
]


class QuotaExceededError(Exception):
    """Rzucany, gdy Google CSE zgłosi przekroczenie limitu (403/429)."""
    pass


def search_google(dork: str, days_back: int, max_results: int) -> list[dict]:
    """Wykonuje wyszukiwanie z paginacją (strony po 10 wyników).

    Zwraca listę słowników {"title", "snippet", "link", "dork"}.
    Obsługuje QuotaExceededError dla 403/429, inne błędy przerywają
    iterację po stronach danego dorka.
    """
    results: list[dict] = []
    start = 1
    while start <= max_results:
        params = {
            "key": config.GOOGLE_API_KEY,
            "cx": config.GOOGLE_CX,
            "q": dork,
            "dateRestrict": f"d{days_back}",
            "num": 10,
            "start": start,
        }
        response = requests.get(ENDPOINT, params=params, timeout=30)
        if response.status_code == 200:
            data = response.json()
            items = data.get("items")
            if not items:
                # Brak wyników - zakończ paginację dla tego dorka
                break
            for item in items:
                results.append({
                    "title": item.get("title", ""),
                    "snippet": item.get("snippet", ""),
                    "link": item.get("link", ""),
                    "dork": dork,
                })
        elif response.status_code in (403, 429):
            # Przekroczenie limitu - odróżnij brak wyników od braku limitu
            try:
                msg = response.json().get("error", {}).get("message", "")
            except (ValueError, AttributeError):
                msg = ""
            if not msg:
                msg = "Limit Google CSE wyczerpany lub brak uprawnień API"
            raise QuotaExceededError(msg)
        else:
            # Inny status - loguj i przerwij iterację po stronach tego dorka
            logger.error(
                "Google CSE błąd status=%s zapytanie=%s (start=%s)",
                response.status_code, dork, start,
            )
            break
        start += 10
        if start <= max_results:
            time.sleep(1)  # odstęp między zapytaniami na kolejne strony
    return results


if __name__ == "__main__":
    # Self-test (ETAP 2a) - jedno zapytanie, max_results wymuszony na 10
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    try:
        config.validate()
    except ValueError as e:
        print(e, file=sys.stderr)
        sys.exit(1)

    query = sys.argv[1] if len(sys.argv) > 1 else "nabór rada nadzorcza"
    results = search_google(query, days_back=config.SEARCH_DAYS_BACK, max_results=10)
    print(f"Liczba wyników: {len(results)}")
    for r in results[:3]:
        print(f"- {r['title']}")
