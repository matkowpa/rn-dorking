# -*- coding: utf-8 -*-
"""Klient LLM: filtrowanie wyników (ETAP B) i ekstrakcja pól (ETAP C)."""

import json
import logging
import re
import sys
import time
from datetime import date

import openai
from pydantic import BaseModel, ValidationError

import config

logger = logging.getLogger(__name__)

# Klient OpenAI (SDK >= 1.0) tworzony leniwie - import modułu NIE wymaga klucza
_client: openai.OpenAI | None = None


def get_client() -> openai.OpenAI:
    """Zwraca klienta OpenAI skonfigurowanego z .env (tworzony przy 1. użyciu)."""
    global _client
    if _client is None:
        _client = openai.OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)
    return _client


def _strip_json(raw: str) -> str:
    """Oczyszcza odpowiedź LLM: usuwa znaczniki markdown i wydobywa JSON."""
    text = raw.strip()
    # Usuń znaczniki ```json i ``` jeśli obecne
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    # Wydobądź podciąg między pierwszym { a ostatnim }
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last != -1 and last > first:
        text = text[first:last + 1]
    return text.strip()


def _create_call(messages: list[dict], model: str, with_response_format: bool):
    """Pojedyncze wywołanie chat.completions.create."""
    kwargs = {"model": model, "temperature": 0.1, "messages": messages}
    if with_response_format:
        kwargs["response_format"] = {"type": "json_object"}
    return get_client().chat.completions.create(**kwargs)


def _call_llm(model: str, system_prompt: str, user_content: str) -> str:
    """Wywołuje LLM z retry wg algorytmu z ETAPU 1, zwraca oczyszczony JSON."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    delays = [3, 6, 12]
    try:
        # KROK 1: wywołanie z response_format
        response = _create_call(messages, model, True)
    except RateLimitError as e:
        # KROK 2a: retry na błąd 429 - do 3 dodatkowych prób z response_format
        for delay in delays:
            logger.warning("LLM rate limit (429), ponawiam za %s s", delay)
            time.sleep(delay)
            try:
                response = _create_call(messages, model, True)
                break
            except RateLimitError:
                continue
        else:
            logger.error("LLM limit zapytań wyczerpany po retry (model=%s): %s", model, e)
            raise
    except Exception as e:
        # KROK 2b: inny błąd - JEDNA próba ponowna BEZ response_format
        logger.warning("LLM błąd z response_format, ponawiam bez: %s", e)
        messages_retry = [
            {"role": "system", "content": system_prompt},
            {"role": "user",
             "content": user_content + "\nZwróć WYŁĄCZNIE surowy JSON bez bloków markdown"},
        ]
        try:
            response = _create_call(messages_retry, model, False)
        except RateLimitError as e2:
            # retry z punktu (a) na wersji bez response_format
            for delay in delays:
                logger.warning("LLM rate limit (429) bez response_format, ponawiam za %s s", delay)
                time.sleep(delay)
                try:
                    response = _create_call(messages_retry, model, False)
                    break
                except RateLimitError:
                    continue
            else:
                logger.error("LLM limit zapytań wyczerpany po retry (model=%s): %s", model, e2)
                raise
        except Exception as e2:
            logger.error("LLM błąd bez response_format: %s (model=%s)", e2, model)
            raise

    # KROK 3: oczyszczenie odpowiedzi
    content = response.choices[0].message.content or ""
    return _strip_json(content)


# System prompt filtra (ETAP B) - dosłownie wg specyfikacji (+ reguła zarządu)
FILTER_SYSTEM_PROMPT = '''Jesteś filtrem ogłoszeń. Na podstawie TYLKO podanego tytułu i fragmentu wyniku wyszukiwania zdecyduj, czy wynik dotyczy otwartego naboru kandydatów na członka rady nadzorczej (spółki, funduszy, instytucji publicznych). Nie dotyczą naboru: archiwalne ogłoszenia, protokoły z posiedzeń, uchwały o powołaniu już wybranych osób, aktualności, strony główne BIP, wzory dokumentów. Nabór na stanowiska zarządu (członek zarządu, prezes zarządu, wiceprezes zarządu) NIE jest istotny - nawet gdy postępowanie przeprowadza rada nadzorcza; odrzucaj takie wyniki. Zwróć WYŁĄCZNIE obiekt JSON: {"czy_to_nabor": true lub false, "uzasadnienie": "maks. 15 słów"}'''

# Deterministyczny pre-filtr (przed LLM): frazy stanowisk zarządu. Ogłoszenia
# o naborze na członka/prezesa zarządu są nieistotne (projekt dotyczy WYŁĄCZNIE
# rad nadzorczych). Stosowany tylko, gdy tekst nie wspomina o radzie nadzorczej
# - przypadki mieszane (np. "rada nadzorcza ogłasza nabór na prezesa zarządu")
# rozstrzyga filtr LLM wg reguły w FILTER_SYSTEM_PROMPT.
ZARZAD_RE = re.compile(
    r"członk\w* zarządu|prezes\w* zarządu|wiceprezes\w* zarządu", re.IGNORECASE)
NADZORCZA_RE = re.compile(r"nadzorcz\w+", re.IGNORECASE)


def rejects_zarzad(title: str, snippet: str) -> bool:
    """True, gdy tytuł+snippet wskazuje nabór na stanowisko zarządu, a treść
    nie wspomina w ogóle o radzie nadzorczej (oszczędza wywołanie LLM)."""
    text = f"{title} {snippet}"
    return bool(ZARZAD_RE.search(text)) and not bool(NADZORCZA_RE.search(text))


def filter_is_announcement(title: str, snippet: str, url: str) -> tuple[bool, str]:
    """ETAP B: klasyfikuje wynik wyszukiwania. Zwraca (czy_to_nabor, uzasadnienie)."""
    user_content = f"Tytuł: {title}\nFragment: {snippet}\nURL: {url}"
    try:
        raw = _call_llm(config.LLM_MODEL, FILTER_SYSTEM_PROMPT, user_content)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"Nieprawidłowy JSON od LLM: {e}. Surowa odpowiedź: {raw}")
        czy_nabor = bool(parsed.get("czy_to_nabor", False))
        uzasadnienie = str(parsed.get("uzasadnienie", "") or "")
        return czy_nabor, uzasadnienie
    except Exception as e:
        # Bezpieczny fallback: wątpliwe wyniki są odrzucane, przyczyna w logu
        logger.warning("Błąd filtra LLM dla URL %s: %s", url, e)
        return False, f"błąd filtra: {e}"


class Offer(BaseModel):
    """Struktura wyekstrahowanej oferty (pydantic 2.x)."""
    podmiot: str = ""
    miejscowosc: str = ""
    termin_skladania_ofert: str = ""
    stanowisko: str = ""
    wymagania: str = ""
    podsumowanie: str = ""
    # Data publikacji ogłoszenia (ISO) - wypełniana w main.py z content_fetcher
    # (metatagi/<time>/etykieta), nie przez LLM
    data_publikacji: str = ""


EXTRACT_SYSTEM_PROMPT = '''Jesteś ekstraktorem danych z ogłoszeń o naborze kandydatów na członków rad nadzorczych. Na podstawie podanego tekstu ogłoszenia wyciągnij dane strukturalne.
Zwróć WYŁĄCZNIE obiekt JSON o polach:
{
  "podmiot": "pełna nazwa spółki/urzędu lub \\"\\"",
  "miejscowosc": "nazwa miejscowości lub \\"\\"",
  "termin_skladania_ofert": "YYYY-MM-DD lub \\"\\"",
  "stanowisko": "członek rady nadzorczej / przewodniczący rady itp.",
  "wymagania": "skrót wymagań, maks. 300 znaków, lub \\"\\"",
  "podsumowanie": "1-2 zdania po polsku"
}
Zasady:
- "podmiot": skopiuj DOKŁADNĄ pełną nazwę spółki/urzędu z tekstu (np. "PKP Polskie Linie Kolejowe S.A."), bez skracania i bez dopisywania formy prawnej, której nie ma w tekście.
- "termin_skladania_ofert": podaj datę w formacie YYYY-MM-DD. Terminy względne policz od DATY DZISIEJSZEJ podanej w treści zapytania (np. "w terminie 14 dni od publikacji" -> data publikacji + 14 dni). Jeśli nie da się jednoznacznie policzyć - zwróć "" (NIE wymyślaj daty).
Przykłady normalizacji dat:
"do 15 września 2026 r." -> "2026-09-15"
"15.09.2026"             -> "2026-09-15"
"15 września 2026, godz. 12:00" -> "2026-09-15"
Jeśli w tekście nie ma terminu - zwróć "" (NIE wymyślaj daty).'''


def extract_fields(full_text: str, url: str) -> dict | None:
    """ETAP C: wyciąga pola strukturalne z pełnego tekstu ogłoszenia.

    Zwraca dict albo None przy jakimkolwiek błędzie.
    """
    # Obetnij tekst PRZED wysłaniem do LLM
    text = full_text[:12000]
    user_content = (f"URL: {url}\n"
                    f"Dzisiejsza data: {date.today().isoformat()}\n\n"
                    f"Tekst ogłoszenia:\n{text}")
    try:
        raw = _call_llm(config.LLM_MODEL_EXTRACT, EXTRACT_SYSTEM_PROMPT, user_content)
        try:
            parsed_dict = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"Nieprawidłowy JSON od LLM: {e}. Surowa odpowiedź: {raw}")
        offer_obj = Offer.model_validate(parsed_dict)  # rzuca ValidationError przy złych typach
        result = offer_obj.model_dump()
        result["url"] = url
        result["znaleziono_dnia"] = date.today().isoformat()
        return result
    except Exception as e:
        logger.error("Błąd ekstrakcji LLM dla URL %s: %s", url, e)
        return None


if __name__ == "__main__":
    # Self-test (ETAP 1a, 1b) - wymaga działającej konfiguracji .env
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    # Walidacja configu przed pierwszym wywołaniem sieciowym
    try:
        config.validate()
    except ValueError as e:
        print(e, file=sys.stderr)
        sys.exit(1)

    print("=== Self-test llm_parser ===")
    r1 = filter_is_announcement(
        "Ogłoszenie o naborze kandydatów na członka rady nadzorczej SPV",
        "Zarząd SpV ogłasza otwarty nabór kandydatów na członka rady nadzorczej. "
        "Kandydatury prosimy składać do 15.09.2026 r.",
        "https://przyklad.pl/ogloszenie",
    )
    print(f"Test 1 (nabór): {r1}")

    r2 = filter_is_announcement(
        "Protokół z LVII posiedzenia Rady",
        "Protokół z posiedzenia Rady Nadzorczej z dnia 3 marca. Zatwierdzono sprawozdanie.",
        "https://przyklad.pl/protokol",
    )
    print(f"Test 2 (protokół): {r2}")

    sample_text = (
        "Ogłoszenie o naborze kandydatów na członka rady nadzorczej Spółki ABC sp. z o.o. "
        "z siedzibą w Warszawie. Oferty prosimy składać w Biurze Zarządu w terminie "
        "do 15.09.2026. Wymagane: wykształcenie wyższe, doświadczenie w finansach."
    )
    offer = extract_fields(sample_text, "https://przyklad.pl/nabor-abc")
    print(f"Test 3 (ekstrakcja): {offer}")
    if offer is not None and offer.get("termin_skladania_ofert") == "2026-09-15":
        print("Self-test OK")
    else:
        print("Self-test NIEZDANY (ekstrakcja)")
        sys.exit(1)
