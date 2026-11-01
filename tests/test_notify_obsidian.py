# -*- coding: utf-8 -*-
"""Testy kanału Obsidian: kolejność sekcji, idempotencja, brak vaulta w CI."""
import sys

sys.stdout.reconfigure(encoding="utf-8")

import notify_obsidian


def _vault(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    return tmp_path / "Nabory-RN.md"


def test_nowa_sekcja_na_gore_nie_rozrywa_poprzedniej(tmp_path, monkeypatch):
    note = _vault(tmp_path, monkeypatch)
    assert notify_obsidian.dopisz("2026-10-30", "pierwszy digest")[0]
    assert notify_obsidian.dopisz("2026-10-31", "drugi digest")[0]

    content = note.read_text(encoding="utf-8")
    # nowszy dzień wyżej, starszy niżej
    assert content.index("## 2026-10-31") < content.index("## 2026-10-30")
    # treść starszego dnia zostaje pod jego nagłówkiem, a nie pod nowym
    starsza = content.split("## 2026-10-30", 1)[1]
    assert "pierwszy digest" in starsza
    assert "drugi digest" not in starsza
    # nowy nagłówek nie jest pusty
    nowsza = content.split("## 2026-10-31", 1)[1].split("## 2026-10-30", 1)[0]
    assert "drugi digest" in nowsza


def test_idempotencja_tej_samej_tresci(tmp_path, monkeypatch):
    note = _vault(tmp_path, monkeypatch)
    assert notify_obsidian.dopisz("2026-10-30", "ten sam digest")[0]
    ok, _ = notify_obsidian.dopisz("2026-10-30", "ten sam digest")
    assert ok is False
    assert note.read_text(encoding="utf-8").count("ten sam digest") == 1


def test_uzupelnienie_istniejacej_sekcji(tmp_path, monkeypatch):
    note = _vault(tmp_path, monkeypatch)
    assert notify_obsidian.dopisz("2026-10-30", "pierwsza partia")[0]
    assert notify_obsidian.dopisz("2026-10-30", "druga partia")[0]
    content = note.read_text(encoding="utf-8")
    assert "pierwsza partia" in content
    assert "druga partia" in content
    assert content.count("## 2026-10-30") == 1


def test_brak_vaulta_pomija_bez_tworzenia_pliku(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path / "nie-ma"))
    ok, msg = notify_obsidian.dopisz("2026-10-30", "cokolwiek")
    assert ok is False
    assert "vault nie istnieje" in msg
    assert not (tmp_path / "nie-ma").exists()
