# -*- coding: utf-8 -*-
"""Testy pre-filtra zarządu (odrzucanie naborów na stanowiska zarządu)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm_parser import rejects_zarzad


def test_zarzad_członek():
    assert rejects_zarzad(
        "Nabór na członka zarządu", "Spółka X ogłasza nabór na członka zarządu.")


def test_zarzad_prezes():
    assert rejects_zarzad(
        "Postępowanie kwalifikacyjne", "Nabór kandydatów na stanowisko prezesa zarządu spółki.")


def test_zarzad_wiceprezes():
    assert rejects_zarzad(
        "Ogłoszenie", "nabór kandydatów na wiceprezesa zarządu spółki")


def test_zarzad_liczba_mnoga():
    assert rejects_zarzad(
        "Nabór", "ogłoszenie naboru kandydatów na członków zarządu spółki")


def test_rada_nadzorcza_ok():
    assert not rejects_zarzad(
        "Nabór na członka rady nadzorczej",
        "Ogłoszenie o naborze kandydatów na członka rady nadzorczej. "
        "Zgłoszenia prosimy składać w Biurze Zarządu.")


def test_mieszany_przypadek_przekazany_do_llm():
    # TORPOL-like: rada nadzorcza przeprowadza nabór na prezesa zarządu -
    # pre-filtr nie odrzuca (decyzję podejmuje LLM z regułą w prompcie)
    assert not rejects_zarzad(
        "TORPOL szuka prezesa zarządu",
        "Rada nadzorcza TORPOLU ogłosiła postępowanie kwalifikacyjne "
        "na stanowisko prezesa zarządu.")


def test_zarzad_jako_miejsce_skladania():
    # "Biuro Zarządu" to miejsce składania ofert, nie stanowisko - nie odrzucamy
    assert not rejects_zarzad(
        "Nabór kandydatów",
        "Zapisy w Biurze Zarządu spółki, nabór do bazy kandydatów.")


import sys

sys.stdout.reconfigure(encoding="utf-8")

from llm_parser import _strip_json


def test_strip_json_removes_markdown():
    raw = "```json\n{\"czy_to_nabor\": true}\n```"
    assert _strip_json(raw) == '{"czy_to_nabor": true}'


def test_strip_json_removes_plain_backticks():
    raw = "```\n{\"a\": 1}\n```"
    assert _strip_json(raw) == '{"a": 1}'


def test_strip_json_extracts_from_surrounding_text():
    raw = 'Oto wynik: {"podmiot": "ABC"} koniec.'
    assert _strip_json(raw) == '{"podmiot": "ABC"}'


def test_strip_json_plain_json_untouched():
    raw = '{"a": 1, "b": {"c": 2}}'
    assert _strip_json(raw) == raw


def test_strip_json_strips_whitespace():
    assert _strip_json('  {"x": 1}  \n') == '{"x": 1}'


# --- Prompt ekstrakcji: terminy względne + dokładna nazwa spółki ---

from llm_parser import EXTRACT_SYSTEM_PROMPT


def test_extract_prompt_has_relative_deadline_rule():
    assert "terminy względne" in EXTRACT_SYSTEM_PROMPT.lower()
    assert "DATY DZISIEJSZEJ" in EXTRACT_SYSTEM_PROMPT
    assert "14 dni od publikacji" in EXTRACT_SYSTEM_PROMPT


def test_extract_prompt_has_exact_company_name_rule():
    assert "DOKŁADNĄ pełną nazwę" in EXTRACT_SYSTEM_PROMPT
    assert "bez skracania" in EXTRACT_SYSTEM_PROMPT


def test_extract_fields_user_content_contains_today():
    # Bez wywołań sieciowych: user_content budowany w extract_fields musi
    # zawierać dzisiejszą datę (do liczenia terminów względnych przez LLM)
    import inspect
    from llm_parser import extract_fields as ef
    src = inspect.getsource(ef)
    assert "Dzisiejsza data" in src
    assert "date.today().isoformat()" in src
