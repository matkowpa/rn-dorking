# -*- coding: utf-8 -*-
"""Testy filtra treści (main.has_content) i Storage.prune_empty."""

import json

import main
from storage import Storage


def _offer(**kw):
    base = {"podmiot": "Test Sp. z o.o.", "termin_skladania_ofert": "",
            "wymagania": "", "podsumowanie": ""}
    base.update(kw)
    return base


class TestHasContent:
    def test_strona_listujaca_bip_odrzucona(self):
        """Tytuł z frazą, ale zero treści - to menu BIP, nie ogłoszenie."""
        o = _offer(podsumowanie="Nabory - Zarząd/ Rada Nadzorcza")
        assert main.has_content(o) is False

    def test_menu_bip_dlugie_odrzucone(self):
        """Dłuższy opis menu BIP nadal nie jest ogłoszeniem."""
        o = _offer(podsumowanie="Ogłoszenia o naborach na stanowiska zarządu, "
                                "rady nadzorczej oraz nabory do rejestru kandydatów.")
        assert main.has_content(o) is False

    def test_puste_wszystko_odrzucone(self):
        assert main.has_content(_offer()) is False

    def test_termin_wystarcza(self):
        o = _offer(termin_skladania_ofert="2026-12-01")
        assert main.has_content(o) is True

    def test_wymagania_wystarczaja(self):
        """Nabór do rejestru kandydatów: termin nieograniczony, ale wymagania są."""
        o = _offer(wymagania="Wykształcenie wyższe ekonomiczne lub prawnicze, "
                             "min. 3 lata stażu w obszarze finansowym.")
        assert main.has_content(o) is True

    def test_podsumowanie_wystarcza(self):
        o = _offer(podsumowanie="Burmistrz ogłasza nabór na członka rady nadzorczej "
                                "spółki komunalnej, zgłoszenia do 15 grudnia.")
        assert main.has_content(o) is True

    def test_krotki_tekst_nie_wystarcza(self):
        """Pojedyncze znaki nie świadczą o treści ogłoszenia."""
        o = _offer(wymagania="-", podsumowanie="n/a")
        assert main.has_content(o) is False

    def test_ukrainskie_ogloszenie_zostaje(self):
        """Filtr NIE odrzuca zagranicznych ogłoszeń - tylko puste strony."""
        o = _offer(podmiot="Комунальне підприємство «Славутська міська лікарня»",
                   data_publikacji="",
                   wymagania="Вища освіта, досвід роботи не менше 5 років у сфері "
                             "управління або фінансів.")
        assert main.has_content(o) is True


class TestPruneEmpty:
    def _seed(self, tmp_path, offers):
        op = tmp_path / "oferty.json"
        sp = tmp_path / "stan.json"
        op.write_text(json.dumps(offers, ensure_ascii=False), encoding="utf-8")
        sp.write_text(json.dumps({"seen_urls": [], "rejected": {}, "reextract": {}}),
                      encoding="utf-8")
        return Storage(offers_path=str(op), state_path=str(sp))

    def test_usuwa_puste_zostawia_tresciwe(self, tmp_path):
        offers = [
            _offer(podmiot="Menu BIP", url="https://a.pl/menu"),
            _offer(podmiot="Realne", url="https://a.pl/real",
                   termin_skladania_ofert="2026-12-01"),
        ]
        st = self._seed(tmp_path, offers)
        assert st.prune_empty(main.has_content) == 1
        assert [o["podmiot"] for o in st.offers] == ["Realne"]
