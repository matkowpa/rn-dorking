# -*- coding: utf-8 -*-
"""Wyszukiwanie Brave Search API (darmowy plan: 2000 zapytań/mies.).

Zwraca dane w TYM SAMYM formacie co search_google/ddg_search.
"""

import logging
import sys
import time

import requests

import config

logger = logging.getLogger(__name__)

ENDPOINT = "https://api.search.brave.com/res/v1/web/search"

# Brave nie wspiera operatorów inurl:/filetype:/site: (zwracają 0 wyników) -
# dedykowany zestaw dorków oparty na frazach i słowach kluczowych
BRAVE_DORKS = [
    '"nabór na członków rady nadzorczej" BIP',
    '"nabór kandydatów" "rady nadzorczej" BIP',
    '"postępowanie kwalifikacyjne" "rady nadzorczej"',
    '"konkurs na członka rady nadzorczej"',
    '"zaproszenie do składania ofert" "rady nadzorczej"',
    '"zgłoszenia kandydatów" "członka rady nadzorczej"',
]


def _freshness(days_back: int) -> str | None:
    """Mapuje days_back na filtr świeżości Brave (pd/pw/pm/py)."""
    if days_back <= 1:
        return "pd"
    if days_back <= 7:
        return "pw"
    if days_back <= 31:
        return "pm"
    if days_back <= 365:
        return "py"
    return None


def search_brave(dork: str, days_back: int, max_results: int) -> list[dict]:
    """Wyszukuje przez Brave API, zwraca listę {"title", "snippet", "link", "dork"}.

    Retry na 429 (3 próby: 5s/10s/20s), inne błędy → WARNING i pusta lista
    (potok przechodzi do kolejnych dorków).
    """
    params = {
        "q": dork,
        "count": min(max_results, 20),  # Brave: max 20 na zapytanie
        "country": "pl",
        "search_lang": "pl",
        "safesearch": "off",
    }
    freshness = _freshness(days_back)
    if freshness:
        params["freshness"] = freshness

    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": config.BRAVE_API_KEY,
    }

    delays = [5, 10, 20]
    attempt = 0
    while True:
        response = requests.get(ENDPOINT, params=params, headers=headers, timeout=30)
        if response.status_code == 200:
            # Brave potrafi zwrócić 200 z pustym wynikiem, gdy filtr daty jest
            # zbyt restrykcyjny (bad_results/should_fallback) - wtedy jedna
            # próba ponowna BEZ filtra świeżości (stare wyniki odfiltruje LLM)
            if freshness and not response.json().get("web", {}).get("results"):
                logger.info("Brave: pusty wynik z freshness=%s, ponawiam bez filtra daty", freshness)
                params.pop("freshness", None)
                freshness = None
                continue
            break
        if response.status_code == 429 and attempt < len(delays):
            delay = delays[attempt]
            attempt += 1
            logger.warning("Brave rate limit (429), ponawiam za %s s: %s", delay, dork)
            time.sleep(delay)
            continue
        # Inny błąd / wyczerpane retry - WARNING i pusty wynik dla tego dorka
        logger.warning("Brave błąd status=%s dla dorka %s: %s",
                       response.status_code, dork, response.text[:200])
        return []

    data = response.json()
    web = data.get("web", {})
    items = web.get("results", [])
    results = [{
        "title": it.get("title", ""),
        "snippet": it.get("description", ""),
        "link": it.get("url", ""),
        "dork": dork,
    } for it in items]
    logger.info("Brave: dork=%s, wyników=%s", dork, len(results))
    return results


if __name__ == "__main__":
    # Self-test - wymaga BRAVE_API_KEY w .env
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    if not config.BRAVE_API_KEY:
        print("Brak BRAVE_API_KEY w .env", file=sys.stderr)
        sys.exit(1)
    results = search_brave('"nabór na członków rady nadzorczej"',
                           config.SEARCH_DAYS_BACK, 10)
    print(f"Liczba wyników: {len(results)}")
    for r in results[:3]:
        print(f"- {r['title']} | {r['link']}")
