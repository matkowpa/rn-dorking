# -*- coding: utf-8 -*-
"""Orkiestrator potoku A->B->C (ETAP 5). Jedyne wejście CLI."""

import argparse
import logging
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    # Konsola Windows: uniknij UnicodeEncodeError przy polskich znakach
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import config
from content_fetcher import fetch_content
from google_search import DORKS, QuotaExceededError, search_google
from llm_parser import extract_fields, filter_is_announcement
from storage import Storage


def _search(dork: str, days_back: int):
    """Wyszukiwanie: Google CSE, a gdy brak kluczy - DuckDuckGo (Plan B).

    Zwraca (lista_wyników, użyto_google, liczba_zapytań, QuotaExceededError|None).
    """
    if config.use_google():
        results = search_google(dork, days_back, config.RESULTS_PER_DORK)
        return results, True, 1, None
    from ddg_search import search_ddg
    results = search_ddg(dork, days_back, config.RESULTS_PER_DORK)
    return results, False, 1, None


def setup_logging() -> None:
    """INFO na konsolę, DEBUG do run.log (oba UTF-8)."""
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    console = logging.StreamHandler(stream=sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)
    file_handler = logging.FileHandler("run.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    logger.addHandler(console)
    logger.addHandler(file_handler)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Potok pozyskiwania ogłoszeń do rad nadzorczych")
    parser.add_argument("--check", action="store_true",
                        help="tylko walidacja .env i wyjście")
    parser.add_argument("--dry-run", action="store_true",
                        help="ETAP A + B bez pobierania treści i ekstrakcji")
    parser.add_argument("--limit", type=int, default=30,
                        help="maks. liczba NOWYCH wyników poddawanych ETAPOWI B (domyślnie 30)")
    parser.add_argument("--days", type=int, default=None,
                        help="nadpisuje SEARCH_DAYS_BACK na to uruchomienie")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    # Walidacja .env; przy --check: lista brakujących zmiennych + exit 1
    try:
        config.validate()
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1
    if args.check:
        logging.basicConfig(level=logging.INFO, stream=sys.stdout)
        logging.getLogger(__name__).info("Konfiguracja .env kompletna")
        return 0

    setup_logging()
    logger = logging.getLogger(__name__)

    days_back = args.days if args.days is not None else config.SEARCH_DAYS_BACK
    storage = Storage()

    # Statystyki
    stats = {
        "google_requests": 0,
        "raw_results": 0,
        "after_dedup": 0,
        "after_filter": 0,
        "offers_added": 0,
        "extract_errors": 0,
    }

    # ETAP A: wyszukiwanie dla wszystkich dorków (Google albo DDG fallback)
    use_google = config.use_google()
    if not use_google:
        logger.warning(
            "Brak GOOGLE_API_KEY/GOOGLE_CX w .env - używam DuckDuckGo (Plan B). "
            "Dla produkcji uzupełnij klucze Google."
        )
    all_results: list[dict] = []
    for dork in DORKS:
        logger.info("Wyszukiwanie (%s): dork=%s",
                    "Google" if use_google else "DuckDuckGo", dork)
        try:
            results, _, _, _ = _search(dork, days_back)
            stats["google_requests"] += 1
            all_results.extend(results)
        except QuotaExceededError as e:
            # Limit Google wyczerpany - przerwij pętlę po dorkach, nie cały program
            logger.error("Limit Google CSE: %s", e)
            break

    stats["raw_results"] = len(all_results)

    # ETAP B: deduplikacja, filtr LLM (z limitem --limit na nowych wynikach)
    dry_run_rows: list[tuple[str, bool, str]] = []
    new_processed = 0
    for result in all_results:
        if new_processed >= args.limit:
            break
        link = result.get("link", "")
        if not storage.is_new(link):
            # Już widziany - nie liczy się do limitu
            continue
        new_processed += 1
        stats["after_dedup"] += 1
        title = result.get("title", "")
        snippet = result.get("snippet", "")
        czy_nabor, uzasadnienie = filter_is_announcement(title, snippet, link)
        stats["after_filter"] += 1 if czy_nabor else 0

        if args.dry_run:
            dry_run_rows.append((title, czy_nabor, uzasadnienie))
        elif czy_nabor:
            # ETAP C: pobranie treści + ekstrakcja
            text = fetch_content(link)
            if not text:
                logger.info("Brak treści (użyto snippetu): %s", link)
                text = snippet
            offer = extract_fields(text, link)
            if offer is None:
                stats["extract_errors"] += 1
            else:
                storage.add_offer(offer)
                stats["offers_added"] += 1
                logger.info("Nowa oferta: podmiot=%s termin=%s",
                            offer.get("podmiot", ""), offer.get("termin_skladania_ofert", ""))
        # Mały odstęp między wywołaniami LLM (mniejsza szansa na rate limit)
        time.sleep(0.5)

    if args.dry_run:
        print(f"{'tytuł':<60} | {'nabór':<5} | uzasadnienie")
        for title, czy_nabor, uzasadnienie in dry_run_rows:
            print(f"{title[:60]:<60} | {'TAK' if czy_nabor else 'NIE':<5} | {uzasadnienie}")
        logger.info("Tryb dry-run: nie zapisano oferty.json ani stan.json")
    else:
        storage.save()

    # Statystyki końcowe
    logger.info("=== Statystyki runu ===")
    logger.info("Zapytania Google (dorki): %s", stats["google_requests"])
    logger.info("Wyniki surowe: %s", stats["raw_results"])
    logger.info("Wyniki po deduplikacji (poddane filtrowi): %s", stats["after_dedup"])
    logger.info("Wyniki po filtrowaniu (nabór): %s", stats["after_filter"])
    logger.info("Nowe oferty dopisane: %s", stats["offers_added"])
    logger.info("Błędy ekstrakcji: %s", stats["extract_errors"])
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        logging.getLogger(__name__).exception("Nieprzechwycony wyjątek w potoku")
        sys.exit(1)
