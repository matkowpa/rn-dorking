# -*- coding: utf-8 -*-
"""Tymczasowa diagnostyka Google CSE - surowa odpowiedź."""
import requests
import os

params = {
    "key": os.environ.get("GOOGLE_API_KEY", ""),
    "cx": "638fe4542346146a3",
    "q": "test",
}
r = requests.get("https://www.googleapis.com/customsearch/v1",
                 params=params, timeout=30)
print("STATUS:", r.status_code)
print(r.text[:600])
