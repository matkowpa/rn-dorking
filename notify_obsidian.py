#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kanał Obsidian: dopisuje nowe nabory do notatki w vaulcie użytkownika.

Etap 3: obok Telegrama i e-maila — trzeci kanał powiadomień. Notatka
`Nabory-RN.md` w vaulcie Obsidian (path z OBSIDIAN_VAULT_PATH, domyślnie
/opt/data/obsidian-vault), sekcja per dzień. Zero zależności zewnętrznych —
zwykły plik Markdown; sync do GitHuba robi cron na serwerze (vault-sync.sh).

Wywołanie: python3 notify_obsidian.py "<tekst digestu>" [data]
  data domyślnie = dziś (YYYY-MM-DD). Idempotentne: ta sama data dopisuje
  do tej samej sekcji (bez duplikatów dnia).
"""

import os
import sys
import re
from datetime import date

VAULT_DEFAULT = "/opt/data/obsidian-vault"
NOTATKA = "Nabory-RN.md"


def vault_path() -> str:
    """Ścieżka notatki. Kanał działa TYLKO gdy vault realnie istnieje
    (serwer hermesa). W CI brak OBSIDIAN_VAULT_PATH i katalogu — dopisz()
    zwróci False z komunikatem, zamiast tworzyć fantomowy plik w repo."""
    base = os.getenv("OBSIDIAN_VAULT_PATH", VAULT_DEFAULT)
    if not os.path.isdir(base):
        return ""
    return os.path.join(base, NOTATKA)


def strip_markdown_noise(text: str) -> str:
    """Digest przychodzi z notify.py — emote i duplikaty podsumowań wyłapujemy."""
    return text.strip()


def zbuduj_sekcje(dnia: str, tresc: str) -> str:
    tresc = strip_markdown_noise(tresc)
    header = f"## {dnia}"
    return f"{header}\n\n{tresc}\n"


def dopisz(dnia: str, tresc: str) -> tuple[bool, str]:
    """Dopisuje sekcję dnia na GÓRĘ pliku (pod nagłówkiem). True gdy zapisano."""
    path = vault_path()
    if not path:
        return False, "vault nie istnieje (CI/brak OBSIDIAN_VAULT_PATH) — kanał pominięty"
    sekcja = zbuduj_sekcje(dnia, tresc)

    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        content = (
            "# Nabory — rady nadzorcze (kanał z rn-dorking)\n\n"
            "Automatyczny digest z potoku rn-dorking (obok Telegrama i e-maila).\n"
            "Najnowsze dni na górze. Źródło: https://matkowpa.github.io/rn-dorking/\n\n"
            + sekcja
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return True, "utworzono plik + sekcja"

    content = open(path, encoding="utf-8").read()
    if f"## {dnia}" in content:
        # dopisz tresc do istniejacej sekcji dnia (idempotentnie: bez duplikatu)
        # znajdz poczatek sekcji i koniec (nastepny "## " albo EOF)
        pattern = re.compile(rf"(## {re.escape(dnia)}\n\n)(.*?)(\n## |\Z)", re.S)
        m = pattern.search(content)
        if m and tresc and tresc not in m.group(2):
            new_body = (m.group(2) + "\n\n" + tresc).strip()
            content = content[:m.start()] + m.group(1) + new_body + (m.group(3) or "\n") + content[m.end():]
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return True, "uzupełniono sekcję dnia"
        return False, "sekcja dnia już zawiera tę treść"

    # nowa sekcja: wstaw pod nagłówkiem i meta-blokiem (pierwsze 4 linie)
    lines = content.split("\n")
    insert_at = 4
    # znajdź koniec bloku nagłówka (linie nie-zaczynające się od # ani >)
    while insert_at < len(lines) and (lines[insert_at].startswith(("#", ">", "!")) or not lines[insert_at].strip()):
        insert_at += 1
    lines.insert(insert_at, sekcja + "\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return True, "dodano sekcję dnia"


def main() -> int:
    if len(sys.argv) < 2:
        print("uzycie: notify_obsidian.py \"<digest>\" [YYYY-MM-DD]", file=sys.stderr)
        return 1
    digest = sys.argv[1]
    dnia = sys.argv[2] if len(sys.argv) > 2 else date.today().isoformat()
    ok, msg = dopisz(dnia, digest)
    print(msg)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
