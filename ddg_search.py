# -*- coding: utf-8 -*-
"""Wyszukiwanie zapasowe DuckDuckGo (Plan B, bez kluczy API).

Zwraca dane w TYM SAMYM formacie co search_google z google_search.py,
żeby reszta potoku (filtr LLM, ekstrakcja) działała bez zmian.
"""

import logging
import time

from ddgs import DDGS
from ddgs.exceptions import DDGSException

logger = logging.getLogger(__name__)


def search_ddg(dork: str, days_back: int, max_results: int) -> list[dict]:
    """Wyszukuje w DuckDuckGo, zwraca listę {"title", "snippet", "link", "dork"}.

    DDG nie ma paginacji jak CSE - jedno zapytanie zwraca do max_results wyników.
    Ograniczenie czasowe: mapowanie days_back na timelimit DDG (d/w/m).
    """
    # Mapowanie dnia na okno czasowe DDG
    if days_back <= 1:
        timelimit = "d"
    elif days_back <= 7:
        timelimit = "w"
    elif days_back <= 30:
        timelimit = "m"
    else:
        timelimit = None  # brak filtra dat (cały rok)

    results: list[dict] = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(dork, region="pl-pl", timelimit=timelimit,
                               max_results=max_results):
                results.append({
                    "title": r.get("title", ""),
                    "snippet": r.get("body", ""),
                    "link": r.get("href", ""),
                    "dork": dork,
                })
    except DDGSException as e:
        # Zapasowe wyszukiwarki potrafią rate-limitować - potraktuj jak brak
        # wyników dla tego dorka (WARNING), potok przechodzi do kolejnych
        logger.warning("DDG błąd dla dorka %s: %s", dork, e)
    logger.info("DDG: dork=%s, wyników=%s", dork, len(results))
    return results


if __name__ == "__main__":
    # Self-test - jedno zapytanie, bez kluczy API
    logging.basicConfig(level=logging.INFO, stream=__import__("sys").stdout)
    results = search_ddg('"nabór na członków rady nadzorczej"', 5, 10)
    print(f"Liczba wyników: {len(results)}")
    for r in results[:3]:
        print(f"- {r['title']}")
