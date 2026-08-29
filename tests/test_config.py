# -*- coding: utf-8 -*-
"""Testy config.py: parsowanie EXTRA_DORKS i walidacja zmiennych liczbowych."""
import importlib
import sys

import pytest

sys.stdout.reconfigure(encoding="utf-8")

import config


def _reload_with(monkeypatch, **env):
    """Przeładowuje config z podanymi zmiennymi środowiskowymi."""
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return importlib.reload(config)


def test_extra_dorks_parsing(monkeypatch):
    cfg = _reload_with(
        monkeypatch,
        EXTRA_DORKS='site:bip.grudziadz.pl "rady nadzorczej"|"ogłoszenie o naborze" Grudziądz |  ',
    )
    assert cfg.EXTRA_DORKS == [
        'site:bip.grudziadz.pl "rady nadzorczej"',
        '"ogłoszenie o naborze" Grudziądz',
    ]


def test_extra_dorks_empty(monkeypatch):
    cfg = _reload_with(monkeypatch, EXTRA_DORKS="")
    assert cfg.EXTRA_DORKS == []


def test_extra_dorks_unset(monkeypatch):
    monkeypatch.delenv("EXTRA_DORKS", raising=False)
    cfg = importlib.reload(config)
    assert cfg.EXTRA_DORKS == []


def test_search_days_back_valid(monkeypatch):
    cfg = _reload_with(monkeypatch, SEARCH_DAYS_BACK="7")
    assert cfg.SEARCH_DAYS_BACK == 7


def test_search_days_back_invalid_falls_back(monkeypatch, caplog):
    cfg = _reload_with(monkeypatch, SEARCH_DAYS_BACK="abc")
    assert cfg.SEARCH_DAYS_BACK == 5  # wartość domyślna + WARNING w logu


def test_results_per_dork_allowed_values(monkeypatch):
    cfg = _reload_with(monkeypatch, RESULTS_PER_DORK="30")
    assert cfg.RESULTS_PER_DORK == 30


def test_results_per_dork_disallowed_falls_back(monkeypatch):
    # 25 nie jest wielokrotnością strony (10) - wraca domyślne 20
    cfg = _reload_with(monkeypatch, RESULTS_PER_DORK="25")
    assert cfg.RESULTS_PER_DORK == 20


def test_validate_missing_vars_raises(monkeypatch):
    # Atrapa zmiennych - nie ruszamy prawdziwego środowiska (.env), bo
    # load_dotenv() przy imporcie config i tak by je odtworzyło
    monkeypatch.setattr(config, "REQUIRED_VARS", ["FAKE_VAR_1", "FAKE_VAR_2"])
    with pytest.raises(ValueError) as exc:
        config.validate()
    assert "FAKE_VAR_1" in str(exc.value)
    assert "FAKE_VAR_2" in str(exc.value)


def test_validate_passes_when_all_present(monkeypatch):
    monkeypatch.setattr(config, "REQUIRED_VARS", ["FAKE_VAR_1"])
    monkeypatch.setenv("FAKE_VAR_1", "x")
    config.validate()  # brak wyjątku = sukces


def teardown_module(module):
    # Przywróć config wczytany z prawdziwego środowiska
    importlib.reload(config)
