# -*- coding: utf-8 -*-
"""Pobieranie treści HTML/PDF dla wyników sklasyfikowanych jako nabór (ETAP C)."""

import html
import io
import logging
import re
import sys
from urllib.parse import urljoin

import pdfplumber
import requests

logger = logging.getLogger(__name__)

MAX_CHARS = 12000  # limit tekstu wysyłanego do LLM
MAX_PDF_PAGES = 20  # limit stron PDF do parsowania
MIN_MAIN_TEXT = 400  # poniżej tej długości strona to zwykle "skorupa" nawigacyjna BIP
MAX_ATTACHMENTS = 2  # maks. liczba załączników/podstron pobieranych dodatkowo (poziom 2)
ATTACHMENT_CHARS = 6000  # limit tekstu dołączonego z jednego załącznika
# Frazy w href/tekście linku sugerujące treść ogłoszenia (poziom 2)
LINK_KEYWORDS = ("nabor", "ogłoszenie", "ogloszenie", "rada nadzor",
                 "kwalifikacyjn", "konkurs", "kandydat")


def _extract_pdf_text(content: bytes) -> str:
    """Wyciąga tekst z maksymalnie 20 pierwszych stron PDF."""
    parts = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages[:MAX_PDF_PAGES]:
            text = page.extract_text() or ""
            parts.append(text)
    return "\n".join(parts)


def _extract_html_text(response: requests.Response) -> str:
    """Wycina treść z HTML: usuwa tagi, dekoduje encje, normalizuje białe znaki."""
    # Ustalenie kodowania: jeśli Content-Type nie zawiera charset,
    # użyj apparent_encoding PRZED odczytaniem response.text
    content_type = response.headers.get("Content-Type", "")
    if "charset" not in content_type.lower():
        response.encoding = response.apparent_encoding
    raw = response.text

    # Usuń bloki script/style z zawartością
    raw = re.sub(r"<script\b[^>]*>.*?</script>", " ", raw, flags=re.IGNORECASE | re.DOTALL)
    raw = re.sub(r"<style\b[^>]*>.*?</style>", " ", raw, flags=re.IGNORECASE | re.DOTALL)
    # Usuń wszystkie pozostałe tagi
    raw = re.sub(r"<[^>]+>", " ", raw)
    # Dekoduj encje HTML
    raw = html.unescape(raw)
    # Redukuj wielokrotne białe znaki do pojedynczych spacji
    raw = re.sub(r"\s+", " ", raw).strip()
    # Podziel na akapity po \n\n (heuristicznie: po podwójnym końcu zdania
    # zostawiamy prosty tekst - specyfikacja wymaga podziału na akapity \n\n)
    return raw


def _fetch(url: str) -> requests.Response | None:
    """Pojedynczy GET z User-Agentem; None przy błędzie lub status != 200."""
    try:
        response = requests.get(
            url,
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) rn-dorking/3.0"},
        )
    except requests.RequestException as e:
        logger.warning("Pobieranie treści: wyjątek %s, URL %s", e, url)
        return None
    if response.status_code != 200:
        logger.warning("Pobieranie treści: status %s, URL %s", response.status_code, url)
        return None
    return response


def _attachment_links(page_html: str, base_url: str) -> list[str]:
    """Wyciąga z HTML linki do PDF-ów i podstron z frazami naborowymi (poziom 2).

    Zwraca maks. MAX_ATTACHMENTS bezwzględnych URL-i (bez duplikatów, bez
    javascript:/mailto:/kotwic).
    """
    found: list[str] = []
    for match in re.finditer(
            r"<a\b[^>]*?href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
            page_html, flags=re.IGNORECASE | re.DOTALL):
        href, inner = match.group(1), match.group(2)
        if href.lower().startswith(("javascript:", "mailto:", "#")):
            continue
        inner_text = re.sub(r"<[^>]+>", " ", inner)
        haystack = f"{href} {inner_text}".lower()
        if not (href.lower().endswith(".pdf")
                or any(k in haystack for k in LINK_KEYWORDS)):
            continue
        absolute = urljoin(base_url, href)
        if absolute not in found:
            found.append(absolute)
        if len(found) >= MAX_ATTACHMENTS:
            break
    return found


def fetch_content(url: str) -> str:
    """Pobiera pełną treść ogłoszenia (HTML albo PDF), obcina do 12000 znaków.

    Poziom 2: gdy strona HTML ma mniej niż MIN_MAIN_TEXT znaków (typowa
    "skorupa" nawigacyjna BIP, treść renderowana JS-em albo w załączniku),
    pobiera dodatkowo do MAX_ATTACHMENTS załączników PDF / podstron z frazami
    naborowymi i dołącza ich treść.
    Błędy sieciowe / 4xx / 403 / timeout / uszkodzony PDF: WARNING + zwróć "".
    """
    response = _fetch(url)
    if response is None:
        return ""

    content_type = response.headers.get("Content-Type", "").lower()
    is_pdf = url.lower().endswith(".pdf") or "application/pdf" in content_type
    if is_pdf:
        try:
            text = _extract_pdf_text(response.content)
        except Exception as e:
            # Serwer potrafi zwrócić HTML/stronę błędu pod adresem .pdf -
            # spróbuj sparsować jako HTML zamiast padać
            logger.warning("PDF parse błąd dla %s (%s), próba jako HTML", url, e)
            text = _extract_html_text(response)
    else:
        text = _extract_html_text(response)
        # POZIOM 2: strona-skorupa -> dołącz treść załączników/podstron
        if len(text) < MIN_MAIN_TEXT:
            for link in _attachment_links(response.text, url):
                sub = _fetch(link)
                if sub is None:
                    continue
                sub_is_pdf = link.lower().endswith(".pdf") or \
                    "application/pdf" in sub.headers.get("Content-Type", "").lower()
                if sub_is_pdf:
                    try:
                        sub_text = _extract_pdf_text(sub.content)
                    except Exception as e:
                        logger.warning("PDF parse błąd (załącznik) %s: %s", link, e)
                        continue
                else:
                    sub_text = _extract_html_text(sub)
                if sub_text:
                    text = f"{text}\n\n{sub_text[:ATTACHMENT_CHARS]}".strip()
                    logger.info("Poziom 2: dołączono treść z %s (%s znaków)",
                                link, len(sub_text))
                if len(text) >= MAX_CHARS:
                    break

    return text[:MAX_CHARS]


if __name__ == "__main__":
    # Self-test (ETAP 3a, 3b)
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    if len(sys.argv) < 2:
        print("Użycie: python content_fetcher.py --self-test <url>", file=sys.stderr)
        sys.exit(1)
    url = sys.argv[-1]
    text = fetch_content(url)
    print(f"Długość tekstu: {len(text)}")
    print(f"Pierwsze 500 znaków:\n{text[:500]}")
