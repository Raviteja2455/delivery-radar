#!/usr/bin/env python3
"""Delivery Radar: nightly NSE delivery, volume and futures-OI tracker.

  python radar.py update                  fetch missing trading days from NSE, then rebuild docs/data.json
  python radar.py update --source-dir D   read the NSE files from folder D instead (offline testing)
  python radar.py build                   rebuild docs/data.json from the stored history only

Data comes from NSE's public end-of-day files: security-wise delivery (sec_bhavdata_full),
the F&O bhavcopy, index closes, bulk/block deals and the provisional FII/DII figures.
History is kept as one small JSON file per trading day under data/.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import sys
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = ROOT / "docs" / "data.json"
IST = ZoneInfo("Asia/Kolkata")

URLS = {
    "eq": "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d:%d%m%Y}.csv",
    "fo": "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip",
    "idx": "https://nsearchives.nseindia.com/content/indices/ind_close_all_{d:%d%m%Y}.csv",
    "n50": "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv",
    "bulk": "https://nsearchives.nseindia.com/content/equities/bulk.csv",
    "block": "https://nsearchives.nseindia.com/content/equities/block.csv",
    "fiidii": "https://www.nseindia.com/api/fiidiiTradeReact",
}
LOOKBACK = {"eq": 110, "fo": 45, "idx": 300}    # calendar days kept filled (first run backfills this)
KEEP_DAYS = {"eq": 200, "fo": 90, "idx": 420}   # day files older than this are deleted
DETAIL_DAYS = 40                                  # sessions of history shipped per stock
PAUSE = 0.6                                       # seconds between NSE requests
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept": "text/html,application/json,text/csv,*/*",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}
# sec_bhavdata_full columns kept, in this order, per stock per day
EQ_FIELDS = ("PREV_CLOSE", "OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE", "CLOSE_PRICE",
             "TTL_TRD_QNTY", "TURNOVER_LACS", "NO_OF_TRADES", "DELIV_QTY", "DELIV_PER")
EQ_KEYS = ("pc", "o", "h", "l", "c", "v", "tl", "nt", "dq", "dp")


# ----------------------------------------------------------------------------- small helpers
def jload(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def jsave(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def num(x):
    x = (x or "").strip().replace(",", "")
    if x in ("", "-", "NA", "N.A.", "nil"):
        return None
    try:
        v = float(x)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def pct(a, b):
    return (a / b - 1) * 100 if a is not None and b else None


def rnd(x, n=2):
    return None if x is None else round(x, n)


def whole(x):
    return None if x is None else int(round(x))


def parse_date(s):
    s = (s or "").strip()
    for f in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y", "%d-%B-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            pass
    return None


def csv_rows(text):
    """Yield dicts from an NSE CSV, tolerating the spaces NSE puts around names and values."""
    header = None
    for rec in csv.reader(io.StringIO(text)):
        if not rec or not any(c.strip() for c in rec):
            continue
        if header is None:
            header = [h.strip() for h in rec]
            continue
        yield {h: (rec[i].strip() if i < len(rec) else "") for i, h in enumerate(header)}


def weekdays(start, end):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def load_config():
    cfg = jload(ROOT / "config.json", {})
    extra = [str(s).strip().upper() for s in cfg.get("extra_symbols", []) if str(s).strip()]
    notes = {}
    for sym, n in (cfg.get("notes") or {}).items():
        if isinstance(n, dict) and n.get("text"):
            bias = n.get("bias", 0)
            notes[str(sym).strip().upper()] = {
                "bias": bias if bias in (-1, 0, 1) else 0,
                "text": str(n["text"]),
                "as_of": str(n.get("as_of", "")),
            }
    return {"extra_symbols": extra, "notes": notes}


# ----------------------------------------------------------------------------- NSE access
class Source:
    """Reads NSE files from the internet, or from a local folder when testing."""

    def __init__(self, folder=None):
        self.folder = Path(folder) if folder else None
        self._session = None

    def _http(self):
        if self._session is None:
            import requests
            s = requests.Session()
            s.headers.update(HEADERS)
            try:
                s.get("https://www.nseindia.com/", timeout=20)  # sets the cookies NSE's API wants
            except Exception:
                pass
            self._session = s
        return self._session

    def get(self, url, binary=False):
        """Return the file's text (or bytes), or None when NSE has no such file."""
        if self.folder:
            name = "fiidiiTradeReact.json" if url == URLS["fiidii"] else url.rsplit("/", 1)[-1]
            p = self.folder / name
            if not p.exists():
                return None
            return p.read_bytes() if binary else p.read_text(encoding="utf-8-sig", errors="replace")
        err = None
        for attempt in range(3):
            try:
                r = self._http().get(url, timeout=40)
                time.sleep(PAUSE)
                if r.status_code in (403, 404):  # NSE answers 403 or 404 for files it doesn't have
                    return None
                r.raise_for_status()
                if binary:
                    return r.content
                text = r.content.decode("utf-8-sig", errors="replace")
                return None if text.lstrip().startswith("<") else text  # an HTML error page, not data
            except Exception as e:
                err = e
                time.sleep(3 * (attempt + 1))
        raise RuntimeError(f"NSE request kept failing: {url} ({err})")


# ----------------------------------------------------------------------------- parsers
def parse_n50(text):
    out = []
    for r in csv_rows(text):
        sym = r.get("Symbol")
        if sym:
            out.append({"s": sym, "n": r.get("Company Name") or sym, "ind": r.get("Industry", "")})
    return out


def parse_eq(text, symbols):
    day, rows = None, {}
    for r in csv_rows(text):
        if r.get("SERIES") != "EQ" or r.get("SYMBOL") not in symbols:
            continue
        day = day or parse_date(r.get("DATE1"))
        rows[r["SYMBOL"]] = [num(r.get(k)) for k in EQ_FIELDS]
    return day, rows


def parse_fo(blob, symbols):
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        text = z.read(name).decode("utf-8-sig", errors="replace")
    by_sym, day = {}, None
    for r in csv_rows(text):
        if r.get("FinInstrmTp") != "STF" or r.get("TckrSymb") not in symbols:
            continue
        day = day or parse_date(r.get("TradDt"))
        by_sym.setdefault(r["TckrSymb"], []).append(r)
    out = {}
    for sym, contracts in by_sym.items():
        contracts.sort(key=lambda r: r.get("XpryDt", ""))
        trade_day = contracts[0].get("TradDt", "")
        expiring = [c for c in contracts if c.get("XpryDt") == trade_day]
        live = [c for c in contracts if c.get("XpryDt") != trade_day] or contracts
        near = live[0]
        out[sym] = {
            "oi": sum(num(c.get("OpnIntrst")) or 0 for c in live),
            "doi": sum(num(c.get("ChngInOpnIntrst")) or 0 for c in live),
            "fc": num(near.get("ClsPric")),
            "x": 1 if expiring else 0,  # expiry day: OI change is distorted by roll-over
        }
    return day, out


def parse_idx(text):
    names = {"nifty 50": "nifty", "india vix": "vix", "nifty bank": "bank"}
    day, out = None, {}
    for r in csv_rows(text):
        key = names.get((r.get("Index Name") or "").strip().lower())
        if not key:
            continue
        day = day or parse_date(r.get("Index Date"))
        out[key] = num(r.get("Closing Index Value"))
        out[key + "_chg"] = num(r.get("Change(%)"))
    return day, out


def parse_deals(text, kind, symbols):
    out = []
    for r in csv_rows(text):
        sym = r.get("Symbol")
        d = parse_date(r.get("Date"))
        if sym not in symbols or not d:
            continue
        price_key = next((k for k in r if k.lower().startswith("trade price")), None)
        out.append({
            "d": d.isoformat(), "s": sym, "k": kind,
            "cl": r.get("Client Name", ""),
            "bs": (r.get("Buy/Sell") or "").strip().upper(),
            "q": num(r.get("Quantity Traded")),
            "p": num(r.get(price_key)) if price_key else None,
        })
    return out


def parse_fiidii(text):
    data = json.loads(text)
    day, out = None, {}
    for r in data if isinstance(data, list) else []:
        cat = str(r.get("category", "")).upper()
        d = parse_date(r.get("date"))
        net = num(str(r.get("netValue", "")))
        if d is None or net is None:
            continue
        day = d
        if "FII" in cat or "FPI" in cat:
            out["fii"] = net
        elif "DII" in cat:
            out["dii"] = net
    return day, out


# ----------------------------------------------------------------------------- update
def update(src, today=None):
    now = datetime.now(IST)
    today = today or now.date()
    meta = jload(DATA / "meta.json", {})
    cfg = load_config()

    text = src.get(URLS["n50"])
    n50 = parse_n50(text) if text else []
    if len(n50) < 40:
        sys.exit("NSE did not send the Nifty 50 list (site down or blocking this server). Nothing was changed.")
    meta["nifty50"] = [x["s"] for x in n50]
    names = meta.get("names", {})
    for x in n50:
        names[x["s"]] = {"n": x["n"], "ind": x["ind"]}
    meta["names"] = names
    universe = sorted(set(meta["nifty50"]) | set(cfg["extra_symbols"]))
    uset = set(universe)

    missing = {k: set(v) for k, v in meta.get("missing", {}).items()}
    for k in ("eq", "fo", "idx"):
        missing.setdefault(k, set())
    fetched = {"eq": 0, "idx": 0, "fo": 0}

    for kind in ("eq", "idx", "fo"):  # eq first: it tells us which weekdays were holidays
        for d in weekdays(today - timedelta(days=LOOKBACK[kind]), today):
            iso = d.isoformat()
            if iso in missing[kind] or (kind != "eq" and iso in missing["eq"]):
                continue
            path = DATA / kind / f"{iso}.json"
            if path.exists():
                if kind != "eq" or uset <= set(jload(path, {}).get("u", [])):
                    continue  # already have it (eq files are re-fetched only when new symbols are added)
            blob = src.get(URLS[kind].format(d=d), binary=(kind == "fo"))
            if blob is None:
                if d < today - timedelta(days=3):  # NSE publishes the same evening; older gaps are holidays
                    missing[kind].add(iso)
                continue
            if kind == "eq":
                _, rows = parse_eq(blob, uset)
                if rows:
                    jsave(path, {"u": universe, "rows": rows})
            elif kind == "fo":
                _, rows = parse_fo(blob, uset)
                jsave(path, rows)
            else:
                _, rows = parse_idx(blob)
                if rows:
                    jsave(path, rows)
            fetched[kind] += 1

    deals = jload(DATA / "deals.json", [])
    seen = {(x["d"], x["s"], x["k"], x["cl"], x["bs"], x["q"], x["p"]) for x in deals}
    for kind in ("bulk", "block"):
        try:
            t = src.get(URLS[kind])
        except RuntimeError as e:
            print(f"{kind} deals unavailable: {e}")
            t = None
        for x in parse_deals(t, kind.upper(), uset) if t else []:
            key = (x["d"], x["s"], x["k"], x["cl"], x["bs"], x["q"], x["p"])
            if key not in seen:
                seen.add(key)
                deals.append(x)
    cut = (today - timedelta(days=KEEP_DAYS["eq"])).isoformat()
    jsave(DATA / "deals.json", sorted((x for x in deals if x["d"] >= cut), key=lambda x: (x["d"], x["s"])))

    flows = jload(DATA / "fiidii.json", {})
    try:
        t = src.get(URLS["fiidii"])
        if t:
            d, row = parse_fiidii(t)
            if d and row:
                flows[d.isoformat()] = row
    except Exception as e:  # NSE's API often refuses cloud servers; the app works without it
        print(f"FII/DII figures unavailable today: {e}")
    jsave(DATA / "fiidii.json", dict(sorted(flows.items())[-260:]))

    for kind, keep in KEEP_DAYS.items():
        cut = (today - timedelta(days=keep)).isoformat()
        for p in (DATA / kind).glob("*.json"):
            if p.stem < cut:
                p.unlink()
    oldest = (today - timedelta(days=KEEP_DAYS["idx"])).isoformat()
    meta["missing"] = {k: sorted(x for x in v if x >= oldest) for k, v in missing.items()}
    meta["last_update"] = now.isoformat(timespec="seconds")
    jsave(DATA / "meta.json", meta)
    print(f"New day files: {fetched}")
    build()


# ----------------------------------------------------------------------------- analytics
def adjusted_rows(series):
    """Turn [(date, raw fields)] into dicts, back-adjusting prices and quantities for splits/bonuses.

    NSE's PREV_CLOSE on an ex-date is already adjusted, so a jump between it and the previous
    day's close reveals the adjustment factor."""
    rows = [dict(zip(EQ_KEYS, raw), d=d) for d, raw in series]
    factor = 1.0
    for i in range(len(rows) - 1, -1, -1):
        r = rows[i]
        if factor != 1.0:
            for k in ("pc", "o", "h", "l", "c"):
                if r[k] is not None:
                    r[k] *= factor
            for k in ("v", "dq"):
                if r[k] is not None:
                    r[k] /= factor
        if i > 0:
            prev_close, prev_close_today = series[i - 1][1][4], series[i][1][0]
            if prev_close and prev_close_today and abs(prev_close_today / prev_close - 1) > 0.02:
                factor *= prev_close_today / prev_close
    return rows


def buildup(chg, oic, expiry):
    if expiry:
        return "Expiry day"
    if chg is None or oic is None:
        return None
    if abs(oic) < 0.5 or chg == 0:
        return "Neutral"
    if chg > 0:
        return "Long buildup" if oic > 0 else "Short covering"
    return "Short buildup" if oic > 0 else "Long unwinding"


def oi_change(f):
    base = f["oi"] - f["doi"]
    return f["doi"] / base * 100 if base > 0 else None


SIGNALS = [
    "Delivery % above its 20-day average",
    "More accumulation than distribution days (last 10)",
    "Futures long buildup",
    "Close above the 20-day average price",
    "Close above the previous 10-day high (highest high)",
    "Delivery quantity at least 1.5x its 5-day average",
]


STOP_BUFFER = 0.0025   # stop sits 0.25% under the 5-session swing low
MIN_STOP_PCT = 1.0     # never plan a stop closer than 1% to the close


def stock_metrics(sym, rows, fo, deals, det_days, names, notes):
    n = len(rows)
    r = rows[-1]
    c, chg = r["c"], pct(r["c"], r["pc"])
    dp = [x["dp"] for x in rows]
    dq = [x["dq"] for x in rows]
    vol = [x["v"] for x in rows]
    cl = [x["c"] for x in rows]
    hi = [x["h"] for x in rows]
    lo = [x["l"] for x in rows]
    ats = [x["tl"] * 1e5 / x["nt"] if x["tl"] and x["nt"] else None for x in rows]

    dp_prior = avg(dp[-21:-1])
    dpd = dp[-1] - dp_prior if dp[-1] is not None and dp_prior is not None else None
    dq_prior = avg(dq[-6:-1])
    dqx = dq[-1] / dq_prior if dq[-1] is not None and dq_prior else None
    v_prior = avg(vol[-21:-1])
    vx = vol[-1] / v_prior if vol[-1] is not None and v_prior else None
    ats_prior = avg(ats[-21:-1])
    atsx = ats[-1] / ats_prior if ats[-1] is not None and ats_prior else None
    sma20 = avg(cl[-20:]) if n >= 20 else None
    prev10 = [x for x in hi[-11:-1] if x is not None]
    hi10 = max(prev10) if n >= 11 and prev10 else None  # highest high of the previous 10 sessions

    lows5 = [x for x in lo[-5:] if x is not None]
    lo5 = min(lows5) if lows5 else None  # swing low of the last 5 sessions, today included
    stop = stopp = None
    if lo5 is not None and c:
        stop = lo5 * (1 - STOP_BUFFER)
        stopp = (c - stop) / c * 100
        if stopp < MIN_STOP_PCT:
            stop, stopp = c * (1 - MIN_STOP_PCT / 100), MIN_STOP_PCT

    acc = dist = 0  # high-delivery up days vs high-delivery down days over the last 10 sessions
    for i in range(max(5, n - 10), n):
        base = avg(dp[max(0, i - 20):i])
        ch = pct(rows[i]["c"], rows[i]["pc"])
        if base is None or dp[i] is None or not ch or dp[i] <= base:
            continue
        if ch > 0:
            acc += 1
        else:
            dist += 1

    asof = rows[-1]["d"]
    f = fo.get(asof, {}).get(sym)
    oi = oic = bu = None
    if f:
        oi, oic = f["oi"], oi_change(f)
        bu = buildup(chg, oic, f.get("x"))

    recent_from = rows[max(0, n - 10)]["d"]
    mine = [x for x in deals if x["s"] == sym and x["d"] >= recent_from and x["p"]]
    ref = mine[-1] if mine else None

    sig = [
        dpd is not None and dpd > 0,
        acc > dist,
        bu == "Long buildup",
        sma20 is not None and c is not None and c > sma20,
        hi10 is not None and c is not None and c > hi10,
        dqx is not None and dqx >= 1.5,
    ]

    pos = {x["d"]: i for i, x in enumerate(rows)}
    hist = {k: [] for k in ("c", "chg", "v", "dq", "dp", "dp5", "oi", "oic", "bu")}
    for d in det_days:
        i = pos.get(d)
        if i is None:
            for k in hist:
                hist[k].append(None)
            continue
        x = rows[i]
        ch = pct(x["c"], x["pc"])
        hist["c"].append(rnd(x["c"]))
        hist["chg"].append(rnd(ch))
        hist["v"].append(whole(x["v"]))
        hist["dq"].append(whole(x["dq"]))
        hist["dp"].append(rnd(x["dp"]))
        hist["dp5"].append(rnd(avg(dp[max(0, i - 4):i + 1])))
        ff = fo.get(d, {}).get(sym)
        o = oi_change(ff) if ff else None
        hist["oi"].append(whole(ff["oi"]) if ff else None)
        hist["oic"].append(rnd(o))
        hist["bu"].append(buildup(ch, o, ff.get("x")) if ff else None)

    nm = names.get(sym, {})
    return {
        "s": sym, "n": nm.get("n", sym), "ind": nm.get("ind", ""),
        "c": rnd(c), "chg": rnd(chg), "v": whole(vol[-1]), "to": rnd(r["tl"] / 100 if r["tl"] else None),
        "nt": whole(r["nt"]), "dq": whole(dq[-1]), "dp": rnd(dp[-1]),
        "dp5": rnd(avg(dp[-5:])), "dp10": rnd(avg(dp[-10:])), "dp20": rnd(avg(dp[-20:])),
        "dpp": rnd(dp_prior), "dpd": rnd(dpd), "dq5": whole(avg(dq[-5:])), "dqx": rnd(dqx),
        "v20": whole(v_prior), "vx": rnd(vx), "ats": whole(ats[-1]), "atsx": rnd(atsx),
        "sma20": rnd(sma20), "hi10": rnd(hi10), "acc": acc, "dist": dist,
        "oi": whole(oi), "oic": rnd(oic), "bu": bu,
        "deal": {"d": ref["d"], "k": ref["k"], "p": ref["p"], "held": bool(c is not None and c >= ref["p"])} if ref else None,
        "sig": [1 if s else 0 for s in sig], "score": sum(sig),
        # MTF entry ingredients: breakout on above-average delivery, futures long buildup, stop distance
        "lo5": rnd(lo5), "stop": rnd(stop), "stopp": rnd(stopp),
        "t1": 1 if sig[4] and sig[0] else 0, "t2": 1 if sig[2] else 0,
        "note": notes.get(sym),
        "h": hist,
    }


def market_summary(idx, flows, stocks, asof):
    days = sorted(d for d in idx if d <= asof)
    closes = [idx[d]["nifty"] for d in days if idx[d].get("nifty")]
    last = idx.get(asof) or (idx[days[-1]] if days else {})
    nifty, vix = last.get("nifty"), last.get("vix")
    dma50 = avg(closes[-50:]) if len(closes) >= 50 else None
    dma200 = avg(closes[-200:]) if len(closes) >= 200 else None
    fdays = sorted(d for d in flows if d <= asof)[-5:]
    fii5 = sum(flows[d].get("fii", 0) for d in fdays) if len(fdays) >= 3 else None
    dii5 = sum(flows[d].get("dii", 0) for d in fdays) if len(fdays) >= 3 else None

    reasons, red = [], False
    if fii5 is not None and fii5 < -10000:
        red = True
        reasons.append(f"FIIs sold ₹{abs(fii5):,.0f} cr over the last {len(fdays)} sessions")
    if vix is not None and vix > 18:
        red = True
        reasons.append(f"India VIX is {vix:.1f}, above 18")
    if dma50 is not None and nifty is not None and nifty < dma50:
        red = True
        reasons.append("Nifty is below its 50-day average")
    if red:
        regime = "red"
    else:
        green = (fii5 is not None and fii5 > 0 and dma50 is not None and nifty is not None
                 and nifty > dma50 and (dma200 is None or nifty > dma200))
        regime = "green" if green else "amber"
        if green:
            reasons.append("FIIs are net buyers and Nifty is above its 50- and 200-day averages")
        else:
            if fii5 is None:
                reasons.append("FII figures are not available yet")
            elif fii5 <= 0:
                reasons.append(f"FIIs are still net sellers (₹{abs(fii5):,.0f} cr over 5 sessions)")
            if dma50 is None:
                reasons.append("Not enough history yet for the 50-day average")
            if dma200 is not None and nifty is not None and nifty < dma200:
                reasons.append("Nifty is below its 200-day average")

    up = [s for s in stocks if (s["chg"] or 0) > 0]
    down = [s for s in stocks if (s["chg"] or 0) < 0]
    return {
        "nifty": rnd(nifty), "nifty_chg": rnd(last.get("nifty_chg")), "vix": rnd(vix),
        "vix_chg": rnd(last.get("vix_chg")), "dma50": rnd(dma50), "dma200": rnd(dma200),
        "fii": rnd(flows.get(asof, {}).get("fii")), "dii": rnd(flows.get(asof, {}).get("dii")),
        "fii5": rnd(fii5), "dii5": rnd(dii5), "flow_days": len(fdays),
        "regime": regime, "reasons": reasons,
        "adv": len(up), "dec": len(down),
        "dp": rnd(avg([s["dp"] for s in stocks])), "dpp": rnd(avg([s["dpp"] for s in stocks])),
        "score4": sum(1 for s in stocks if s["score"] >= 4),
        "long": sum(1 for s in stocks if s["bu"] == "Long buildup"),
        "short": sum(1 for s in stocks if s["bu"] == "Short buildup"),
    }


def build():
    meta = jload(DATA / "meta.json", {})
    cfg = load_config()
    names = meta.get("names", {})
    universe = sorted(set(meta.get("nifty50", [])) | set(cfg["extra_symbols"]))
    eq = {p.stem: jload(p, {}).get("rows", {}) for p in sorted((DATA / "eq").glob("*.json"))}
    days = sorted(d for d in eq if eq[d])
    if not days:
        sys.exit("No delivery data stored yet; run `python radar.py update` first.")
    fo = {p.stem: jload(p, {}) for p in (DATA / "fo").glob("*.json")}
    idx = {p.stem: jload(p, {}) for p in (DATA / "idx").glob("*.json")}
    deals = jload(DATA / "deals.json", [])
    flows = jload(DATA / "fiidii.json", {})
    asof = days[-1]
    det_days = days[-DETAIL_DAYS:]

    stocks = []
    for sym in universe:
        series = [(d, eq[d][sym]) for d in days if sym in eq[d]]
        if not series or series[-1][0] != asof:
            continue  # did not trade on the latest day
        stocks.append(stock_metrics(sym, adjusted_rows(series), fo, deals, det_days, names, cfg["notes"]))

    out = {
        "asof": asof,
        "generated": datetime.now(IST).isoformat(timespec="minutes"),
        "last_update": meta.get("last_update"),
        "dates": det_days,
        "signals": SIGNALS,
        "market": market_summary(idx, flows, stocks, asof),
        "stocks": stocks,
        "deals": [x for x in deals if x["d"] >= det_days[0]][-80:],
        "have": {"fo": asof in fo, "idx": asof in idx, "flows": asof in flows},
        "mtf": {"stop_buffer_pct": STOP_BUFFER * 100, "min_stop_pct": MIN_STOP_PCT},
        "extra": [s for s in cfg["extra_symbols"] if s not in set(meta.get("nifty50", []))],
    }
    jsave(OUT, out)
    print(f"Built {OUT.relative_to(ROOT)}: {len(stocks)} stocks, data as of {asof}")


def main():
    ap = argparse.ArgumentParser(description="Delivery Radar")
    ap.add_argument("command", choices=["update", "build"])
    ap.add_argument("--source-dir", help="read NSE files from this folder instead of nseindia.com")
    ap.add_argument("--today", help="treat this date (YYYY-MM-DD) as today; for testing")
    a = ap.parse_args()
    if a.command == "build":
        build()
    else:
        today = date.fromisoformat(a.today) if a.today else None
        update(Source(a.source_dir), today)


if __name__ == "__main__":
    main()
