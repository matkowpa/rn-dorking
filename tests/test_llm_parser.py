# -*- coding: utf-8 -*-
"""Testy czystych funkcji llm_parser (bez wywołań sieciowych)."""
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
