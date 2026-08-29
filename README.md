# rn-dorking — nabory na rady nadzorcze

Automatyczne codzienne wykrywanie ogłoszeń o naborze kandydatów na członków
rad nadzorczych (spółki, fundusze, instytucje publiczne) — wyszukiwanie
w Brave Search, klasyfikacja i ekstrakcja danych przez LLM, publikacja na
GitHub Pages.

## Jak działa
1. Codziennie o **07:00 i 19:00** (czas polski) GitHub Actions uruchamia potok:
   Brave Search (dorki frazowe + opcjonalne `EXTRA_DORKS`) → deduplikacja →
   filtr LLM → pobranie treści → ekstrakcja pól (podmiot, termin, miejscowość…).
   W razie niepowodzenia runu wysyłany jest alert na Telegram.
2. Wyniki zapisywane są per dzień do `data/dnia/<data>.json` i łączone
   w pełną historię `oferty.json`.
3. `build_docs.py` buduje dane dla strony (`docs/data/`), commit i GitHub
   Pages odświeża stronę.

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
(`content_fetcher.py`) i budowę digestu powiadomień (`notify.py`).

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

