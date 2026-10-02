"""TEMPORARY probe #3 (stdlib only): mine the risk-parameters SSR payload.

Read-only. De-escapes \\uXXXX, then dumps every uploads/*.xls* link and any
context around 'risk', 'Расчет', 'параметр', plus the media base host.

Run:  py -3 scripts\\probe_rp3.py
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

PAGE = "https://kase.kz/ru/markets/markets-valuation/risk-parameters"


def fetch(url: str) -> str:
    req = Request(url, headers={"User-Agent": UA, "Accept-Language": "ru,en;q=0.8"})
    with urlopen(req, timeout=40, context=_CTX) as resp:
        return resp.read().decode("utf-8", "replace")


def deescape(s: str) -> str:
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), s)


def main() -> None:
    raw = fetch(PAGE)
    text = deescape(raw)
    print(f"len(raw)={len(raw)} len(deescaped)={len(text)}")

    print("\n=== all uploads/*.xls* links ===")
    uploads = sorted(set(re.findall(r"/uploads/[^\s\"'<>\\]+\.xlsx?", text, re.I)))
    for u in uploads:
        print("  ", u)
    print(f"  total: {len(uploads)}")

    print("\n=== media/CDN hosts referenced ===")
    hosts = sorted(set(re.findall(r"https?://[a-z0-9.\-]+", text, re.I)))
    for h in hosts:
        if any(k in h for k in ("upload", "media", "cdn", "amazon", "storage", "kase")):
            print("  ", h)

    for needle in ("risk", "Расчет", "параметр", "Риск", "ГЦБ_ФР", "_ФР"):
        print(f"\n=== context around {needle!r} (first 5) ===")
        count = 0
        for m in re.finditer(re.escape(needle), text):
            s = max(0, m.start() - 90)
            e = min(len(text), m.end() + 90)
            snippet = text[s:e].replace("\n", " ")
            print(f"  …{snippet}…")
            count += 1
            if count >= 5:
                break
        if count == 0:
            print("  (none)")


if __name__ == "__main__":
    main()
