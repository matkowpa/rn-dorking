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

# BIP-y samorządowe: strona główna to zwykle "Dane podstawowe" z menu
# podmiotowym - ogłoszenia o naborach leżą w sekcjach (aktualności, konkursy).
# Bez pogłębionego skanu rotacja JST dawała 0 kandydatów.
JST_DEEP_SCAN = True
JST_MAX_LINKS = 2          # dziennie wystarczą 1-2 ogłoszenia na podmiot
JST_SECTION_HINTS = ("menu-przedmiotowe", "ogloszen", "ogłoszen", "konkurs",
                     "nabor", "nabór", "aktualnosci", "aktualności")

# Adresy "nieustalone" w mapowaniu JST (slug gov.pl = przekierowanie do
# wewnętrznej wyszukiwarki, brak realnej strony BIP).
BAD_URLS = {"https://www.gov.pl", "http://www.gov.pl", "https://gov.pl"}

# Domy portalu rządowego. Link do gov.pl/<slug> to strona gminy na portalu,
# NIE BIP: w 2026-10 było tam 824/1106 wpisów rejestru (75%) i skanowanie ich
# dawało zero kandydatów - strona gminy nie linkuje ogłoszeń o naborach.
PORTAL_HOSTS = ("gov.pl", "www.gov.pl")


def is_portal_url(url: str) -> bool:
    """Czy URL prowadzi do portalu gov.pl zamiast do realnej strony BIP.

    Wyjątkiem są ścieżki /web/bip/ - to faktyczne BIP-y hostowane na gov.pl,
    które mają własną strukturę i warto je skanować.
    """
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host not in PORTAL_HOSTS:
        return False
    return not parsed.path.startswith("/web/bip")


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


def jst_daily_slice(registry: list, window: int = JST_WINDOW_DEFAULT,
                    day_of_year: int | None = None) -> list:
    """Deterministyczne okno próbkowania rejestru JST.

    Każdy przebieg bierze inne, ciągłe okno wpisów. Okno przesuwa się o swoją
    długość, ale start liczymy modulo LICZBA OKIEN, nie modulo długość listy
    (poprzednia wersja: `(day * window) % len(registry)` - gdy okno nie dzieli
    listy bez reszty, część wpisów była pomijana w cyklu, a inne odwiedzane
    dwa razy). Teraz kolejne dni przechodzą przez wszystkie okna po kolei,
    a po wyczerpaniu cyklu wracamy na początek.
    """
    if not registry or window <= 0:
        return []
    if window >= len(registry):
        return list(registry)
    day = day_of_year if day_of_year is not None else datetime.now().timetuple().tm_yday
    n_windows = -(-len(registry) // window)          # ceil - liczba okien
    idx = (day - 1) % n_windows
    start = idx * window
    end = start + window
    # Ostatnie okno przy niedzielnej długości rejestru wychodzi za koniec listy
    # (10 wpisów / okno 3 -> start 9 daje 1 wpis). Zawijamy je na początek, żeby
    # KAŻDE okno miało dokładnie `window` wpisów; inaczej w co n-ty dzień skan
    # po cichu obejmuje kilka podmiotów zamiast pełnego okna.
    if end <= len(registry):
        return registry[start:end]
    return registry[start:] + registry[:end - len(registry)]


def looks_like_notice_url(url: str) -> bool:
    """Czy URL prowadzi do KONKRETNEGO wpisu ogłoszenia, a nie do menu.

    Audyt bazy (2026-10-21) pokazał, że 47% wpisów to strony nawigacyjne BIP,
    a 23% to martwe linki. Powód: _collect_from_page brała każdy link z kotwicą
    "nabór + nadzorcz", a takie kotwice wiszą w menu, sidebary i działach.

    Wpis ogłoszenia ma w adresie identyfikator:
      - BIP24:      /12345/slug-ogloszenia
      - bip.net.pl: ?a=12345
      - bip.org.pl: /artykul/12345/slug
    Odrzucamy też adresy techniczne (edycja, porównywanie wersji, wydruk,
    pobieranie pliku) - to nie ogłoszenia.
    """
    if not url:
        return False
    lowered = url.lower()
    if _TECH_URL_RE.search(lowered):
        return False
    if _NOTICE_ID_RE.search(url):
        return True
    # CMS-y bez numeru w adresie: dla znanych domen wystarcza sam slug wpisu
    host = urlparse(url).netloc.lower()
    if any(host.endswith(h) for h in SLUG_NOTICE_HOSTS):
        return bool(_SLUG_PATH_RE.search(url))
    return False


# Parametry/ścieżki techniczne: podgląd wydruku, porównywanie wersji,
# pobieranie załącznika, koszyk/edycja CMS.
_TECH_URL_RE = re.compile(
    r"(?:[?&](?:print|printd|wydruk|porownaj|diff|version|edit|podglad)=)"
    r"|/porownaj/"
    r"|/plik,"
    r"|/files/download"
    r"|\.pdf(?:\?|$)"
    r"|\.docx?(?:\?|$)",
    re.IGNORECASE)

# Identyfikator wpisu w adresie
_NOTICE_ID_RE = re.compile(
    r"/\d{2,6}/[a-z0-9\-]{6,}"           # BIP24: /12345/slug
    r"|[?&]a=\d{3,6}"                    # bip.net.pl: ?a=12345
    r"|/artykul/[a-z0-9\-]{6,}"          # bip.org.pl: /artykul/ogloszenie-o-naborze
    r"|/artykul/\d+"                     # bip.org.pl: /artykul/12345
    r"|/aktualnosci/\d+"                 # strony gmin: /aktualnosci/12345
    r"|/news/\d+"
    r"|/news/content/\d+"                # gminy: /news/content/20202
    r"|/articles?/[a-z0-9\-]{6,}"        # ogolne CMS: /article/nabor-do-bazy
    r"|/archives/\d+"                    # wordpress: /archives/68605
    r"|/tenders?/[a-z0-9\-]{6,}"         # portale przetargowe: /tenders/vidkrytyy-vidbir
    r"|/documents?/detail",              # me.gov.ua: /Documents/Detail/<uuid>
    re.IGNORECASE)


# Domy, w których artykuł = konkretny wpis (a nie dział "aktualności").
# Dla tych domen sam segment /aktualnosci/<slug> wystarcza za dowód wpisu,
# nawet gdy CMS nie wstawia numeru.
SLUG_NOTICE_HOSTS = (
    "bip.powiatbytowski.pl", "powiatraciborski.pl", "tarnow.pl",
    "brzeszcze.pl", "piastow.pl", "skoczow.pl", "goldap.pl",
    "niepelnosprawni.gov.pl", "pion.pl", "parkiet.com", "mazovia.pl",
)
_SLUG_PATH_RE = re.compile(
    r"/(?:aktualnosci|artykul|article|ogloszenie|ogloszenia|nabor|nabor-y|"
    r"news|komunikaty|strony)/[a-z0-9\-\.]{8,}"
    # gov.pl i CMS-y bez prefiksu: sam slug ze słowem "ogloszenie"/"nabor"
    r"|/[a-z0-9\-\.]{0,40}(?:ogloszenie|nabor)[a-z0-9\-\.]{8,}",
    re.IGNORECASE)


def _collect_from_page(soup, base_url: str, max_links: int, dork_label: str,
                       seen: set, results: list) -> int:
    """Dopisuje kandydatów ze sparsowanej strony do results. Zwraca liczbę
    dodanych (po deduplikacji i odfiltrowaniu starych roczników).

    Przyjmuje wyłącznie linki prowadzące do konkretnego wpisu (patrz
    looks_like_notice_url) - menu i dział nie są ogłoszeniem, choć mają
    identyczną kotwicę.
    """
    added = 0
    for anchor_text, url in _candidate_links(soup, base_url, max_links):
        if url in seen:
            continue
        seen.add(url)
        if not looks_like_notice_url(url):
            logger.debug("[Faza 0] pomijam (nie wpis, %s): %.60s", dork_label, url)
            continue
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
    """Podstrony-sekcje warte pogłębionego skanu (NA TEJ SAMEJ domenie).

    Szuka dwóch rzeczy:
    - sekcji o nazwie sugerującej ogłoszenia (aktualności, konkursy, relacje,
      kariera) - wspólne dla wszystkich systemów BIP;
    - menu podmiotowego/przedmiotowego systemu BIP24, które jest jedynym
      wejściem do działu "Ogłoszenia o naborach" na tych stronach.

    Sekcje z ogłoszeniami mają priorytet nad menu - inaczej limit podstron
    zjadałby samo menu.
    """
    base_host = urlparse(base_url).netloc.lower()
    priority: list[str] = []   # linki z frazą "ogłoszen/nabór/konkurs"
    fallback: list[str] = []   # menu podmiotowe / przedmiotowe
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"].strip())
        if not href.startswith("http"):
            continue
        if urlparse(href).netloc.lower() != base_host:
            continue
        if href.rstrip("/") == base_url.rstrip("/"):
            continue
        haystack = f"{href} {a.get_text(' ', strip=True)}".lower()
        if not SECTION_LINK_RE.search(haystack):
            if any(h in haystack for h in ("menu-podmiotowe", "menu-przedmiotowe")):
                if href not in fallback:
                    fallback.append(href)
            continue
        if href not in priority:
            priority.append(href)
    out = priority[:max_subpages]
    if len(out) < max_subpages:
        out += [u for u in fallback if u not in out][:max_subpages - len(out)]
    return out


def _scan_entries(entries: list, dork_label: str, max_links_per_source: int,
                  delay: float, seen: set, results: list,
                  deep: bool = False, max_subpages: int = 0) -> None:
    """Skanuje listę źródeł (whitelist lub JST) i dopisuje kandydatów
    do results (format zgodny z wyszukiwarkami). Gdy deep=True, skanuje
    dodatkowo podstrony-sekcje źródła (max_subpages, domyślnie
    MAX_SUBPAGES_PER_SOURCE).

    Dla JST deep=True jest kluczowe: strona główna BIP to "Dane podstawowe"
    z menu podmiotowym, a ogłoszenia leżą w sekcjach - bez tego skan dawał
    zero kandydatów (analiza 2026-10-21).
    """
    if max_subpages <= 0:
        max_subpages = MAX_SUBPAGES_PER_SOURCE
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
            subpages = _section_links(soup, src["url"], max_subpages)
            for sub_url in subpages:
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
            jst_window: int = JST_WINDOW_DEFAULT,
            stats: dict | None = None) -> list[dict]:
    """FAZA 0: whitelist + rotacyjne okno JST. Zwraca listę wyników
    ({"title", "snippet", "link", "dork", "_direct": True}).

    Gdy przekazano `stats`, uzupełnia rozbicie: direct_whitelist,
    direct_jst, jst_skipped_portal - dzięki temu wiadomo, która ścieżka
    faktycznie daje wyniki (wcześniej direct_results mieszał obie).
    """
    results: list[dict] = []
    seen: set = set()

    # Faza 0a: whitelist źródeł (ministerstwa / spółki SP / porty / duże miasta)
    # deep=True: dodatkowy skan podstron-sekcji (aktualności / konkursy / relacje)
    entries = [{"id": s.id, "name": s.name, "url": s.url} for s in SOURCES]
    _scan_entries(entries, "źródło bezpośrednie", max_links_per_source,
                  delay, seen, results, deep=True)
    if stats is not None:
        stats["direct_whitelist"] = len(results)
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
                  if e.get("url") and e["url"].rstrip("/") not in BAD_URLS
                  and not is_portal_url(e["url"])]
        skipped = len(window) - len(usable)
        portal = sum(1 for e in window if e.get("url") and is_portal_url(e["url"]))
        if stats is not None:
            stats["jst_skipped_portal"] = portal
        if skipped:
            logger.warning(
                "Faza 0b: pominięto %s/%s wpisów JST (%s to linki do portalu "
                "gov.pl, nie BIP) - uruchom tools/resolve_bip_urls.py.",
                skipped, len(window), portal)
        logger.info("Faza 0b: JST - okno dzienne %s/%s podmiotów (%s do skanu)",
                    len(window), len(registry), len(usable))
        before = len(results)
        _scan_entries(usable, "BIP JST", max_links_per_source=JST_MAX_LINKS,
                      delay=delay, seen=seen, results=results,
                      deep=JST_DEEP_SCAN, max_subpages=MAX_SUBPAGES_PER_SOURCE)
        if stats is not None:
            stats["direct_jst"] = len(results) - before
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