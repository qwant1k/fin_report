"""TEMPORARY probe #6: collapse whitespace and dump tight context around the
market-valuations request builder + download URL.

Run:  py -3 scripts\\probe_rp6.py
"""
from __future__ import annotations

import re
import ssl
from urllib.request import Request, urlopen

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE
URL = "https://kase.kz/chunk-2GK3KLX2.js"


def fetch(url: str) -> str:
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=60, context=_CTX) as resp:
        return resp.read().decode("utf-8", "replace")


def main() -> None:
    body = fetch(URL)
    body = re.sub(r"[ \t]{2,}", " ", body)  # collapse padding runs
    # The market-valuation service: capture from 'class' before the
    # 'indicators/market-valuations/' get, up to after it.
    for m in re.finditer(r"indicators/market-valuations/", body):
        s = max(0, m.start() - 1500)
        e = min(len(body), m.end() + 300)
        chunk = body[s:e]
        print("================ market-valuations context ================")
        print(chunk)
        print()

    print("\n================ rpfile / calendarType ================")
    for m in re.finditer(r"rpfile|waprfile|calendarType|currentTab", body):
        s = max(0, m.start() - 250)
        e = min(len(body), m.end() + 250)
        print("…", body[s:e], "…\n")
        break  # the first window already shows the ternary

    # Look for a download url builder referencing market-valuations or a file
    print("\n================ getDownloadUrl windows ================")
    for m in list(re.finditer(r"getDownloadUrl", body))[:8]:
        s = max(0, m.start() - 200)
        e = min(len(body), m.end() + 200)
        print("…", body[s:e], "…\n")


if __name__ == "__main__":
    main()
