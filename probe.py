"""Second MCX probe: TradingView vs Moneycontrol side by side, and where Moneycontrol lists expiries (temporary)."""
import json
import re
import sys
import time

import requests

ORIGIN = "https://raviteja2455.github.io"
UA = ("Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/129.0.0.0 Mobile Safari/537.36")
H = {"User-Agent": UA, "Origin": ORIGIN, "Referer": ORIGIN + "/delivery-radar/",
     "Accept": "application/json, text/plain, */*"}
TV = "https://scanner.tradingview.com/global/scan"
MC = "https://priceapi.moneycontrol.com/pricefeed/mcx/commodityfutures/{}?expiry={}"
TV_T = ["MCX:GOLDZ2026", "MCX:GOLDG2027", "MCX:GOLDJ2027", "MCX:SILVERZ2026", "MCX:SILVERH2027", "MCX:SILVERK2027",
        "MCX:GOLDMX2026", "MCX:GOLDMZ2026", "MCX:GOLD1!", "MCX:SILVER1!", "MCX:GOLD2!", "MCX:SILVER2!"]
TV_C = ["close", "change", "change_abs", "open", "high", "low", "volume", "update_time", "open_interest",
        "expiration", "bid", "ask", "current_session", "update_mode"]
MC_K = [("GOLD", "2026-12-04"), ("GOLD", "2027-02-05"), ("SILVER", "2026-12-04"), ("SILVER", "2027-03-05"),
        ("GOLDM", "2026-11-05"), ("GOLDM", "2026-12-04"), ("GOLD", "2026-12-03"), ("SILVER", "2026-12-05")]


def out(obj):
    print(json.dumps(obj, ensure_ascii=False))
    sys.stdout.flush()


def tv_once():
    body = json.dumps({"symbols": {"tickers": TV_T, "query": {"types": []}}, "columns": TV_C})
    try:
        r = requests.post(TV, data=body, headers={**H, "Content-Type": "text/plain;charset=UTF-8"}, timeout=20)
        j = r.json()
        return {row["s"]: dict(zip(TV_C, row["d"])) for row in j.get("data", [])}
    except Exception as e:  # noqa: BLE001
        return {"error": repr(e)[:200]}


def mc_once():
    res = {}
    for sym, exp in MC_K:
        try:
            r = requests.get(MC.format(sym, exp), headers=H, timeout=20)
            j = r.json()
            d = j.get("data") or {}
            res[f"{sym} {exp}"] = {"code": j.get("code"), "acao": r.headers.get("access-control-allow-origin"),
                                   "cache": r.headers.get("cache-control"), "age": r.headers.get("age"),
                                   **{k: d.get(k) for k in ["lastPrice", "change", "perChange", "prevClose", "openPrice",
                                                            "highPrice", "lowPrice", "tradedVol", "openInt", "lastupd",
                                                            "bidPrice", "askPrice", "contractMonth"]}}
        except Exception as e:  # noqa: BLE001
            res[f"{sym} {exp}"] = {"error": repr(e)[:200]}
    return res


def expiry_hunt():
    """Look through Moneycontrol's commodity page scripts for whatever fetches the expiry list."""
    sess = requests.Session()
    page = "https://www.moneycontrol.com/commodity/gold-price.html"
    r = sess.get(page, headers={**H, "Accept": "text/html"}, timeout=25)
    srcs = re.findall(r'<script[^>]+src="([^"]+)"', r.text)
    hits = []
    for src in srcs[:45]:
        u = requests.compat.urljoin(page, src)
        try:
            js = sess.get(u, headers={"User-Agent": UA}, timeout=20).text
        except Exception:  # noqa: BLE001
            continue
        for m in re.finditer(r'(?i)expiry|commodityfutures|futureexpiry|getExpiry', js):
            ctx = js[max(0, m.start() - 220): m.end() + 220]
            if "http" in ctx or "pricefeed" in ctx or "api" in ctx.lower():
                hits.append({"src": u[-80:], "ctx": ctx})
            if len(hits) > 40:
                break
    out({"label": "mc expiry hunt", "scripts": len(srcs), "hits": hits[:40]})


def main():
    out({"now_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), "epoch": int(time.time())})
    for i in range(4):
        t0 = time.time()
        a = tv_once()
        b = mc_once()
        out({"label": f"round {i}", "epoch": int(t0), "tv": a, "mc": b})
        time.sleep(max(0, 15 - (time.time() - t0)))
    for path in ["pricefeed/mcx/commodityfutures/expiry/GOLD", "pricefeed/mcx/expiry/GOLD",
                 "pricefeed/mcx/commodityfutures/GOLD/expiry", "pricefeed/mcx/commodityexpiry/GOLD",
                 "pricefeed/mcx/futures/expiry?symbol=GOLD"]:
        try:
            r = requests.get("https://priceapi.moneycontrol.com/" + path, headers=H, timeout=20)
            out({"label": "mc guess " + path, "status": r.status_code, "body": r.text[:400]})
        except Exception as e:  # noqa: BLE001
            out({"label": "mc guess " + path, "error": repr(e)[:200]})
    expiry_hunt()
    out({"end_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())})


if __name__ == "__main__":
    main()
