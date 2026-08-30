# -*- coding: utf-8 -*-
"""Orkiestrator potoku A->B->C (ETAP 5). Jedyne wejście CLI."""

import argparse
import logging
import sys
import time
from datetime import date

if hasattr(sys.stdout, "reconfigure"):
    # Konsola Windows: uniknij UnicodeEncodeError przy polskich znakach
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import config
import direct_sources
import heuristics
from content_fetcher import fetch_content
from llm_parser import extract_fields, filter_is_announcement, rejects_zarzad
from storage import Storage

logger = logging.getLogger(__name__)


def _search(dork: str, days_back: int):
    """Wyszukiwanie: łańcuch zapasowy Brave -> DuckDuckGo.

    Zwraca (lista_wyników, nazwa_backendu). Gdy Brave zwróci błąd lub 0
    wyników, dla tego dorka użyty zostaje darmowy backend DuckDuckGo.
    """
    if config.use_brave():
        from brave_search import search_brave
        time.sleep(1)  # ostrożny odstęp między zapytaniami do Brave
        results = search_brave(dork, days_back, config.RESULTS_PER_DORK)
        if results:
            return results, "Brave"
        logger.warning("Brave: brak wyników dla dorka %s - fallback na DuckDuckGo",
                       dork)
    from ddg_search import search_ddg
    time.sleep(1)  # odstęp między dorkami zmniejsza rate-limit DDG
    results = search_ddg(dork, days_back, config.RESULTS_PER_DORK)
    return results, "DuckDuckGo"


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
        "search_requests": 0,
        "raw_results": 0,
        "direct_results": 0,
        "after_dedup": 0,
        "after_filter": 0,
        "offers_added": 0,
        "extract_errors": 0,
        "offers_updated": 0,
    }

    # Re-ekstrakcja: oferty bez terminu z poprzednich dni - spróbuj ponownie
    # (treść BIP często pojawia się z opóźnieniem albo w załączniku PDF;
    # maks. MAX_EXTRACT_ATTEMPTS prób na ofertę, pilnuje storage)
    if not args.dry_run:
        candidates = storage.get_reextract_candidates(5)
        if candidates:
            logger.info("Re-ekstrakcja: %s ofert bez terminu", len(candidates))
        for cand in candidates:
            url = cand.get("url", "")
            text, _ = fetch_content(url)
            offer = extract_fields(text, url) if text else None
            storage.mark_extract_attempt(url)
            if offer and offer.get("termin_skladania_ofert"):
                if storage.update_offer(url, offer):
                    stats["offers_updated"] += 1
                    logger.info("Re-ekstrakcja: uzupełniono termin %s: %s",
                                offer.get("termin_skladania_ofert"),
                                offer.get("podmiot", ""))
            time.sleep(0.5)

    # ETAP A: wyszukiwanie dla wszystkich dorków (Brave / DuckDuckGo)
    backend = "Brave" if config.use_brave() else "DuckDuckGo"
    if backend == "DuckDuckGo":
        logger.warning(
            "Brak BRAVE_API_KEY w .env - używam DuckDuckGo (niższa jakość "
            "wyników). Dodaj BRAVE_API_KEY dla produkcji."
        )
    # Brave potrzebuje własnych dorków (bez inurl:/filetype:/site:)
    if backend == "Brave":
        from brave_search import BRAVE_DORKS
        dorks = BRAVE_DORKS
    else:
        from ddg_search import DORKS
        dorks = DORKS
    # Dodatkowe dorki z .env (EXTRA_DORKS, oddzielone |) - np. per konkretny BIP:
    # EXTRA_DORKS=site:bip.grudziadz.pl "rady nadzorczej"|site:bip.skoczow.pl nabór
    if config.EXTRA_DORKS:
        logger.info("Dopisuję %s dorków z EXTRA_DORKS", len(config.EXTRA_DORKS))
        dorks = dorks + config.EXTRA_DORKS
    all_results: list[dict] = []
    for dork in dorks:
        logger.info("Wyszukiwanie (%s): dork=%s", backend, dork)
        results, _ = _search(dork, days_back)
        stats["search_requests"] += 1
        all_results.extend(results)

    # FAZA 0: bezpośredni skan źródeł (whitelist + rotacyjne okno BIP JST).
    # Kandydaci są pre-filtrowani po tekście kotwicy linku, więc NIE liczą się
    # do limitu --limit; wynikom z domen *.gov.pl pomijamy filtr LLM.
    try:
        direct = direct_sources.collect(jst_window=config.JST_WINDOW)
    except Exception as e:
        logger.error("Faza 0 (źródła bezpośrednie) nieudana: %s", e)
        direct = []
    stats["direct_results"] = len(direct)
    all_results = direct + all_results

    stats["raw_results"] = len(all_results)

    # ETAP B: deduplikacja, filtr LLM (z limitem --limit na nowych wynikach)
    dry_run_rows: list[tuple[str, bool, str]] = []
    new_processed = 0
    for result in all_results:
        is_direct = bool(result.get("_direct"))
        # Kandydaci ze źródeł bezpośrednich nie zużywają limitu --limit
        if not is_direct and new_processed >= args.limit:
            break
        link = result.get("link", "")
        if not link or storage.is_rejected(link):
            # Odrzucony wcześniej (w oknie TTL) - nie liczy się do limitu
            continue
        if not storage.is_new(link):
            # Już widziany - nie liczy się do limitu
            continue
        if not is_direct:
            new_processed += 1
        stats["after_dedup"] += 1
        title = result.get("title", "")
        snippet = result.get("snippet", "")
        # Tanie heurystyki pre-LLM: agregatory, artykuły/poradniki, treści
        # edukacyjne, zakończone nabory i archiwalne roczniki (bez wywołania LLM)
        odrzucony, powod = heuristics.prefilter_reject(title, snippet, link)
        if odrzucony:
            czy_nabor, uzasadnienie = False, powod
        elif is_direct and heuristics.is_trusted_domain(link):
            # Kotwica "ogłoszenie o naborze..." na BIP *.gov.pl jest formalnym
            # ogłoszeniem - filtr LLM zbędny (port z rn-scrapper)
            czy_nabor, uzasadnienie = True, \
                "domena urzędowa (*.gov.pl), źródło bezpośrednie"
        # Tani pre-filtr: nabór na stanowiska zarządu (bez wzmianki o radzie
        # nadzorczej) odrzucamy bez wywołania LLM - oszczędność kosztu i czasu.
        elif rejects_zarzad(title, snippet):
            czy_nabor, uzasadnienie = False, "nabór na zarząd, nie na radę nadzorczą"
        else:
            czy_nabor, uzasadnienie = filter_is_announcement(title, snippet, link)
        stats["after_filter"] += 1 if czy_nabor else 0

        if args.dry_run:
            dry_run_rows.append((title, czy_nabor, uzasadnienie))
        elif czy_nabor:
            # ETAP C: pobranie treści + ekstrakcja
            text, pub_date = fetch_content(link)
            if not text:
                logger.info("Brak treści (użyto snippetu): %s", link)
                text = snippet
            offer = extract_fields(text, link)
            if offer is None:
                stats["extract_errors"] += 1
            else:
                offer["data_publikacji"] = pub_date
                # Filtr świeżości: znany termin w przeszłości = archiwalne,
                # pomijamy ("" = termin nieznany - zostaje)
                termin = offer.get("termin_skladania_ofert", "")
                if termin:
                    try:
                        if date.fromisoformat(termin) < date.today():
                            logger.info(
                                "Pomijam archiwalną ofertę (termin %s): %s",
                                termin, offer.get("podmiot", ""))
                            continue
                    except ValueError:
                        pass  # termin w nietypowym formacie - zostaw
                storage.add_offer(offer)
                stats["offers_added"] += 1
                logger.info("Nowa oferta: podmiot=%s termin=%s",
                            offer.get("podmiot", ""), offer.get("termin_skladania_ofert", ""))
        else:
            # Odrzucone przez filtr - zapamiętaj, żeby nie marnować wywołań
            # filtra przy kolejnych runach (chyba że to chwilowy błąd LLM)
            if not uzasadnienie.startswith("błąd filtra"):
                storage.add_rejected(link)
        # Mały odstęp między wywołaniami LLM (mniejsza szansa na rate limit)
        time.sleep(0.5)

    if args.dry_run:
        print(f"{'tytuł':<60} | {'nabór':<5} | uzasadnienie")
        for title, czy_nabor, uzasadnienie in dry_run_rows:
            print(f"{title[:60]:<60} | {'TAK' if czy_nabor else 'NIE':<5} | {uzasadnienie}")
        logger.info("Tryb dry-run: nie zapisano oferty.json ani stan.json")
    else:
        storage.save()
        storage.save_daily(stats)

    # Statystyki końcowe
    logger.info("=== Statystyki runu ===")
    logger.info("Kandydaci ze źródeł bezpośrednich (Faza 0): %s", stats["direct_results"])
    logger.info("Zapytania wyszukiwarki (dorki): %s", stats["search_requests"])
    logger.info("Wyniki surowe: %s", stats["raw_results"])
    logger.info("Wyniki po deduplikacji (poddane filtrowi): %s", stats["after_dedup"])
    logger.info("Wyniki po filtrowaniu (nabór): %s", stats["after_filter"])
    logger.info("Nowe oferty dopisane: %s", stats["offers_added"])
    logger.info("Błędy ekstrakcji: %s", stats["extract_errors"])
    logger.info("Uzupełnione terminy (re-ekstrakcja): %s", stats["offers_updated"])
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        logging.getLogger(__name__).exception("Nieprzechwycony wyjątek w potoku")
        sys.exit(1)
