# -*- coding: utf-8 -*-
"""Wczytanie i walidacja konfiguracji z pliku .env (ETAP 0)."""

import logging
import os

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Wczytanie pliku .env (jeśli istnieje)
load_dotenv()


def _parse_int(name: str, default: int, allowed: list[int] | None = None) -> int:
    """Parsuje zmienną środowiskową jako int z obsługą wartości domyślnej.

    Jeśli wartości jest poza listą dozwolonych (allowed) lub nie da się
    skonwertować - loguje WARNING i zwraca wartość domyślną.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        logger.warning("%s niepoprawne, użyto wartości domyślnej %s", name, default)
        return default
    if allowed is not None and value not in allowed:
        logger.warning("%s niepoprawne, użyto wartości domyślnej %s", name, default)
        return default
    return value


# Walidacja obecności zmiennych
REQUIRED_VARS = ["LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "LLM_MODEL_EXTRACT"]

# ClinePass: klucz CLINE_API_KEY ma pierwszeństwo nad parą LLM_* (OpenRouter).
# Klucz Cline nie może polecieć na api.openrouter.ai, a model musi być w formie
# subskrypcyjnej cline-pass/<model>, nie w surowej vendor/model.
CLINE_BASE_URL = "https://api.cline.bot/api/v1"
CLINE_MODEL = "cline-pass/deepseek-v4.1-flash-1017"


def _resolve_llm() -> tuple[str, str, str, str]:
    """Zwraca (api_key, base_url, model, model_extract) dla aktywnego dostawcy."""
    cline = os.getenv("CLINE_API_KEY", "").strip()
    if cline:
        base = os.getenv("CLINE_BASE_URL", "").strip() or CLINE_BASE_URL
        model = os.getenv("LLM_MODEL", "").strip()
        extract = os.getenv("LLM_MODEL_EXTRACT", "").strip()
        # Piny z sekretów działają tylko wtedy, gdy są już w formie Cline.
        model = model if model.startswith("cline-pass/") else CLINE_MODEL
        extract = extract if extract.startswith("cline-pass/") else CLINE_MODEL
        return cline, base, model, extract
    return (os.getenv("LLM_API_KEY", ""), os.getenv("LLM_BASE_URL", ""),
            os.getenv("LLM_MODEL", ""), os.getenv("LLM_MODEL_EXTRACT", ""))


def validate() -> None:
    """Sprawdza obecność wymaganych zmiennych .env.

    Wystarczy komplet LLM_* albo sam CLINE_API_KEY (wtedy base_url i model
    biorą się z domyślnych ClinePass). Backend wyszukiwania wybiera
    use_brave(): Brave API, a gdy brak klucza - zapasowe DuckDuckGo.
    Rzuca ValueError z listą brakujących zmiennych obowiązkowych.
    """
    if os.getenv("CLINE_API_KEY", "").strip():
        return
    missing = [v for v in REQUIRED_VARS if not os.getenv(v)]
    if missing:
        raise ValueError(
            "Brakujące zmienne w .env: " + ", ".join(missing)
        )


def use_brave() -> bool:
    """True, jeśli skonfigurowano Brave Search API."""
    return bool(os.getenv("BRAVE_API_KEY"))


# Eksportowane stałe modułu
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")
LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_MODEL_EXTRACT = _resolve_llm()
# Oba modele pochodza ze zmiennych srodowiskowych; w CI ustawia je sekret
# GitHub Actions CLINE_API_KEY (workflow .github/workflows/daily.yml), ktory
# wygrywa z historycznymi LLM_* (OpenRouter). Standard projektu:
# cline-pass/deepseek-v4.1-flash-1017.
SEARCH_DAYS_BACK = _parse_int("SEARCH_DAYS_BACK", 5)
RESULTS_PER_DORK = _parse_int("RESULTS_PER_DORK", 20, allowed=[10, 20, 30, 40])
# Dodatkowe dorki z .env, oddzielone znakiem | (pusta wartość = brak)
EXTRA_DORKS = [d.strip() for d in os.getenv("EXTRA_DORKS", "").split("|") if d.strip()]
# Rozmiar dziennego okna skanu BIP-ów samorządowych (FAZA 0b, direct_sources)
JST_WINDOW = _parse_int("JST_WINDOW", 100)
# FAZA 0c (R2): wyszukiwarka treści / dział ogłoszeń na BIP-ach.
# R2_ENABLED=0 wyłącza krok, R2_SITES ogranicza liczbę podmiotów na run
# (0 = bez limitu). Domyślnie 40 podmiotów: ~3 requesty każdy, ~2 min.
R2_ENABLED = os.getenv("R2_ENABLED", "1").strip().lower() not in ("0", "false", "nie")
R2_SITES = _parse_int("R2_SITES", 40)
