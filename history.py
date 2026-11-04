"""Download about two years of NSE end-of-day history for a backtest (temporary).

For every weekday from 2024-07-08 (when NSE's F&O bhavcopy moved to the UDiFF layout) to the last date given:
  sec_bhavdata_full  -> OHLC, volume, delivery for the Nifty 50 (+ extras)
  F&O bhavcopy       -> stock-futures OI across expiries, near-month close, expiry flags; Nifty options expiry flag
  ind_close_all      -> Nifty 50, Nifty Bank, India VIX closes
  fao_participant_oi -> FII / DII / Pro / Client index-futures and index-option positions
Writes hist.json (compact) and hist_log.txt. Missing files (holidays) are skipped.
"""
import concurrent.futures as cf
import csv
import io
import json
import re
import sys
import threading
import time
import zipfile
from datetime import date, datetime, timedelta

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")
H = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-IN,en;q=0.9", "Referer": "https://www.nseindia.com/"}
URLS = {
    "eq": "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d:%d%m%Y}.csv",
    "fo": "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip",
    "idx": "https://nsearchives.nseindia.com/content/indices/ind_close_all_{d:%d%m%Y}.csv",
    "part": "https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{d:%d%m%Y}.csv",
}
START = date(2024, 7, 8)
END = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
LOG = open("hist_log.txt", "w")
lock = threading.Lock()


def log(*a):
    with lock:
        print(*a, file=LOG, flush=True)


local = threading.local()


def sess():
    if not hasattr(local, "s"):
        s = requests.Session()
        s.headers.update(H)
        local.s = s
    return local.s


def fetch(url, binary=False):
    for attempt in range(4):
        try:
            r = sess().get(url, timeout=60)
            if r.status_code in (403, 404):
                return None
            r.raise_for_status()
            if binary:
                return r.content
            t = r.content.decode("utf-8-sig", errors="replace")
            return None if t.lstrip().startswith("<") else t
        except Exception as e:  # noqa: BLE001
            time.sleep(2 + 3 * attempt)
            err = e
    log("FAIL", url, repr(err)[:120])
    return None


def rows(text):
    header = None
    for rec in csv.reader(io.StringIO(text)):
        if not rec or not any(c.strip() for c in rec):
            continue
        if header is None:
            header = [h.strip() for h in rec]
            continue
        yield {h: (rec[i].strip() if i < len(rec) else "") for i, h in enumerate(header)}


def num(x):
    try:
        x = (x or "").replace(",", "").strip()
        return float(x) if x not in ("", "-", "NA") else None
    except ValueError:
        return None


def day(d, symbols):
    out = {"d": d.isoformat()}
    t = fetch(URLS["eq"].format(d=d))
    if t:
        eq, fdate = {}, None
        for r in rows(t):
            if r.get("SERIES") == "EQ" and r.get("SYMBOL") in symbols:
                fdate = fdate or r.get("DATE1")
                eq[r["SYMBOL"]] = [num(r.get(k)) for k in ("PREV_CLOSE", "OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE",
                                                           "CLOSE_PRICE", "TTL_TRD_QNTY", "TURNOVER_LACS", "NO_OF_TRADES",
                                                           "DELIV_QTY", "DELIV_PER")]
        try:
            fd = datetime.strptime(fdate, "%d-%b-%Y").date() if fdate else None
        except ValueError:
            fd = None
        if eq and (fd is None or fd == d):
            out["eq"] = eq
        elif eq:
            log("eq date mismatch", d, fdate)
    if "eq" not in out:
        return out  # not a trading day (or no file): skip the rest
    b = fetch(URLS["fo"].format(d=d), binary=True)
    if b:
        try:
            with zipfile.ZipFile(io.BytesIO(b)) as z:
                name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
                text = z.read(name).decode("utf-8-sig", errors="replace")
            fo, nx = {}, 0
            for r in rows(text):
                tp, sym = r.get("FinInstrmTp"), r.get("TckrSymb")
                if tp == "IDO" and sym == "NIFTY" and r.get("XpryDt") == r.get("TradDt"):
                    nx = 1
                if tp != "STF" or sym not in symbols:
                    continue
                fo.setdefault(sym, []).append((r.get("XpryDt", ""), num(r.get("OpnIntrst")), num(r.get("ChngInOpnIntrst")),
                                               num(r.get("ClsPric")), r.get("TradDt", "")))
            agg = {}
            for sym, cs in fo.items():
                cs.sort()
                td = cs[0][4]
                expiring = [c for c in cs if c[0] == td]
                live = [c for c in cs if c[0] != td] or cs
                agg[sym] = [sum(c[1] or 0 for c in live), sum(c[2] or 0 for c in live), live[0][3], 1 if expiring else 0]
            out["fo"], out["nx"] = agg, nx
        except Exception as e:  # noqa: BLE001
            log("fo parse", d, repr(e)[:100])
    t = fetch(URLS["idx"].format(d=d))
    if t:
        names = {"nifty 50": "nifty", "india vix": "vix", "nifty bank": "bank"}
        ix = {}
        for r in rows(t):
            k = names.get((r.get("Index Name") or "").strip().lower())
            if k:
                ix[k] = num(r.get("Closing Index Value"))
                ix[k + "_h"] = num(r.get("High Index Value"))
                ix[k + "_l"] = num(r.get("Low Index Value"))
        out["idx"] = ix
    t = fetch(URLS["part"].format(d=d))
    if t:
        lines = [ln for ln in t.splitlines() if ln.strip()]
        st = next((i for i, ln in enumerate(lines) if ln.lstrip('"').lower().startswith("client type")), None)
        if st is not None:
            p = {}
            for r in rows("\n".join(lines[st:])):
                k = r.get("Client Type")
                if k in ("FII", "DII", "Pro", "Client"):
                    p[k] = [num(r.get(c)) for c in ("Future Index Long", "Future Index Short", "Option Index Call Long",
                                                    "Option Index Call Short", "Option Index Put Long",
                                                    "Option Index Put Short", "Future Stock Long", "Future Stock Short")]
            out["part"] = p
    return out


def main():
    n50 = fetch("https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv")
    symbols = {r["Symbol"] for r in rows(n50)} if n50 else set()
    # Large caps that were in the Nifty 50 for part of the period, so the test isn't only today's winners.
    symbols |= {"BPCL", "BRITANNIA", "DIVISLAB", "HEROMOTOCO", "INDUSINDBK", "LTIM", "TATAMOTORS", "UPL", "NESTLEIND"}
    log("symbols", len(symbols), sorted(symbols))
    days = []
    d = START
    while d <= END:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    t0 = time.time()
    results = []
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        for i, res in enumerate(ex.map(lambda x: day(x, symbols), days)):
            results.append(res)
            if i % 50 == 0:
                log(f"{i}/{len(days)} {res['d']} eq={'eq' in res} fo={'fo' in res} part={'part' in res} t={time.time()-t0:.0f}s")
    sessions = [r for r in results if "eq" in r]
    json.dump({"symbols": sorted(symbols), "sessions": sessions}, open("hist.json", "w"), separators=(",", ":"))
    log("done", len(sessions), "sessions", f"{time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
