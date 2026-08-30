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