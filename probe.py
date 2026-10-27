"""Second probe: which TradingView columns exist, contract details, and fallbacks."""
import json
import sys
import time

import requests

ORIGIN = "https://raviteja2455.github.io"
UA = ("Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/129.0.0.0 Mobile Safari/537.36")
H = {"User-Agent": UA, "Origin": ORIGIN, "Referer": ORIGIN + "/delivery-radar/",
     "Accept": "application/json, text/plain, */*"}
TV = "https://scanner.tradingview.com/global/scan"


def out(obj):
    print(json.dumps(obj, ensure_ascii=False))
    sys.stdout.flush()


def tv(tickers, cols, label):
    body = json.dumps({"symbols": {"tickers": tickers, "query": {"types": []}}, "columns": cols})
    try:
        r = requests.post(TV, data=body, headers={**H, "Content-Type": "text/plain;charset=UTF-8"}, timeout=20)
        out({"label": label, "status": r.status_code, "body": r.text[:3000]})
    except Exception as e:  # noqa: BLE001
        out({"label": label, "error": repr(e)[:200]})


def get(label, url, n=3000):
    try:
        r = requests.get(url, headers=H, timeout=20)
        out({"label": label, "status": r.status_code, "acao": r.headers.get("access-control-allow-origin"),
             "body": r.text[:n]})
    except Exception as e:  # noqa: BLE001
        out({"label": label, "error": repr(e)[:200]})


def main():
    out({"start": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())})
    base = ["NSEIX:NIFTY1!"]
    for col in ["time", "update_time", "current_session", "session", "market_status", "is_trading",
                "expiration", "prev_close_price", "close_prev", "pricescale", "lp_time", "change_from_open",
                "close|1", "Recommend.All", "is_primary", "subtype", "typespecs", "contract_month", "root",
                "base_currency", "country", "logoid", "premarket_close", "postmarket_close",
                "regular_close", "regular_close_time", "local_popularity", "rtc", "rtc_time"]:
        tv(base, ["close", col], "col " + col)
    tv(["NSEIX:NIFTY1!", "NSEIX:NIFTY2!", "NSE:NIFTY1!", "NSE:NIFTY", "ICEEUR:BRN1!", "ICEEUR:BRN2!",
        "ICEEUR:BRNZ2026", "ICEEUR:BRNF2027", "NYMEX:CL1!", "NYMEX:CLZ2026", "FX_IDC:USDINR",
        "NSEIX:NIFTYX2026", "NSEIX:NIFTYV2026"],
       ["name", "description", "close", "change", "change_abs", "update_mode", "open", "high", "low", "volume"],
       "contracts")

    get("mc overview full", "https://priceapi.moneycontrol.com/technicalCompanyData/globalMarket/"
        "getGlobalIndicesListingData?view=overview&deviceType=W", 9000)
    for path in ["inidicesindia/in%3Bgsx", "global/in%3Bgsx", "notapplicable/inidicesindia/in%3Bgsx"]:
        get("mc feed " + path, "https://priceapi.moneycontrol.com/pricefeed/notapplicable/" + path, 1500)
    get("mc feed global gsx", "https://priceapi.moneycontrol.com/pricefeed/global/in%3Bgsx", 1500)
    get("cnbc gift?", "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?"
        "symbols=.NSEI%7C%40SIN.1%7C%40NIFTY.1%7CNIFTY.1%7C.GIFTNIFTY&requestMethod=itv&noform=1&partnerId=2"
        "&fund=1&exthrs=1&output=json&events=1", 3000)
    out({"end": True})


if __name__ == "__main__":
    main()
