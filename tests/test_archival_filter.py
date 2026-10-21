# -*- coding: utf-8 -*-
"""Testy filtra archiwalnych ofert i sanity checku terminu (main.py)."""

from datetime import date, timedelta

import main


TODAY = date(2026, 10, 21)


def _offer(**kw):
    base = {"podmiot": "Test Sp. z o.o.", "termin_skladania_ofert": "",
            "data_publikacji": "", "znaleziono_dnia": TODAY.isoformat()}
    base.update(kw)
    return base


class TestIsArchival:
    def test_przyszly_termin_nie_jest_archiwalny(self):
        o = _offer(termin_skladania_ofert=(TODAY + timedelta(days=14)).isoformat())
        assert main.is_archival(o, today=TODAY) is False

    def test_termin_sprzed_miesiaca_w_oknie(self):
        o = _offer(termin_skladania_ofert=(TODAY - timedelta(days=30)).isoformat())
        assert main.is_archival(o, today=TODAY) is False

    def test_termin_sprzed_pol_roku_jest_archiwalny(self):
        o = _offer(termin_skladania_ofert=(TODAY - timedelta(days=180)).isoformat())
        assert main.is_archival(o, today=TODAY) is True

    def test_regresja_mae_2023(self):
        """Oferta MAE z terminem 2023-03-27 nie może przejść (stary bug)."""
        o = _offer(termin_skladania_ofert="2023-03-27")
        assert main.is_archival(o, today=TODAY) is True

    def test_nietypowy_termin_fallback_na_publikacje(self):
        """Nieparsowalny termin -> decyduje data publikacji."""
        o = _offer(termin_skladania_ofert="w terminie 14 dni",
                   data_publikacji=(TODAY - timedelta(days=200)).isoformat())
        assert main.is_archival(o, today=TODAY) is True

    def test_nietypowy_termin_swieza_publikacja(self):
        o = _offer(termin_skladania_ofert="do 15 listopada",
                   data_publikacji=(TODAY - timedelta(days=5)).isoformat())
        assert main.is_archival(o, today=TODAY) is False

    def test_brak_dat_zostaje(self):
        """Brak jakiejkolwiek daty - nie gubimy oferty."""
        o = _offer(znaleziono_dnia="")
        assert main.is_archival(o, today=TODAY) is False

    def test_termin_z_godzina(self):
        o = _offer(termin_skladania_ofert="2023-03-27T12:00:00")
        assert main.is_archival(o, today=TODAY) is True


class TestSanitizeTermin:
    def test_poprawny_termin_zostaje(self):
        o = _offer(termin_skladania_ofert=(TODAY + timedelta(days=30)).isoformat())
        assert main.sanitize_termin(o, today=TODAY) is False
        assert o["termin_skladania_ofert"] != ""

    def test_termin_z_2023_czyszczony(self):
        o = _offer(termin_skladania_ofert="2023-03-27")
        assert main.sanitize_termin(o, today=TODAY) is True
        assert o["termin_skladania_ofert"] == ""

    def test_termin_za_5_lat_czyszczony(self):
        o = _offer(termin_skladania_ofert="2031-01-01")
        assert main.sanitize_termin(o, today=TODAY) is True
        assert o["termin_skladania_ofert"] == ""

    def test_puste_nie_zmienia(self):
        o = _offer()
        assert main.sanitize_termin(o, today=TODAY) is False

    def test_format_nietypowy_nie_zmienia(self):
        o = _offer(termin_skladania_ofert="15 listopada 2026")
        assert main.sanitize_termin(o, today=TODAY) is False
        assert o["termin_skladania_ofert"] == "15 listopada 2026"
