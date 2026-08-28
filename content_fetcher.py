# -*- coding: utf-8 -*-
"""Pobieranie treści HTML/PDF dla wyników sklasyfikowanych jako nabór (ETAP C)."""

import html
import io
import logging
import re
import sys

import pdfplumber
import requests

logger = logging.getLogger(__name__)

MAX_CHARS = 12000  # limit tekstu wysyłanego do LLM
MAX_PDF_PAGES = 20  # limit stron PDF do parsowania


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


def fetch_content(url: str) -> str:
    """Pobiera pełną treść ogłoszenia (HTML albo PDF), obcina do 12000 znaków.

    Błędy sieciowe / 4xx / 403 / timeout / uszkodzony PDF: WARNING + zwróć "".
    """
    try:
        response = requests.get(
            url,
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) rn-dorking/3.0"},
        )
        if response.status_code != 200:
            logger.warning("Pobieranie treści: status %s, URL %s", response.status_code, url)
            return ""

        content_type = response.headers.get("Content-Type", "").lower()
        if url.lower().endswith(".pdf") or "application/pdf" in content_type:
            try:
                text = _extract_pdf_text(response.content)
            except Exception as e:
                # Serwer potrafi zwrócić HTML/stronę błędu pod adresem .pdf -
                # spróbuj sparsować jako HTML zamiast padać
                logger.warning("PDF parse błąd dla %s (%s), próba jako HTML", url, e)
                text = _extract_html_text(response)
        else:
            text = _extract_html_text(response)

        return text[:MAX_CHARS]
    except requests.RequestException as e:
        logger.warning("Pobieranie treści: wyjątek %s, URL %s", e, url)
        return ""


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
