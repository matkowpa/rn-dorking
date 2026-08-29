# -*- coding: utf-8 -*-
"""Testy content_fetcher: ekstrakcja HTML (bez wywołań sieciowych)."""
import sys

sys.stdout.reconfigure(encoding="utf-8")

import content_fetcher
from content_fetcher import _attachment_links, _extract_html_text, fetch_content


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


class FakeHtmlResponse:
    """Minimalna odpowiedź HTTP dla fetch_content (status/headers/text/content)."""

    def __init__(self, html, content_type="text/html"):
        self.status_code = 200
        self.headers = {"Content-Type": content_type}
        self.text = html
        self.content = html.encode("utf-8")
        self.apparent_encoding = "utf-8"
        self.encoding = None


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


# --- Poziom 2: linki do załączników/podstron i ich pobieranie ---

def test_attachment_links_finds_pdf_and_keyword_links():
    page = ('<html><body>'
            '<a href="/files/ogloszenie.pdf">Ogłoszenie o naborze</a>'
            '<a href="mailto:x@y.pl">kontakt</a>'
            '<a href="javascript:void(0)">menu</a>'
            '<a href="/strona/nabor-kandydatow">Nabór kandydatów</a>'
            '<a href="https://inna.pl/rada-nadzorcza">Rada</a>'
            '</body></html>')
    links = _attachment_links(page, "https://bip.example.pl/aktualnosci")
    # MAX_ATTACHMENTS=2: PDF i podstrona z frazą "nabor"; link zewnętrzny
    # "rada-nadzorcza" odpada (myślnik nie pasuje do frazy ze spacją)
    assert "https://bip.example.pl/files/ogloszenie.pdf" in links
    assert "https://bip.example.pl/strona/nabor-kandydatow" in links
    assert "https://inna.pl/rada-nadzorcza" not in links
    assert all(not l.startswith("mailto") for l in links)


def test_attachment_links_ignores_irrelevant_links():
    page = ('<a href="/kontakt">Kontakt</a>'
            '<a href="/menu/glowne">Menu główne</a>')
    assert _attachment_links(page, "https://bip.example.pl/") == []


def test_attachment_links_caps_max():
    page = "".join(f'<a href="/nabor-{i}">nabór {i}</a>' for i in range(5))
    links = _attachment_links(page, "https://bip.example.pl/")
    assert len(links) == content_fetcher.MAX_ATTACHMENTS


def test_attachment_links_deduplicates():
    page = ('<a href="/nabor">nabór</a>'
            '<a href="/nabor">nabór (powtórka)</a>')
    links = _attachment_links(page, "https://bip.example.pl/")
    assert links == ["https://bip.example.pl/nabor"]


def test_fetch_content_level2_appends_subpage(monkeypatch):
    # Strona-skorupa (nawigacja) + podstrona z właściwą treścią ogłoszenia
    main_html = ('<html><body><div>menu BIP</div>'
                 '<a href="/ogloszenie-nabor">ogłoszenie</a></body></html>')
    sub_html = ('<html><body><p>Nabór kandydatów na członka rady nadzorczej '
                'w terminie do 15.09.2026 r.</p></body></html>')

    def fake_get(url, timeout=30, headers=None):
        return FakeHtmlResponse(main_html if url == "https://bip.pl/a" else sub_html)

    monkeypatch.setattr(content_fetcher.requests, "get", fake_get)
    out = fetch_content("https://bip.pl/a")
    assert "Nabór kandydatów na członka rady nadzorczej" in out
    assert "do 15.09.2026" in out


def test_fetch_content_skips_level2_when_text_rich(monkeypatch):
    # Strona z treścią (> MIN_MAIN_TEXT znaków) - poziom 2 nie powinien się włączyć
    rich_html = "<html><body><p>" + ("Nabór kandydatów. " * 60) + "</p></body></html>"
    calls = []

    def fake_get(url, timeout=30, headers=None):
        calls.append(url)
        return FakeHtmlResponse(rich_html)

    monkeypatch.setattr(content_fetcher.requests, "get", fake_get)
    out = fetch_content("https://bip.pl/bogata")
    assert "Nabór kandydatów." in out
    assert len(calls) == 1  # tylko strona główna, bez podstron
