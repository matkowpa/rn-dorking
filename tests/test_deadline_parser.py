# -*- coding: utf-8 -*-
"""Testy deterministycznego parsera terminu (deadline_parser)."""

from datetime import date

import deadline_parser as dp

TODAY = date(2026, 10, 21)


class TestExtractDeadline:
    def test_termin_slowny(self):
        text = "Oferty należy składać do dnia 15 listopada 2026 r. do godz. 12:00."
        assert dp.extract_deadline(text, TODAY) == "2026-11-15"

    def test_termin_kropkowany(self):
        text = "Zgłoszenia przyjmowane są do 30.11.2026."
        assert dp.extract_deadline(text, TODAY) == "2026-11-30"

    def test_termin_iso(self):
        text = "Termin składania ofert upływa 2026-12-05."
        assert dp.extract_deadline(text, TODAY) == "2026-12-05"

    def test_termin_z_myslnikami(self):
        text = "Oferty składać do 15-12-2026"
        assert dp.extract_deadline(text, TODAY) == "2026-12-15"

    def test_wyklucza_date_publikacji_bez_kontekstu(self):
        """Data publikacji bez słowa o składaniu nie jest terminem."""
        text = "Ogłoszenie opublikowano 12.03.2026 roku."
        assert dp.extract_deadline(text, TODAY) == ""

    def test_wyklucza_kadencje(self):
        text = "Uchwała z 12.03.2026, kadencja do 2029 roku."
        assert dp.extract_deadline(text, TODAY) == ""

    def test_wybierana_najwczesniejsza_przyszla(self):
        text = ("Ogłoszenie z 1 października 2026. Oferty składać do "
                "15 listopada 2026. Rozstrzygnięcie do 30 grudnia 2026.")
        assert dp.extract_deadline(text, TODAY) == "2026-11-15"

    def test_pusty_tekst(self):
        assert dp.extract_deadline("", TODAY) == ""

    def test_brak_dat(self):
        assert dp.extract_deadline("Nabór na członka rady nadzorczej.", TODAY) == ""

    def test_przeterminowany_termin_zwracany(self):
        """Termin już minął, ale dane są lepsze niż puste pole."""
        text = "Oferty składać do 30.09.2026."
        assert dp.extract_deadline(text, TODAY) == "2026-09-30"

    def test_bardzo_stary_termin_odrzucony(self):
        text = "Oferty składać do 30.09.2019."
        assert dp.extract_deadline(text, TODAY) == ""

    def test_niepoprawna_data(self):
        text = "Oferty składać do 31.02.2026."
        assert dp.extract_deadline(text, TODAY) == ""

    def test_przyjmowane_sa(self):
        text = "Oferty przyjmowane są do dnia 5 grudnia 2026 r."
        assert dp.extract_deadline(text, TODAY) == "2026-12-05"


class TestFilename:
    def test_iso_w_nazwie(self):
        assert dp.deadline_from_filename(
            "https://bip.x.pl/pliki/ogloszenie-2026-11-15.pdf") == "2026-11-15"

    def test_kropkowana_w_nazwie(self):
        assert dp.deadline_from_filename(
            "https://bip.x.pl/pliki/nabor_15.11.2026.pdf") == "2026-11-15"

    def test_brak_daty(self):
        assert dp.deadline_from_filename(
            "https://bip.x.pl/pliki/ogloszenie.pdf") == ""

    def test_pusty_url(self):
        assert dp.deadline_from_filename("") == ""
