"""Third MCX probe: record the full set of responses the updated page will ask for (test fixtures, temporary)."""
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
MONTHS = ["X2026", "Z2026", "F2027", "G2027", "H2027", "J2027"]
TICKERS = ([f"NSEIX:NIFTY{m}" for m in MONTHS] + [f"NSE:NIFTY{m}" for m in MONTHS] + ["NSEIX:NIFTY1!", "NSE:NIFTY"]
           + ["ICEEUR:BRN1!"] + [f"ICEEUR:BRN{m}" for m in MONTHS] + ["NYMEX:CL1!"] + [f"NYMEX:CL{m}" for m in MONTHS]
           + ["FX_IDC:USDINR", "MCX:GOLD1!", "MCX:SILVER1!"] + [f"MCX:GOLD{m}" for m in MONTHS]
           + [f"MCX:SILVER{m}" for m in MONTHS])
PAGE_COLS = ["close", "change", "change_abs", "update_mode", "volume", "current_session", "expiration", "open_interest"]
CNBC = ("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols="
        "%40LCO.1%7C%40LCO.2%7C%40CL.1%7C%40CL.2%7CINR%3D&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1"
        "&output=json&events=1")
MC_GIFT = ("https://priceapi.moneycontrol.com/technicalCompanyData/globalMarket/"
           "getGlobalIndicesListingData?view=overview&deviceType=W")
MC_MCX = "https://priceapi.moneycontrol.com/pricefeed/mcx/commodityfutures/{}?expiry={}"


def out(obj):
    print(json.dumps(obj, ensure_ascii=False))
    sys.stdout.flush()


def main():
    out({"now_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), "epoch": int(time.time())})
    body = json.dumps({"symbols": {"tickers": TICKERS, "query": {"types": []}}, "columns": PAGE_COLS})
    r = requests.post(TV, data=body, headers={**H, "Content-Type": "text/plain;charset=UTF-8"}, timeout=20)
    out({"label": "tv page cols", "status": r.status_code, "acao": r.headers.get("access-control-allow-origin"),
         "cols": PAGE_COLS, "body": r.text})
    for label, url in [("cnbc", CNBC), ("mc gift", MC_GIFT)]:
        r = requests.get(url, headers=H, timeout=20)
        out({"label": label, "status": r.status_code, "acao": r.headers.get("access-control-allow-origin"),
             "body": r.text})
    for sym in ["GOLD", "SILVER"]:
        for exp in ["2026-12-04", "2027-02-05", "2027-03-05"]:
            r = requests.get(MC_MCX.format(sym, exp), headers=H, timeout=20)
            out({"label": f"mc mcx {sym} {exp}", "status": r.status_code,
                 "acao": r.headers.get("access-control-allow-origin"), "body": r.text})


if __name__ == "__main__":
    main()
