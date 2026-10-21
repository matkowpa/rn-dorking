# -*- coding: utf-8 -*-
"""Testy archiwum pre-filtra (Storage.save_raw)."""

import json

from storage import Storage


def _storage(tmp_path):
    op = tmp_path / "oferty.json"
    sp = tmp_path / "stan.json"
    op.write_text("[]", encoding="utf-8")
    sp.write_text(json.dumps({"seen_urls": [], "rejected": {}, "reextract": {}}),
                  encoding="utf-8")
    st = Storage(offers_path=str(op), state_path=str(sp))
    return st


def _raw(url, decision, reason=""):
    return {"url": url, "title": "Tytuł " + url, "snippet": "fragment",
            "source": "dork", "direct": False,
            "decision": decision, "reason": reason}


def test_zapisuje_wszystkie_wyniki(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    st = _storage(tmp_path)
    raw = [
        _raw("https://a.pl/1", "accepted"),
        _raw("https://a.pl/2", "rejected", "frazy dyskwalifikujące: kurs"),
        _raw("https://a.pl/3", "duplicate", "URL już widziany"),
        _raw("https://a.pl/4", "limit"),
    ]
    path = st.save_raw(raw, run_date="2026-10-21")
    payload = json.load(open(path, encoding="utf-8"))
    assert payload["count"] == 4
    assert payload["date"] == "2026-10-21"
    assert payload["decisions"] == {"accepted": 1, "rejected": 1,
                                    "duplicate": 1, "limit": 1}
    assert len(payload["raw"]) == 4


def test_scala_dwa_runy_tego_dnia(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    st = _storage(tmp_path)
    st.save_raw([_raw("https://a.pl/1", "rejected")], run_date="2026-10-21")
    path = st.save_raw([_raw("https://a.pl/2", "accepted")], run_date="2026-10-21")
    payload = json.load(open(path, encoding="utf-8"))
    assert payload["count"] == 2
    assert payload["decisions"] == {"rejected": 1, "accepted": 1}


def test_nowsza_decyzja_wygrywa(tmp_path, monkeypatch):
    """Ten sam URL w drugim runie: decyzja jest aktualizowana, nie duplikowana."""
    monkeypatch.chdir(tmp_path)
    st = _storage(tmp_path)
    st.save_raw([_raw("https://a.pl/1", "rejected")], run_date="2026-10-21")
    path = st.save_raw([_raw("https://a.pl/1", "accepted")], run_date="2026-10-21")
    payload = json.load(open(path, encoding="utf-8"))
    assert payload["count"] == 1
    assert payload["raw"][0]["decision"] == "accepted"


def test_oferta_dolaczona_przy_accepted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    st = _storage(tmp_path)
    entry = _raw("https://a.pl/1", "accepted", "dodano do bazy")
    entry["offer"] = {"podmiot": "Gmina X", "termin_skladania_ofert": "2026-12-01"}
    path = st.save_raw([entry], run_date="2026-10-21")
    payload = json.load(open(path, encoding="utf-8"))
    assert payload["raw"][0]["offer"]["podmiot"] == "Gmina X"


def test_zapis_atomowy_nie_zostawia_smieci(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    st = _storage(tmp_path)
    st.save_raw([_raw("https://a.pl/1", "accepted")], run_date="2026-10-21")
    files = sorted(p.name for p in (tmp_path / "data" / "dnia").iterdir())
    assert files == ["raw-2026-10-21.json"]  # brak plików .tmp
