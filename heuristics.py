# -*- coding: utf-8 -*-
"""Tanie heurystyki pre-LLM (port z projektu rn-scrapper).

Odrzucają agregatory, artykuły/poradniki, treści edukacyjne, zakończone
nabory i archiwalne roczniki ZANIM wynik trafi do filtra LLM - oszczędność
kosztu i czasu. Stosowane w main.py przed rejects_zarzad/filtra LLM.

Etap 2 (fix): dopasowanie fraz po granicach słów (\b), nie substring.
Fraza "kurs" nie odrzuca już ogłoszenia z "konkurs" (najczęstsze fałszywe
odrzucenie w danych produkcyjnych: 18/196). Frazy edukacyjne są pomijane,
gdy tytuł wygląda na realne ogłoszenie naboru (ochrona BIP-ów).
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
    "granice odpowiedzialności",
    "nowelizacja", "już od",
    "analiza", "ekspert", "komentarz", "opinia",
    "poruszyliśmy", "kancelaria",
    "stan prawny",
]

# Frazy wskazujące treści EDUKACYJNE / egzaminacyjne (kursy, testy).
# UWAGA: "kurs" jako substring łapie "konkurs" (częste w ogłoszeniach!) -
# dlatego frazy edukacyjne działają TYLKO po granicach słów (\b) i TYLKO
# gdy tytuł nie wygląda na realne ogłoszenie naboru (ochrona BIP-ów).
EXAM_OR_EDU_PHRASES = [
    "egzamin", "egzaminu", "egzaminacyjny",
    "kurs", "kursy", "kursów", "kursu",
    "test kwalifikacyjny", "certyfikat",
    "szkolenie dla", "szkolenia dla",
    "praktyka",
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
    *STALE_OR_CLOSED_PHRASES,
    *AD_MARKETING_PHRASES,
]

# Sygnały w TYTULE, że mamy realne ogłoszenie naboru - chronią przed
# odrzuceniem przez frazy edukacyjne (np. "konkurs na stanowisko prezesa
# zarządu" na BIP gminy to ogłoszenie, nie szkolenie).
OFFER_TITLE_HINTS = (
    "nabór", "naboru", "ogłoszenie",
    "rady nadzorczej", "rada nadzorcza",
    "członek rady", "członków rady", "członka rady",
    "zarządu", "prezesa",
    "bip", "urząd", "gmina", "wójt", "burmistrz",
)


def is_blocked_domain(url: str) -> bool:
    """True, gdy host URL-a pasuje do listy domen-agregatorów/reklam."""
    host = urlsplit(url).netloc.lower()
    return any(b in host for b in BLOCKED_DOMAINS)


def is_trusted_domain(url: str) -> bool:
    """True dla domen urzędowych (*.gov.pl) - treść z definicji wiarygodna."""
    host = urlsplit(url).netloc.lower()
    return host.endswith("gov.pl")


def _phrase_matches(phrase: str, text_lower: str) -> bool:
    """Dopasowanie frazy po granicach słów (\b...\b).

    "kurs" NIE pasuje do "konkursu" (litery 'n' przed 'k' w "konkurs"
    nie tworzą granicy słowa). Działa też dla odmian: kurs/kursy/kursów.
    """
    return re.search(rf"\b{re.escape(phrase)}\b", text_lower) is not None


def _title_looks_like_offer(title: str) -> bool:
    """True, gdy tytuł zawiera sygnał realnego ogłoszenia naboru."""
    t = title.lower()
    return any(h in t for h in OFFER_TITLE_HINTS)


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

    Etap 2:
    - frazy DO-EDUKACYJNE (kurs/egzamin/...) dopasowywane po granicach
      słów i pomijane, gdy tytuł wygląda na ogłoszenie naboru
    - pozostałe frazy (artykuły, zamknięte, reklamy) - także word boundary
      (bezpieczniejsze, bez zmiany zachowania w praktyce)
    """
    if url and is_blocked_domain(url):
        return True, "domena zablokowana (agregator/reklama)"

    combined = f"{title} {snippet}".lower()
    looks_like_offer = _title_looks_like_offer(title)

    for phrase in DISQUALIFYING_PHRASES:
        if _phrase_matches(phrase, combined):
            return True, f"frazy dyskwalifikujące: {phrase}"

    # Frazy edukacyjne: word boundary + ochrona tytułów-ofert
    if not looks_like_offer:
        for phrase in EXAM_OR_EDU_PHRASES:
            if _phrase_matches(phrase, combined):
                return True, f"frazy dyskwalifikujące: {phrase}"

    if has_stale_years(title, snippet):
        return True, "przeterminowane ogłoszenie (tylko stare roczniki)"
    return False, ""
