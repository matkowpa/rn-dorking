# -*- coding: utf-8 -*-
"""Tanie heurystyki pre-LLM (port z projektu rn-scrapper).

Odrzucają agregatory, artykuły/poradniki, treści edukacyjne, zakończone
nabory i archiwalne roczniki ZANIM wynik trafi do filtra LLM - oszczędność
kosztu i czasu. Stosowane w main.py przed rejects_zarzad/filtra LLM.
"""

import re
from datetime import datetime
from urllib.parse import urlsplit

# Serwisy agregujące / reklamowe - wyniki z nich NIE są realnymi ogłoszeniami
# o naborach. Dopasowanie przez podciąg w domenie; celowo bez generycznych
# słów (np. "kariera"), by nie odcinać oficjalnych stron BIP.
BLOCKED_DOMAINS = (
    "jooble",        # agregator / reklamy
    "pracuj.pl",     # portal ofert
    "pracujw.pl",
    "indeed",        # globalny agregator
    "linkedin",      # sieć / oferty spon.
    "careerjet", "monster.com", "neuvoo", "adzuna",
    "olx.pl",        # ogłoszenia drobne
    "youtube",       # filmy o karierze, nie ogłoszenia
    "lex.pl",        # bazy aktów prawnych - nigdy nie zawierają ogłoszeń naboru
    "cire.pl",       # serwis branżowy z artykułami, nie ogłoszeniami
)

# Frazy wskazujące, że mamy do czynienia z ARTYKUŁEM / poradnikiem / analizą
# prawniczą, a NIE z realnym ogłoszeniem o naborze.
ARTICLE_OR_LEGAL_PHRASES = [
    "wyjaśniamy", "wyjaśniam", "poradnik",
    "jak zostać", "co robi rada", "jak powstaje",
    "wszystko o", "przewodnik", "na czym polega",
    "opisującą", "opisuje", "o tym czym jest",
    "granice odpowiedzialności", "badanie",
    "nowelizacja", "już od", "obowiązki członka", "prawa i obowiązki",
    "jakie kompetencje", "kompetencje rady", "rola rady",
    "analiza", "ekspert", "komentarz", "opinia",
    "poruszyliśmy", "kancelaria",
    "stan prawny",
]

# Frazy wskazujące treści EDUKACYJNE / egzaminacyjne (kursy, testy).
EXAM_OR_EDU_PHRASES = [
    "egzamin", "test kwalifikacyjny", "certyfikat",
    "kurs", "szkolenie dla", "praktyka",
]

# Frazy sygnalizujące, że ogłoszenie już się zakończyło (nieaktualne).
STALE_OR_CLOSED_PHRASES = [
    "zakończył się", "zakończono",
    "minął termin", "upłynął termin", "termin minął",
    "nabór zakończony", "rekrutacja zakończona",
    "nieaktualne", "usunięto ogłoszenie",
    "nie aktualne",
]

# Reklamy serwisów rekrutacyjnych - typowe frazy marketingowe agregatorów.
AD_MARKETING_PHRASES = [
    "serwisy pracy", "portale pracy", "zobacz więcej ofert",
    "setki ofert", "zweryfikowany pracodawca",
    "praca w branży", "oferta z portalu",
]

DISQUALIFYING_PHRASES = [
    *ARTICLE_OR_LEGAL_PHRASES,
    *EXAM_OR_EDU_PHRASES,
    *STALE_OR_CLOSED_PHRASES,
    *AD_MARKETING_PHRASES,
]


def is_blocked_domain(url: str) -> bool:
    """True, gdy host URL-a pasuje do listy domen-agregatorów/reklam."""
    host = urlsplit(url).netloc.lower()
    return any(b in host for b in BLOCKED_DOMAINS)


def is_trusted_domain(url: str) -> bool:
    """True dla domen urzędowych (*.gov.pl) - treść z definicji wiarygodna."""
    host = urlsplit(url).netloc.lower()
    return host.endswith("gov.pl")


def has_stale_years(title: str, text: str = "") -> bool:
    """Heurystyka przeterminowanych ogłoszeń (port z rn-scrapper).

    DDG/Brave potrafią zwracać archiwalne nabory z 2018/2021. Zasada:
      * jakikolwiek rok >= (rok bieżący - 1) w tytule+treści -> AKTUALNE,
      * tylko starsze roczniki -> PRZETERMINOWANE,
      * brak lat 20xx -> nie rozstrzyga (False).
    """
    current_year = datetime.now().year
    window = f"{title} {(text or '')[:1200]}"
    years = [int(y) for y in re.findall(r"\b(20[0-3]\d)\b", window)]
    if not years:
        return False
    return max(years) < current_year - 1


def prefilter_reject(title: str, snippet: str, url: str = "") -> tuple[bool, str]:
    """Deterministyczny pre-filtr przed LLM. Zwraca (odrzucony, powód).

    Zwrócony powód NIE zaczyna się od "błąd filtra", więc main.py trwale
    zapisuje taki URL jako odrzucony (do wygaśnięcia TTL w storage).
    """
    if url and is_blocked_domain(url):
        return True, "domena zablokowana (agregator/reklama)"
    combined = f"{title} {snippet}".lower()
    for phrase in DISQUALIFYING_PHRASES:
        if phrase in combined:
            return True, f"frazy dyskwalifikujące: {phrase}"
    if has_stale_years(title, snippet):
        return True, "przeterminowane ogłoszenie (tylko stare roczniki)"
    return False, ""