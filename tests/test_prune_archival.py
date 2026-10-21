# -*- coding: utf-8 -*-
"""Testy prune_archival w Storage."""

import json

import main
from storage import Storage


def _seed(tmp_path, offers):
    offers_path = tmp_path / "oferty.json"
    state_path = tmp_path / "stan.json"
    offers_path.write_text(json.dumps(offers, ensure_ascii=False), encoding="utf-8")
    state_path.write_text(json.dumps({"seen_urls": [], "rejected": {}, "reextract": {}}),
                          encoding="utf-8")
    return Storage(offers_path=str(offers_path), state_path=str(state_path))


def test_prune_usuwa_archiwalne(tmp_path):
    offers = [
        {"podmiot": "Stara", "url": "https://a.pl/1", "termin_skladania_ofert": "2023-03-27",
         "data_publikacji": "", "znaleziono_dnia": "2026-10-15"},
        {"podmiot": "Nowa", "url": "https://a.pl/2", "termin_skladania_ofert": "2026-12-01",
         "data_publikacji": "", "znaleziono_dnia": "2026-10-15"},
    ]
    st = _seed(tmp_path, offers)
    removed = st.prune_archival(main.is_archival)
    assert removed == 1
    assert len(st.offers) == 1
    assert st.offers[0]["podmiot"] == "Nowa"


def test_prune_nic_nie_usuwa_gdy_wszystko_swieze(tmp_path):
    offers = [
        {"podmiot": "A", "url": "https://a.pl/1", "termin_skladania_ofert": "2026-12-01",
         "data_publikacji": "", "znaleziono_dnia": "2026-10-15"},
    ]
    st = _seed(tmp_path, offers)
    assert st.prune_archival(main.is_archival) == 0
    assert len(st.offers) == 1


def test_prune_zachowuje_seen_urls(tmp_path):
    """Odrzucona oferta nadal jest 'widziana' - nie zostanie dodana ponownie."""
    offers = [
        {"podmiot": "Stara", "url": "https://a.pl/1", "termin_skladania_ofert": "2023-03-27",
         "data_publikacji": "", "znaleziono_dnia": "2026-10-15"},
    ]
    st = _seed(tmp_path, offers)
    st.prune_archival(main.is_archival)
    assert not st.is_new("https://a.pl/1")
