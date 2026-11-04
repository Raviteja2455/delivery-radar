"""Research probe (temporary): today's NSE large deals, participant-wise F&O data, HDFC Bank/Reliance files,
live ADR quotes and Nifty history. Output goes to out.jsonl, committed back to this branch."""
import csv
import io
import json
import sys
import time
import zipfile
from datetime import date, timedelta

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/129.0.0.0 Safari/537.36")
H = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-IN,en;q=0.9"}
TODAY = date(2026, 11, 4)
SYMS = {"HDFCBANK", "RELIANCE"}


def out(obj):
    print(json.dumps(obj, ensure_ascii=False))
    sys.stdout.flush()


def get(url, sess=None, binary=False, tries=3, **kw):
    s = sess or requests
    last = None
    for i in range(tries):
        try:
            r = s.get(url, headers={**H, **kw.pop("headers", {})}, timeout=30, **kw)
            if r.status_code == 200:
                return r.content if binary else r.text
            last = f"HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001
            last = repr(e)[:200]
        time.sleep(1.5 * (i + 1))
    raise RuntimeError(last)


def weekdays(a, b):
    d = a
    while d <= b:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def main():
    out({"now_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())})

    # 1. Today's bulk and block deal files (named, published after the close).
    for kind in ("bulk", "block"):
        try:
            t = get(f"https://nsearchives.nseindia.com/content/equities/{kind}.csv")
            lines = t.splitlines()
            out({"label": f"nse {kind}.csv", "rows": len(lines) - 1, "header": lines[0] if lines else None,
                 "first": lines[1:4], "ours": [l for l in lines if any(s in l for s in SYMS)][:30]})
        except Exception as e:  # noqa: BLE001
            out({"label": f"nse {kind}.csv", "error": str(e)})

    # 2. NSE's large-deal snapshot and live block-deal feed (need cookies first).
    sess = requests.Session()
    try:
        get("https://www.nseindia.com/", sess)
        get("https://www.nseindia.com/market-data/large-deals", sess)
        for path in ("snapshot-capital-market-largedeal", "block-deal"):
            try:
                t = get(f"https://www.nseindia.com/api/{path}", sess,
                        headers={"Referer": "https://www.nseindia.com/market-data/large-deals"})
                j = json.loads(t)
                if isinstance(j, dict):
                    summ = {}
                    for k, v in j.items():
                        if isinstance(v, list):
                            summ[k] = {"n": len(v), "ours": [x for x in v if any(s in json.dumps(x) for s in SYMS)][:20],
                                       "first": v[:2]}
                        else:
                            summ[k] = v
                    out({"label": "nse api " + path, "data": summ})
                else:
                    out({"label": "nse api " + path, "data": j[:40] if isinstance(j, list) else j})
            except Exception as e:  # noqa: BLE001
                out({"label": "nse api " + path, "error": str(e)[:300]})
    except Exception as e:  # noqa: BLE001
        out({"label": "nse cookies", "error": str(e)[:300]})

    # 3. Participant-wise open interest and volume (category totals only: Client, DII, FII, Pro).
    for d in weekdays(TODAY - timedelta(days=24), TODAY):
        for kind in ("oi", "vol"):
            url = f"https://nsearchives.nseindia.com/content/nsccl/fao_participant_{kind}_{d:%d%m%Y}.csv"
            try:
                out({"label": f"participant {kind}", "d": d.isoformat(), "text": get(url, tries=1)[:3000]})
            except Exception as e:  # noqa: BLE001
                out({"label": f"participant {kind}", "d": d.isoformat(), "error": str(e)[:120]})

    # 4. Today's delivery file rows for HDFC Bank and Reliance.
    try:
        t = get(f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{TODAY:%d%m%Y}.csv")
        lines = t.splitlines()
        out({"label": "sec_bhavdata today", "header": lines[0],
             "ours": [l for l in lines if l.split(",")[0].strip() in SYMS and ",EQ" in l.replace(" ", "")]})
    except Exception as e:  # noqa: BLE001
        out({"label": "sec_bhavdata today", "error": str(e)[:200]})

    # 5. Today's F&O bhavcopy: HDFC Bank and Nifty contracts traded, in lots.
    try:
        blob = get(f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{TODAY:%Y%m%d}_F_0000.csv.zip",
                   binary=True)
        z = zipfile.ZipFile(io.BytesIO(blob))
        rows = list(csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode("utf-8", "replace"))))
        out({"label": "fo bhavcopy cols", "cols": list(rows[0].keys()) if rows else None, "n": len(rows)})
        agg = {}
        for r in rows:
            sym = (r.get("TckrSymb") or "").strip()
            if sym not in ("HDFCBANK", "NIFTY", "BANKNIFTY", "RELIANCE"):
                continue
            tp = (r.get("FinInstrmTp") or "").strip()
            lot = float(r.get("NewBrdLotQty") or 0) or None
            vol = float(r.get("TtlTradgVol") or 0)
            oi = float(r.get("OpnIntrst") or 0)
            doi = float(r.get("ChngInOpnIntrst") or 0)
            val = float(r.get("TtlTrfVal") or 0)
            k = f"{sym} {tp}"
            a = agg.setdefault(k, {"lot": lot, "vol_shares": 0, "oi_shares": 0, "doi_shares": 0, "value_cr": 0,
                                   "contracts": 0})
            a["vol_shares"] += vol
            a["oi_shares"] += oi
            a["doi_shares"] += doi
            a["value_cr"] += val / 1e7
            a["contracts"] += 1
        for k, a in agg.items():
            if a["lot"]:
                a["vol_lots"] = round(a["vol_shares"] / a["lot"])
                a["oi_lots"] = round(a["oi_shares"] / a["lot"])
                a["doi_lots"] = round(a["doi_shares"] / a["lot"])
        out({"label": "fo today", "agg": agg,
             "hdfc_fut": [{k: r.get(k) for k in ("XpryDt", "ClsPric", "TtlTradgVol", "OpnIntrst", "ChngInOpnIntrst",
                                                  "NewBrdLotQty")} for r in rows
                          if (r.get("TckrSymb") or "").strip() == "HDFCBANK" and r.get("FinInstrmTp") == "STF"]})
    except Exception as e:  # noqa: BLE001
        out({"label": "fo today", "error": str(e)[:300]})

    # 6. FII/DII provisional figures for today.
    try:
        t = get("https://www.nseindia.com/api/fiidiiTradeReact", sess,
                headers={"Referer": "https://www.nseindia.com/reports/fii-dii"})
        out({"label": "fiidii", "data": json.loads(t)})
    except Exception as e:  # noqa: BLE001
        out({"label": "fiidii", "error": str(e)[:200]})

    # 7. Live quotes: HDFC Bank ADR against the NSE share, peers, India ETF.
    tickers = ["NYSE:HDB", "NSE:HDFCBANK", "NYSE:IBN", "NSE:ICICIBANK", "NYSE:INFY", "NSE:INFY", "NSE:RELIANCE",
               "NSE:NIFTY", "NSE:BANKNIFTY", "FX_IDC:USDINR", "AMEX:INDA", "NSEIX:NIFTY1!", "NSE:NIFTY1!"]
    cols = ["close", "change", "change_abs", "volume", "update_mode", "current_session", "Perf.W", "Perf.1M",
            "high", "low", "open", "average_volume_10d_calc"]
    try:
        body = json.dumps({"symbols": {"tickers": tickers, "query": {"types": []}}, "columns": cols})
        r = requests.post("https://scanner.tradingview.com/global/scan", data=body,
                          headers={**H, "Content-Type": "text/plain;charset=UTF-8",
                                   "Origin": "https://raviteja2455.github.io"}, timeout=20)
        out({"label": "tv quotes", "cols": cols, "body": r.text[:8000]})
    except Exception as e:  # noqa: BLE001
        out({"label": "tv quotes", "error": str(e)[:200]})

    # 8. Nifty daily history for base rates.
    for name, url in [("yahoo nsei", "https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI?range=15y&interval=1d"),
                      ("yahoo nsei q2", "https://query2.finance.yahoo.com/v8/finance/chart/%5ENSEI?range=15y&interval=1d")]:
        try:
            j = json.loads(get(url, tries=2))
            res = j["chart"]["result"][0]
            ts = res["timestamp"]
            q = res["indicators"]["quote"][0]
            out({"label": name, "n": len(ts), "t": ts, "close": q["close"], "high": q["high"], "low": q["low"]})
            break
        except Exception as e:  # noqa: BLE001
            out({"label": name, "error": str(e)[:200]})
    out({"end_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())})


if __name__ == "__main__":
    main()
