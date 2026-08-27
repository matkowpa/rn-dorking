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
# Zmienne Google są opcjonalne tylko w trybie testowym DuckDuckGo (Plan B);
# przy normalnym uruchomieniu Google ich brak oznacza awaryjny tryb DDG
GOOGLE_VARS = ["GOOGLE_API_KEY", "GOOGLE_CX"]


def validate() -> None:
    """Sprawdza obecność wymaganych zmiennych .env.

    Zmienne LLM są obowiązkowe (bez nich potok nie działa).
    Zmienne Google są sprawdzane osobno: use_google() mówi, czy potok
    może użyć Google CSE, czy ma użyć zapasowego DuckDuckGo (Plan B).
    Rzuca ValueError z listą brakujących zmiennych obowiązkowych.
    """
    missing = [v for v in REQUIRED_VARS if not os.getenv(v)]
    if missing:
        raise ValueError(
            "Brakujące zmienne w .env: " + ", ".join(missing)
        )


def use_google() -> bool:
    """True, jeśli skonfigurowano Google CSE (obie zmienne Google obecne)."""
    return all(bool(os.getenv(v)) for v in GOOGLE_VARS)


# Eksportowane stałe modułu
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GOOGLE_CX = os.getenv("GOOGLE_CX", "")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
LLM_MODEL = os.getenv("LLM_MODEL", "")
LLM_MODEL_EXTRACT = os.getenv("LLM_MODEL_EXTRACT", "")
SEARCH_DAYS_BACK = _parse_int("SEARCH_DAYS_BACK", 5)
RESULTS_PER_DORK = _parse_int("RESULTS_PER_DORK", 20, allowed=[10, 20, 30, 40])
