# -*- coding: utf-8 -*-
"""Deterministyczna ekstrakcja terminu składania ofert z treści ogłoszenia.

Dlaczego osobny moduł, a nie tylko LLM: 25 z 30 ofert w bazie nie miało
terminu, mimo że termin JEST w treści - model go po prostu nie wyciągnął
(często bo termin siedzi w zdaniu "Oferty należy składać do dnia 15 listopada
2026 r. do godz. 12:00", a nie w wyodrębnionym polu). Ten parser działa
niezależnie od LLM i jest uruchamiany, gdy LLM zwrócił puste pole.

Zasada: szukamy KONTEKSTU terminu (fraza "składać", "naboru", "ofert"),
a nie dowolnej daty w tekście - w ogłoszeniu są też daty publikacji,
uchwał, kadencji. Bez tego trafialibyśmy na datę ogłoszenia zamiast terminu.
"""

import logging
import re
from datetime import date

logger = logging.getLogger(__name__)

MIESIACE = {
    "stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4, "maja": 5,
    "czerwca": 6, "lipca": 7, "sierpnia": 8, "września": 9, "wrzesnia": 9,
    "października": 10, "pazdziernika": 10, "listopada": 11, "grudnia": 12,
}

# Kontekst terminu: fraza wskazująca, że podana niżej data to termin
# składania ofert (a nie data publikacji, uchwały czy początek kadencji).
_DEADLINE_CONTEXT = re.compile(
    r"(?:składa[cć]|składania|przesła[cć]|przesyła[cć]|wpłynąć|wpłynięcia|"
    r"złożenia|zgłosze[nń]|zgłaszać|przyjmowane\s+są|przyjmujemy|"
    r"upływa|upływu|naboru|konkursu|ofert)",
    re.IGNORECASE)

_ISO = re.compile(r"\b(20[2-5]\d)-(\d{2})-(\d{2})\b")
_DOTTED = re.compile(r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})\b")
_LONG = re.compile(
    r"\b(\d{1,2})\s+(" + "|".join(MIESIACE) + r")\s+(20[2-5]\d)\b",
    re.IGNORECASE)

# Okno tekstu wokół daty, w którym szukamy kontekstu terminu.
_CONTEXT_WINDOW = 160


def _to_iso(day: int, month: int, year: int) -> str:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return ""


def _candidate_dates(text: str) -> list[tuple[int, str]]:
    """Wszystkie daty w tekście jako (pozycja, ISO)."""
    out: list[tuple[int, str]] = []
    for m in _ISO.finditer(text):
        iso = _to_iso(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if iso:
            out.append((m.start(), iso))
    for m in _DOTTED.finditer(text):
        # DD.MM.RRRR - w polskich ogłoszeniach kolejność dzienna
        iso = _to_iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if iso:
            out.append((m.start(), iso))
    for m in _LONG.finditer(text):
        month = MIESIACE.get(m.group(2).lower())
        if month:
            iso = _to_iso(int(m.group(1)), month, int(m.group(3)))
            if iso:
                out.append((m.start(), iso))
    out.sort()
    return out


def _has_deadline_context(text: str, pos: int) -> bool:
    """Czy w okolicy daty jest fraza wskazująca na termin składania ofert."""
    start = max(0, pos - _CONTEXT_WINDOW)
    window = text[start:pos + _CONTEXT_WINDOW]
    return bool(_DEADLINE_CONTEXT.search(window))


def extract_deadline(text: str, today: date | None = None) -> str:
    """Wyciąga termin składania ofert jako ISO YYYY-MM-DD albo "".

    Wybiera najwcześniejszą datę przyszłą, która ma wokół siebie kontekst
    terminu. Gdy takiej nie ma - najwcześniejszą datę z kontekstem, o ile
    nie jest starsza niż rok (wtedy to raczej archiwum niż termin).

    `today` do testów; domyślnie date.today().
    """
    if not text:
        return ""
    today = today or date.today()
    with_context = [(p, iso) for p, iso in _candidate_dates(text)
                    if _has_deadline_context(text, p)]
    if not with_context:
        return ""

    future = [iso for _, iso in with_context if iso >= today.isoformat()]
    if future:
        return min(future)

    # Brak daty przyszłej: weź najpóźniejszą z kontekstem, jeśli sensowna
    # (termin mógł już minąć, ale dane są lepsze niż puste pole).
    latest = max(iso for _, iso in with_context)
    if latest >= f"{today.year - 1}-01-01":
        return latest
    return ""


def deadline_from_filename(url: str) -> str:
    """Data terminu zaszyta w nazwie pliku PDF (np. "ogloszenie-2026-11-15.pdf").

    BIP-y często umieszczają termin w nazwie załącznika, gdy treść jest
    skanem bez warstwy tekstowej.
    """
    if not url:
        return ""
    name = url.rsplit("/", 1)[-1]
    m = re.search(r"(20[2-5]\d)[-_]?(\d{2})[-_]?(\d{2})", name)
    if m:
        return _to_iso(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    m = re.search(r"(\d{1,2})[._-](\d{1,2})[._-](20[2-5]\d)", name)
    if m:
        return _to_iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return ""
