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


def validate() -> None:
    """Sprawdza obecność wymaganych zmiennych .env.

    Zmienne LLM są obowiązkowe (bez nich potok nie działa).
    Backend wyszukiwania wybiera use_brave(): Brave API, a gdy brak klucza -
    zapasowe DuckDuckGo.
    Rzuca ValueError z listą brakujących zmiennych obowiązkowych.
    """
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
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
LLM_MODEL = os.getenv("LLM_MODEL", "")
LLM_MODEL_EXTRACT = os.getenv("LLM_MODEL_EXTRACT", "")
SEARCH_DAYS_BACK = _parse_int("SEARCH_DAYS_BACK", 5)
RESULTS_PER_DORK = _parse_int("RESULTS_PER_DORK", 20, allowed=[10, 20, 30, 40])
# Dodatkowe dorki z .env, oddzielone znakiem | (pusta wartość = brak)
EXTRA_DORKS = [d.strip() for d in os.getenv("EXTRA_DORKS", "").split("|") if d.strip()]
# Rozmiar dziennego okna skanu BIP-ów samorządowych (FAZA 0b, direct_sources)
JST_WINDOW = _parse_int("JST_WINDOW", 100)
