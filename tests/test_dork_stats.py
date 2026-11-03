# -*- coding: utf-8 -*-
"""Raport wydajności dorków (offline, na syntetycznym archiwum)."""

import importlib.util
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "dork_stats", ROOT / "tools" / "dork_stats.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ds = _load()


def _write(tmp_path, day, rows):
    p = tmp_path / f"raw-{day}.json"
    p.write_text(json.dumps(rows), encoding="utf-8")
    return str(p)


def test_liczy_swieze_i_powtorki(tmp_path):
    p1 = _write(tmp_path, "2026-11-01", [
        {"url": "https://a.pl/1", "source": "dork A", "decision": "accepted"},
        {"url": "https://a.pl/2", "source": "dork A", "decision": "cached"},
        {"url": "https://a.pl/3", "source": "dork A", "decision": "duplicate"},
    ])
    p2 = _write(tmp_path, "2026-11-02", [
        {"url": "https://a.pl/1", "source": "dork A", "decision": "cached"},
        {"url": "https://a.pl/4", "source": "dork A", "decision": "rejected"},
        {"url": "https://fb.com/x", "source": "dork B", "decision": "blocked"},
    ])
    stats = ds.collect([p1, p2])
    a = stats["per_dork"]["dork A"]
    assert a["total"] == 5
    assert a["stale"] == 3          # cached x2 + duplicate
    assert a["accepted"] == 1
    assert a["rejected"] == 1
    assert len(a["fresh_urls"]) == 2   # /1 i /4
    b = stats["per_dork"]["dork B"]
    assert b["blocked"] == 1 and b["fresh_urls"] == set()
    assert stats["per_day"]["2026-11-01"] == {"total": 3, "fresh": 1, "accepted": 1}
    assert stats["per_day"]["2026-11-02"]["fresh"] == 1


def test_brak_zrodla_trafia_do_zbiorczego(tmp_path):
    p = _write(tmp_path, "2026-11-01", [{"url": "https://a.pl/1", "decision": "accepted"}])
    stats = ds.collect([p])
    assert "(bez źródła)" in stats["per_dork"]


def test_render_sortuje_po_ofertach(tmp_path):
    p = _write(tmp_path, "2026-11-01", [
        {"url": "https://a.pl/1", "source": "slaby", "decision": "cached"},
        {"url": "https://a.pl/2", "source": "dobry", "decision": "accepted"},
    ])
    out = ds.render(ds.collect([p]))
    assert out.splitlines()[1].endswith("dobry")
    assert "2026-11-01" in out


def test_format_json(tmp_path, capsys, monkeypatch):
    p = _write(tmp_path, "2026-11-01", [
        {"url": "https://a.pl/1", "source": "dork A", "decision": "accepted"}])
    monkeypatch.setattr(ds, "RAW_GLOB", str(tmp_path / "raw-*.json"))
    assert ds.main(["--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["dorki"]["dork A"]["accepted"] == 1
    assert "urls" not in data["dorki"]["dork A"]
