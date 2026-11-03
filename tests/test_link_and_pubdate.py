# -*- coding: utf-8 -*-
"""Testy walidacji URL-a oferty (menu != ogłoszenie) i fallbacku daty publikacji."""

from datetime import date

import main
import content_fetcher
from storage import Storage


def _offer(**kw):
    base = {
        "podmiot": "Test Sp. z o.o.",
        "url": "https://bip.example.pl/12345/nabor-na-czlonka-rady-nadzorczej",
        "termin_skladania_ofert": "2026-12-01",
        "data_publikacji": "",
        "znaleziono_dnia": "2026-11-01",
    }
    base.update(kw)
    return base


class TestHasNoticeUrl:
    def test_bip24_wpis_jest_ogloszeniem(self):
        assert main.has_notice_url(_offer()) is True

    def test_bip_net_parametr_a(self):
        o = _offer(url="https://gmina.bip.net.pl/?a=12345")
        assert main.has_notice_url(o) is True

    def test_dzial_bip_bez_id_wpisu_nie_jest_ogloszeniem(self):
        o = _offer(url="https://bip.example.pl/ogloszenia-o-naborach")
        assert main.has_notice_url(o) is False

    def test_porownanie_wersji_dokumentu_odrzucone(self):
        o = _offer(url="https://bip.piastow.pl/nabor/porownaj/3/2")
        assert main.has_notice_url(o) is False

    def test_sam_pdf_nie_jest_ogloszeniem(self):
        o = _offer(url="https://bip.example.pl/files/ogloszenie.pdf")
        assert main.has_notice_url(o) is False

    def test_strona_glowna_bez_wpisu(self):
        assert main.has_notice_url(_offer(url="https://bip.example.pl")) is False


class TestMarkMenuLinks:
    def _storage(self, tmp_path, offers):
        import json
        p = tmp_path / "oferty.json"
        s = tmp_path / "stan.json"
        p.write_text(json.dumps(offers, ensure_ascii=False), encoding="utf-8")
        s.write_text(json.dumps({"seen_urls": [], "rejected": {}, "reextract": {}}),
                     encoding="utf-8")
        return Storage(offers_path=str(p), state_path=str(s))

    def test_oznacza_tylko_menu(self, tmp_path):
        offers = [
            _offer(url="https://bip.example.pl/12345/nabor-na-czlonka-rady-nadzorczej"),
            _offer(url="https://bip.example.pl/ogloszenia-o-naborach"),
        ]
        st = self._storage(tmp_path, offers)
        url_pred = lambda u: main.has_notice_url({"url": u})  # noqa: E731
        assert st.mark_menu_links(url_pred, today="2026-11-03") == 1
        assert st.offers[1]["nieaktualna"] is True
        assert st.offers[1]["nieaktualna_data"] == "2026-11-03"
        assert "nieaktualna" not in st.offers[0]

    def test_oznacza_wpis_z_audytu_menu(self, tmp_path):
        """Werdykt audytu (link_status=menu) jest mocniejszy niż kształt URL-a."""
        offers = [_offer(url="https://bip.example.pl/18229/ogloszenie-o-naborze",
                         link_status="menu")]
        st = self._storage(tmp_path, offers)
        url_pred = lambda u: main.has_notice_url({"url": u})  # noqa: E731
        assert st.mark_menu_links(url_pred) == 1
        assert st.offers[0]["nieaktualna"] is True
        assert "audyt" in st.offers[0]["nieaktualna_powod"]

    def test_nie_nadpisuje_juz_oznaczonych(self, tmp_path):
        offers = [_offer(url="https://bip.example.pl/menu",
                         nieaktualna=True,
                         nieaktualna_powod="wcześniejszy powód")]
        st = self._storage(tmp_path, offers)
        url_pred = lambda u: main.has_notice_url({"url": u})  # noqa: E731
        assert st.mark_menu_links(url_pred) == 0
        assert st.offers[0]["nieaktualna_powod"] == "wcześniejszy powód"


class TestMergePublicationDate:
    def test_html_wygrywa(self):
        o = main.merge_publication_date(_offer(data_publikacji="2026-10-01"),
                                        "2026-10-10", "")
        assert o["data_publikacji"] == "2026-10-10"
        assert o["data_publikacji_zrodlo"] == "html"

    def test_data_z_llm_nie_jest_kasowana_gdy_html_pusty(self):
        o = main.merge_publication_date(_offer(data_publikacji="2026-10-01"), "", "")
        assert o["data_publikacji"] == "2026-10-01"
        assert o["data_publikacji_zrodlo"] == "llm"

    def test_fallback_parsera_z_tekstu(self):
        tekst = "Data publikacji: 12.10.2026. Ogłoszenie o naborze..."
        o = main.merge_publication_date(_offer(), "", tekst)
        assert o["data_publikacji"] == "2026-10-12"
        assert o["data_publikacji_zrodlo"] == "parser"

    def test_brak_daty_zostaje_pusty(self):
        o = main.merge_publication_date(_offer(), "", "Ogłoszenie bez żadnej daty")
        assert o["data_publikacji"] == ""
        assert "data_publikacji_zrodlo" not in o


class TestPublicatonFromText:
    def test_data_w_przyszlosci_odrzucona(self):
        future = date.today().replace(year=date.today().year + 1).isoformat()
        tekst = f"Data publikacji: {future}"
        assert content_fetcher.extract_publication_from_text(tekst) == ""

    def test_bez_etykiety_pusto(self):
        assert content_fetcher.extract_publication_from_text(
            "Termin składania ofert: 15.11.2026") == ""


class TestReextractCandidates:
    def test_brak_daty_publikacji_tez_kandydatem(self, tmp_path):
        import json
        p = tmp_path / "oferty.json"
        s = tmp_path / "stan.json"
        offers = [
            _offer(url="https://bip.example.pl/1/a", data_publikacji=""),
            _offer(url="https://bip.example.pl/2/b", data_publikacji="2026-10-01"),
        ]
        p.write_text(json.dumps(offers, ensure_ascii=False), encoding="utf-8")
        s.write_text(json.dumps({"seen_urls": [], "rejected": {}, "reextract": {}}),
                     encoding="utf-8")
        st = Storage(offers_path=str(p), state_path=str(s))
        cands = st.get_reextract_candidates(10)
        assert [c["url"] for c in cands] == ["https://bip.example.pl/1/a"]
