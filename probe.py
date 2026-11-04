"""Research probe (temporary): minute bars for Indian stocks, US futures, crude and ADRs around the US midterm
results, plus a live snapshot. Output goes to out.jsonl, committed back to this branch."""
import json
import sys
import time

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/129.0.0.0 Safari/537.36")
H = {"User-Agent": UA, "Accept": "application/json,*/*"}


def out(obj):
    print(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
    sys.stdout.flush()


def yahoo(sym, interval, rng):
    last = None
    for host in ("query1", "query2"):
        try:
            r = requests.get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}",
                             params={"interval": interval, "range": rng, "includePrePost": "true"},
                             headers=H, timeout=30)
            j = r.json()
            res = j["chart"]["result"][0]
            q = res["indicators"]["quote"][0]
            return {"sym": sym, "interval": interval, "meta": {k: res["meta"].get(k) for k in
                    ("exchangeName", "currency", "gmtoffset", "regularMarketPrice", "previousClose",
                     "chartPreviousClose", "regularMarketTime")},
                    "t": res.get("timestamp", []), "o": q.get("open"), "h": q.get("high"), "l": q.get("low"),
                    "c": q.get("close"), "v": q.get("volume")}
        except Exception as e:  # noqa: BLE001
            last = repr(e)[:200]
    return {"sym": sym, "error": last}


def main():
    out({"now_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())})
    # Indian cash market, 1-minute bars for the last two sessions.
    for sym in ["HDFCBANK.NS", "RELIANCE.NS", "ICICIBANK.NS", "^NSEI", "^NSEBANK", "SBIN.NS", "AXISBANK.NS"]:
        out({"label": "yahoo", **yahoo(sym, "1m", "2d")})
    # US index futures, crude, gold, dollar, VIX: 5-minute bars over three days (overnight included).
    for sym in ["ES=F", "NQ=F", "YM=F", "BZ=F", "CL=F", "GC=F", "DX-Y.NYB", "^VIX", "INR=X"]:
        out({"label": "yahoo", **yahoo(sym, "5m", "3d")})
    # India ADRs and ETF tonight, 1-minute bars.
    for sym in ["HDB", "IBN", "INFY", "WIT", "INDA"]:
        out({"label": "yahoo", **yahoo(sym, "1m", "2d")})
    # Live snapshot.
    tickers = ["NSEIX:NIFTY1!", "NSE:NIFTY", "NSE:NIFTY1!", "NYSE:HDB", "NYSE:IBN", "NYSE:INFY", "NYSE:WIT",
               "NYSE:RDY", "AMEX:INDA", "AMEX:EPI", "ICEEUR:BRN1!", "NYMEX:CL1!", "MCX:CRUDEOIL1!", "CME_MINI:ES1!",
               "CME_MINI:NQ1!", "CBOT_MINI:YM1!", "TVC:DXY", "FX_IDC:USDINR", "TVC:US10Y", "COMEX:GC1!",
               "SP:SPX", "DJ:DJI", "NASDAQ:IXIC", "TVC:VIX"]
    cols = ["close", "change", "change_abs", "update_mode", "current_session", "high", "low", "open"]
    try:
        body = json.dumps({"symbols": {"tickers": tickers, "query": {"types": []}}, "columns": cols})
        r = requests.post("https://scanner.tradingview.com/global/scan", data=body,
                          headers={**H, "Content-Type": "text/plain;charset=UTF-8",
                                   "Origin": "https://raviteja2455.github.io"}, timeout=20)
        out({"label": "tv snapshot", "cols": cols, "body": r.text})
    except Exception as e:  # noqa: BLE001
        out({"label": "tv snapshot", "error": repr(e)[:200]})
    out({"end_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())})


if __name__ == "__main__":
    main()
