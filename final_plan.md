# PLAN WDROŻENIA — FINAL: System automatycznego pozyskiwania ogłoszeń do rad nadzorczych

**(Brave Search „dorking" + LLM parser, prezentacja na GitHub Pages)**

> **STATUS: ZREALIZOWANY (as-built).** Data sporządzenia: 2026-08-29.
> Niniejszy dokument zastępuje `plan_wdrozenia_google_dorking_llm_v3.txt` i opisuje
> system **tak, jak faktycznie działa w produkcji** — po wszystkich zmianach
> wprowadzonych w trakcie realizacji. Wszystkie kryteria akceptacji v3 zostały
> spełnione, część z odchyleń opisanymi poniżej.

---

## 0. Odchylenia od planu v3 (co się zmieniło i dlaczego)

| Obszar | Plan v3 | Realizacja (FINAL) | Powód |
|---|---|---|---|
| Backend wyszukiwania | Google Custom Search JSON API (`google_search.py`) | **Brave Search API** (primary) + **DuckDuckGo** (fallback) | Google CSE wymagał skonfigurowania Programmable Search Engine; Brave daje 2000 zapytań/mies. bez CSE |
| Zestaw dorków | 5 dorków z operatorami `inurl:`/`site:`/`filetype:` | **12 dorków frazowych** dla Brave; **8 dorków z operatorami** dla DDG | Brave nie obsługuje `inurl:`/`filetype:`/`site:` (zwracają 0 wyników) |
| Dodatkowe dorki | brak | **`EXTRA_DORKS`** z `.env` lub repository variable | rozszerzanie pokrycia per BIP/spółka bez zmian w kodzie |
| Harmonogram | codziennie 06:00 UTC | **2× dziennie**: 05:00 i 17:00 UTC (07:00/19:00 PL) | ogłoszenia publikowane też po południu |
| Obsługa błędów runu | brak | **Alert na Telegram** przy `failure()` w workflow | cicha porażka = dzień bez danych |
| Powiadomienia | brak (poza ETAPem 7) | **Telegram + e-mail (Brevo SMTP)** z digestem i przypomnieniami | wartość biznesowa bez wchodzenia na stronę |
| Archiwum wyników | tylko `oferty.json` + `stan.json` | dodatkowo **`data/dnia/<data>.json`** (plik dnia ze statystykami) | frontend per-dzień, audyt runów |
| Testy | self-testy `if __name__ == "__main__"` | **32 testy pytest** + krok `Run tests` w CI przed każdym potokiem | powtarzalna weryfikacja bez wywołań sieciowych |
| PostgreSQL (ETAP 7) | planowane | **niewdrożone** (JSON wystarcza) | wracamy przy realnych problemach z `oferty.json` |
| Google CSE jako backend | obowiązkowy | **niewdrożone** (architektura gotowa na dodanie) | Brave/DDG pokrywają potrzeby |

**Niezrealizowany element v3 o wadze krytycznej: brak.** Cały potok, deduplikacja,
retry, walidacja LLM i UTF-8 działają zgodnie ze specyfikacją v3.

---

## 1. Cel biznesowy

Codzienne (2× dziennie) wykrywanie świeżych ogłoszeń o naborze kandydatów na
członków rad nadzorczych, publikowanych w polskich systemach BIP i innych
źródłach publicznych, strukturyzacja ich przez LLM i prezentacja w formacie
JSON dla frontendu na GitHub Pages: **https://matkowpa.github.io/rn-dorking/**

---

## 2. Architektura as-built

```
GitHub Actions (cron 05:00 & 17:00 UTC / workflow_dispatch / push na kod)
  │
  ├─ python -m pytest tests/ -q          (gate — padnięty test przerywa run)
  ├─ python main.py                      (potok A → B → C)
  │    ETAP A: wyszukiwanie  ── Brave Search API (BRAVE_API_KEY)
  │    │                        └─ fallback: DuckDuckGo (ddgs), gdy brak klucza
  │    ETAP B: deduplikacja (storage, URL-hash) → filtr LLM (czy_to_nabor)
  │    ETAP C: fetch_content (HTML/PDF) → extract_fields (LLM, pydantic v2)
  │    WYJŚCIE: oferty.json, stan.json, data/dnia/<data>.json
  ├─ python build_docs.py                (docs/data/index.json, all.json, <data>.json)
  ├─ python notify.py                    (Telegram + Brevo SMTP, anty-spam)
  ├─ commit wyników (github-actions[bot])
  └─ Alert on failure (Telegram)         (jeśli jakikolwiek krok padł)
        │
        └─ GitHub Pages serwuje docs/ (frontend czyta docs/data/*.json)
```

Kolejność w potoku ma znaczenie kosztowe: **NAJPIERW deduplikacja** (darmowa,
lokalna), **POTEM tani filtr LLM** na snippecie, **DOPIERO POTEM pobieranie
strony i droższa ekstrakcja**. Nigdy odwrotnie.

### Struktura katalogów

```
rn-dorking/
  main.py              # orkiestrator potoku (ETAP 5) — jedyne CLI
  llm_parser.py        # klient LLM: filter_is_announcement + extract_fields
  brave_search.py      # ETAP A primary: Brave Search API (+ BRAVE_DORKS)
  ddg_search.py        # ETAP A fallback: DuckDuckGo (+ DORKS z operatorami)
  content_fetcher.py   # ETAP C-1: pobieranie treści HTML/PDF
  storage.py           # ETAP 4: deduplikacja, stan, oferty.json, plik dnia
  config.py            # ETAP 0: wczytanie i walidacja .env (+ EXTRA_DORKS)
  notify.py            # powiadomienia Telegram + e-mail (Brevo SMTP)
  build_docs.py        # buduje docs/data/ dla frontendu
  conftest.py          # pytest: root dir na sys.path
  tests/               # 32 testy jednostkowe (bez sieci)
  .github/workflows/daily.yml
  docs/                # frontend GitHub Pages (index.html, app.js, style.css)
  requirements.txt, .env.example, .gitignore
```

---

## 3. Zasady ogólne (jak w v3, obowiązują we wszystkich modułach)

1. Python 3.11+. Sekrety i konfiguracja wyłącznie z `.env` — zero kluczy i nazw
   modeli zaszytych w kodzie.
2. Każde wywołanie HTTP: `timeout=30`, obsługa 4xx/5xx z wpisem w logu
   (status + URL, bez kluczy).
3. Logowanie przez `logging`: INFO na konsolę, DEBUG do `run.log`
   (FileHandler z `encoding="utf-8"`).
4. Komentarze po polsku, identyfikatory po angielsku.
5. Daty na wyjściu WYŁĄCZNIE `YYYY-MM-DD` albo `""`.
6. LLM: `temperature=0.1`, `response_format={"type": "json_object"}`;
   przy błędzie innym niż 429 — jedna próba ponowna bez `response_format`
   z dopiskiem „Zwróć WYŁĄCZNIE surowy JSON bez bloków markdown" (szczegóły: ETAP 1).
7. Przed `json.loads`: usuń znaczniki ```` ```json ````/```` ``` ````, wytnij
   podciąg od pierwszego `{` do ostatniego `}`.
8. UTF-8 wszędzie: `open(..., encoding="utf-8")`, `ensure_ascii=False` przy
   `json.dump`, `sys.stdout.reconfigure(encoding="utf-8")` na starcie `main.py`.

---

## 4. ETAP 0 — środowisko i konfiguracja (`config.py`)

| Zmienna | Wymagana | Znaczenie |
|---|---|---|
| `LLM_API_KEY` | TAK | klucz API LLM (OpenRouter) |
| `LLM_BASE_URL` | TAK | np. `https://openrouter.ai/api/v1` |
| `LLM_MODEL` | TAK | model filtra (tani, np. `z-ai/glm-4.5-flash`) |
| `LLM_MODEL_EXTRACT` | TAK | model ekstrakcji (może być = `LLM_MODEL`) |
| `BRAVE_API_KEY` | NIE | obecność = backend Brave; brak = fallback DDG (+ WARNING) |
| `SEARCH_DAYS_BACK` | NIE | int, domyślnie 5; błędna wartość → WARNING + default |
| `RESULTS_PER_DORK` | NIE | int, domyślnie 20, dozwolone **tylko** 10/20/30/40 |
| `EXTRA_DORKS` | NIE | dodatkowe dorki oddzielone znakiem `\|` |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `NOTIFY_EMAIL_TO` | NIE | powiadomienia (brak = kanał pomijany) |

- `validate()` rzuca `ValueError` z listą brakujących zmiennych obowiązkowych.
- `main.py --check` kończy się kodem 0 (kompletny) / 1 (lista braków na stderr).
- Klient LLM tworzony **leniwie** — import modułu nie wymaga klucza.
- `requirements.txt`: `requests>=2.31`, `python-dotenv>=1.0`, `openai>=1.0`,
  `pydantic>=2.0`, `pdfplumber>=0.10`, `ddgs>=9.0`, `pytest>=8.0`.

---

## 5. ETAP 1 — klient LLM (`llm_parser.py`)

Dwie funkcje o różnych promptach i (potencjalnie) różnych modelach:

- `rejects_zarzad(title, snippet) -> bool` — **deterministyczny pre-filtr**
  (przed LLM): odrzuca wyniki z frazami stanowisk zarządu (członek/prezes/
  wiceprezes zarządu), gdy tekst nie wspomina w ogóle o radzie nadzorczej —
  oszczędza wywołanie LLM. Przypadki mieszane rozstrzyga filtr LLM.
- `filter_is_announcement(title, snippet, url) -> tuple[bool, str]` — model
  `LLM_MODEL`; zwraca `(czy_to_nabor, uzasadnienie)`; prompt zawiera regułę:
  **nabór na stanowiska zarządu (członek/prezes/wiceprezes) NIE jest istotny
  — nawet gdy postępowanie przeprowadza rada nadzorcza**; przy JAKIMKOLWIEK
  błędzie: WARNING + `(False, "błąd filtra: ...")` — bezpieczny fallback
  (wątpliwe wyniki odrzucane, przyczyna widoczna w logu i przy `--dry-run`).
- `extract_fields(full_text, url) -> dict | None` — model `LLM_MODEL_EXTRACT`;
  tekst obcinany do **12000 znaków PRZED** wysłaniem; pola: `podmiot`,
  `miejscowosc`, `termin_skladania_ofert`, `stanowisko`, `wymagania`,
  `podsumowanie`; walidacja **pydantic v2** (`Offer.model_validate` / `model_dump`);
  do wyniku dopisywane `url` i `znaleziono_dnia` (dzisiaj); przy błędzie:
  ERROR z URL + `None`.

Wspólny `_call_llm(model, system_prompt, user_content)` — algorytm retry zgodny z v3:

1. Wywołanie z `response_format`.
2. **429 / RateLimitError** → do 3 dodatkowych prób (po 3s, 6s, 12s);
   po wyczerpaniu — ERROR i raise.
3. **Inny błąd** → jedna próba ponowna BEZ `response_format` z dopiskiem
   „Zwróć WYŁĄCZNIE surowy JSON bez bloków markdown"; 429 na tej próbie →
   retry jak w pkt 2.
4. `_strip_json`: usunięcie znaczników markdown i wycięcie od pierwszego
   `{` do ostatniego `}`.

Prompt filtra (dosłownie, po polsku) — jak w v3, łącznie z listą wykluczeń
(archiwalne ogłoszenia, protokoły z posiedzeń, uchwały o powołaniu, aktualności,
strony główne BIP, wzory dokumentów). Prompt ekstrakcji zawiera 3 przykłady
normalizacji dat („do 15 września 2026 r." → `2026-09-15` itd.) i zakaz
wymyślania daty. Self-testy modułów (`python llm_parser.py`) pozostały
jako szybka diagnostyka.

---

## 6. ETAP 2 — wyszukiwanie (`brave_search.py` primary, `ddg_search.py` fallback)

### 6.1 Brave Search API — `search_brave(dork, days_back, max_results)`

- Endpoint: `https://api.search.brave.com/res/v1/web/search`; parametry:
  `q`, `count=min(max_results, 20)` (Brave max 20/zapytanie), `country=pl`,
  `search_lang=pl`, `safesearch=off`, `freshness` z mapowania `days_back` →
  `pd`(≤1)/`pw`(≤7)/`pm`(≤31)/`py`(≤365).
- **Pusty wynik z `freshness`** (Brave zwraca 200 bez `web.results`) → jedna
  próba ponowna **bez filtra daty** (stare wyniki odfiltruje LLM).
- Retry na 429: 5s / 10s / 20s; wyczerpane lub inny status → WARNING + `[]`
  dla tego dorka (potok jedzie dalej).
- Wynik: lista `{"title", "snippet", "link", "dork"}`.

`BRAVE_DORKS` (12, frazowe — Brave nie wspiera `inurl:`/`filetype:`/`site:`):

```
"nabór na członków rady nadzorczej" BIP
"nabór kandydatów" "rady nadzorczej" BIP
"postępowanie kwalifikacyjne" "rady nadzorczej"
"konkurs na członka rady nadzorczej"
"zaproszenie do składania ofert" "rady nadzorczej"
"zgłoszenia kandydatów" "członka rady nadzorczej"
"ogłoszenie o naborze kandydatów" "rada nadzorcza"
"kandydatów na członków rad nadzorczych"
"nabór do bazy danych kandydatów" "rada nadzorcza"
"ogłasza nabór" "rady nadzorczej"
"kandydatów do rady nadzorczej"
"konkurs na członków rady nadzorczej"
```

### 6.2 DuckDuckGo — `search_ddg(dork, days_back, max_results)` (fallback)

- Biblioteka `ddgs`, `region="pl-pl"`, `timelimit` z mapowania d/w/m
  (≤1/≤7/≤30 dni; dalej bez filtra).
- Retry na `DDGSException`: 5s / 10s / 20s → po wyczerpaniu WARNING + `[]`.
- `DORKS` (8, z operatorami — DDG je obsługuje w ograniczonym zakresie):

```
inurl:bip "nabór na członków rady nadzorczej"
inurl:bip "postępowanie kwalifikacyjne" "rady nadzorczej" filetype:pdf
site:gov.pl "konkurs na członka rady nadzorczej"
site:gov.pl "nabór na członków rady nadzorczej"
"zaproszenie do składania ofert" "rady nadzorczej" filetype:pdf
"zgłoszenia kandydatów" "członka rady nadzorczej" -archiwum -protokół
"konkurs na członków rady nadzorczej" site:gov.pl
"nabór do bazy danych kandydatów" "rada nadzorcza"
```

### 6.3 EXTRA_DORKS

`main.py` dopisuje `config.EXTRA_DORKS` do dorków backendu (log INFO o liczbie).
W GitHub Actions przekazywane jako repository **variable** `EXTRA_DORKS`
(`${{ vars.EXTRA_DORKS }}`). Dorki z `site:` dają wyniki tylko przy backendzie DDG.
Między dorkami: `time.sleep(1)` (ostrożny odstęp, mniejszy rate-limit).

Quota Brave: 12 dorków × 2 runy ≈ 24 zapytania/dzień (limit 2000/mies. — bezpiecznie).

---

## 7. ETAP 3 — pobieranie treści (`content_fetcher.py`)

`fetch_content(url) -> str`:

1. `requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) rn-dorking/3.0"})` (helper `_fetch`).
2. Status ≠ 200 → WARNING (status + URL) + `""`.
3. PDF (URL kończy się `.pdf` lub Content-Type `application/pdf`):
   `pdfplumber.open(BytesIO)`, maks. **20 pierwszych stron**; błąd parsowania
   (serwer zwraca HTML pod adresem `.pdf`) → próba parsowania jako HTML.
4. HTML: jeśli Content-Type **nie zawiera** `charset` →
   `response.encoding = response.apparent_encoding` PRZED odczytem `.text`
   (strony BIP często są w windows-1250/iso-8859-2). Potem: usunięcie
   `script`/`style`, usunięcie tagów, `html.unescape`, normalizacja białych znaków.
5. **Poziom 2** (strony-skorupy): gdy strona HTML ma < **400 znaków** treści
   (typowa nawigacja BIP — treść renderowana JS-em albo w załączniku),
   `_attachment_links` wybiera z HTML do **2** linków (bezwzględnych, bez duplikatów,
   bez `javascript:`/`mailto:`/kotwic), których href kończy się `.pdf` LUB
   href/tekst zawiera frazę z `LINK_KEYWORDS` (nabor, ogłoszenie, rada nadzor,
   kwalifikacyjn, konkurs, kandydat); każdy załącznik/podstronę pobiera osobno
   (PDF → pdfplumber, HTML → ekstrakcja), tekst dołączany po `\n\n`
   (limit 6000 znaków na załącznik).
6. Zwrot obcięty do **12000 znaków**. Wyjątki sieciowe → WARNING + `""`
   (potok użyje snippetu jako tekstu zapasowego).

---

## 8. ETAP 4 — storage (`storage.py`)

- `_normalize_url(url)`: lowercase hosta, usunięcie parametrów `utm_*`,
  fragmentu, końcowego `/` ze ścieżki; `_url_hash` = SHA1 z normalizowanego URL-a.
- `Storage(offers_path="oferty.json", state_path="stan.json")`:
  - wczytuje `seen_urls` ze `stan.json` ORAZ migruje hashe URL-i z
    `oferty.json` (nic nie ginie przy braku stanu),
  - `is_new(url)` / `add_offer(offer)` / `merge_offers(new_offers) -> int`,
  - **pamięć odrzuconych**: `add_rejected(url)` (hash → data, w `stan.json`
    jako `rejected`) / `is_rejected(url)`; wpisy starsze niż
    `REJECT_TTL_DAYS = 30` są przycinane przy wczytaniu i zapisie (po miesiącu
    URL może wrócić do rozpatrzenia — treść BIP potrafi się zmienić),
  - **re-ekstrakcja**: `get_reextract_candidates(max_n)` (oferty z pustym
    `termin_skladania_ofert`, najstarsze `znaleziono_dnia` najpierw, pomija
    wyczerpane), `mark_extract_attempt(url)` (licznik w `stan.json` jako
    `reextract`, limit `MAX_EXTRACT_ATTEMPTS = 2`),
    `update_offer(url, new_fields)` (podmienia pola, zachowuje oryginalne
    `url` i `znaleziono_dnia`),
  - `save()`: **atomowy** zapis (`.tmp` + `os.replace`) obu plików, UTF-8,
    `ensure_ascii=False`; oferty sortowane malejąco po
    `termin_skladania_ofert` (`""` na końcu),
  - `save_daily(stats, run_date)`: zapis do `data/dnia/<data>.json`
    (`{"date", "stats", "offers"}`); drugi run tego samego dnia **scala**
    oferty po URL-u — niczego nie gubimy.
- Deduplikacja działa między uruchomieniami i maszynami (`stan.json` podróżuje z repo).

---

## 9. ETAP 5 — orkiestrator (`main.py`)

Argumenty (argparse):

| Flaga | Działanie |
|---|---|
| `--check` | tylko walidacja `.env` i wyjście (kod 0/1) |
| `--dry-run` | ETAP A + B bez pobierania treści i ekstrakcji; tabela `tytuł \| nabór \| uzasadnienie`; NIE zapisuje `oferty.json`/`stan.json` |
| `--limit N` | maks. liczba NOWYCH wyników poddawanych ETAPOWI B (domyślnie 30); już widziane odrzucane PRZED limitem |
| `--days N` | nadpisuje `SEARCH_DAYS_BACK` na to uruchomienie |

Przebieg:

1. Logging (INFO konsola / DEBUG `run.log`, oba UTF-8).
2. `config.validate()`; `--check` → exit; inicjalizacja `Storage`.
3. **Faza 0 — re-ekstrakcja** (pomijana przy `--dry-run`): do 5 ofert bez
   terminu (`get_reextract_candidates(5)`) przechodzi ponownie `fetch_content`
   (z poziomem 2) i `extract_fields`; przy sukcesie `update_offer` uzupełnia
   termin; każda próba zapisywana przez `mark_extract_attempt` (max 2 na ofertę);
   statystyka `offers_updated`.
4. **ETAP A**: wybór dorków wg backendu (`BRAVE_DORKS` / `DORKS`) + `EXTRA_DORKS`;
   pętla po dorkach z `sleep(1)`; zebranie wyników (dedup naprawi duble między dorkami).
5. **ETAP B**: iteracja w kolejności zbierania; najpierw `is_rejected(link)`
   (odrzucone w oknie 30 dni — pomijane BEZ liczenia do limitu), potem
   `is_new(link)` (widziane — pomijane) i licznik nowych vs `--limit`;
   `filter_is_announcement(title, snippet, link)`;
   wynik NIE = `storage.add_rejected(link)` (chyba że uzasadnienie zaczyna się
   od „błąd filtra" — chwilowy błąd LLM nie jest pamiętany);
   `--dry-run` → tylko zapamiętanie wiersza tabeli.
6. **ETAP C** (gdy `czy_nabor`): `fetch_content(link)` (pusty → snippet),
   `extract_fields`, następnie **filtr świeżości**: znany termin w przeszłości =
   oferta archiwalna → pomijana (log INFO); nowa → `storage.add_offer`.
   Między wywołaniami LLM: `time.sleep(0.5)`.
7. `--dry-run` → tabela i koniec bez zapisu; inaczej `storage.save()` +
   `storage.save_daily(stats)`.
8. Statystyki końcowe (log INFO): zapytania, wyniki surowe, po deduplikacji,
   po filtrowaniu, nowe oferty, błędy ekstrakcji, uzupełnione terminy
   (re-ekstrakcja).
9. Wyjście kod 0; nieprzechwycony wyjątek → `logger.exception` + `sys.exit(1)`.

---

## 10. ETAP 6 — testy (zamiennik self-testów z v3)

**54 testy pytest**, zero wywołań sieciowych, uruchamiane w CI **przed** potokiem:

```
python -m pytest tests/ -q
```

| Plik | Pokrycie |
|---|---|
| `tests/test_storage.py` (18) | normalizacja URL (utm_/host/trailing slash/fragment), deduplikacja między uruchomieniami, UTF-8 + sortowanie przy zapisie, scalanie pliku dnia, stabilność hasha, pamięć odrzuconych (skip, TTL 30 dni, trwałość, backcompat starego stan.json), re-ekstrakcja (kolejność najstarszych, limit prób, trwałość licznika), `update_offer` (podmiana pól + zachowanie historii, nieznany URL) |
| `tests/test_config.py` (10) | parsowanie `EXTRA_DORKS` (pełny/pusty/nieustawiony), `SEARCH_DAYS_BACK`/`RESULTS_PER_DORK` (błędne → default + WARNING), `validate()` |
| `tests/test_llm_parser.py` (12) | `_strip_json`: markdown, otaczający tekst, czysty JSON, białe znaki; pre-filtr zarządu `rejects_zarzad`: członek/prezes/wiceprezes zarządu → odrzucenie, „Biuro Zarządu" i przypadki mieszane (rada nadzorcza w tekście) → przekazane do LLM |
| `tests/test_content_fetcher.py` (11) | ekstrakcja HTML: script/style, encje, białe znaki, logika charset; poziom 2: `_attachment_links` (PDF/frazy, odrzucanie nieistotnych, limit MAX_ATTACHMENTS, deduplikacja), `fetch_content` z podstroną (poziom 2) i pomijaniem poziomu 2 przy bogatej treści |
| `tests/test_notify.py` (4) | budowa digestu (tekst+HTML), sekcja przypomnień, „termin: nieznany" |

`.github/workflows/daily.yml`: krok `Run tests` między „Install dependencies"
a „Run pipeline" — padnięty test przerywa run **przed** wywołaniami płatnymi
i uruchamia alert Telegram. Self-testy modułów (`python <modul>.py`) zostają
jako szybka diagnostyka ręczna.

---

## 11. ETAP 7 — rozbudowa (status wdrożenia)

### Wdrożone ✅

- **Harmonogram** (`.github/workflows/daily.yml`): cron `0 5 * * *` i
  `0 17 * * *` (07:00 / 19:00 PL), `workflow_dispatch`, push na pliki kodu
  (paths-ignore: `docs/**`, `oferty.json`, `stan.json`, `data/**`, `**.md`),
  `permissions: contents: write`.
- **Sekrety** (repository secrets): `BRAVE_API_KEY`, `LLM_API_KEY`,
  `LLM_BASE_URL`, `LLM_MODEL` (+ `LLM_MODEL_EXTRACT` = `LLM_MODEL`),
  opcjonalnie `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `SMTP_HOST`,
  `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `NOTIFY_EMAIL_TO`;
  repository **variable**: `EXTRA_DORKS`.
- **Alert na błąd**: krok `Alert on failure (Telegram)` z `if: failure()` —
  wysyła link do logu runu; brak sekretów Telegram = pominięty.
- **Prezentacja** (GitHub Pages, `docs/`): SPA zero-build — **statyczny CSS**
  z design tokenami wg koncepcji „Clean Structured Cards" (`front-end.txt`):
  paleta slate-950/900 + violet (#8b5cf6), fonty Inter + Fira Code.
  Tailwind CDN usunięty (runtime-JS z CDN powodował, że strona nie
  renderowała się na mobile). Funkcjonalność: hero + banner statystyk
  (aktywne nabory / oferty / dni), sekcja „Najbliżej terminu", kafle
  „Wyniki według dni" (`data/index.json`), pełna lista ofert z toolbarem
  (wyszukiwanie na żywo, select sortowania: najnowsze / termin ↑ / termin ↓,
  chip „tylko aktywne"), karty z pełną treścią (badge terminu z odliczaniem
  dni: zielony >14 / żółty ≤14 / czerwony ≤7 / szary zakończony-nieznany),
  `#/YYYY-MM-DD` = widok dnia ze statystykami runu i nawigacją ←/→.
  Dane z `data/all.json` (jedno żądanie zamiast per-dzień); `esc()` przy
  każdej interpolacji. URL: **https://matkowpa.github.io/rn-dorking/**
  (Pages: main /docs).
- **Powiadomienia** (`notify.py`): digest nowych ofert dnia + przypomnienia
  o terminach ≤7 dni (anty-spam: `data/notified.json`, idempotentny zapis stanu
  tylko po udanej wysyłce); kanały: Telegram + e-mail (Brevo SMTP, STARTTLS);
  błędy wysyłki nie zawalają workflow.
- **build_docs.py**: kopiuje pliki dzienne do `docs/data/<data>.json`, buduje
  `docs/data/index.json` (lista dni malejąco) i `docs/data/all.json` (pełna historia).

### Niewdrożone ❌ (roadmapa)

- Migracja `oferty.json` → PostgreSQL (np. Supabase); `storage.py` pozostaje
  warstwą abstrakcji.
- Backend Google CSE (`google_search.py`) — format wyników ujednolicony,
  dodanie = nowy moduł + `GOOGLE_API_KEY`/`GOOGLE_CX` w config.

---

## 12. Uruchomienie lokalne

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # i uzupełnij BRAVE_API_KEY, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
python -m pytest tests/ -q  # testy (bez sieci)
python main.py --check      # walidacja konfiguracji
python main.py              # pełny run
python build_docs.py        # odbudowa danych strony
python notify.py            # wysyłka digestu (opcjonalnie)
```

---

## 13. Checklista końcowa (odhaczona)

- [x] wszystkie moduły zgodne ze strukturą (sekcja 2)
- [x] `--check`, `--dry-run`, `--limit`, `--days` działają (argparse)
- [x] 54 testy pytest przechodzą lokalnie i w CI (krok `Run tests`)
- [x] deduplikacja działa między uruchomieniami (potwierdzone produkcją)
- [x] polskie znaki diakrytyczne poprawne w `oferty.json`, `stan.json`, `run.log`
- [x] żadnych sekretów w kodzie i w repo (`.gitignore`: `.env`, `venv/`, `run.log`, `__pycache__/`)
- [x] `run.log` zawiera ślad pełnego uruchomienia
- [x] workflow 2× dziennie zielony (dowód: commity `daily update [skip ci]` bota)
- [x] strona GitHub Pages live z danymi
- [x] alert Telegram przy niepowodzeniu runu

---

## 14. Znane pułapki i ograniczenia

1. **Brave nie wspiera** `inurl:`/`filetype:`/`site:` — dorki z tymi operatorami
   zwracają 0 wyników; `site:` działa tylko przy backendzie DDG.
2. DuckDuckGo z IP GitHub Actions bywa rate-limitowany — dlatego Brave jest primary.
3. **60 dni bez aktywności w repo = GitHub wyłącza scheduled workflows**;
   jakikolwiek commit (nawet ręczny) je re-enables.
4. Free LLM (OpenRouter) potrafi zwracać 429 — potok robi retry 3s/6s/12s;
   okazjonalne opóźnienie, nie porażka.
5. Nie commitować `.env` (lokalny `BRAVE_API_KEY` jest nieważny — produkcja
   używa sekretu z GitHuba; odnowić klucz przy testach lokalnych).
6. **Off-by-one w `notify.py`**: liczba dni w przypomnieniach liczy się z porą
   dnia (`(termin - datetime.today()).days`) — wieczorem „za 5 dni" pokazuje
   „za 4 dni". Zachowanie bezpieczne (przypomnienie wcześniej); test pokryty regexem.
7. Jeśli strona pokazuje stare dane — cache Pages: twardy refresh (Ctrl+F5).
8. Lokalna kopia na OneDrive: przed pracą zawsze `git pull` (bot commituje
   `oferty.json`/`stan.json` 2× dziennie — ryzyko konfliktu).
9. Odrzucone URL-e są pamiętane 30 dni (`rejected` w `stan.json`) — zmiana
   promptu filtra nie odblokuje ich wcześniej; można wyczyścić klucz ręcznie.

---

## 15. Roadmapa (kandydaci na kolejne iteracje)

Zrealizowane w iteracji 2026-08-29: poziom 2 pobierania treści (załączniki/
podstrony), re-ekstrakcja ofert bez terminu (max 2 próby), pamięć odrzuconych
URL-i (TTL 30 dni), rozszerzenie dorków (12 Brave / 8 DDG).

1. **Dorki per konkretny BIP/spółkę** przez repository variable `EXTRA_DORKS`
   (bez zmian w kodzie) — największy zysk pokrycia przy najniższym koszcie.
2. ICS/RSS feed z terminami naborów (frontend już ma posortowane aktywne oferty).
3. Log odrzuconych wyników z uzasadnieniem do `data/odrzucone-<data>.json`
   (dziś przyczyny widoczne tylko w logu) — przegląd pod kątem fałszywych
   negatywów filtra i doprecyzowanie promptu.
4. Poprawka promptu ekstrakcji: terminy względne („w terminie 14 dni od
   publikacji" → policzona data) + polecenie kopiowania dokładnej nazwy spółki.
5. Metryki jakości w statystykach (`offers_with_termin`, `content_empty`) i digescie notify.
6. Backend Google CSE jako trzeci ogniwo łańcucha (Brave → DDG → Google).
7. Migracja do PostgreSQL/Supabase — dopiero gdy `oferty.json`/`stan.json`
   zaczną powodować konflikty merge lub urosnąć.
