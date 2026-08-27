# -*- coding: utf-8 -*-
"""Deduplikacja, stan i trwałość ofert (ETAP 4)."""

import hashlib
import json
import logging
import os
from urllib.parse import urlsplit, urlunsplit

logger = logging.getLogger(__name__)


def _normalize_url(url: str) -> str:
    """Normalizuje URL: lowercase host, usuwa parametry utm_, fragment,
    końcowy '/' ze ścieżki."""
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    host = parts.netloc.lower()
    # Usuń parametry zapytania zaczynające się od "utm_"
    if parts.query:
        kept = [p for p in parts.query.split("&") if not p.split("=")[0].startswith("utm_")]
        query = "&".join(kept)
    else:
        query = ""
    path = parts.path
    if path.endswith("/"):
        path = path[:-1]
    return urlunsplit((scheme, host, path, query, ""))


def _url_hash(url: str) -> str:
    """SHA1 znormalizowanego URL-a."""
    return hashlib.sha1(_normalize_url(url).encode("utf-8")).hexdigest()


class Storage:
    """Zarządza plikami oferty.json (merge) i stan.json (pamięć deduplikacji)."""

    def __init__(self, offers_path: str = "oferty.json", state_path: str = "stan.json"):
        self.offers_path = offers_path
        self.state_path = state_path
        self.offers: list[dict] = []
        self.seen_urls: set[str] = set()
        self._load_state()

    def _load_json(self, path: str):
        """Wczytuje JSON z pliku w UTF-8 albo None, jeśli brak pliku."""
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Nie udało się wczytać %s: %s", path, e)
            return None

    def _load_state(self) -> set:
        """Wczytuje seen_urls ze stan.json albo migruje z oferty.json."""
        state = self._load_json(self.state_path)
        if state is not None:
            self.seen_urls = set(state.get("seen_urls", []))
            return self.seen_urls
        # Migracja ze starej wersji: stan.json brak, oferty.json istnieje
        offers = self._load_json(self.offers_path)
        if offers is not None:
            self.offers = list(offers)
            self.seen_urls = {_url_hash(o.get("url", "")) for o in self.offers if o.get("url")}
        return self.seen_urls

    def is_new(self, url: str) -> bool:
        """True, jeśli hash znormalizowanego URL-a nie występuje w seen_urls."""
        return _url_hash(url) not in self.seen_urls

    def add_offer(self, offer: dict) -> None:
        """Dopisuje ofertę do pamięci i hash URL-a do seen_urls."""
        self.offers.append(offer)
        self.seen_urls.add(_url_hash(offer.get("url", "")))

    def save(self) -> None:
        """Atomowo zapisuje oferty.json i stan.json (UTF-8, ensure_ascii=False)."""
        # Sortuj oferty malejąco po terminie ("" trafia na koniec przy reverse=True)
        self.offers.sort(key=lambda o: o.get("termin_skladania_ofert", ""), reverse=True)
        self._atomic_write(self.offers_path, self.offers)
        self._atomic_write(self.state_path, {"seen_urls": sorted(self.seen_urls)})

    def _atomic_write(self, path: str, data) -> None:
        """Zapis do pliku tymczasowego w tym samym katalogu, potem os.replace."""
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)

    def merge_offers(self, new_offers: list[dict]) -> int:
        """Dopisuje tylko nowe oferty (po URL); zwraca liczbę DODANYCH."""
        added = 0
        for offer in new_offers:
            if self.is_new(offer.get("url", "")):
                self.add_offer(offer)
                added += 1
        return added


if __name__ == "__main__":
    # Self-test (ETAP 4a, 4b)
    logging.basicConfig(level=logging.INFO)
    storage = Storage(offers_path="test_oferty.json", state_path="test_stan.json")
    offer = {
        "podmiot": "Spółka Testowa Łąć Węgiel",
        "url": "https://Przyklad.pl/nabor/?utm_source=test",
        "termin_skladania_ofert": "",
    }
    first = storage.merge_offers([offer])
    second = storage.merge_offers([offer])
    storage.save()
    # Weryfikacja zapisu
    with open("test_oferty.json", "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert first == 1 and second == 0, f"deduplication failed: {first}, {second}"
    assert "ą" in saved[0]["podmiot"] and "ę" in saved[0]["podmiot"], "UTF-8 failed"
    # Ten sam URL z różnymi utm_ musi być uznany za duplikat
    storage2 = Storage(offers_path="test_oferty.json", state_path="test_stan.json")
    assert not storage2.is_new("https://przyklad.pl/nabor/?utm_source=other#frag"), "norm failed"
    os.remove("test_oferty.json")
    os.remove("test_stan.json")
    print("Self-test storage OK")
