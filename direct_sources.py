# -*- coding: utf-8 -*-
"""FAZA 0: bezpośredni skan źródeł (port z projektu rn-scrapper).

Dwie fazy bez wywołań wyszukiwarek:
  1. whitelist źródeł (ministerstwa, spółki SP, porty) - ogłoszenia o
     konkursach na członków rad nadzorczych MUSZĄ być publikowane na stronach
     spółek i właściwego ministra, więc czytamy te strony BEZPOŚREDNIO;
  2. rotacyjne okno BIP-ów samorządowych (rejestr data/bip_jst.json,
     ~1940 podmiotów) - każdy run skanuje inny fragment listy.

Zwraca wyniki w TYM SAMYM formacie co search_brave/search_ddg
({"title", "snippet", "link", "dork"}), żeby reszta potoku (filtr LLM,
ekstrakcja) działała bez zmian. Tekstem jest tekst kotwicy linku - jest
pre-filtrowany (RECRUITMENT_LINK_RE + RAD_NADZORCZA_RE), więc kandydaci
z domen *.gov.pl mogą pomijać filtr LLM (patrz heuristics.is_trusted_domain).
"""

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import heuristics

logger = logging.getLogger(__name__)

JST_WINDOW_DEFAULT = 100  # rozmiar dziennego okna skanu BIP-ów samorządowych

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) rn-dorking/3.0 "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
}

# Tekst kotwicy musi wskazywać nabór/konkurs i dotyczyć rady nadzorczej.
RECRUITMENT_LINK_RE = re.compile(
    r"nab[oó]r|konkurs|rekrutacj|kandydat|kandydatur|ogłoszen|zgłoszen", re.IGNORECASE)
RAD_NADZORCZA_RE = re.compile(r"nadzorcz", re.IGNORECASE)

# Podstrony-sekcje warte pogłębionego skanu (tylko ta sama domena)
SECTION_LINK_RE = re.compile(
    r"aktualnos|aktualnoś|wiadomos|komunikat|konkurs|nab[oó]r"
    r"|ogłoszen|ogloszen|relacje|karier",
    re.IGNORECASE)
MAX_SUBPAGES_PER_SOURCE = 2  # maks. podstron-sekcji skanowanych per źródło

# Adresy "nieustalone" w mapowaniu JST (slug gov.pl = przekierowanie do
# wewnętrznej wyszukiwarki, brak realnej strony BIP).
BAD_URLS = {"https://www.gov.pl", "http://www.gov.pl", "https://gov.pl"}


@dataclass(frozen=True)
class Source:
    """Jedno źródło do bezpośredniego przeszukiwania (whitelist)."""
    id: str          # krótki identyfikator techniczny
    name: str        # nazwa wyświetlana w logach
    url: str         # punkt startowy (strona główna lub sekcja aktualności)
    category: str    # 'ministerstwo' | 'spolka' | 'portal'
    verified: bool   # czy potwierdzono dostępność i właściwą encję


SOURCES: list = [
    # Ministerstwa / centra rządowe (obowiązek publikacji konkursów)
    Source("map",      "Ministerstwo Aktywów Państwowych",
           "https://www.gov.pl/web/aktywa-majatkowe/aktualnosci", "ministerstwo", True),
    Source("mf",       "Ministerstwo Finansów",
           "https://www.gov.pl/web/finanse/aktualnosci", "ministerstwo", False),
    Source("miklimat", "Ministerstwo Klimatu i Środowiska",
           "https://www.gov.pl/web/klimat/aktualnosci", "ministerstwo", False),
    Source("minfra",   "Ministerstwo Infrastruktury",
           "https://www.gov.pl/web/infrastruktura/aktualnosci", "ministerstwo", False),
    Source("mcyrfr",   "Ministerstwo Cyfryzacji",
           "https://www.gov.pl/web/cyfryzacja/aktualnosci", "ministerstwo", False),
    # Największe spółki Skarbu Państwa / z istotnym udziałem SP
    Source("orlen",    "ORLEN S.A.",
           "https://www.orlen.pl/pl/relacje-inwestorskie", "spolka", True),
    Source("gkpge",    "Grupa PGE", "https://www.gkpge.pl", "spolka", False),
    Source("tauron",   "TAURON Polska Energia", "https://www.tauron.pl", "spolka", True),
    Source("enea",     "Grupa Enea", "https://www.enea.pl", "spolka", False),
    Source("energa",   "Grupa Energa", "https://www.energa.pl", "spolka", False),
    Source("kghm",     "KGHM Polska Miedź", "https://kghm.com", "spolka", True),
    Source("plk",      "PKP Polskie Linie Kolejowe", "https://www.plk-sa.pl", "spolka", True),
    Source("pkpcargo", "PKP Cargo", "https://pkpcargo.com", "spolka", False),
    Source("intercity", "PKP Intercity", "https://www.intercity.pl", "spolka", False),
    Source("poczta",   "Poczta Polska", "https://www.poczta-polska.pl", "spolka", True),
    Source("pzu",      "Grupa PZU", "https://www.pzu.pl", "spolka", True),
    Source("gpw",      "GPW Warszawska Giełda Papierów Wartościowych",
           "https://www.gpw.pl", "spolka", True),
    Source("kdpw",     "KDPW", "https://www.kdpw.pl", "spolka", False),
    Source("bgk",      "Bank Gospodarstwa Krajowego", "https://www.bgk.pl", "spolka", True),
    Source("pkobp",    "PKO Bank Polski", "https://www.pkobp.pl", "spolka", False),
    Source("gazsystem", "Gaz-System", "https://www.gaz-system.pl", "spolka", False),
    Source("pse",      "Polskie Sieci Elektroenergetyczne", "https://www.pse.pl", "spolka", True),
    Source("pfr",      "Polski Fundusz Rozwoju", "https://pfr.pl", "spolka", False),
    Source("cpk",      "Centralny Port Komunikacyjny", "https://cpk.pl", "spolka", False),
    Source("wody",     "Wody Polskie", "https://www.wody.gov.pl", "spolka", False),
    Source("arp",      "ARP Industrial (Agencja Rozwoju Przemysłu)",
           "https://www.arpindustrial.pl", "spolka", False),
    # BIP-y największych miast
    Source("bip_krakow",   "BIP m.st. Kraków", "https://www.bip.krakow.pl", "bip", True),
    Source("bip_wroclaw",  "BIP m.st. Wrocław", "https://bip.wroclaw.pl", "bip", True),
    Source("bip_poznan",   "BIP m.st. Poznań", "https://bip.poznan.pl", "bip", True),
    Source("bip_bialystok", "BIP m.st. Białystok", "https://bip.bialystok.pl", "bip", True),
    # Porty morskie (samorządowe / spółki z udziałem państwa)
    Source("portgd",   "Zarząd Morskich Portów Gdańsk",
           "https://www.port.gdansk.pl", "spolka", False),
    Source("portgy",   "Zarząd Portów Gdynia", "https://www.port.gdynia.pl", "spolka", False),
    Source("portszcz", "Szczecińskie i Świnoujskie Porty",
           "https://port.szczecin.pl", "spolka", False),
]


def _fetch_html(url: str, timeout: int = 12) -> str | None:
    """Pobiera HTML strony. Przy błędzie SSL (częste na BIP-ach) ponawia bez
    weryfikacji certyfikatu. None przy niepowodzeniu."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=(6, timeout), verify=True)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        return resp.text
    except requests.exceptions.SSLError:
        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            resp = requests.get(url, headers=HEADERS, timeout=(6, timeout), verify=False)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            logger.debug("Pobrano bez weryfikacji SSL: %s", url)
            return resp.text
        except Exception as exc:
            logger.warning("Nie udało się pobrać (SSL) %s: %s", url, exc)
            return None
    except Exception as exc:
        logger.warning("Nie udało się pobrać %s: %s", url, exc)
        return None


def _candidate_links(soup, base_url: str, max_links: int) -> list[tuple[str, str]]:
    """Wyciąga ze sparsowanej strony linki-kandydatów (tekst kotwicy musi
    wskazywać nabór DOTYCZĄCY rady nadzorczej). Zwraca (tekst, absolutny URL)."""
    candidates: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        if not text or len(text) < 12:
            continue
        t = text.lower()
        if not RECRUITMENT_LINK_RE.search(t):
            continue
        if not RAD_NADZORCZA_RE.search(t):
            continue
        href = urljoin(base_url, a["href"].strip())
        if not href.startswith("http"):
            continue
        candidates.append((text, href))
        if len(candidates) >= max_links:
            break
    return candidates


def _load_jst_registry() -> list:
    """Rejestr BIP-ów samorządów z data/bip_jst.json (generator:
    tools/fetch_bip_registry.py). [] gdy brak/uszkodzony plik."""
    try:
        with open("data/bip_jst.json", encoding="utf-8") as f:
            reg = json.load(f)
        if isinstance(reg, list) and reg:
            return reg
    except FileNotFoundError:
        logger.warning("Brak data/bip_jst.json - faza JST pominięta "
                       "(uruchom tools/fetch_bip_registry.py)")
    except Exception as exc:
        logger.warning("Rejestr JST uszkodzony: %s", exc)
    return []


def _load_jst_urls() -> dict:
    """Mapowanie slug -> realny adres BIP (tools/resolve_bip_urls.py)."""
    try:
        with open("data/bip_jst_urls.json", encoding="utf-8") as f:
            m = json.load(f)
        if isinstance(m, dict):
            return m
    except FileNotFoundError:
        logger.warning("Brak data/bip_jst_urls.json - skanuję tylko wpisy "
                       "z bezpośrednim adresem (uruchom tools/resolve_bip_urls.py)")
    except Exception as exc:
        logger.warning("Mapa URL-i JST uszkodzona: %s", exc)
    return {}


def jst_daily_slice(registry: list, window: int = JST_WINDOW_DEFAULT) -> list:
    """Deterministyczne okno próbkowania: całości ~1940 podmiotów nie da się
    skanować przy każdym uruchomieniu, więc każdy przebieg bierze inne, ciągłe
    okno wpisów przesuwane według dnia roku (dzień * window % len)."""
    if not registry or window <= 0:
        return []
    if window >= len(registry):
        return list(registry)
    day = datetime.now().timetuple().tm_yday
    start = (day * window) % len(registry)
    if start + window <= len(registry):
        return registry[start:start + window]
    return registry[start:] + registry[:window - (len(registry) - start)]


def _collect_from_page(soup, base_url: str, max_links: int, dork_label: str,
                       seen: set, results: list) -> int:
    """Dopisuje kandydatów ze sparsowanej strony do results. Zwraca liczbę
    dodanych (po deduplikacji i odfiltrowaniu starych roczników)."""
    added = 0
    for anchor_text, url in _candidate_links(soup, base_url, max_links):
        if url in seen:
            continue
        seen.add(url)
        # Kotwica z rocznikiem starszym niż ubiegły = archiwalny nabór
        if heuristics.has_stale_years(anchor_text):
            logger.debug("[Faza 0] pomijam (stare): %.60s", anchor_text)
            continue
        results.append({
            "title": anchor_text,
            "snippet": anchor_text,
            "link": url,
            "dork": dork_label,
            "_direct": True,
        })
        added += 1
    return added


def _section_links(soup, base_url: str, max_subpages: int) -> list[str]:
    """Podstrony-sekcje (aktualności / konkursy / relacje / kariera) na TEJ
    SAMEJ domenie co źródło - warte pogłębionego skanu."""
    base_host = urlparse(base_url).netloc.lower()
    out: list[str] = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"].strip())
        if not href.startswith("http"):
            continue
        if urlparse(href).netloc.lower() != base_host:
            continue
        if href.rstrip("/") == base_url.rstrip("/"):
            continue
        haystack = f"{href} {a.get_text(' ', strip=True)}".lower()
        if SECTION_LINK_RE.search(haystack) and href not in out:
            out.append(href)
        if len(out) >= max_subpages:
            break
    return out


def _scan_entries(entries: list, dork_label: str, max_links_per_source: int,
                  delay: float, seen: set, results: list,
                  deep: bool = False) -> None:
    """Skanuje listę źródeł (whitelist lub JST) i dopisuje kandydatów
    do results (format zgodny z wyszukiwarkami). Gdy deep=True (whitelist),
    skanuje dodatkowo do MAX_SUBPAGES_PER_SOURCE podstron-sekcji źródła."""
    for src in entries:
        logger.info("[Faza 0:%s] %s → %s", dork_label, src["name"], src["url"])
        html = _fetch_html(src["url"])
        if not html:
            continue
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception as exc:
            logger.warning("[Faza 0:%s] błąd parsowania: %s", dork_label, exc)
            continue
        added = _collect_from_page(soup, src["url"], max_links_per_source,
                                   dork_label, seen, results)
        if deep:
            for sub_url in _section_links(soup, src["url"], MAX_SUBPAGES_PER_SOURCE):
                time.sleep(delay)
                sub_html = _fetch_html(sub_url)
                if not sub_html:
                    continue
                try:
                    sub_soup = BeautifulSoup(sub_html, "html.parser")
                except Exception:
                    continue
                added += _collect_from_page(sub_soup, sub_url,
                                            max_links_per_source,
                                            dork_label, seen, results)
        logger.info("[Faza 0:%s] %s → %s kandydatów", dork_label, src["name"], added)
        time.sleep(delay)


def collect(max_links_per_source: int = 3, delay: float = 0.5,
            jst_window: int = JST_WINDOW_DEFAULT) -> list[dict]:
    """FAZA 0: whitelist + rotacyjne okno JST. Zwraca listę wyników
    ({"title", "snippet", "link", "dork", "_direct": True})."""
    results: list[dict] = []
    seen: set = set()

    # Faza 0a: whitelist źródeł (ministerstwa / spółki SP / porty / duże miasta)
    # deep=True: dodatkowy skan podstron-sekcji (aktualności / konkursy / relacje)
    entries = [{"id": s.id, "name": s.name, "url": s.url} for s in SOURCES]
    _scan_entries(entries, "źródło bezpośrednie", max_links_per_source,
                  delay, seen, results, deep=True)
    logger.info("Faza 0a (whitelist): %s kandydatów", len(results))

    # Faza 0b: rotacyjne okno BIP-ów samorządowych
    registry = _load_jst_registry()
    if registry:
        urls_map = _load_jst_urls()
        for e in registry:
            real = urls_map.get(e.get("slug", ""))
            if real:
                e["url"] = real
        window = jst_daily_slice(registry, window=jst_window)
        usable = [e for e in window
                  if e.get("url") and e["url"].rstrip("/") not in BAD_URLS]
        skipped = len(window) - len(usable)
        if skipped:
            logger.warning("Faza 0b: pominięto %s/%s wpisów JST bez realnego "
                           "adresu BIP - uruchom tools/resolve_bip_urls.py.",
                           skipped, len(window))
        logger.info("Faza 0b: JST - okno dzienne %s/%s podmiotów (%s do skanu)",
                    len(window), len(registry), len(usable))
        before = len(results)
        _scan_entries(usable, "BIP JST", max_links_per_source=1,
                      delay=delay, seen=seen, results=results)
        logger.info("Faza 0b (JST): %s kandydatów", len(results) - before)

    return results


if __name__ == "__main__":
    # Self-test - pobiera strony źródeł (sieć), bez kluczy API
    import sys
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    if sys.stdout.reconfigure:
        sys.stdout.reconfigure(encoding="utf-8")
    for r in collect(jst_window=20):
        print(f"- {r['title'][:80]} | {r['link']}")