# -*- coding: utf-8 -*-
"""Plan zapytań do wyszukiwarki: stała baza + rotacja regionalna i spółkowa.

Problem (analiza 66 dni): ten sam zestaw 12 dorków szedł w każdym runie, więc
wyszukiwarka zwracała codziennie te same 60-70 adresów - 81% wsadu to wpisy
"cached"/"duplicate", a nowych ofert było 15 na 4556 surowych wyników.

Rozwiązanie: dorki bazowe zostają (dają najlepsze trafienia), ale dokładamy
zapytania regionalne (16 województw) i spółkowe, wybierane deterministycznie
po dniu roku. Każdy region wypada raz na cztery dni, każdy wariant spółkowy
raz na kilka dni, więc zbiór zapytań w kolejnych runach jest różny, a budżet
Brave (2000 zapytań/mies.) pozostaje pod kontrolą.
"""

import datetime

# Dorki bazowe - formuły, które w produkcji dawały trafienia.
BASE_DORKS = [
    '"nabór na członków rady nadzorczej" BIP',
    '"nabór kandydatów" "rady nadzorczej" BIP',
    '"postępowanie kwalifikacyjne" "rady nadzorczej"',
    '"konkurs na członka rady nadzorczej"',
    # Wymienione 2026-11-03 po pomiarze tools/dork_stats.py:
    #  - "zaproszenie do składania ofert" "rady nadzorczej": 110 wyników,
    #    0 świeżych adresów, 0 ofert (fraza łapie przetargi, nie nabory RN),
    #  - "nabór do bazy danych kandydatów" "rada nadzorcza": 7 wyników,
    #    wszystkie odrzucone (bazy kandydatów na stanowiska, nie RN).
    # Zamiast nich frazy celujące w spółki komunalne - tam RN są najczęściej,
    # a tytuły nie zawierają "BIP".
    '"rada nadzorcza" "spółka z o.o." nabór ogłoszenie',
    '"nabór kandydatów na członków rady nadzorczej" spółka',
    '"zgłoszenia kandydatów" "członka rady nadzorczej"',
    '"ogłoszenie o naborze kandydatów" "rada nadzorcza"',
    '"kandydatów na członków rad nadzorczych"',
    '"ogłasza nabór" "rady nadzorczej"',
    '"kandydatów do rady nadzorczej"',
    '"konkurs na członków rady nadzorczej"',
]

REGIONS = [
    "dolnośląskie", "kujawsko-pomorskie", "lubelskie", "lubuskie", "łódzkie",
    "małopolskie", "mazowieckie", "opolskie", "podkarpackie", "podlaskie",
    "pomorskie", "śląskie", "świętokrzyskie", "warmińsko-mazurskie",
    "wielkopolskie", "zachodniopomorskie",
]

REGIONAL_TEMPLATES = [
    '"nabór na członka rady nadzorczej" {region}',
    '"nabór kandydatów" "rady nadzorczej" {region}',
    '"ogłoszenie o naborze" "rady nadzorczej" {region}',
]

# Spółki komunalne/państwowe publikują ogłoszenia własnym tonem - te frazy
# łapią ogłoszenia bez słowa "BIP" w tytule.
COMPANY_TEMPLATES = [
    '"spółka z o.o." "nabór" "rady nadzorczej"',
    '"spółka komunalna" "nabór" "rady nadzorczej"',
    '"zgromadzenie wspólników" "nabór" "rady nadzorczej"',
    '"nabór uzupełniający" "rady nadzorczej"',
    '"kandydatów na członków rady nadzorczej" spółka',
]

REGIONS_PER_RUN = 4
COMPANIES_PER_RUN = 2


def regional_dorks(day_of_year: int, per_run: int = REGIONS_PER_RUN) -> list[str]:
    """Kolejne `per_run` województw, z szablonem zmienianym co dzień.

    Przy 16 regionach i 4 na run każdy region wypada raz na 4 dni.
    """
    if per_run <= 0:
        return []
    per_run = min(per_run, len(REGIONS))
    start = (day_of_year * per_run) % len(REGIONS)
    template = REGIONAL_TEMPLATES[day_of_year % len(REGIONAL_TEMPLATES)]
    out = []
    for i in range(per_run):
        region = REGIONS[(start + i) % len(REGIONS)]
        out.append(template.format(region=region))
    return out


def company_dorks(day_of_year: int, per_run: int = COMPANIES_PER_RUN) -> list[str]:
    """Warianty spółkowe - rotacja co dzień, bez powtórzeń w jednym runie."""
    if per_run <= 0:
        return []
    per_run = min(per_run, len(COMPANY_TEMPLATES))
    start = day_of_year % len(COMPANY_TEMPLATES)
    return [COMPANY_TEMPLATES[(start + i) % len(COMPANY_TEMPLATES)]
            for i in range(per_run)]


def build_plan(day_of_year: int | None = None,
               base: list[str] | None = None,
               regions_per_run: int = REGIONS_PER_RUN,
               companies_per_run: int = COMPANIES_PER_RUN) -> list[str]:
    """Pełny plan zapytań na jeden run (bez duplikatów, kolejność stała)."""
    if day_of_year is None:
        day_of_year = datetime.date.today().timetuple().tm_yday
    base = BASE_DORKS if base is None else base
    plan = list(base)
    plan += regional_dorks(day_of_year, regions_per_run)
    plan += company_dorks(day_of_year, companies_per_run)
    seen, unique = set(), []
    for dork in plan:
        if dork not in seen:
            seen.add(dork)
            unique.append(dork)
    return unique
