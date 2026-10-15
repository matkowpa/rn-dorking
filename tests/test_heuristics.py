# -*- coding: utf-8 -*-
"""Testy heurystyk pre-LLM (bez wywołań sieciowych)."""
import sys

sys.stdout.reconfigure(encoding="utf-8")

from heuristics import (
    has_stale_years,
    is_blocked_domain,
    is_trusted_domain,
    prefilter_reject,
)


def test_blocked_domain():
    assert is_blocked_domain("https://pl.jooble.org/praca/rada-nadzorcza")
    assert is_blocked_domain("https://www.indeed.com/viewjob?jk=1")
    assert not is_blocked_domain("https://bip.poznan.pl/ogloszenie")


def test_trusted_domain():
    assert is_trusted_domain("https://umj.bip.gov.pl/ogloszenie-o-naborze")
    assert is_trusted_domain("https://www.gov.pl/web/finanse/aktualnosci")
    assert not is_trusted_domain("https://www.orlen.pl/aktualnosci")
    assert not is_trusted_domain("https://bip.poznan.pl/ogloszenie")


def test_stale_years_old():
    # Tylko stare roczniki -> przeterminowane
    assert has_stale_years("Nabór kandydatów 2019 r.", "Ogłoszenie z 2021 roku")
    # Mieszanka ze świeżym rokiem -> aktualne
    assert not has_stale_years("Nabór kandydatów 2019 r.", "Aktualizacja 2026")


def test_stale_years_no_years():
    assert not has_stale_years("Nabór kandydatów na członka rady nadzorczej", "")


def test_prefilter_passes_real_announcement():
    odrzucony, powod = prefilter_reject(
        "Ogłoszenie o naborze kandydatów na członka rady nadzorczej",
        "Zapraszamy do składania zgłoszeń do 15 września 2026 r.",
        "https://bip.example.pl/nabor",
    )
    assert not odrzucony
    assert powod == ""


def test_prefilter_rejects_aggregator():
    odrzucony, powod = prefilter_reject(
        "Rada nadzorcza - oferty pracy",
        "nabór członków rad nadzorczych",
        "https://jooble.pl/praca/rada-nadzorcza",
    )
    assert odrzucony
    assert "agregator" in powod


def test_prefilter_rejects_article():
    odrzucony, powod = prefilter_reject(
        "Jak zostać członkiem rady nadzorczej - poradnik",
        "Wszystko o kompetencjach rady nadzorczej",
        "https://portalprawny.pl/rada-nadzorcza",
    )
    assert odrzucony
    assert "dyskwalifikujące" in powod


def test_prefilter_rejects_closed():
    odrzucony, _ = prefilter_reject(
        "Ogłoszenie o naborze kandydatów na członka rady nadzorczej",
        "Nabór zakończony - dziękujemy za zgłoszenia",
        "https://bip.example.pl/nabor-zamkniety",
    )
    assert odrzucony


def test_prefilter_rejects_stale():
    odrzucony, powod = prefilter_reject(
        "Ogłoszenie o naborze kandydatów na członka rady nadzorczej 2018",
        "Zapraszamy do składania zgłoszeń.",
        "https://bip.example.pl/nabor-2018",
    )
    assert odrzucony
    assert "przeterminowane" in powod

# ---------- Etap 2: word boundaries + ochrona tytułów-ofert ----------

def test_kurs_ne_lapie_konkursu():
    """'kurs' po substring łapie 'konkurs' — po word boundary nie może."""
    odrzucony, powod = prefilter_reject(
        "Ogłoszenie o konkursie na stanowisko Prezesa Zarządu",
        "Gmina Ryczywół ogłasza nabór kandydatów", "")
    assert not odrzucony, f"'konkurs' odrzucone przez 'kurs': {powod}"


def test_kursy_w_tresci_realnego_ogloszenia():
    """Realne ogłoszenie naboru ze słowem 'kursy' w treści przechodzi."""
    odrzucony, powod = prefilter_reject(
        "Ogłoszenie o naborze kandydatów na członka rady nadzorczej",
        "Spółka notowana na GPW, kursy akcji notowane od 2026 r.",
        "https://bip.example.pl/ogloszenie")
    assert not odrzucony, f"oferta odrzucona: {powod}"


def test_kurs_dla_kandydatow_nadal_odrzucony():
    """Realny kurs/szkolenie (bez sygnałów oferty) nadal odrzucany."""
    odrzucony, powod = prefilter_reject(
        "Kurs dla kandydatów na członków rad nadzorczych | Baza pytań",
        "Zapisy otwarte", "https://ibd.pl/szkolenie/kurs")
    assert odrzucony
    assert "kurs" in powod


def test_egzamin_w_realnym_ogloszeniu_nie_odrzuca():
    """Ogłoszenie o naborze, które wspomina egzamin — przechodzi."""
    odrzucony, powod = prefilter_reject(
        "Ogłoszenie o naborze na członka rady nadzorczej spółki",
        "Wymagany zdany egzamin na członka rad nadzorczych",
        "https://bip.example.pl/nabor")
    assert not odrzucony, f"oferta odrzucona przez egzamin: {powod}"


def test_ochrona_tytulow_ofert_przed_frazami_edu():
    """'szkolenie dla' w tytule-oferty (nabór) nie odrzuca."""
    odrzucony, powod = prefilter_reject(
        "Ogłoszenie Wójta Gminy o naborze - szkolenie dla kandydatów nie obowiązuje",
        "Nabór kandydatów na członka rady nadzorczej OZC",
        "https://gmina.example.pl/bip")
    assert not odrzucony, f"oferta odrzucona: {powod}"


def test_artykuly_nadal_odrzucone():
    """Frazy artykulowe nadal dzialaja (nie zepsute przez etap 2)."""
    for t in ("Wyjaśniamy, jak zostać członkiem rady nadzorczej",
              "Analiza rynku rad nadzorczych",
              "Stan prawny dotyczący rad nadzorczych"):
        odrzucony, powod = prefilter_reject(t, "", "")
        assert odrzucony, f"artykuł przepuszczony: {t[:50]}"


def test_zamkniete_nabory_nadal_odrzucone():
    odrzucony, powod = prefilter_reject(
        "Nabór zakończony - rada nadzorcza spółki",
        "Dziękujemy za zgłoszenia", "https://bip.example.pl/")
    assert odrzucony, f"zakończony przepuszczony: {powod}"


def test_domeny_agregatorow_nadal_odrzucone():
    odrzucony, powod = prefilter_reject(
        "Nabór na członka rady nadzorczej", "", "https://pl.jooble.org/x")
    assert odrzucony and "domena" in powod
