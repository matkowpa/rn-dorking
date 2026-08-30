# rn-dorking — nabory na rady nadzorcze

Automatyczne codzienne wykrywanie ogłoszeń o naborze kandydatów na członków
rad nadzorczych (spółki, fundusze, instytucje publiczne) — wyszukiwanie
w Brave Search, klasyfikacja i ekstrakcja danych przez LLM, publikacja na
GitHub Pages.

## Jak działa
1. Codziennie o **07:00 i 19:00** (czas polski, odporny na zmianę DST) GitHub
   Actions uruchamia potok:
   - **Faza 0** — bezpośredni skan źródeł (port z rn-scrapper): whitelist
     ministerstw, spółek SP, portów i dużych miast (`direct_sources.py`)
     oraz **rotacyjne okno BIP-ów samorządowych** (rejestr `data/bip_jst.json`,
     rozmiar okna `JST_WINDOW`, domyślnie 100 podmiotów/run). Dla whitelisty
     skan jest **pogłębiony** (dodatkowo do 2 podstron-sekcji: aktualności,
     konkursy, relacje). Kandydaci są wykrywani po tekście kotwicy linku;
     dla domen `*.gov.pl` filtr LLM jest pomijany (sam link „ogłoszenie
     o naborze" na BIP jest wiarygodny).
   - **ETAP A** — Brave Search (dorki frazowe + opcjonalne `EXTRA_DORKS`);
     przy błędzie/pustym wyniku automatyczny fallback na DuckDuckGo.
   - **Pre-filtr heurystyczny** (`heuristics.py`, port z rn-scrapper) — bez
     wywołania LLM odrzuca agregatory (jooble, indeed…), artykuły/poradniki,
     treści edukacyjne, zakończone nabory i archiwalne roczniki.
   - **ETAP B** — deduplikacja + filtr LLM → **ETAP C** — pobranie treści
     (HTML/PDF, poziom 2: załączniki) + ekstrakcja pól przez LLM
     (podmiot, termin, miejscowość… oraz **data publikacji** z metatagów/
     `<time>`/etykiet). W razie niepowodzenia runu alert na Telegram.
2. Wyniki zapisywane są per dzień do `data/dnia/<data>.json` i łączone
   w pełną historię `oferty.json`.
3. `build_docs.py` buduje dane dla strony (`docs/data/`), commit i GitHub
   Pages odświeża stronę.

## Narzędzia rejestru BIP (tools/)
- `tools/fetch_bip_registry.py` — pobiera pełny rejestr podmiotów BIP
  z API gov.pl do `data/bip_jst.json` (GitHub Actions: Run workflow →
  *regenerate_registry*).
- `tools/resolve_bip_urls.py` — mapuje slugi podmiotów na realne adresy BIP
  (`data/bip_jst_urls.json`; GitHub Actions: Run workflow → *resolve_urls*).

## 🌐 Strona z ogłoszeniami (live)

**👉 https://matkowpa.github.io/rn-dorking/**

Strona główna z listą dni, każdy dzień pod osobnym linkiem `#/YYYY-MM-DD`.


## Uruchomienie lokalne
```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # i uzupełnij BRAVE_API_KEY, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
python main.py           # pełny run
python build_docs.py     # odbudowa danych dla strony
```

### Dodatkowe dorki (EXTRA_DORKS)
W `.env` (lokalnie) lub jako **repository variable** `EXTRA_DORKS` (GitHub →
Settings → Secrets and variables → Actions → Variables) można dopisać własne
dorki oddzielone znakiem `|`, np. per konkretny BIP/spółkę:
```
EXTRA_DORKS=site:bip.grudziadz.pl "rady nadzorczej"|"ogłoszenie o naborze" "Grudziądz"
```
Uwaga: Brave (backend produkcyjny) nie wspiera operatorów `inurl:`/`filetype:`/
`site:` — dorki z tymi operatorami zwrócą 0 wyników; używaj fraz z nazwą domeny
w treści zapytania. `site:` działa przy backendzie DuckDuckGo.

## Testy
Testy jednostkowe (bez wywołań sieciowych) uruchamiane są w CI przed każdym
runem potoku, lokalnie:
```
python -m pytest tests/ -q
```
Obejmują: deduplikację i trwałość (`storage.py`), parsowanie konfiguracji
(`config.py`), czyszczenie odpowiedzi LLM (`llm_parser.py`), ekstrakcję HTML
i daty publikacji (`content_fetcher.py`), heurystyki pre-LLM (`heuristics.py`),
linki-kandydatów i okno JST (`direct_sources.py`) oraz budowę digestu
powiadomień (`notify.py`).

## Sekrety (GitHub Actions)
`BRAVE_API_KEY`, `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` (i `LLM_MODEL_EXTRACT` = `LLM_MODEL`).

### Powiadomienia (opcjonalne)
Po każdym runie, gdy pojawią się **nowe ogłoszenia** (lub termin naboru ≤7 dni),
wysyłany jest digest:
- **Telegram**: sekrety `TELEGRAM_BOT_TOKEN` (od @BotFather) i `TELEGRAM_CHAT_ID`
  (od @userinfobot)
- **E-mail (Brevo SMTP)**: sekrety `SMTP_HOST` (smtp-relay.brevo.com), `SMTP_PORT` (587),
  `SMTP_USER`, `SMTP_PASSWORD`, `NOTIFY_EMAIL_TO`
Bez skonfigurowanych sekretów kanały są pomijane — workflow działa normalnie.

