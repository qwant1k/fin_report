"""TEMPORARY probe #4 (stdlib only): grep KASE Angular JS bundles for the
risk-parameters API / Excel endpoint.

Run:  py -3 scripts\\probe_rp4.py
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
PAGE = f"{BASE}/ru/markets/markets-valuation/risk-parameters"
KEYWORDS = (
    "risk-parameter", "risk_param", "riskParam", "recalc", "settlement",
    "market-valuation", "indicators/", "/uploads/", ".xls", "archive-xls",
    "download", "valuation", "estimated-price", "calc-price",
)


def fetch(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": UA, "Accept-Language": "ru,en;q=0.8"})
    with urlopen(req, timeout=60, context=_CTX) as resp:
        return resp.read()


def main() -> None:
    html = fetch(PAGE).decode("utf-8", "replace")
    scripts = sorted(set(re.findall(r'src=["\']([^"\']+\.js)["\']', html)))
    # Angular: also modulepreload links
    scripts += re.findall(r'<link[^>]+href=["\']([^"\']+\.js)["\']', html)
    scripts = sorted(set(scripts))
    print("JS bundles found:", len(scripts))
    for s in scripts:
        print("  ", s)

    seen_urls: set[str] = set()
    for s in scripts:
        url = s if s.startswith("http") else BASE + ("" if s.startswith("/") else "/") + s
        try:
            body = fetch(url).decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001
            print(f"\n[ERR] {url}: {exc!r}")
            continue
        hits = []
        for kw in KEYWORDS:
            for m in re.finditer(re.escape(kw), body):
                s0 = max(0, m.start() - 70)
                e0 = min(len(body), m.end() + 70)
                frag = body[s0:e0]
                # collect URL-ish tokens nearby
                for tok in re.findall(r"[`\"'][^`\"']{4,80}[`\"']", frag):
                    t = tok.strip("`\"'")
                    if any(k in t for k in ("api/", "uploads/", ".xls", "risk", "valuation", "indicator")):
                        seen_urls.add(t)
                hits.append(frag.replace("\n", " "))
        if hits:
            print(f"\n=== {url} ({len(body)} bytes) — {len(hits)} hits ===")
            for h in hits[:12]:
                print("   …", h, "…")

    print("\n=== candidate path/URL tokens ===")
    for t in sorted(seen_urls):
        print("  ", t)


if __name__ == "__main__":
    main()
