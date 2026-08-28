# -*- coding: utf-8 -*-
"""Buduje dane dla frontendu GitHub Pages (docs/data/).

- kopiuje pliki dzienne data/dnia/<data>.json do docs/data/<data>.json
- tworzy docs/data/index.json (lista dni z liczbą ofert, malejąco)
- tworzy docs/data/all.json (wszystkie oferty - wyszukiwanie globalne,
  najbliższe terminy)
"""

import glob
import json
import logging
import os

logger = logging.getLogger(__name__)
DOCS_DATA = os.path.join("docs", "data")


def _read(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def build() -> None:
    days: list[dict] = []
    all_offers: list[dict] = []

    for path in sorted(glob.glob(os.path.join("data", "dnia", "*.json"))):
        payload = _read(path)
        run_date = payload.get("date") or os.path.basename(path)[:-5]
        offers = payload.get("offers", [])
        stats = payload.get("stats", {})
        entry = {
            "date": run_date,
            "count": len(offers),
            "stats": {
                "raw_results": stats.get("raw_results", 0),
                "after_filter": stats.get("after_filter", 0),
                "offers_added": stats.get("offers_added", 0),
            },
        }
        days.append(entry)
        all_offers.extend(offers)
        _write(os.path.join(DOCS_DATA, f"{run_date}.json"), payload)

    days.sort(key=lambda d: d["date"], reverse=True)
    _write(os.path.join(DOCS_DATA, "index.json"), days)
    _write(os.path.join(DOCS_DATA, "all.json"), all_offers)
    logger.info("build_docs: %s dni, %s ofert łącznie", len(days), len(all_offers))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=__import__("sys").stdout)
    build()
