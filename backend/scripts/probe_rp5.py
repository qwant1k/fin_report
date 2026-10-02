"""TEMPORARY probe #5 (stdlib only): dump wide context around the
market-valuation service in the KASE bundle to find the risk-parameters
request param and the Excel/xls download URL.

Run:  py -3 scripts\\probe_rp5.py
"""
from __future__ import annotations

import re
import ssl
from urllib.request import Request, urlopen

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE
BASE = "https://kase.kz"
URL = f"{BASE}/chunk-2GK3KLX2.js"

ANCHORS = (
    "indicators/market-valuations/",
    "rpfile",
    "waprfile",
    "calendarType",
    "getDownloadUrl",
    "currentTab",
    "archive-xls",
    "market-valuations/archive",
)


def fetch(url: str) -> str:
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=60, context=_CTX) as resp:
        return resp.read().decode("utf-8", "replace")


def main() -> None:
    body = fetch(URL)
    print(f"len={len(body)}")
    for anchor in ANCHORS:
        idxs = [m.start() for m in re.finditer(re.escape(anchor), body)]
        print(f"\n######## anchor {anchor!r}: {len(idxs)} occ ########")
        for i, pos in enumerate(idxs[:3]):
            s = max(0, pos - 600)
            e = min(len(body), pos + 600)
            print(f"\n--- occ {i} @ {pos} ---")
            print(body[s:e])


if __name__ == "__main__":
    main()
