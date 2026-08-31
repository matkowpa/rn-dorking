# -*- coding: utf-8 -*-
"""Powiadomienia o nowych ogłoszeniach (Telegram + e-mail Brevo).

Uruchamiane w workflow PO potoku:
- czyta plik dnia data/dnia/<dzisiaj>.json (nowe oferty) i oferty.json
  (przypomnienia o terminach ≤7 dni),
- pomija to, co już wysłane (data/notified.json - anty-spam),
- wysyła digest na skonfigurowane kanały; brak konfiguracji kanału = skip.

Nigdy nie zawala workflow'u: błędy wysyłki logujemy, wychodzimy z kodem 0.
"""

import json
import logging
import os
import smtplib
import ssl
import time
from datetime import date, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from dotenv import load_dotenv

# Wczytaj .env (notify uruchamiany jest samodzielnie - nie przez config)
load_dotenv()

logger = logging.getLogger(__name__)

REMINDER_DAYS = 7  # przypomnienie, gdy termin naboru ≤ 7 dni


# ---------- wczytywanie danych ----------

def _read_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Nie udało się wczytać %s: %s", path, e)
        return default


def _write_json(path, data) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ---------- budowa treści ----------

def _fmt_date(iso: str) -> str:
    if not iso:
        return ""
    d = datetime.fromisoformat(iso)
    return d.strftime("%d.%m.%Y")


def build_digest(new_offers: list[dict], reminders: list[dict],
                 today: str, stats: dict | None = None) -> tuple[str, str]:
    """Zwraca (treść_text, treść_html) digestu.

    stats (opcjonalnie) - metryki jakości runu (offers_with_termin,
    content_empty) dopisywane na końcu wiadomości.
    """
    day = _fmt_date(today)
    lines = [f"🔔 {len(new_offers)} nowe nabory na członków rad nadzorczych ({day})", ""]
    html_items = []
    for i, o in enumerate(new_offers, 1):
        term = o.get("termin_skladania_ofert") or "nieznany"
        place = f" — {o['miejscowosc']}" if o.get("miejscowosc") else ""
        lines.append(f"{i}. {o.get('podmiot', '(bez nazwy)')}{place}")
        lines.append(f"   termin: {term}")
        lines.append(f"   → {o.get('url', '')}")
        lines.append("")
        html_items.append(
            f"<li><b>{o.get('podmiot', '(bez nazwy)')}{place}</b><br>"
            f"termin: {term}<br>"
            f"<a href='{o.get('url', '')}'>{o.get('url', '')}</a></li>")

    if reminders:
        lines.append("⏰ Przypomnienia o zbliżających się terminach:")
        html_rem = []
        for o in reminders:
            d = (datetime.fromisoformat(o["termin_skladania_ofert"]) - datetime.today()).days
            lines.append(f"- {o.get('podmiot', '(bez nazwy)')} — kończy się "
                         f"{_fmt_date(o['termin_skladania_ofert'])} (za {d} dni)")
            html_rem.append(
                f"<li><b>{o.get('podmiot', '(bez nazwy)')}</b> — kończy się "
                f"{_fmt_date(o['termin_skladania_ofert'])} (za {d} dni)</li>")
        lines.append("")

    # Metryki jakości runu (jeśli przekazane przez potok)
    if stats:
        added = stats.get("offers_added", 0)
        with_term = stats.get("offers_with_termin", 0)
        empty = stats.get("content_empty", 0)
        lines.append("📊 Metryki runu:")
        lines.append(f"- oferty z terminem: {with_term}/{added}")
        lines.append(f"- oferty bez treści (snippet): {empty}")
        lines.append("")

    text = "\n".join(lines)
    html = (
        f"<h2>🔔 {len(new_offers)} nowe nabory na członków rad nadzorczych</h2>"
        f"<p><i>{day}</i></p><ol>{''.join(html_items)}</ol>"
        + (f"<h3>⏰ Przypomnienia</h3><ul>{''.join(html_rem)}</ul>" if reminders else "")
        + (f"<h3>📊 Metryki runu</h3><ul>"
           f"<li>oferty z terminem: {stats.get('offers_with_termin', 0)}/"
           f"{stats.get('offers_added', 0)}</li>"
           f"<li>oferty bez treści (snippet): {stats.get('content_empty', 0)}</li>"
           f"</ul>" if stats else "")
    )
    return text, html

# ---------- kanały ----------

def send_telegram(text: str) -> bool:
    """Wysyła wiadomość na Telegram. Retry 429 (5s/10s/20s)."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        logger.info("Telegram: brak TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID - pomijam")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    delays = [5, 10, 20]
    for attempt in range(len(delays) + 1):
        try:
            r = requests.post(url, json={
                "chat_id": chat_id, "text": text, "disable_web_page_preview": False,
            }, timeout=30)
            if r.status_code == 200:
                logger.info("Telegram: wiadomość wysłana")
                return True
            if r.status_code == 429 and attempt < len(delays):
                delay = delays[attempt]
                logger.warning("Telegram 429, ponawiam za %s s", delay)
                time.sleep(delay)
                continue
            logger.warning("Telegram błąd %s: %s", r.status_code, r.text[:200])
            return False
        except requests.RequestException as e:
            logger.warning("Telegram wyjątek: %s", e)
            return False
    return False


def send_email(text: str, html: str, subject: str) -> bool:
    """Wysyła e-mail przez SMTP Brevo (TLS 587)."""
    host = os.getenv("SMTP_HOST", "")
    user = os.getenv("SMTP_USER", "")
    password = os.getenv("SMTP_PASSWORD", "")
    to_addr = os.getenv("NOTIFY_EMAIL_TO", "")
    if not all([host, user, password, to_addr]):
        logger.info("E-mail: brak SMTP_HOST/SMTP_USER/SMTP_PASSWORD/NOTIFY_EMAIL_TO - pomijam")
        return False
    port = int(os.getenv("SMTP_PORT", "587"))

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    delays = [5, 10, 20]
    for attempt in range(len(delays) + 1):
        try:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(user, password)
                smtp.sendmail(user, [to_addr], msg.as_string())
            logger.info("E-mail: wiadomość wysłana na %s", to_addr)
            return True
        except smtplib.SMTPResponseException as e:
            if e.smtp_code == 429 and attempt < len(delays):
                delay = delays[attempt]
                logger.warning("E-mail 429, ponawiam za %s s", delay)
                time.sleep(delay)
                continue
            logger.warning("E-mail błąd SMTP %s: %s", e.smtp_code, e)
            return False
        except (smtplib.SMTPException, OSError) as e:
            logger.warning("E-mail wyjątek: %s", e)
            return False
    return False

# ---------- główna logika ----------

def run() -> int:
    today = date.today().isoformat()
    daily = _read_json(os.path.join("data", "dnia", f"{today}.json"), {})
    state = _read_json(os.path.join("data", "notified.json"),
                       {"offers": [], "reminders": {}})
    sent_urls = set(state.get("offers", []))

    new_offers = [o for o in daily.get("offers", []) if o.get("url") not in sent_urls]
    reminders = []
    for o in _read_json("oferty.json", []):
        url = o.get("url", "")
        term = o.get("termin_skladania_ofert", "")
        if not term or url in sent_urls:
            continue
        try:
            days_left = (datetime.fromisoformat(term) - datetime.today()).days
        except ValueError:
            continue
        if 0 <= days_left <= REMINDER_DAYS and state.get("reminders", {}).get(url) != today:
            reminders.append(o)

    if not new_offers and not reminders:
        logger.info("Notify: brak nowych ofert i przypomnień - nic nie wysyłam")
        return 0

    text, html = build_digest(new_offers, reminders, today, daily.get("stats"))
    subject = f"🔔 {len(new_offers)} nowe nabory na rady nadzorcze — {_fmt_date(today)}"

    ok_tg = send_telegram(text)
    ok_mail = send_email(text, html, subject)

    # Zapisz stan tylko, jeśli któraś wiadomość dotarła (idempotentność)
    if ok_tg or ok_mail:
        sent_urls |= {o.get("url", "") for o in new_offers}
        state["offers"] = sorted(sent_urls)
        for o in reminders:
            state.setdefault("reminders", {})[o.get("url", "")] = today
        _write_json(os.path.join("data", "notified.json"), state)
    else:
        logger.warning("Notify: żaden kanał nie dostarczył wiadomości - stan nie zapisany")
    return 0


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        stream=sys.stdout)
    sys.exit(run())


