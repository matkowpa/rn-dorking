# -*- coding: utf-8 -*-
"""Testy resolvera adresów BIP (offline, bez sieci)."""

import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "resolve_bip_urls", ROOT / "tools" / "resolve_bip_urls.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rb = _load()


class TestLooksLikeBip:
    def test_podstrona_bip_gov_pl(self):
        assert rb.looks_like_bip("https://gmina.bip.gov.pl") is True

    def test_bip_w_domenie(self):
        assert rb.looks_like_bip("https://bip.gogolin.pl") is True

    def test_sciezka_bip(self):
        assert rb.looks_like_bip("https://leczna.pl/bip") is True

    def test_portal_gov_pl_odrzucony(self):
        assert rb.looks_like_bip("https://www.gov.pl/web/bip/gmina-kodrab") is False

    def test_wikipedia_odrzucona(self):
        assert rb.looks_like_bip("https://pl.wikipedia.org/wiki/Gmina_Barcin") is False


class TestQueryFor:
    def test_gmina_teryt_dostaje_powiat(self):
        q = rb.query_for({"name": "Gmina Barcin", "hint": "Nakielski Kujawsko-Pomorskie",
                          "kind": "gmina-teryt"})
        assert q == '"Barcin" BIP Nakielski Kujawsko-Pomorskie'

    def test_bez_hinta_zostaje_krotkie(self):
        q = rb.query_for({"name": "Gmina Barcin", "hint": "", "kind": "gmina"})
        assert q == '"Gmina Barcin" BIP'


class TestBuildTodo:
    def test_teryt_bez_adresu_jest_w_todo(self):
        teryt = [{"teryt": "020101", "name": "Bolesławiec", "powiat": "Bolesławiecki",
                  "voivodeship": "Dolnośląskie", "gmina_type": "1"}]
        todo = rb.build_todo([], teryt, {})
        assert todo[0]["slug"] == "teryt-020101"
        assert todo[0]["name"] == "Miasto Bolesławiec"

    def test_rozwiazane_sa_pomijane(self):
        teryt = [{"teryt": "020101", "name": "Bolesławiec"}]
        todo = rb.build_todo([], teryt, {"teryt-020101": "https://bip.example.pl"})
        assert todo == []

    def test_force_nadpisuje(self):
        teryt = [{"teryt": "020101", "name": "Bolesławiec"}]
        todo = rb.build_todo([], teryt, {"teryt-020101": "https://bip.example.pl"},
                             force=True)
        assert len(todo) == 1

    def test_teryt_only_pomija_rejestr(self):
        registry = [{"slug": "/gmina-x", "name": "Gmina X"}]
        teryt = [{"teryt": "020101", "name": "Bolesławiec"}]
        todo = rb.build_todo(registry, teryt, {}, teryt_only=True)
        assert [t["slug"] for t in todo] == ["teryt-020101"]


class TestResolve:
    def test_przyjmuje_pierwszego_zwalidowanego(self, monkeypatch):
        monkeypatch.setattr(rb, "search", lambda q, limit=6: [
            "https://bip.zla-gmina.pl", "https://bip.dobra-gmina.pl"])
        monkeypatch.setattr(rb, "validate", lambda url, name, timeout=12: (
            (False, "nazwa nie pasuje") if "zla" in url else (True, "200")))
        url, detail = rb.resolve({"name": "Gmina Dobra", "slug": "teryt-1"})
        assert url == "https://bip.dobra-gmina.pl"
        assert detail == "200"

    def test_brak_kandydatow(self, monkeypatch):
        monkeypatch.setattr(rb, "search", lambda q, limit=6: [])
        url, detail = rb.resolve({"name": "Gmina Dobra", "slug": "teryt-1"})
        assert url == ""
        assert "brak kandydata" in detail

    def test_wszystkie_odrzucone(self, monkeypatch):
        monkeypatch.setattr(rb, "search", lambda q, limit=6: ["https://bip.zla.pl"])
        monkeypatch.setattr(rb, "validate", lambda url, name, timeout=12: (False, "HTTP 404"))
        url, detail = rb.resolve({"name": "Gmina Dobra", "slug": "teryt-1"})
        assert url == ""
        assert "404" in detail


class TestValidate:
    class Resp:
        def __init__(self, status, text):
            self.status_code = status
            self.text = text

    def test_akceptuje_strone_z_nazwa(self, monkeypatch):
        monkeypatch.setattr(rb.requests, "get", lambda *a, **k: self.Resp(
            200, "<h1>Urząd Gminy Barcin</h1><a href='?a=1'>Ogłoszenia o naborze</a>"))
        ok, detail = rb.validate("https://bip.barcin.pl", "Gmina Barcin")
        assert ok is True
        assert "sekcja ogłoszeń: tak" in detail

    def test_odrzuca_inna_gmine(self, monkeypatch):
        monkeypatch.setattr(rb.requests, "get", lambda *a, **k: self.Resp(
            200, "<h1>Urząd Gminy Kcynia</h1>"))
        ok, detail = rb.validate("https://bip.example.pl", "Gmina Barcin")
        assert ok is False
        assert "nazwa" in detail

    def test_odrzuca_http_404(self, monkeypatch):
        monkeypatch.setattr(rb.requests, "get", lambda *a, **k: self.Resp(404, ""))
        ok, detail = rb.validate("https://bip.barcin.pl", "Gmina Barcin")
        assert ok is False
        assert "404" in detail

    def test_odrzuca_strone_pokontrolna_rio(self, monkeypatch):
        """Współdzielony portal RIO wymienia gminy w treści - to nie ich BIP."""
        html = ("<html><head><title>31- Lelów- wystąpienie pokontrolne</title></head>"
                "<body>Gmina Kornowac, Gmina Lelów, Gmina Krzanowice</body></html>")
        monkeypatch.setattr(rb.requests, "get", lambda *a, **k: self.Resp(200, html))
        ok, detail = rb.validate("https://riokatowice.bip.net.pl/?c=246", "Gmina Kornowac")
        assert ok is False
        assert "kontroli" in detail
