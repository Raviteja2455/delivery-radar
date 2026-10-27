"""Probe candidate live-quote sources for GIFT Nifty, crude (USD) and USD/INR.

Records, for each request: status, CORS headers as seen by a page on raviteja2455.github.io,
content type and the start of the body. Run on a GitHub runner; output goes to the job log.
"""
import json
import re
import sys
import time

import requests

ORIGIN = "https://raviteja2455.github.io"
UA = ("Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/129.0.0.0 Mobile Safari/537.36")
BASE_H = {"User-Agent": UA, "Origin": ORIGIN, "Referer": ORIGIN + "/delivery-radar/",
          "Accept": "application/json, text/plain, */*", "Accept-Language": "en-IN,en;q=0.9"}
KEEP = ["access-control-allow-origin", "access-control-allow-methods", "access-control-allow-headers",
        "access-control-allow-credentials", "content-type", "cache-control", "server", "cf-ray", "vary"]

TV_TICKERS = ["NSEIX:NIFTY1!", "NSEIX:NIFTY2!", "TVC:UKOIL", "TVC:USOIL", "FX_IDC:USDINR",
              "NSE:NIFTY", "NYMEX:CL1!", "ICEEUR:BRN1!", "FX:USDINR", "TVC:DXY"]
TV_COLS = ["close", "change", "change_abs", "description", "update_mode", "currency", "open", "high", "low",
           "volume", "type", "exchange", "name"]


def show(label, r, body_chars=900):
    hdr = {k: r.headers.get(k) for k in KEEP if r.headers.get(k) is not None}
    body = r.text if r.text else ""
    print(json.dumps({"label": label, "status": r.status_code, "url": r.url[:200], "headers": hdr,
                      "len": len(body), "body": body[:body_chars]}, ensure_ascii=False))
    sys.stdout.flush()


def get(label, url, extra=None, body_chars=900, session=None):
    s = session or requests
    try:
        r = s.get(url, headers={**BASE_H, **(extra or {})}, timeout=20)
        show(label, r, body_chars)
        return r
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"label": label, "error": repr(e)[:300], "url": url[:200]}))
        return None


def post(label, url, data, ctype, body_chars=900):
    try:
        r = requests.post(url, data=data, headers={**BASE_H, "Content-Type": ctype}, timeout=20)
        show(label, r, body_chars)
        return r
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"label": label, "error": repr(e)[:300]}))
        return None


def preflight(label, url, method="POST", req_headers="content-type"):
    try:
        r = requests.options(url, headers={"User-Agent": UA, "Origin": ORIGIN,
                                           "Access-Control-Request-Method": method,
                                           "Access-Control-Request-Headers": req_headers}, timeout=20)
        show(label, r, 200)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"label": label, "error": repr(e)[:300]}))


def scan_for_apis(label, page_url, pattern, limit=60):
    """Fetch a page and its scripts; list strings that look like data endpoints."""
    sess = requests.Session()
    r = get(label + " page", page_url, {"Accept": "text/html"}, 300, sess)
    if r is None or not r.ok:
        return
    found, texts = set(), [r.text]
    srcs = re.findall(r'<script[^>]+src="([^"]+)"', r.text)
    for src in srcs[:25]:
        u = requests.compat.urljoin(page_url, src)
        try:
            js = sess.get(u, headers={"User-Agent": UA}, timeout=20)
            if js.ok:
                texts.append(js.text)
        except Exception:  # noqa: BLE001
            pass
    for t in texts:
        for m in re.findall(pattern, t):
            found.add(m if isinstance(m, str) else m[0])
    print(json.dumps({"label": label + " endpoints", "scripts": len(srcs), "found": sorted(found)[:limit]},
                     ensure_ascii=False))


def main():
    print("== start", time.strftime("%Y-%m-%d %H:%M:%S %Z"))

    # TradingView scanner: one call could cover every quote.
    q = json.dumps({"symbols": {"tickers": TV_TICKERS, "query": {"types": []}}, "columns": TV_COLS})
    post("tv scan json", "https://scanner.tradingview.com/global/scan", q, "application/json", 4000)
    post("tv scan text/plain", "https://scanner.tradingview.com/global/scan", q, "text/plain;charset=UTF-8", 400)
    post("tv scan form", "https://scanner.tradingview.com/global/scan", q,
         "application/x-www-form-urlencoded", 400)
    preflight("tv scan preflight", "https://scanner.tradingview.com/global/scan")
    get("tv symbol GET gift", "https://scanner.tradingview.com/symbol?symbol=NSEIX%3ANIFTY1%21"
        "&fields=close,change,change_abs,update_mode,description,currency&no_404=true")
    get("tv symbol GET brent", "https://scanner.tradingview.com/symbol?symbol=TVC%3AUKOIL"
        "&fields=close,change,change_abs,update_mode,description,currency&no_404=true")

    # CNBC quote service.
    get("cnbc", "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?"
        "symbols=%40LCO.1%7C%40CL.1%7CINR%3D%7C.NSEI&requestMethod=itv&noform=1&partnerId=2&fund=1"
        "&exthrs=1&output=json&events=1", body_chars=2500)

    # Yahoo chart API.
    for sym in ["BZ%3DF", "CL%3DF", "INR%3DX", "%5ENSEI"]:
        get("yahoo " + sym, f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=5m&range=1d",
            body_chars=500)
    get("yahoo q2 BZ", "https://query2.finance.yahoo.com/v8/finance/chart/BZ%3DF?interval=5m&range=1d",
        body_chars=300)

    # Stooq.
    get("stooq csv", "https://stooq.com/q/l/?s=cb.f+cl.f+usdinr&f=sd2t2ohlcv&h&e=csv", body_chars=500)
    get("stooq json", "https://stooq.com/q/l/?s=cb.f+cl.f+usdinr&f=sd2t2ohlcv&h&e=json", body_chars=500)

    # Moneycontrol.
    for view in ["overview", "asia", "ASIA"]:
        get("mc global " + view, "https://priceapi.moneycontrol.com/technicalCompanyData/globalMarket/"
            f"getGlobalIndicesListingData?view={view}&deviceType=W", body_chars=2500)
    get("mc commodities", "https://priceapi.moneycontrol.com/technicalCompanyData/globalMarket/"
        "getGlobalCommoditiesListingData?view=overview&deviceType=W", body_chars=1500)
    scan_for_apis("mc gift page", "https://www.moneycontrol.com/live-index/gift-nifty",
                  r'(https?://[a-z0-9.\-]*moneycontrol\.com/[^"\'\s<>]{0,160}(?:gift|GIFT|global|Global)[^"\'\s<>]{0,120})')

    # NSE IX (the exchange that lists GIFT Nifty).
    scan_for_apis("nseix home", "https://www.nseix.com/",
                  r'(["\'](?:https?://[a-z0-9.\-]*nseix\.com)?/api/[^"\'\s]{1,120}["\'])')

    # Groww and ET.
    get("groww global", "https://groww.in/v1/api/stocks_data/v1/global_instruments?instrumentType=GLOBAL_INSTRUMENTS",
        body_chars=1500)
    scan_for_apis("et gift page", "https://economictimes.indiatimes.com/markets/indices/gift-nifty",
                  r'(https?://[a-z0-9.\-]*indiatimes\.com/[^"\'\s<>]{0,200})')
    print("== end")


if __name__ == "__main__":
    main()
