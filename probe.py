"""Third probe: contract months, session state and timestamps."""
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
    r = requests.post(TV, data=body, headers={**H, "Content-Type": "text/plain;charset=UTF-8"}, timeout=20)
    out({"label": label, "status": r.status_code, "acao": r.headers.get("access-control-allow-origin"),
         "body": r.text[:6000]})


def main():
    out({"now_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), "epoch": int(time.time())})
    cols = ["name", "description", "close", "change", "change_abs", "update_mode", "volume", "current_session",
            "time", "update_time", "expiration", "open", "high", "low"]
    tv(["NSEIX:NIFTY1!", "NSEIX:NIFTY2!", "NSEIX:NIFTYV2026", "NSEIX:NIFTYX2026", "NSEIX:NIFTYZ2026",
        "NSE:NIFTY1!", "NSE:NIFTY2!", "NSE:NIFTYV2026", "NSE:NIFTYX2026", "NSE:NIFTYZ2026", "NSE:NIFTY",
        "ICEEUR:BRN1!", "ICEEUR:BRN2!", "ICEEUR:BRNX2026", "ICEEUR:BRNZ2026", "ICEEUR:BRNF2027",
        "NYMEX:CL1!", "NYMEX:CL2!", "NYMEX:CLX2026", "NYMEX:CLZ2026", "NYMEX:CLF2027", "FX_IDC:USDINR"],
       cols, "tv all")
    r = requests.get("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?"
                     "symbols=%40LCO.1%7C%40LCO.2%7C%40CL.1%7C%40CL.2%7CINR%3D&requestMethod=itv&noform=1"
                     "&partnerId=2&fund=1&exthrs=1&output=json&events=1", headers=H, timeout=20)
    q = r.json()["FormattedQuoteResult"]["FormattedQuote"]
    keep = ["symbol", "name", "last", "change", "change_pct", "last_time", "volume", "previous_day_closing",
            "curmktstatus", "realTime", "expiration_date", "settlePrice", "settleDate", "code"]
    out({"label": "cnbc", "acao": r.headers.get("access-control-allow-origin"),
         "quotes": [{k: x.get(k) for k in keep} for x in q]})


if __name__ == "__main__":
    main()
