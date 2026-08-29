# -*- coding: utf-8 -*-
"""Testy content_fetcher: ekstrakcja HTML (bez wywołań sieciowych)."""
import sys

sys.stdout.reconfigure(encoding="utf-8")

from content_fetcher import _extract_html_text


class FakeResponse:
    """Minimum interfejsu requests.Response używanego przez _extract_html_text."""

    def __init__(self, text, content_type, apparent_encoding="utf-8"):
        self.headers = {"Content-Type": content_type} if content_type else {}
        self._text = text
        self.apparent_encoding = apparent_encoding
        self.encoding = None

    @property
    def text(self):
        return self._text


def test_strips_script_and_style():
    html = "<html><head><style>b{color:red}</style></head>" \
           "<body><script>var x=1;</script><p>Nabór kandydatów</p></body></html>"
    out = _extract_html_text(FakeResponse(html, "text/html; charset=utf-8"))
    assert "Nabór kandydatów" in out
    assert "var x=1" not in out
    assert "color:red" not in out


def test_strips_tags_and_decodes_entities():
    html = "<p>Zarząd&nbsp;Spółki &quot;ABC&quot;</p><p>termin: 15.09.2026</p>"
    out = _extract_html_text(FakeResponse(html, "text/html; charset=utf-8"))
    assert 'Zarząd Spółki "ABC"' in out
    assert "15.09.2026" in out
    assert "<p>" not in out


def test_collapses_whitespace():
    html = "<p>a</p>   <p>b</p>\n\n<p>c</p>"
    out = _extract_html_text(FakeResponse(html, "text/html; charset=utf-8"))
    assert out == "a b c"


def test_charset_declared_encoding_untouched():
    r = FakeResponse("<p>x</p>", "text/html; charset=iso-8859-2")
    _extract_html_text(r)
    assert r.encoding is None  # charset obecny - nie nadpisujemy


def test_no_charset_uses_apparent_encoding():
    r = FakeResponse("<p>x</p>", "text/html", apparent_encoding="windows-1250")
    _extract_html_text(r)
    assert r.encoding == "windows-1250"
