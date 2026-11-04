"""Probe MCX gold and silver quote sources for Delivery Radar's live strip (temporary).

Records, for each request: status, CORS headers as a page on raviteja2455.github.io would see them,
and the start of the body. Runs on a GitHub runner; output is committed back to this branch.
"""
import json
import re
import sys
import time

import requests

ORIGIN = "https://raviteja2455.github.io"
UA = ("Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/129.0.0.0 Mobile Safari/537.36")
H = {"User-Agent": UA, "Origin": ORIGIN, "Referer": ORIGIN + "/delivery-radar/",
     "Accept": "application/json, text/plain, */*", "Accept-Language": "en-IN,en;q=0.9"}
KEEP = ["access-control-allow-origin", "access-control-allow-methods", "access-control-allow-headers",
        "access-control-allow-credentials", "content-type", "cache-control", "server", "date", "age",
        "last-modified"]
TV = "https://scanner.tradingview.com/global/scan"


def out(obj):
    print(json.dumps(obj, ensure_ascii=False))
    sys.stdout.flush()


def hdrs(r):
    return {k: r.headers.get(k) for k in KEEP if r.headers.get(k) is not None}


def get(label, url, n=3000, extra=None, session=None):
    s = session or requests
    try:
        r = s.get(url, headers={**H, **(extra or {})}, timeout=20)
        out({"label": label, "status": r.status_code, "url": r.url[:240], "headers": hdrs(r), "len": len(r.text),
             "body": r.text[:n]})
        return r
    except Exception as e:  # noqa: BLE001
        out({"label": label, "error": repr(e)[:300], "url": url[:240]})
        return None


def post(label, url, data, ctype, n=3000):
    try:
        r = requests.post(url, data=data, headers={**H, "Content-Type": ctype}, timeout=20)
        out({"label": label, "status": r.status_code, "url": url[:240], "headers": hdrs(r), "len": len(r.text),
             "body": r.text[:n]})
        return r
    except Exception as e:  # noqa: BLE001
        out({"label": label, "error": repr(e)[:300], "url": url[:240]})
        return None


def tv(label, tickers, cols, n=60000):
    body = json.dumps({"symbols": {"tickers": tickers, "query": {"types": []}}, "columns": cols})
    try:
        r = requests.post(TV, data=body, headers={**H, "Content-Type": "text/plain;charset=UTF-8"}, timeout=20)
        out({"label": label, "status": r.status_code, "headers": hdrs(r), "cols": cols, "body": r.text[:n]})
    except Exception as e:  # noqa: BLE001
        out({"label": label, "error": repr(e)[:300]})


def scan_page(label, page_url, patterns, snippets=(), limit=120):
    """Fetch a page and its scripts; list strings that look like data endpoints, plus text around keywords."""
    sess = requests.Session()
    try:
        r = sess.get(page_url, headers={**H, "Accept": "text/html"}, timeout=25)
    except Exception as e:  # noqa: BLE001
        out({"label": label, "error": repr(e)[:300]})
        return
    out({"label": label + " page", "status": r.status_code, "len": len(r.text), "headers": hdrs(r)})
    if not r.ok:
        return
    texts = [r.text]
    srcs = re.findall(r'<script[^>]+src="([^"]+)"', r.text)
    for src in srcs[:40]:
        u = requests.compat.urljoin(page_url, src)
        try:
            js = sess.get(u, headers={"User-Agent": UA}, timeout=20)
            if js.ok:
                texts.append(js.text)
        except Exception:  # noqa: BLE001
            pass
    found = set()
    for t in texts:
        for p in patterns:
            for m in re.findall(p, t):
                found.add(m if isinstance(m, str) else m[0])
    snips = []
    for kw in snippets:
        for m in re.finditer(kw, r.text):
            snips.append(r.text[max(0, m.start() - 160): m.end() + 260])
            if len(snips) > 24:
                break
    out({"label": label + " endpoints", "scripts": len(srcs), "found": sorted(found)[:limit], "snippets": snips[:24]})


def main():
    out({"now_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), "epoch": int(time.time())})

    # ---- TradingView: continuous and dated MCX bullion contracts, plus international references.
    months = ["X2026", "Z2026", "F2027", "G2027", "H2027", "J2027", "K2027", "M2027", "N2027", "Q2027"]
    roots = ["GOLD", "SILVER", "GOLDM", "SILVERM", "SILVERMIC", "GOLDPETAL"]
    tickers = []
    for r in roots:
        tickers += [f"MCX:{r}1!", f"MCX:{r}2!", f"MCX:{r}3!"] + [f"MCX:{r}{m}" for m in months]
    tickers += ["COMEX:GC1!", "COMEX:SI1!", "TVC:GOLD", "TVC:SILVER", "OANDA:XAUUSD", "OANDA:XAGUSD",
                "FX_IDC:USDINR", "NSE:GOLDBEES", "NSE:SILVERBEES"]
    cols = ["name", "description", "close", "change", "change_abs", "update_mode", "volume", "current_session",
            "time", "update_time", "expiration", "open", "high", "low", "currency", "pricescale", "type", "exchange"]
    tv("tv mcx", tickers, cols)
    # Extra columns, one at a time so an unknown one can't spoil the rest.
    for col in ["open_interest", "average_volume_10d_calc", "average_volume_30d_calc", "relative_volume_10d_calc",
                "Value.Traded", "prev_close_price", "lp_time", "rtc", "rtc_time", "regular_close",
                "regular_close_time", "first_bar_time", "contract_month", "root", "typespecs", "subtype",
                "session", "timezone", "is_tradable"]:
        tv("col " + col, ["MCX:GOLDZ2026", "MCX:SILVERZ2026", "MCX:GOLD1!"], ["close", col], 3000)
    get("tv symbol GET gold", "https://scanner.tradingview.com/symbol?symbol=MCX%3AGOLD1%21"
        "&fields=close,change,change_abs,update_mode,description,currency,expiration,current_session&no_404=true")
    disc = {"filter": [{"left": "exchange", "operation": "equal", "right": "MCX"},
                       {"left": "name", "operation": "match", "right": "GOLD|SILVER"}],
            "columns": ["name", "description", "close", "volume", "expiration", "update_mode", "current_session"],
            "sort": {"sortBy": "volume", "sortOrder": "desc"}, "range": [0, 60]}
    post("tv futures discovery", "https://scanner.tradingview.com/futures/scan", json.dumps(disc),
         "text/plain;charset=UTF-8", 12000)

    # ---- Moneycontrol: guessed price-feed endpoints, then what its commodity pages actually call.
    for sym, exp in [("GOLD", "2026-12-05"), ("SILVER", "2026-12-05"), ("GOLD", ""), ("SILVER", ""),
                     ("GOLDM", "2026-11-05"), ("GOLD", "2027-02-05")]:
        q = f"?expiry={exp}" if exp else ""
        get(f"mc feed {sym} {exp or 'noexp'}",
            f"https://priceapi.moneycontrol.com/pricefeed/mcx/commodityfutures/{sym}{q}", 2500)
    get("mc global commodities", "https://priceapi.moneycontrol.com/technicalCompanyData/globalMarket/"
        "getGlobalCommoditiesListingData?view=overview&deviceType=W", 6000)
    mc_pat = [r'((?:https?:)?//[a-z0-9.\-]*moneycontrol\.com/[^"\'\s<>\\]{0,200})',
              r'((?:pricefeed|techCharts|technicalCompanyData|mcapi)/[A-Za-z0-9_/\-{}$.?=&]{0,160})']
    scan_page("mc gold", "https://www.moneycontrol.com/commodity/gold-price.html", mc_pat,
              ("expiry", "lastPrice", "LTP", "commodityfutures"))
    scan_page("mc silver", "https://www.moneycontrol.com/commodity/silver-price.html", mc_pat, ("expiry",))

    # ---- Groww and Economic Times commodity pages.
    scan_page("groww gold", "https://groww.in/commodities/futures/mcx_gold",
              [r'((?:https?:)?//[a-z0-9.\-]*groww\.in/[^"\'\s<>\\]{0,200})', r'(/v1/api/[A-Za-z0-9_/\-{}$.?=&]{0,160})'],
              ("ltp", "expiry", "contractId", "growwContractId"))
    scan_page("et gold", "https://economictimes.indiatimes.com/commoditysummary/symbol-GOLD.cms",
              [r'(https?://[a-z0-9.\-]*indiatimes\.com/[^"\'\s<>\\]{0,220})'], ("expiry", "LTP", "lastTradedPrice"))

    # ---- MCX's own market watch.
    post("mcx marketwatch", "https://www.mcxindia.com/backpage.aspx/GetMarketWatch", "{}",
         "application/json; charset=UTF-8", 2500)
    out({"end_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())})


if __name__ == "__main__":
    main()
