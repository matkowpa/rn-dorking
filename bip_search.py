# -*- coding: utf-8 -*-
"""R2: wyszukiwarka treści na stronach BIP (zamiast łażenia po linkach).

Problem: żeby znaleźć ogłoszenie o naborze na BIP-ie, trzeba zgadnąć, w której
sekcji ono leży. BIP24 ma jednak wbudowaną wyszukiwarkę pełnotekstową
(`?szukaj=...`), która zwraca wpisy z każdego działu. Podobnie działają
systemy bip.org.pl, bip.net.pl i finn.pl.

Ten moduł nie próbuje odgadnąć API każdego systemu: wysyła zapytanie pod
kilka znanych wzorców URL-a, sprawdza, czy odpowiedź faktycznie różni się od
strony głównej (system, który szukania nie wspiera, po prostu zwraca stronę
główną - to trzeba odsiać), i wyciąga linki do wpisów.

Wynik ma ten sam format co reszta Fazy 0, więc wchodzi do potoku bez zmian.
"""

import json
import logging
import re
import time
from urllib.parse import quote_plus, urlparse

import requests
from bs4 import BeautifulSoup

import direct_sources

logger = logging.getLogger(__name__)

# Frazy szukane na BIP-ach. Jedna fraza na zapytanie - systemy BIP-owe źle
# obsługują zapytania wielowyrazowe w cudzysłowie.
QUERIES = [
    "nabór rady nadzorczej",
    "członek rady nadzorczej",
    "postępowanie kwalifikacyjne rada nadzorcza",
]

# Wzorce URL-a wyszukiwarki: (nazwa systemu, szablon z {q}).
# Kolejność ma znaczenie - najpierw te, które znamy jako działające.
SEARCH_PATTERNS = [
    ("BIP24", "/?szukaj={q}"),
    ("BIP24-alt", "/szukaj/{q}"),
    ("bip.org.pl", "/search?query={q}"),
    ("bip.net.pl", "/?s={q}"),
    ("finn", "/szukaj?q={q}"),
]

# Działy "ogłoszenia o naborach" w systemach, które nie mają wyszukiwarki
# pełnotekstowej (BIP24, bip.net.pl). Rozpoznawane po tekście linku w menu.
NOTICE_SECTION_RE = re.compile(
    r"ogłoszenia o naborze|ogloszenia o naborze|ogłoszenia i komunikaty|"
    r"ogloszenia i komunikaty|nabór pracowników|nabory i konkursy|"
    r"konkursy na stanowiska|ogłoszenia o konkursach",
    re.IGNORECASE)

# Link do wpisu w poszczególnych systemach:
#   BIP24:         /<id>/<slug>
#   bip.net.pl:    ?a=<id>
#   bip.org.pl:    /artykul/<id>/... albo ?a=<id>
ENTRY_HREF_RE = re.compile(r"/(\d{2,6})/[a-z0-9\-]{8,}|[?&]a=\d{3,6}", re.IGNORECASE)

# Nagłówki typowych ODPOWIEDZI-aplikacji, a nie merytorycznej treści:
# "Ogłoszenie o konsultacjach projektu uchwały", "Zarządzenie Nr 271/2026",
# "Uchwała Nr XXX/194/2026", "XXXI sesja Rady Miejskiej". Dział "Ogłoszenia
# o naborze" w praktyce zawiera też te dokumenty - odpadać muszą, bo to nie
# nabory do rady nadzorczej.
NON_RECRUIT_RE = re.compile(
    r"konsultacj|projekt uchwały|projektu uchwały|zarządzeni[ae] nr|"
    r"uchwał[ae] nr|sesj[ai] rady|obwieszczeni|zawiadomieni|decyzj[ai]|"
    r"postanowieni|protokół|sprawozdani|rozstrzygnięcie|interpelacj|"
    r"zapytani|wniosk[ui]|skarg|petycj|budżet|wieloletni|plan finansow",
    re.IGNORECASE)

# Frazy wskazujące, że to jest nabór (jako uzupełnienie braku "rady nadzorczej"
# w tytule - część gmin tytułuje wpisy "Ogłoszenie Nr OOD.2110.3.2026").
RECRUIT_TITLE_RE = re.compile(
    r"nab[oó]r|kandydat|konkurs|post[eę]powani[ea] kwalifikacyjn|rekrutacj",
    re.IGNORECASE)
RECRUIT_RE = re.compile(
    r"nab[oó]r|kandydat|konkurs|post[eę]powanie kwalifikacyjne", re.IGNORECASE)
RN_RE = re.compile(r"rad[yęae]?\s+nadzorcz|rady nadzorczej", re.IGNORECASE)

# Ile linków maksymalnie z jednej strony wyników
MAX_ENTRIES_PER_QUERY = 5


def _fetch(url: str, timeout: int = 15) -> str | None:
    """Pobiera HTML z nagłówkami przeglądarki (BIP-y blokują domyślne UA)."""
    try:
        resp = requests.get(url, headers=direct_sources.HEADERS,
                            timeout=(6, timeout))
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        return resp.text
    except requests.exceptions.SSLError:
        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            resp = requests.get(url, headers=direct_sources.HEADERS,
                                timeout=(6, timeout), verify=False)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text
        except Exception:
            return None
    except Exception:
        return None


def _text_signature(soup) -> str:
    """Sygnatura treści strony - do wykrycia, czy wyszukiwarka zadziałała."""
    return " ".join(soup.get_text(" ", strip=True).split())[:2000]


def _looks_like_homepage(query: str, soup) -> bool:
    """Czy odpowiedź to po prostu strona główna (wyszukiwarka ignorowana).

    System, który nie wspiera `?szukaj=`, zwraca normalną stronę startową.
    Rozpoznajemy to po braku jakiegokolwiek słowa z zapytania w treści.
    """
    text = _text_signature(soup).lower()
    words = [w for w in query.lower().split() if len(w) > 4]
    return not any(w in text for w in words)


def _extract_entries(soup, base_url: str) -> list[tuple[str, str]]:
    """Wyciąga linki do wpisów wyglądających na ogłoszenie o naborze na RN.

    Działa w dwóch trybach, bo systemy BIP różnią się radykalnie:
    - strona wyników wyszukiwania: linki mają już w tytule "nabór" i "rady
      nadzorczej", więc wymagamy obu fraz;
    - dział "Ogłoszenia o naborze": tytuły wpisów to często tylko
      "Ogłoszenie Nr OOD.2110.3.2026 Burmistrza...", bez słowa "nabór".
      Wtedy wystarczy, że link jest wpisem (ma ID) - dział jest już
      wstępnie przefiltrowany przez NOTICE_SECTION_RE.
    """
    out: list[tuple[str, str]] = []
    seen: set = set()
    host = urlparse(base_url).netloc.lower()
    in_notice_section = _is_notice_section_url(base_url)
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        if not text or len(text) < 12:
            continue
        # Tytuł wpisu w bip.net.pl bywa schowany za linkiem "Czytaj dalej";
        # bierzemy otaczający tekst, żeby nazwa ogłoszenia nie przepadła.
        title = _entry_title(a, text)
        href = a["href"].strip()
        if not href.startswith("http"):
            from urllib.parse import urljoin
            href = urljoin(base_url, href)
        if urlparse(href).netloc.lower() != host:
            continue
        if href in seen:
            continue
        if not ENTRY_HREF_RE.search(href):
            continue          # menu/sekcja, nie wpis
        if NON_RECRUIT_RE.search(title):
            continue          # uchwała/zarządzenie/konsultacje, nie nabór
        if not in_notice_section:
            haystack = f"{title} {href}"
            if not (RECRUIT_RE.search(haystack) and RN_RE.search(haystack)):
                continue
        elif not RN_RE.search(title) and not RECRUIT_TITLE_RE.search(title):
            # Dział ogłoszeń: tytuł bez "rady nadzorczej" bywa skrótowy
            # ("Ogłoszenie Nr OOD.2110.3.2026"), ale musi mieć choć ślad naboru.
            continue
        seen.add(href)
        out.append((title, href))
        if len(out) >= MAX_ENTRIES_PER_QUERY:
            break
    return out


# Adresy działów "ogłoszenia o naborach" w znanych systemach BIP.
# BIP24 i bip.net.pl nie mają działającej wyszukiwarki pełnotekstowej
# (parametr jest ignorowany, wraca strona główna), ale mają stałe działy.
NOTICE_SECTION_PATHS = {
    "bip.net.pl": ["?c=230"],       # "Ogłoszenia o naborze"
    "bip24": [],                    # tytuł działu zależy od gminy - szukamy po tekście
}

GENERIC_LINK_TEXT = {
    "czytaj dalej", "więcej", "wiecej", "czytaj więcej", "zobacz", "pokaż",
    "szczegóły", "szczegoly", "zobacz więcej", "przejdź",
}


def _entry_title(anchor, fallback: str) -> str:
    """Tytuł wpisu: własny tekst linku, a gdy ogólny ("Czytaj dalej") -
    najbliższy poprzedzający nagłówek/akapit z treścią."""
    text = fallback.strip()
    if text.lower() not in GENERIC_LINK_TEXT:
        return text
    node = anchor
    for _ in range(6):          # kilka poziomów w górę drzewa DOM
        node = node.parent
        if node is None:
            break
        candidate = node.get_text(" ", strip=True)
        candidate = candidate.replace(text, " ", 1).strip()
        if len(candidate) >= 15:
            return candidate[:200]
    return text


def _is_notice_section_url(url: str) -> bool:
    """Czy URL to dział ogłoszeń (a nie strona wyników wyszukiwania).

    Dział ogłoszeń obsługujemy łagodniej: tytuły wpisów bywają bez słowa
    "nabór" (np. "Ogłoszenie Nr OOD.2110.3.2026 Burmistrza"), bo dział jest
    już sam w sobie przefiltrowany. Dlatego rozpoznajemy też `?c=` - tak
    numerowane są działy w bip.net.pl - oraz ścieżki /N/ogloszenia-...
    """
    lowered = url.lower()
    if "szukaj" in lowered or "?s=" in lowered:
        return False
    if "c=" in lowered and "a=" not in lowered:
        return True          # bip.net.pl: ?c=230 = dział "Ogłoszenia o naborze"
    return any(tok in lowered for tok in (
        "ogloszenia-o-naborze", "ogloszenia_o_naborze", "ogloszenia-i-komunikaty",
        "nabor", "konkurs"))


def _find_notice_sections(soup, base_url: str) -> list[str]:
    """Adresy działów "Ogłoszenia o naborze".

    Najpierw znane adresy systemu (bip.net.pl: ?c=230), potem linki z menu,
    których tekst wskazuje na ogłoszenia o naborach. BIP24 nie ma stałego
    adresu - tytuł działu zależy od gminy ("Ogłoszenia i komunikaty",
    "Nabory i konkursy"), więc zostaje wyszukiwanie po tekście linku.
    """
    from urllib.parse import urljoin
    host = urlparse(base_url).netloc.lower()
    root = base_url.rstrip("/")
    found: list[str] = []

    # 1. Znane adresy działów - tylko dla domeny systemu, którego dotyczą.
    # ?c=230 istnieje wyłącznie w bip.net.pl; na innych BIP-ach to śmieć.
    for system, paths in NOTICE_SECTION_PATHS.items():
        if system not in host:
            continue
        for path in paths:
            candidate = (root + path) if path.startswith("/") else (root + "/" + path)
            if candidate not in found:
                found.append(candidate)

    # 2. Działy rozpoznane po tekście linku w menu
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        if not text or not NOTICE_SECTION_RE.search(text):
            continue
        href = urljoin(base_url, a["href"].strip())
        if urlparse(href).netloc.lower() != host:
            continue
        # Dedup: ten sam dział może przyjść z NOTICE_SECTION_PATHS i z menu.
        # Porównujemy ścieżkę z zapytaniem bez wiodącego ukośnika - dział bywa
        # podawany raz jako "/?c=230", a raz jako "?c=230".
        def _path_key(u: str) -> str:
            parsed = urlparse(u)
            key = (parsed.path or "/") + ("?" + parsed.query if parsed.query else "")
            return key.lstrip("/")

        if any(_path_key(href) == _path_key(f) for f in found):
            continue
        if href not in found:
            found.append(href)
    return found[:2]


def _scan_notice_sections(base_url: str, root_html: str,
                          delay: float = 0.4) -> list[dict]:
    """Wchodzi w dział ogłoszeń i zbiera linki do wpisów."""
    try:
        soup = BeautifulSoup(root_html, "html.parser")
    except Exception:
        return []
    results: list[dict] = []
    seen_links: set = set()
    for section_url in _find_notice_sections(soup, base_url):
        html = _fetch(section_url)
        time.sleep(delay)
        if not html:
            continue
        try:
            sec_soup = BeautifulSoup(html, "html.parser")
        except Exception:
            continue
        entries = _extract_entries(sec_soup, section_url)
        if entries:
            logger.info("[R2] %s → dział ogłoszeń %s: %s wpisów",
                        base_url, section_url, len(entries))
        for text, href in entries:
            if href in seen_links:      # ten sam dział bywa pod 2 adresami
                continue
            seen_links.add(href)
            results.append({
                "title": text,
                "snippet": text,
                "link": href,
                "dork": "szukaj:dział-ogłoszeń",
                "_direct": True,
            })
    return results


def search_site(base_url: str, delay: float = 0.4) -> list[dict]:
    """Szuka ogłoszeń na jednym BIP-ie: wyszukiwarka, potem dział ogłoszeń.

    Zwraca listę wyników w formacie Fazy 0 (z `_direct: True`).
    Puste, gdy witryna nie ma działającej wyszukiwarki ani działu ogłoszeń.
    """
    results: list[dict] = []
    seen_urls: set = set()
    root = base_url.rstrip("/")
    root_html: str | None = None

    for system, pattern in SEARCH_PATTERNS:
        if results:
            break  # ten BIP już odpowiedział - nie męczymy kolejnych wzorców
        for query in QUERIES:
            url = root + pattern.format(q=quote_plus(query))
            html = _fetch(url)
            if not html:
                time.sleep(delay)
                continue
            if root_html is None:
                root_html = html
            try:
                soup = BeautifulSoup(html, "html.parser")
            except Exception:
                continue
            if _looks_like_homepage(query, soup):
                # System nie obsługuje tego parametru - przerwij ten wzorzec
                logger.debug("[R2] %s: %s nie obsługuje szukania", root, system)
                break
            entries = _extract_entries(soup, url)
            if entries:
                logger.info("[R2] %s (%s): %s wpisów na \"%s\"",
                            root, system, len(entries), query)
            for text, href in entries:
                if href in seen_urls:
                    continue
                seen_urls.add(href)
                results.append({
                    "title": text,
                    "snippet": text,
                    "link": href,
                    "dork": f"szukaj:{system}",
                    "_direct": True,
                })
            time.sleep(delay)

    if not results:
        # Wyszukiwarka nie zadziałała (albo nic nie znalazła) - spróbuj działu
        # ogłoszeń, który BIP24 i bip.net.pl mają zawsze w menu.
        if root_html is None:
            root_html = _fetch(root + "/")
        if root_html:
            results = _scan_notice_sections(base_url, root_html, delay=delay)

    return results


def search_many(base_urls: list[str], delay: float = 0.4,
                limit_sites: int = 0) -> list[dict]:
    """Szuka na wielu BIP-ach. limit_sites=0 oznacza bez limitu."""
    results: list[dict] = []
    targets = base_urls[:limit_sites] if limit_sites else base_urls
    for i, base in enumerate(targets, 1):
        found = search_site(base, delay=delay)
        if found:
            logger.info("[R2] %s/%s %s → %s wyników",
                        i, len(targets), base, len(found))
        results.extend(found)
    return results
