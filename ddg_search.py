# -*- coding: utf-8 -*-
"""Wyszukiwanie zapasowe DuckDuckGo (Plan B, bez kluczy API).

Zwraca dane w TYM SAMYM formacie co search_brave, żeby reszta potoku
(filtr LLM, ekstrakcja) działała bez zmian.
"""

import logging
import sys
import time

from ddgs import DDGS
from ddgs.exceptions import DDGSException

logger = logging.getLogger(__name__)

# Zestaw dorków dla DuckDuckGo (obsługuje operatory w ograniczonym zakresie)
DORKS = [
    'inurl:bip "nabór na członków rady nadzorczej"',
    'inurl:bip "postępowanie kwalifikacyjne" "rady nadzorczej" filetype:pdf',
    'site:gov.pl "konkurs na członka rady nadzorczej"',
    'site:gov.pl "nabór na członków rady nadzorczej"',
    '"zaproszenie do składania ofert" "rady nadzorczej" filetype:pdf',
    '"zgłoszenia kandydatów" "członka rady nadzorczej" -archiwum -protokół',
    # Frazy z realnych ogłoszeń w produkcji (konkurs w liczbie mnogiej,
    # nabór do bazy kandydatów)
    '"konkurs na członków rady nadzorczej" site:gov.pl',
    '"nabór do bazy danych kandydatów" "rada nadzorcza"',
]


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
    delays = [5, 10, 20]  # retry na chwilowe rate-limity backendów DDG
    for attempt in range(len(delays) + 1):
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
            break  # sukces - koniec retry
        except DDGSException as e:
            if attempt < len(delays):
                delay = delays[attempt]
                logger.warning("DDG błąd dla dorka %s (próba %s), ponawiam za %s s: %s",
                               dork, attempt + 1, delay, e)
                time.sleep(delay)
                continue
            # Wyczerpane retry - potraktuj jak brak wyników dla tego dorka
            logger.warning("DDG błąd dla dorka %s po %s próbach: %s",
                           dork, attempt + 1, e)
    logger.info("DDG: dork=%s, wyników=%s", dork, len(results))
    return results


if __name__ == "__main__":
    # Self-test - jedno zapytanie, bez kluczy API
    logging.basicConfig(level=logging.INFO, stream=__import__("sys").stdout)
    results = search_ddg('"nabór na członków rady nadzorczej"', 5, 10)
    print(f"Liczba wyników: {len(results)}")
    for r in results[:3]:
        print(f"- {r['title']}")
