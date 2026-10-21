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
    r"upływa|upływu|naboru|konkursu|ofert|terminie)",
    re.IGNORECASE)


def _has_deadline_context(text: str, pos: int, len_date: int = 0) -> bool:
    """Czy fraza terminu stoi tuż PRZED datą.

    Sprawdzamy tylko okno przed datą, bo w polskich ogłoszeniach kolejność
    jest stała ("składać do dnia <data>"). "Termin" odwołujący się do innej
    daty PO dacie ("Ogłoszenie z <data>. Termin składania...") nie może
    kwalifikować tej pierwszej - inaczej data publikacji wygrywa z terminem.
    """
    start = max(0, pos - _CONTEXT_WINDOW)
    window = text[start:pos]
    return bool(_DEADLINE_CONTEXT.search(window))

_ISO = re.compile(r"\b(20[2-5]\d)-(\d{2})-(\d{2})\b")
_DOTTED = re.compile(r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})\b")
_LONG = re.compile(
    r"\b(\d{1,2})\s+(" + "|".join(MIESIACE) + r")\s+(20[2-5]\d)\b",
    re.IGNORECASE)

# Okno tekstu wokół daty, w którym szukamy kontekstu terminu.
_CONTEXT_WINDOW = 160

# Bloki nawigacji, w których BIP-y listują daty INNYCH artykułów
# ("Powiązane informacje", "Zobacz także", "Wszystkie aktualności").
# Daty stamtąd nie mają nic wspólnego z terminem i wygrywały jako
# "najwcześniejsza data przyszła".
_RELATED_BLOCK_RE = re.compile(
    r"(?:wszystkie\s+aktualności|powiązane\s+informacje|zobacz\s+także|"
    r"inne\s+aktualności|podziel\s+się|copyright|©\s*20\d\d|mapa\s+serwisu)",
    re.IGNORECASE)


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


def extract_deadline(text: str, today: date | None = None,
                     pub_date: str = "") -> str:
    """Wyciąga termin składania ofert jako ISO YYYY-MM-DD albo "".

    `pub_date` (ISO) zawęża okno: termin składania ofert nie może być
    starszy niż data publikacji ogłoszenia. Bez tego parser łapał daty
    z bocznych kolumn BIP ("Powiązane informacje: 16 października 2026"),
    które są nowsze niż prawdziwy termin i wygrywały jako "najwcześniejsza
    data przyszła".

    Wybiera najwcześniejszą datę przyszłą, która ma wokół siebie kontekst
    terminu. Gdy takiej nie ma - najpóźniejszą datę z kontekstem, o ile
    nie jest starsza niż rok.
    """
    if not text:
        return ""
    today = today or date.today()
    # Powiązane informacje / nawigacja boczna: obcinamy ogon strony, gdzie
    # BIP-y listują "Powiązane informacje" z datami innych artykułów.
    cut = _RELATED_BLOCK_RE.search(text)
    if cut and cut.start() > 200:
        text = text[:cut.start()]
    with_context = [(p, iso) for p, iso in _candidate_dates(text)
                    if _has_deadline_context(text, p)]
    if not with_context:
        return ""

    future = [iso for _, iso in with_context if iso >= today.isoformat()]
    if pub_date and pub_date[:10] > "1900-01-01":
        # Termin przed publikacją ogłoszenia jest niemożliwy - odrzucamy
        # takie daty (data publikacji bywa mylona z terminem).
        future = [iso for iso in future if iso >= pub_date[:10]]
    if future:
        return min(future)
    # Brak daty przyszłej po publikacji: termin mógł minąć, ale pole z datą
    # jest lepsze niż puste - pod warunkiem, że data nie jest starsza niż rok.
    candidates = [iso for _, iso in with_context]
    if pub_date and pub_date[:10] > "1900-01-01":
        candidates = [iso for iso in candidates if iso >= pub_date[:10]]
    if not candidates:
        return ""
    latest = max(candidates)
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
