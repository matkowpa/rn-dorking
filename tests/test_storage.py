# -*- coding: utf-8 -*-
"""Testy storage.py: normalizacja URL, deduplikacja, trwałość, plik dnia."""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

import pytest

import storage as storage_mod
from storage import Storage, _normalize_url, _url_hash


@pytest.fixture
def storage(tmp_path, monkeypatch):
    """Storage działający w katalogu tymczasowym (izolacja od repo)."""
    monkeypatch.chdir(tmp_path)
    return Storage(offers_path="oferty.json", state_path="stan.json")


OFFER = {
    "podmiot": "Spółka Testowa Łąć Węgiel",
    "url": "https://Przyklad.pl/nabor/?utm_source=test",
    "termin_skladania_ofert": "2026-09-15",
}


def test_normalize_url_lowercases_host():
    assert _normalize_url("HTTPS://Przykład.PL/Ścieżka") == "https://przykład.pl/Ścieżka"


def test_normalize_url_strips_utm_and_fragment():
    url = "https://example.pl/a?utm_source=x&utm_medium=y&id=1#top"
    assert _normalize_url(url) == "https://example.pl/a?id=1"


def test_normalize_url_strips_trailing_slash():
    assert _normalize_url("https://example.pl/a/") == "https://example.pl/a"


def test_is_new_and_dedup(storage):
    assert storage.is_new(OFFER["url"]) is True
    assert storage.merge_offers([OFFER]) == 1
    assert storage.merge_offers([OFFER]) == 0  # drugi raz = duplikat


def test_dedup_across_url_variants(storage):
    storage.merge_offers([OFFER])
    # Ten sam URL: inne wielkości, utm_, fragment, trailing slash -> duplikat
    assert storage.is_new("https://przyklad.pl/nabor/?utm_source=other#frag") is False


def test_persistence_utf8_and_sort(storage):
    storage.merge_offers([
        {**OFFER, "termin_skladania_ofert": "2026-09-01"},
        {**OFFER, "url": "https://example.pl/b", "termin_skladania_ofert": "2026-09-20"},
        {**OFFER, "url": "https://example.pl/c", "termin_skladania_ofert": ""},
    ])
    storage.save()
    with open("oferty.json", encoding="utf-8") as f:
        saved = json.load(f)
    # polskie znaki surowo (bez \uXXXX)
    assert "Łąć" in json.dumps(saved, ensure_ascii=False)
    # sortowanie malejąco po terminie, "" na końcu
    terms = [o["termin_skladania_ofert"] for o in saved]
    assert terms == ["2026-09-20", "2026-09-01", ""]


def test_reload_keeps_seen_urls(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s1 = Storage(offers_path="o.json", state_path="s.json")
    s1.merge_offers([OFFER])
    s1.save()
    s2 = Storage(offers_path="o.json", state_path="s.json")
    assert s2.is_new(OFFER["url"]) is False


def test_save_daily_merges_same_day(storage):
    storage.merge_offers([{**OFFER, "znaleziono_dnia": "2026-08-29"}])
    stats = {"raw_results": 1, "offers_added": 1}
    p1 = storage.save_daily(stats, run_date="2026-08-29")
    assert storage._load_json(p1)["offers"]
    # Drugi run tego samego dnia z nową ofertą - nic nie ginie
    storage.merge_offers([{**OFFER, "url": "https://example.pl/2",
                           "znaleziono_dnia": "2026-08-29"}])
    p2 = storage.save_daily(stats, run_date="2026-08-29")
    assert p1 == p2
    day = storage._load_json(p2)
    assert len(day["offers"]) == 2
    assert day["stats"] == stats


def test_url_hash_stable():
    assert _url_hash("https://a.pl/x") == _url_hash("https://a.pl/x/")


# --- Pamięć odrzuconych URL-i (rejected, TTL 30 dni) ---

def test_rejected_url_is_skipped(storage):
    storage.add_rejected(OFFER["url"])
    assert storage.is_rejected(OFFER["url"]) is True
    # Wariant URL (utm_/trailing slash) też rozpoznawany jako odrzucony
    assert storage.is_rejected("https://przyklad.pl/nabor/") is True


def test_rejected_ttl_prunes_old_entries(storage):
    old_date = (date.today() - timedelta(days=storage_mod.REJECT_TTL_DAYS + 1)).isoformat()
    storage.rejected[_url_hash("https://old.pl/a")] = old_date
    storage.rejected[_url_hash("https://fresh.pl/b")] = date.today().isoformat()
    storage._prune_rejected()
    assert _url_hash("https://old.pl/a") not in storage.rejected
    assert _url_hash("https://fresh.pl/b") in storage.rejected


def test_rejected_persist_across_reload(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s1 = Storage(offers_path="o.json", state_path="s.json")
    s1.add_rejected("https://example.pl/odrzucony")
    s1.save()
    s2 = Storage(offers_path="o.json", state_path="s.json")
    assert s2.is_rejected("https://example.pl/odrzucony") is True


def test_old_state_format_backcompat(tmp_path, monkeypatch):
    # stan.json sprzed zmiany (tylko seen_urls) musi się wczytać bez błędu
    monkeypatch.chdir(tmp_path)
    Path("s.json").write_text(json.dumps({"seen_urls": []}), encoding="utf-8")
    s = Storage(offers_path="o.json", state_path="s.json")
    assert s.rejected == {} and s.reextract == {}


# --- Re-ekstrakcja ofert bez terminu ---

def test_reextract_candidates_sorted_oldest_first(storage):
    storage.merge_offers([
        {**OFFER, "url": "https://a.pl/1", "termin_skladania_ofert": "",
         "znaleziono_dnia": "2026-08-29"},
        {**OFFER, "url": "https://a.pl/2", "termin_skladania_ofert": "",
         "znaleziono_dnia": "2026-08-28"},
        {**OFFER, "url": "https://a.pl/3", "termin_skladania_ofert": "2026-09-01"},
    ])
    cands = storage.get_reextract_candidates(5)
    assert [c["url"] for c in cands] == ["https://a.pl/2", "https://a.pl/1"]


def test_reextract_respects_max_attempts(storage):
    storage.merge_offers([{**OFFER, "termin_skladania_ofert": ""}])
    storage.mark_extract_attempt(OFFER["url"])
    storage.mark_extract_attempt(OFFER["url"])
    assert storage.get_reextract_candidates(5) == []


def test_mark_attempt_persists(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s1 = Storage(offers_path="o.json", state_path="s.json")
    s1.merge_offers([{**OFFER, "termin_skladania_ofert": ""}])
    s1.mark_extract_attempt(OFFER["url"])
    s1.save()
    s2 = Storage(offers_path="o.json", state_path="s.json")
    assert s2.reextract[_url_hash(OFFER["url"])]["attempts"] == 1


def test_update_offer_replaces_fields_keeps_history(storage):
    storage.merge_offers([{**OFFER, "termin_skladania_ofert": "",
                           "znaleziono_dnia": "2026-08-28"}])
    ok = storage.update_offer(OFFER["url"], {
        "podmiot": "Nowa Nazwa", "termin_skladania_ofert": "2026-09-20",
        "url": OFFER["url"], "znaleziono_dnia": date.today().isoformat(),
    })
    assert ok is True
    offer = storage.offers[0]
    assert offer["podmiot"] == "Nowa Nazwa"
    assert offer["termin_skladania_ofert"] == "2026-09-20"
    # Historia zachowana: url i znaleziono_dnia z pierwotnego dodania
    assert offer["url"] == OFFER["url"]
    assert offer["znaleziono_dnia"] == "2026-08-28"


def test_update_offer_unknown_url_returns_false(storage):
    assert storage.update_offer("https://nietma.pl/x", {"podmiot": "X"}) is False
