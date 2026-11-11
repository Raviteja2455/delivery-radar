#!/usr/bin/env python3
"""Delivery Radar: nightly NSE delivery, volume and futures-OI tracker.

  python radar.py update                  fetch missing trading days from NSE, then rebuild docs/data.json
  python radar.py update --source-dir D   read the NSE files from folder D instead (offline testing)
  python radar.py build                   rebuild docs/data.json from the stored history only

Data comes from NSE's public end-of-day files: security-wise delivery (sec_bhavdata_full),
the F&O bhavcopy, index closes, bulk/block deals, participant-wise F&O open interest and the
provisional FII/DII figures. History is kept as one small JSON file per trading day under data/.

Every night the script also ranks all Nifty 100 stocks for a three-month swing pick, names one
pick every ten days and tracks how each pick did; the pick log is data/picks.json.

It also runs a research screen over the Nifty 500 (large, mid and small caps) for 6-month to
2-year investments: quality checks, a fair value from four methods, and a buy only at a discount
to it. Fundamentals come from TradingView's screener; the research log is data/research.json.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import sys
import time
import zipfile
from bisect import bisect_left, bisect_right
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
    "n100": "https://nsearchives.nseindia.com/content/indices/ind_nifty100list.csv",
    "nn50": "https://nsearchives.nseindia.com/content/indices/ind_niftynext50list.csv",
    "n100_alt": "https://www.niftyindices.com/IndexConstituent/ind_nifty100list.csv",
    "n500": "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv",
    "mid150": "https://nsearchives.nseindia.com/content/indices/ind_niftymidcap150list.csv",
    "small250": "https://nsearchives.nseindia.com/content/indices/ind_niftysmallcap250list.csv",
    "tv": "https://scanner.tradingview.com/india/scan",
    "bulk": "https://nsearchives.nseindia.com/content/equities/bulk.csv",
    "block": "https://nsearchives.nseindia.com/content/equities/block.csv",
    "fiidii": "https://www.nseindia.com/api/fiidiiTradeReact",
    "part": "https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{d:%d%m%Y}.csv",
}
# Delivery history runs about nine months: the pick rule needs three months to warm up, and the
# replay of past picks needs three more for each pick's result to be final.
LOOKBACK = {"eq": 300, "fo": 45, "idx": 300, "part": 45}    # calendar days kept filled (first run backfills this)
KEEP_DAYS = {"eq": 420, "fo": 90, "idx": 420, "part": 200}  # day files older than this are deleted
DEALS_KEEP = 200   # calendar days of bulk and block deals kept
RECENT_DAYS = 5    # a failed download this recent stops the run; an older one only pauses the backfill
FO_FLAG_DAYS = 21  # stored F&O days this recent are fetched again once if they lack the Nifty-expiry flag
FII_DAYS = 6       # sessions shown in the app's FII table
# participant-wise OI columns kept, in this order, per category per day
PART_FIELDS = ("Future Index Long", "Future Index Short", "Option Index Call Long", "Option Index Call Short",
               "Option Index Put Long", "Option Index Put Short", "Future Stock Long", "Future Stock Short")
PART_TYPES = ("FII", "DII", "Pro", "Client")
DETAIL_DAYS = 40                                  # sessions of history shipped per stock
PAUSE = 0.6                                       # seconds between NSE requests
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept": "text/html,application/json,text/csv,*/*",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}
# Fundamentals asked of TradingView's screener for the research screen: one request for the whole
# Nifty 500. A column the server does not know is dropped and the request repeated, so a renamed
# field costs that one reading instead of the whole screen.
TV_COLS = (
    "close", "currency", "fundamental_currency_code", "market_cap_basic", "sector", "industry",
    "earnings_per_share_diluted_ttm", "earnings_per_share_basic_ttm", "price_earnings_ttm",
    "book_value_per_share_fq", "book_value_per_share_fy", "price_book_fq",
    "return_on_equity", "return_on_equity_fy", "return_on_assets", "return_on_assets_fy",
    "return_on_invested_capital", "return_on_invested_capital_fy",
    "debt_to_equity", "debt_to_equity_fy", "interst_cover_ttm", "interst_cover_fy", "net_debt_to_ebitda_fy",
    "total_revenue_yoy_growth_ttm", "total_revenue_yoy_growth_fy", "total_revenue_cagr_5y",
    "earnings_per_share_diluted_yoy_growth_ttm", "earnings_per_share_diluted_yoy_growth_fy",
    "earnings_per_share_basic_cagr_5y", "net_income_cagr_5y", "net_income_yoy_growth_ttm",
    "sustainable_growth_rate_ttm", "sustainable_growth_rate_fy",
    "net_income_ttm", "net_income_fy", "free_cash_flow_ttm", "free_cash_flow_fy",
    "cash_f_operating_activities_ttm", "cash_f_operating_activities_fy",
    "operating_margin_ttm", "net_margin_ttm",
    "dividends_yield_current", "dividend_payout_ratio_ttm", "dividend_payout_ratio_fy",
    "piotroski_f_score_ttm", "piotroski_f_score_fy", "altman_z_score_ttm", "altman_z_score_fy",
    "price_target_average", "price_target_median", "price_target_high", "price_target_low",
    "recommendation_total", "recommendation_mark", "earnings_per_share_forecast_next_fy",
    "SMA50", "SMA200", "price_52_week_high", "price_52_week_low", "Perf.3M", "Perf.6M", "Perf.Y",
    "average_volume_30d_calc", "float_shares_percent_current",
    "earnings_release_date", "earnings_release_next_date", "fiscal_period_end_current",
)
TV_CHUNK = 250

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


# Three-month swing pick: one stock every `every_days` calendar days, aiming for `target_pct` within
# `window_days`, with a closing-basis stop `stop_pct` under the entry. config.json's "pick" block overrides these.
PICK_DEFAULTS = {"every_days": 10, "target_pct": 5.0, "window_days": 91, "stop_pct": 8.0}


# Research portfolio: 6-month to 2-year investments from the Nifty 500, bought only at a discount to fair
# value. All percentages; config.json's "research" block overrides any of them.
RESEARCH_DEFAULTS = {
    "pot": 100000, "max_positions": 5, "every_days": 14, "max_sector": 2, "max_small": 2,
    "hurdle_large": 15.0, "hurdle_mid": 20.0, "hurdle_small": 25.0,   # discount to fair value needed to buy
    "stop_large": 15.0, "stop_mid": 18.0, "stop_small": 22.0,         # closing-basis stop under the buy price
    "coe_large": 12.0, "coe_mid": 13.0, "coe_small": 14.5,            # return demanded: bond yield + equity + size premium
    "terminal_growth": 5.0, "growth_cap": 18.0,
    "medium_days": 365, "long_days": 730,
}


def load_config():
    cfg = jload(ROOT / "config.json", {})
    research = dict(RESEARCH_DEFAULTS)
    for k, v in (cfg.get("research") or {}).items():
        if k in research and isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            research[k] = int(v) if isinstance(RESEARCH_DEFAULTS[k], int) else float(v)
    pick = dict(PICK_DEFAULTS)
    for k, v in (cfg.get("pick") or {}).items():
        if k in pick and isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            pick[k] = int(v) if k in ("every_days", "window_days") else float(v)
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
    return {"extra_symbols": extra, "notes": notes, "pick": pick, "research": research}


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

    def post_json(self, url, payload):
        """POST a JSON query (TradingView's screener). Returns (HTTP status, parsed body or None)."""
        if self.folder:
            # Offline: tv_scan.json holds {"unknown": [columns to refuse], "rows": {ticker: {column: value}}}.
            doc = jload(self.folder / "tv_scan.json", None)
            if doc is None:
                return 404, None
            bad = [c for c in payload["columns"] if c in doc.get("unknown", [])]
            if bad:
                return 400, {"error": f'Unknown field "{bad[0]}"', "data": None}
            data = [{"s": t, "d": [doc["rows"][t].get(c) for c in payload["columns"]]}
                    for t in payload["symbols"]["tickers"] if t in doc["rows"]]
            return 200, {"totalCount": len(data), "data": data}
        import requests
        err = None
        for attempt in range(3):
            try:
                r = requests.post(url, data=json.dumps(payload), timeout=40, headers={
                    "User-Agent": HEADERS["User-Agent"], "Content-Type": "text/plain;charset=UTF-8",
                    "Origin": "https://in.tradingview.com", "Referer": "https://in.tradingview.com/"})
                time.sleep(PAUSE)
                try:
                    body = r.json()
                except ValueError:
                    body = None
                if r.status_code in (200, 400):
                    return r.status_code, body
                err = f"HTTP {r.status_code}"
            except Exception as e:
                err = e
            time.sleep(3 * (attempt + 1))
        raise RuntimeError(f"screener request kept failing: {url} ({err})")


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
    by_sym, day, nifty_expiry = {}, None, 0
    for r in csv_rows(text):
        if (r.get("FinInstrmTp") == "IDO" and r.get("TckrSymb") == "NIFTY"
                and r.get("XpryDt") and r.get("XpryDt") == r.get("TradDt")):
            nifty_expiry = 1
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
    # Nifty options expired today (weekly expiry), so the day's option open interest lost the expiring series.
    out["_nx"] = nifty_expiry
    return day, out


def parse_part(text):
    """Participant-wise open interest: contracts held long and short by FIIs, DIIs, Pros and Clients."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    start = next((i for i, ln in enumerate(lines) if ln.lstrip('"').lower().startswith("client type")), None)
    if start is None:
        return None, {}
    m = re.search(r"as on\s+([A-Za-z]{3,9}\s+\d{1,2},\s*\d{4})", " ".join(lines[:start]))
    day = None
    if m:
        for f in ("%b %d, %Y", "%B %d, %Y", "%b %d,%Y"):
            try:
                day = datetime.strptime(m.group(1), f).date()
                break
            except ValueError:
                pass
    out = {}
    for r in csv_rows("\n".join(lines[start:])):
        kind = r.get("Client Type")
        vals = [num(r.get(k)) for k in PART_FIELDS]
        if kind in PART_TYPES and all(v is not None for v in vals):
            out[kind] = [int(v) for v in vals]
    return day, out


def parse_idx(text):
    names = {"nifty 50": "nifty", "india vix": "vix", "nifty bank": "bank", "nifty 500": "n500"}
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
def fetch_n100(src, n50):
    """The Nifty 100 list: NSE's own file, else Nifty 50 + Nifty Next 50, else the copy on niftyindices.com.

    Returns [] when none of them answers with a list that looks right (about 100 names, the Nifty 50 among them)."""
    have = {x["s"] for x in n50}

    def good(rows):
        syms = {x["s"] for x in rows}
        return 90 <= len(syms) <= 110 and len(have & syms) >= 40

    def read(key):
        try:
            text = src.get(URLS[key])
        except RuntimeError as e:
            print(f"{key} list unavailable: {e}")
            return []
        return parse_n50(text) if text else []

    rows = read("n100")
    if good(rows):
        return rows
    nxt = read("nn50")
    if nxt:
        seen, both = set(), []
        for x in n50 + nxt:
            if x["s"] not in seen:
                seen.add(x["s"])
                both.append(x)
        if good(both):
            return both
    rows = read("n100_alt")
    return rows if good(rows) else []


def fetch_n500(src, meta, names):
    """The research universe: the Nifty 500, each stock tagged large (Nifty 100), mid (Nifty Midcap 150)
    or small (Nifty Smallcap 250). Keeps the saved list when NSE does not answer."""
    def read(key):
        try:
            text = src.get(URLS[key])
        except RuntimeError as e:
            print(f"{key} list unavailable: {e}")
            return []
        return parse_n50(text) if text else []

    rows = read("n500")
    least = 100 if src.folder else 450  # the offline sample has a short list
    if not least <= len({x["s"] for x in rows}) <= 520:
        print("NSE did not send the Nifty 500 list; " + ("using the list saved earlier." if meta.get("nifty500")
              else "the research screen covers the Nifty 100 only."))
        return
    mid, small = {x["s"] for x in read("mid150")}, {x["s"] for x in read("small250")}
    large = set(meta.get("nifty100", []))
    cap = {}
    for x in rows:
        s = x["s"]
        names.setdefault(s, {"n": x["n"], "ind": x["ind"]})
        cap[s] = "L" if s in large else "M" if s in mid else "S" if s in small else None
    meta["nifty500"] = [x["s"] for x in rows]
    meta["cap"] = cap  # None where the mid and small lists did not arrive; market value decides those


def tv_tickers(sym):
    """The screener's names for an NSE symbol. It writes M&M as M_M in some places and M&M in others,
    so both are asked for; the one it doesn't know is ignored."""
    sym = sym.upper()
    return list(dict.fromkeys(["NSE:" + re.sub(r"[^A-Z0-9]", "_", sym), "NSE:" + sym]))


def fetch_fundamentals(src, symbols, today):
    """One fundamentals snapshot for `symbols` from TradingView's screener, saved as data/fund.json.

    Keeps the previous snapshot when the screener does not answer; the app then shows its date."""
    back = {t: s for s in symbols for t in tv_tickers(s)}
    tickers = sorted(back)
    cols, dropped, rows = list(TV_COLS), [], {}
    try:
        for _ in range(len(TV_COLS)):  # each pass either completes or drops one column the screener refuses
            rows, unknown = {}, None
            for k in range(0, len(tickers), TV_CHUNK):
                query = {"symbols": {"tickers": tickers[k:k + TV_CHUNK], "query": {"types": []}}, "columns": cols}
                status, body = src.post_json(URLS["tv"], query)
                if status == 200 and body and isinstance(body.get("data"), list):
                    for x in body["data"]:
                        if x.get("s") in back and isinstance(x.get("d"), list) and len(x["d"]) == len(cols):
                            rows[back[x["s"]]] = x["d"]
                    continue
                m = re.search(r'Unknown field "([^"]+)"', str((body or {}).get("error", "")))
                if status == 400 and m and m.group(1) in cols and len(cols) > 10:
                    unknown = m.group(1)
                    break
                raise RuntimeError(f"unexpected screener answer (HTTP {status}): {str(body)[:200]}")
            if unknown is None:
                break
            cols.remove(unknown)
            dropped.append(unknown)
    except RuntimeError as e:
        print(f"Fundamentals unavailable tonight: {e}")
        return
    save_fundamentals(rows, cols, dropped, symbols, today)


def save_fundamentals(rows, cols, dropped, symbols, today):
    if len(rows) < 0.5 * len(symbols):
        print(f"Fundamentals: only {len(rows)} of {len(symbols)} stocks answered, so the earlier snapshot is kept.")
        return
    if dropped:
        print(f"Fundamentals: the screener no longer has {', '.join(dropped)}")
    missing = sorted(set(symbols) - set(rows))
    if missing:
        print(f"Fundamentals: no row for {len(missing)} stocks: {', '.join(missing[:25])}{' …' if len(missing) > 25 else ''}")
    jsave(DATA / "fund.json", {"d": today.isoformat(), "cols": cols, "rows": rows})
    print(f"Fundamentals: {len(rows)} of {len(symbols)} stocks, {len(cols)} readings each")


def tracked_symbols(doc, today, rules):
    """Symbols of live picks still inside their three-month window."""
    cut = (today - timedelta(days=rules["window_days"] + 30)).isoformat()
    return {p["s"] for p in doc.get("picks", []) if p.get("d", "") >= cut and p.get("s")}


def holiday_copies(eq):
    """Stored days whose delivery file repeats the previous stored day's exactly.

    On some holidays NSE answers that day's address with the previous session's file instead of
    "not found". A real session never repeats every stock's prices and volumes, so an exact
    repeat is a holiday, not a trading day."""
    days = sorted(d for d in eq if eq[d])
    return {d for prev, d in zip(days, days[1:]) if eq[d] == eq[prev]}


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
    n100 = fetch_n100(src, n50)
    if n100:
        meta["nifty100"] = [x["s"] for x in n100]
        for x in n100:
            names[x["s"]] = {"n": x["n"], "ind": x["ind"]}
    elif meta.get("nifty100"):
        print("NSE did not send the Nifty 100 list today; using the list saved earlier.")
    else:
        print("NSE did not send the Nifty 100 list; tonight covers the Nifty 50 only and no pick is made.")
    fetch_n500(src, meta, names)
    meta["names"] = names
    # Stocks with a live pick stay in the downloads even if they leave the index, so the pick can be tracked.
    tracked = tracked_symbols(jload(DATA / "picks.json", {}), today, cfg["pick"])
    tracked |= {p["s"] for p in jload(DATA / "research.json", {}).get("picks", []) if p.get("s") and not p.get("done")}
    research = set(meta.get("nifty500", [])) or set(meta.get("nifty100", []))
    universe = sorted(set(meta["nifty50"]) | set(meta.get("nifty100", [])) | research | set(cfg["extra_symbols"]) | tracked)
    uset = set(universe)
    fetch_fundamentals(src, sorted(research | tracked), today)

    missing = {k: set(v) for k, v in meta.get("missing", {}).items()}
    for k in ("eq", "fo", "idx", "part"):
        missing.setdefault(k, set())
    fetched = {"eq": 0, "idx": 0, "fo": 0, "part": 0}

    # Earlier versions saved those holiday copies as trading days; drop any still stored.
    stored = {p.stem: jload(p, {}).get("rows", {}) for p in (DATA / "eq").glob("*.json")}
    for iso in sorted(holiday_copies(stored)):
        (DATA / "eq" / f"{iso}.json").unlink()
        missing["eq"].add(iso)
        print(f"Removed eq {iso}: it repeated the previous session's file, so it was a holiday")

    for kind in ("eq", "idx", "fo", "part"):  # eq first: it tells us which weekdays were holidays
        # Newest day first, so tonight's files are in before any long backfill starts.
        for d in reversed(list(weekdays(today - timedelta(days=LOOKBACK[kind]), today))):
            iso = d.isoformat()
            if iso in missing[kind] or (kind != "eq" and iso in missing["eq"]):
                continue
            path = DATA / kind / f"{iso}.json"
            if path.exists():
                stored = jload(path, {})
                if kind == "eq" and not uset <= set(stored.get("u", [])):
                    pass  # fetch again: symbols were added since this day was saved
                elif kind == "fo" and "_nx" not in stored and d >= today - timedelta(days=FO_FLAG_DAYS):
                    pass  # fetch again once to record whether Nifty options expired that day
                elif kind == "fo" and not uset <= set(stored.get("_u", [])):
                    pass  # fetch again: symbols were added since this day was saved
                else:
                    continue
            try:
                blob = src.get(URLS[kind].format(d=d), binary=(kind == "fo"))
            except RuntimeError as e:
                if d >= today - timedelta(days=RECENT_DAYS):
                    raise
                # NSE sometimes stops answering part-way through a long backfill. Keep what arrived;
                # the next run carries on from here.
                print(f"{kind}: stopped back-filling at {iso}; the next run continues ({e})")
                break
            if blob is None:
                if d < today - timedelta(days=3):  # NSE publishes the same evening; older gaps are holidays
                    missing[kind].add(iso)
                continue
            if kind == "eq":
                day, rows = parse_eq(blob, uset)
            elif kind == "fo":
                day, rows = parse_fo(blob, uset)
            elif kind == "part":
                day, rows = parse_part(blob)
            else:
                day, rows = parse_idx(blob)
            if day and day != d:
                # A holiday answered with the previous session's file: saving it would count the
                # holiday as a trading day and repeat that session in every average.
                print(f"{kind} {iso}: NSE sent the file for {day.isoformat()}, so {iso} was not a trading day")
                if d < today - timedelta(days=3):
                    missing[kind].add(iso)
                continue
            if kind == "eq":
                if rows:
                    jsave(path, {"u": universe, "rows": rows})
            elif kind == "fo":
                rows["_u"] = universe
                jsave(path, rows)
            elif rows:
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
    cut = (today - timedelta(days=DEALS_KEEP)).isoformat()
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
    build(make_picks=True)


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
        "dpp": rnd(dp_prior), "dpd": rnd(dpd), "dq5": whole(avg(dq[-5:])),
        "dqp": whole(dq_prior), "dqx": rnd(dqx),  # dqx is today's delivered qty ÷ dqp (previous 5 sessions)
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
        "regime": regime, "reasons": reasons,
        "adv": len(up), "dec": len(down),
        "dp": rnd(avg([s["dp"] for s in stocks])), "dpp": rnd(avg([s["dpp"] for s in stocks])),
        "score4": sum(1 for s in stocks if s["score"] >= 4),
        "long": sum(1 for s in stocks if s["bu"] == "Long buildup"),
        "short": sum(1 for s in stocks if s["bu"] == "Short buildup"),
    }


def fii_net(row):
    """FII net contracts (long minus short) from a stored participant row."""
    fl, fs, cl, cs, pl, ps = row[:6]
    return {"fut": fl - fs, "calls": cl - cs, "puts": pl - ps, "fl": fl, "fs": fs,
            "long": rnd(fl / (fl + fs) * 100, 1) if fl + fs else None}


def kfmt(x):
    """Contracts in thousands for the summary sentence: 16,778 -> 16.8k, 1,04,657 -> 105k."""
    a = abs(x) / 1000
    return f"{a:.0f}k" if a >= 100 else f"{a:.1f}k"


def crore(x):
    """Rupee crores with Indian digit grouping: 72840 -> 72,840; 123456 -> 1,23,456."""
    s = str(int(round(abs(x))))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = ",".join(re.findall(r"\d{1,2}", head[::-1]))[::-1] if len(head) > 2 else head
        s = head + "," + tail
    return s


def fii_activity(days, flows, part, fo, asof):
    """FII activity by session: net cash bought or sold, and how their index futures, calls and puts changed.

    Changes compare each session's participant-wise open interest with the previous session's, so a day
    without the previous day's file has no change. On Nifty's weekly expiry the day's option open interest
    loses the expiring series, which makes that day's call and put changes look larger than the trades were."""
    sess = [d for d in days if d <= asof]
    rows = []
    for i, d in enumerate(sess):
        cur = part.get(d, {}).get("FII")
        prev = part.get(sess[i - 1], {}).get("FII") if i else None
        cash = flows.get(d, {}).get("fii")
        if cur is None and cash is None:
            continue
        row = {"d": d, "cash": rnd(cash, 0), "fut": None, "calls": None, "puts": None,
               "dl": None, "ds": None, "x": int(bool(fo.get(d, {}).get("_nx")))}
        if cur and prev:
            a, b = fii_net(cur), fii_net(prev)
            row.update({"fut": a["fut"] - b["fut"], "calls": a["calls"] - b["calls"], "puts": a["puts"] - b["puts"],
                        "dl": a["fl"] - b["fl"], "ds": a["fs"] - b["fs"]})
        rows.append(row)
    pos_day = next((d for d in reversed(sess) if part.get(d, {}).get("FII")), None)
    pos = None
    if pos_day:
        n = fii_net(part[pos_day]["FII"])
        pos = {"d": pos_day, "fut": n["fut"], "long": n["long"], "calls": n["calls"], "puts": n["puts"]}
    streak = 0
    if sess and flows.get(sess[-1], {}).get("fii"):
        sign = flows[sess[-1]]["fii"] > 0
        for d in reversed(sess):
            v = flows.get(d, {}).get("fii")
            if v is None or (v > 0) != sign or v == 0:
                break
            streak += 1
    shown = rows[-FII_DAYS:]
    view = fii_view(shown[-1], streak, pos) if shown and shown[-1]["d"] == asof else None
    for r in shown:
        r.pop("dl"), r.pop("ds")
    return {"days": shown, "pos": pos, "view": view}


def fii_view(r, streak, pos):
    """One-line verdict on the latest session: cash, index futures and index options, then positioning."""
    legs, said = [], []
    if r["cash"] is not None:
        act = "bought" if r["cash"] > 0 else "sold"
        run = f" ({streak}{'th' if 10 <= streak % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(streak % 10, 'th')} straight day)" if streak >= 2 else ""
        said.append(f"{act} ₹{crore(r['cash'])} cr{run}")
        legs.append(1 if r["cash"] > 0 else -1 if r["cash"] < 0 else 0)
    if r["fut"] is not None:
        dl, ds = r["dl"], r["ds"]
        if r["fut"] > 0:
            said.append(f"covered {kfmt(ds)} futures shorts" if -ds >= dl else f"added {kfmt(dl)} futures longs")
        elif r["fut"] < 0:
            said.append(f"added {kfmt(ds)} futures shorts" if ds >= -dl else f"cut {kfmt(dl)} futures longs")
        else:
            said.append("left index futures unchanged")
        legs.append((r["fut"] > 0) - (r["fut"] < 0))
    opt = None
    if r["calls"] is not None and not r["x"]:
        opt = r["calls"] - r["puts"]  # more net calls, or fewer net puts, is the bullish side
        legs.append((opt > 0) - (opt < 0))
    if not legs:
        return None
    # All legs agree (at least two of them): a full verdict; otherwise the majority sets the lean.
    score, n = sum(legs), len(legs)
    verdict = ("bullish" if n >= 2 and score == n else "bearish" if n >= 2 and score == -n else
               "lean-bullish" if score > 0 else "lean-bearish" if score < 0 else "neutral")
    text = "FIIs " + (", ".join(said[:-1]) + " and " + said[-1] if len(said) > 1 else said[0]) if said else ""
    if opt is not None:
        lean = "bullish" if opt > 0 else "bearish" if opt < 0 else "neutral"
        opt_text = f"options lean {lean}" + (f" by {kfmt(opt)} contracts" if opt else "")
        text = f"{text}; {opt_text}" if text else opt_text[0].upper() + opt_text[1:]
    elif r["x"] and r["calls"] is not None:
        text += "; options skipped (weekly expiry)"
    text += "."
    if pos and pos["long"] is not None:
        lg = pos["long"]
        if lg < 20:
            # FIIs hold heavy index shorts most of the time (largely hedges); in 2024–26 a reading this low followed by
            # Nifty reclaiming its 20-day average did not lead to above-normal gains, so the text stays descriptive.
            text += f" Futures are {100 - lg:.0f}% short, which is common for FIIs and not a rally signal by itself."
        elif lg > 80:
            text += f" Futures are {lg:.0f}% long, unusually long for FIIs."
        elif lg < 40:
            text += f" Futures lean short ({100 - lg:.0f}% short)."
        elif lg > 60:
            text += f" Futures lean long ({lg:.0f}% long)."
        else:
            text += f" Futures are balanced ({lg:.0f}% long)."
    return {"verdict": verdict, "text": text}


# ----------------------------------------------------------------------------- three-month swing pick
# One stock every ten days from the Nifty 100, aiming for +5% inside three months. The rule looks for a
# stock already in an uptrend that funds are taking delivery of, and avoids one that has just run.
# It reads only prices and delivery, so it can be replayed over the stored history.
PICK_HISTORY = 63          # sessions of history a stock needs before it can be ranked (about three months)
PICK_COVERAGE = 0.8        # share of the universe that must be rankable before a pick is made
PICK_MAX_EXT = 8.0         # gate: not more than this % above the 20-day average, or up this much in 5 sessions
PICK_PARTS = (             # reading, weight in the 0-100 score, label
    ("r63", 30, "3-month return"),
    ("r21", 15, "1-month return"),
    ("dl", 25, "Delivery % last 10 sessions vs the 50 before"),
    ("net", 15, "Accumulation minus distribution days (last 20)"),
    ("near", 15, "Distance from the 3-month high"),
)


def pick_features(rows, i):
    """Trend, momentum and delivery readings for one stock at session i, or None without enough history."""
    if i is None or i < PICK_HISTORY:
        return None
    win = rows[i - PICK_HISTORY:i + 1]  # 64 sessions, the pick day last
    cl = [x["c"] for x in win]
    if any(v is None or v <= 0 for v in cl):
        return None
    dp = [x["dp"] for x in win]
    c = cl[-1]
    sma20, sma50, sma50_then = avg(cl[-20:]), avg(cl[-50:]), avg(cl[-60:-10])
    dp10, dp_base = avg(dp[-10:]), avg(dp[-60:-10])
    acc = dist = 0  # up days and down days on above-average delivery, last 20 sessions
    for j in range(len(win) - 20, len(win)):
        base = avg(dp[j - 20:j])
        ch = pct(win[j]["c"], win[j]["pc"])
        if base is None or dp[j] is None or not ch or dp[j] <= base:
            continue
        if ch > 0:
            acc += 1
        else:
            dist += 1
    hi63 = max([x["h"] for x in win if x["h"] is not None] + [c])
    f = {
        "c": c, "r63": pct(c, cl[0]), "r21": pct(c, cl[-22]), "r5": pct(c, cl[-6]),
        "dl": (dp10 / dp_base - 1) * 100 if dp10 and dp_base else None,
        "dp10": dp10, "dpb": dp_base, "acc": acc, "dist": dist, "net": acc - dist,
        "near": pct(c, hi63), "s50": sma50, "up": 1 if sma50 > sma50_then else 0, "ext": pct(c, sma20),
    }
    # The gates: above a rising 50-day average, and not stretched.
    f["ok"] = 1 if (c > sma50 and f["up"] and f["ext"] <= PICK_MAX_EXT and f["r5"] <= PICK_MAX_EXT) else 0
    return f


def pick_scores(feats):
    """Add a 0-100 score to each stock's readings: its percentile among the ranked stocks on each
    reading, weighted. Returns the symbols, best first."""
    syms = sorted(feats)
    n = len(syms)
    for s in syms:
        feats[s]["p"] = []
    for key, _, _ in PICK_PARTS:
        vals = {s: (feats[s][key] if feats[s][key] is not None else -math.inf) for s in syms}
        ranked = sorted(vals.values())
        for s in syms:
            below = bisect_left(ranked, vals[s])
            ties = bisect_right(ranked, vals[s]) - below - 1
            feats[s]["p"].append((below + ties / 2) / (n - 1) * 100 if n > 1 else 50.0)
    for s in syms:
        feats[s]["sc"] = sum(w * q for (_, w, _), q in zip(PICK_PARTS, feats[s]["p"])) / 100
    return sorted(syms, key=lambda s: (-feats[s]["sc"], s))


def pick_candidates(adj, pos, symbols, day):
    """Readings and scores for every rankable stock on `day`: ({symbol: readings}, symbols best first)."""
    feats = {}
    for s in symbols:
        f = pick_features(adj[s], pos[s].get(day)) if s in adj else None
        if f:
            feats[s] = f
    return feats, pick_scores(feats) if feats else []


def pick_choose(feats, order, day, recent, notes):
    """The best-scoring stock that passes the gates, was not picked within the window, and has no
    negative institutional note dated on or before `day`."""
    for s in order:
        note = notes.get(s)
        barred = note and note["bias"] == -1 and (not note["as_of"] or note["as_of"] <= day)
        if feats[s]["ok"] and s not in recent and not barred:
            return s
    return None


def pick_why(f):
    """The pick's readings as stored and shown: value and percentile for each scored part."""
    return {"sc": rnd(f["sc"], 1), "v": [rnd(f[k], 2) for k, _, _ in PICK_PARTS], "p": [whole(q) for q in f["p"]],
            "acc": f["acc"], "dist": f["dist"], "dp10": rnd(f["dp10"], 1), "dpb": rnd(f["dpb"], 1),
            "s50": rnd(f["s50"]), "ext": rnd(f["ext"], 1), "r5": rnd(f["r5"], 1)}


def plus_days(iso, n):
    return (date.fromisoformat(iso) + timedelta(days=n)).isoformat()


def pick_outcome(rows, i, rules, asof, nifty_on):
    """How a pick made at session i did. Bought at the next session's open; sold at the target the
    first time the day's high reaches it; out at the close on the first close at or below the stop;
    otherwise held to the last session inside the window."""
    out = {"st": "new", "c": rnd(rows[i]["c"]), "ed": None, "e": None, "t": None, "sl": None, "dl": None,
           "last": rnd(rows[i]["c"]), "ld": rows[i]["d"], "ret": None, "hold": None, "peak": None, "low": None,
           "hd": None, "xd": None, "days": None, "nif": None, "vs": None}
    if i + 1 >= len(rows):
        return out  # the entry session has not traded yet
    first = rows[i + 1]
    entry = first["o"] or first["c"]
    if not entry:
        return out
    ed, dl = first["d"], plus_days(first["d"], rules["window_days"])
    target, stop = entry * (1 + rules["target_pct"] / 100), entry * (1 - rules["stop_pct"] / 100)
    peak = low = 0.0
    hit = stopped = None
    last, ld = entry, ed
    for x in rows[i + 1:]:
        if x["d"] > dl or x["c"] is None:
            break
        hi, lo = x["h"] or x["c"], x["l"] or x["c"]
        peak, low = max(peak, pct(hi, entry)), min(low, pct(lo, entry))
        last, ld = x["c"], x["d"]
        if hit is None:
            if hi >= target:
                hit = x["d"]
            elif x["c"] <= stop:
                stopped = x["d"]
                break
    held = pct(last, entry)
    if hit:
        st, ret, end = "target", rules["target_pct"], hit
    elif stopped:
        st, ret, end = "stopped", held, stopped
    elif asof >= dl:
        st, ret, end = "timeup", held, ld
    else:
        st, ret, end = "open", held, ld
    n0, n1 = nifty_on(rows[i]["d"]), nifty_on(end)
    nif = pct(n1, n0) if n0 and n1 else None
    out.update({"st": st, "ed": ed, "e": rnd(entry), "t": rnd(target), "sl": rnd(stop), "dl": dl,
                "last": rnd(last), "ld": ld, "ret": rnd(ret), "hold": rnd(held), "peak": rnd(peak), "low": rnd(low),
                "hd": hit, "xd": end if st in ("stopped", "timeup") else None,
                "days": (date.fromisoformat(end) - date.fromisoformat(ed)).days,
                "nif": rnd(nif), "vs": rnd(ret - nif) if nif is not None else None})
    return out


CLOSED = ("target", "stopped", "timeup")


def pick_stats(items, base):
    """Summary of a set of picks, with `base`: every ranked stock bought on the same dates under the same exits."""
    done = [x for x in items if x["st"] in CLOSED]
    live = [x for x in items if x["st"] == "open"]
    hits = [x for x in done if x["st"] == "target"]
    bdone = [x for x in base if x["st"] in CLOSED]
    return {
        "n": len(items), "closed": len(done), "target": len(hits),
        "stopped": sum(1 for x in done if x["st"] == "stopped"), "timeup": sum(1 for x in done if x["st"] == "timeup"),
        "open": len(live), "new": sum(1 for x in items if x["st"] == "new"),
        "hit": rnd(len(hits) / len(done) * 100, 1) if done else None,
        "avg": rnd(avg([x["ret"] for x in done])), "vs": rnd(avg([x["vs"] for x in done])),
        "days": rnd(avg([x["days"] for x in hits]), 0), "open_avg": rnd(avg([x["ret"] for x in live])),
        "base_n": len(bdone), "base_hit": rnd(sum(1 for x in bdone if x["st"] == "target") / len(bdone) * 100, 1) if bdone else None,
        "base_avg": rnd(avg([x["ret"] for x in bdone])),
    }


def build_picks(adj, days, idx, meta, cfg, names, asof, make_picks=True):
    """Make tonight's pick if one is due, replay the rule over the stored history, and score both.

    Returns the app's "picks" block and each ranked stock's readings for tonight. Live picks are kept
    in data/picks.json with their latest result, so they outlast the day files they were scored from."""
    rules = cfg["pick"]
    n100 = meta.get("nifty100") or []
    pool = sorted(set(n100) & set(adj))
    pos = {s: {x["d"]: i for i, x in enumerate(rows)} for s, rows in adj.items()}
    idays = sorted(d for d in idx if idx[d].get("nifty"))

    def nifty_on(d):  # Nifty close on d, or on the last session before it
        k = bisect_right(idays, d)
        return idx[idays[k - 1]]["nifty"] if k else None

    def enough(feats):
        return len(n100) >= 90 and len(feats) >= PICK_COVERAGE * len(n100)

    def item(d, s, why, res, src, r):
        return {"d": d, "s": s, "n": names.get(s, {}).get("n", s), "src": src, "why": why,
                "rules": {k: r[k] for k in ("target_pct", "stop_pct", "window_days")}, **res}

    doc = jload(DATA / "picks.json", {})
    live = [p for p in doc.get("picks", []) if p.get("d") and p.get("s")]
    feats, order = pick_candidates(adj, pos, pool, asof)
    ready = enough(feats)

    # Tonight's pick, when one is due.
    last_d = max((p["d"] for p in live), default=None)
    due = plus_days(last_d, rules["every_days"]) if last_d else asof
    note = None
    if not ready:
        note = ("The Nifty 100 list or its three months of history isn't complete yet, so no pick is made. "
                "It fills in over the next nightly runs.")
    elif asof >= due and make_picks:
        cut = plus_days(asof, -rules["window_days"])
        s = pick_choose(feats, order, asof, {p["s"] for p in live if p["d"] >= cut}, cfg["notes"])
        if s:
            live.append({"d": asof, "s": s, "why": pick_why(feats[s]), "rules": dict(rules)})
            due = plus_days(asof, rules["every_days"])
        else:
            note = "A pick is due, but no Nifty 100 stock passes the trend checks tonight. The rule looks again every night."

    out, base = [], {"live": [], "bt": []}

    def everyone(day, r, group):  # the comparison: every ranked stock bought on the same day, same exits
        for s in pool:
            i = pos[s].get(day)
            if i is not None and i >= PICK_HISTORY:
                base[group].append(pick_outcome(adj[s], i, r, asof, nifty_on))

    for p in live:
        r = {**rules, **(p.get("rules") or {})}
        i = pos.get(p["s"], {}).get(p["d"])
        if i is not None:
            p["res"] = pick_outcome(adj[p["s"]], i, r, asof, nifty_on)
            everyone(p["d"], r, "live")
        if p.get("res"):  # older than the stored history: keep the last result worked out
            out.append(item(p["d"], p["s"], p.get("why"), p["res"], "live", r))
    jsave(DATA / "picks.json", {"picks": sorted(live, key=lambda p: p["d"])})

    # Replay: the same rule on the same ten-day grid, counted back from the first live pick.
    anchor = min((p["d"] for p in live), default=asof)
    grid, g = [], plus_days(anchor, -rules["every_days"])
    while days and g >= days[0]:
        grid.append(g)
        g = plus_days(g, -rules["every_days"])
    grid.reverse()
    past = []
    for k, g in enumerate(grid):
        end = grid[k + 1] if k + 1 < len(grid) else anchor
        for d in (x for x in days if g <= x < end):
            f, o = pick_candidates(adj, pos, pool, d)
            if not enough(f):
                continue
            cut = plus_days(d, -rules["window_days"])
            s = pick_choose(f, o, d, {q["s"] for q in past if q["d"] >= cut}, cfg["notes"])
            if s:
                past.append({"d": d, "s": s})
                out.append(item(d, s, pick_why(f[s]), pick_outcome(adj[s], pos[s][d], rules, asof, nifty_on), "bt", rules))
                everyone(d, rules, "bt")
                break

    out.sort(key=lambda x: (x["d"], x["src"] == "live"), reverse=True)
    block = {
        "rules": rules, "ready": ready, "note": note, "due": due,
        "parts": [[k, w, label] for k, w, label in PICK_PARTS],
        "max_ext": PICK_MAX_EXT, "ranked": len(feats), "passing": sum(1 for s in feats if feats[s]["ok"]),
        "top": [s for s in order if feats[s]["ok"]][:5],
        "list": out,
        "stats": {g: pick_stats([x for x in out if x["src"] == g], base[g]) for g in ("live", "bt")},
        "from": days[0] if days else None,
    }
    tonight = {s: {**pick_why(feats[s]), "ok": feats[s]["ok"], "up": feats[s]["up"], "rank": order.index(s) + 1} for s in feats}
    return block, tonight


# ----------------------------------------------------------------------------- research screen
# A fund manager's routine, written as fixed rules. 1) Quality first: only profitable, well-financed,
# growing businesses. 2) Fair value from four independent methods; the middle of them is the estimate.
# 3) Buy only at a discount to it, larger for smaller companies. 4) Never buy a falling stock.
# 5) Small equal positions, spread across sectors. 6) Sell at the target, at the stop, when the
# business stops passing the checks, or when time is up.
CAPS = {"L": "large", "M": "mid", "S": "small"}
RESEARCH_MIN = {                 # entry checks
    "roe": 15.0, "roe_fin": 13.0,          # return on equity, %
    "de": 1.0, "de_small": 0.6,            # debt to equity (non-financials)
    "icov": 3.0,                           # operating profit covers interest this many times
    "growth": 8.0,                         # long-run sales growth, % a year
    "pio": 5,                              # Piotroski F-score, 0-9 (non-financials)
    "turnover_cr": 5.0,                    # median daily turnover, ₹ crore
    "lenses": 3,                           # fair-value methods that must be available
    "analysts": 5,                         # analysts needed before their target counts
}
RESEARCH_HOLD = {"roe": 10.0, "de": 1.5, "pio": 3}   # a holding that breaks any of these is sold
LONG_TERM = {"roe": 18.0, "growth": 12.0, "de": 0.5, "pio": 6}  # compounders get the 1-2 year horizon
PE_CAP, LENS_CAP = 35.0, 2.0     # no method may use a P/E above 35 or put fair value above twice the price
RESEARCH_PARTS = (               # reading, weight in the 0-100 score, label
    ("up", 35, "Discount to fair value"),
    ("roe", 12, "Return on equity"),
    ("pio", 10, "Financial strength (Piotroski)"),
    ("cash", 8, "Cash conversion (return on assets for lenders)"),
    ("g", 10, "Long-run growth"),
    ("eps_g", 10, "Earnings growth, last 12 months"),
    ("p6m", 8, "6-month return"),
    ("dl", 7, "Delivery % last 10 sessions vs the 50 before"),
)


def fund_rows(doc):
    """The stored screener snapshot as {symbol: readings}, using each reading's latest-period value and
    falling back to the last full year where the latest is missing."""
    cols = doc.get("cols") or []
    out = {}
    for sym, vals in (doc.get("rows") or {}).items():
        r = dict(zip(cols, vals))

        def first(*keys):
            for k in keys:
                v = r.get(k)
                if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
                    return float(v)
            return None

        out[sym] = {
            "px": first("close"), "cur": r.get("fundamental_currency_code") or r.get("currency"),
            "mcap": first("market_cap_basic"), "sector": r.get("sector") or "", "industry": r.get("industry") or "",
            "eps": first("earnings_per_share_diluted_ttm", "earnings_per_share_basic_ttm"),
            "bvps": first("book_value_per_share_fq", "book_value_per_share_fy"),
            "roe": first("return_on_equity", "return_on_equity_fy"),
            "roa": first("return_on_assets", "return_on_assets_fy"),
            "de": first("debt_to_equity", "debt_to_equity_fy"),
            "icov": first("interst_cover_ttm", "interst_cover_fy"),
            "rev_g": first("total_revenue_yoy_growth_ttm", "total_revenue_yoy_growth_fy"),
            "rev_c5": first("total_revenue_cagr_5y"),
            "eps_g": first("earnings_per_share_diluted_yoy_growth_ttm", "earnings_per_share_diluted_yoy_growth_fy",
                           "net_income_yoy_growth_ttm"),
            "eps_c5": first("earnings_per_share_basic_cagr_5y", "net_income_cagr_5y"),
            "sgr": first("sustainable_growth_rate_ttm", "sustainable_growth_rate_fy"),
            "ni": first("net_income_ttm", "net_income_fy"),
            "fcf": first("free_cash_flow_ttm", "free_cash_flow_fy"),
            "cfo": first("cash_f_operating_activities_ttm", "cash_f_operating_activities_fy"),
            "dy": first("dividends_yield_current"),
            "pio": first("piotroski_f_score_ttm", "piotroski_f_score_fy"),
            "eps_f": first("earnings_per_share_forecast_next_fy"),
            "tgt": first("price_target_median", "price_target_average"),
            "tgt_n": first("recommendation_total"),
            "sma200": first("SMA200"), "p6m": first("Perf.6M"),
            "next": first("earnings_release_next_date"),
        }
    return out


def dcf_value(eps, roe, g1, r, g2):
    """Value per share of the cash a shareholder can take out: five years growing at g1, five years
    fading to g2, then g2 for ever, discounted at r (all in %). Each year's payout is what is left
    after reinvesting g/ROE of the earnings, which is what that growth costs. The long-run return on
    equity is held to 18% at most, because competition erodes exceptional returns."""
    roe, g1, r, g2 = roe / 100, g1 / 100, r / 100, g2 / 100
    value, e = 0.0, eps
    for t in range(1, 11):
        g = g1 if t <= 5 else g1 + (g2 - g1) * (t - 5) / 5
        e *= 1 + g
        value += e * max(0.0, 1 - g / roe) / (1 + r) ** t
    last = e * (1 + g2) * max(0.0, 1 - g2 / min(roe, 0.18)) / (r - g2)
    return value + last / (1 + r) ** 10


def research_growth(f, cap, fin=False):
    """The growth rate the valuation may assume, % a year: the lower of five-year sales and earnings
    growth, pulled half-way down to the last twelve months' sales growth when that is slower,
    never negative and never above the cap. Without five-year figures the last year stands in, capped at 12%.
    A lender's growth is also held to what its retained profit can fund (return on equity x share retained),
    because lending more needs more capital."""
    long_run = [x for x in (f["rev_c5"], f["eps_c5"]) if x is not None]
    if long_run:
        g = min(long_run)
        if f["rev_g"] is not None and f["rev_g"] < g:
            g = (g + f["rev_g"]) / 2
    else:
        recent = [x for x in (f["rev_g"], f["eps_g"]) if x is not None]
        if not recent:
            return None
        g, cap = min(recent), min(cap, 12.0)
    if fin and f["sgr"] is not None:
        g = min(g, f["sgr"])
    return max(0.0, min(g, cap))


def normal_eps(f, g):
    """Earnings per share a valuation may rely on: the last twelve months', but no more than last
    year's grown at the long-run rate, and no more than analysts expect for next year.

    Refiners, metals and other cyclicals look cheapest, with their best return on equity, at the top of
    their cycle. Capping a boom year this way is the through-the-cycle adjustment a fund manager makes."""
    eps = f["eps"]
    if g is not None and f["eps_g"] is not None and f["eps_g"] > -90:
        eps = min(eps, f["eps"] / (1 + f["eps_g"] / 100) * (1 + g / 100))
    if f["eps_f"] is not None and f["eps_f"] > 0 and (f["tgt_n"] or 0) >= RESEARCH_MIN["analysts"]:
        eps = min(eps, f["eps_f"])
    return eps


def research_assess(sym, f, c, cap, fin, peers_pe, R):
    """Run one stock through the valuation: growth, normalised earnings, the four fair-value methods,
    the blend, and the buy-below price. Returns None when the basics (price, earnings, return on
    equity) are missing."""
    if not c or f["eps"] is None or f["eps"] <= 0 or f["roe"] is None:
        return None
    key = {"L": "large", "M": "mid", "S": "small"}[cap]
    r, hurdle = R["coe_" + key], R["hurdle_" + key]
    g = research_growth(f, R["growth_cap"], fin)
    eps = normal_eps(f, g)
    roe = f["roe"] * eps / f["eps"]  # return on equity on the same normalised earnings
    if eps <= 0 or roe <= R["terminal_growth"]:
        return None
    top = c * LENS_CAP
    lens = {"dcf": None, "lynch": None, "sector": None, "street": None}
    if g is not None:
        lens["dcf"] = dcf_value(eps, roe, g, r, R["terminal_growth"])
        lens["lynch"] = eps * max(8.0, min(g + (f["dy"] or 0.0), PE_CAP))  # Lynch: a fair P/E equals growth plus yield
    if peers_pe:
        lens["sector"] = eps * min(peers_pe, PE_CAP)
    if f["tgt"] and (f["tgt_n"] or 0) >= RESEARCH_MIN["analysts"]:
        lens["street"] = f["tgt"] / (1 + r / 100)  # a 12-month target, brought back to today
    have = sorted(min(v, top) for v in lens.values() if v is not None and v > 0)
    fv = None
    if len(have) >= RESEARCH_MIN["lenses"]:
        m = len(have) // 2
        fv = have[m] if len(have) % 2 else (have[m - 1] + have[m]) / 2
    long_term = (fv is not None and g is not None and roe >= LONG_TERM["roe"] and g >= LONG_TERM["growth"]
                 and (fin or (f["de"] is not None and f["de"] <= LONG_TERM["de"]))
                 and (f["pio"] is None or f["pio"] >= LONG_TERM["pio"]))
    # Long-term picks aim at fair value 18 months on, grown at the assumed rate (15% a year at most).
    target = fv * (1 + min(g, 15.0) / 100) ** 1.5 if long_term else fv
    return {
        "g": g, "r": r, "hurdle": hurdle, "lens": lens, "n_lens": len(have), "fv": fv, "eps": eps, "roe": roe,
        "up": pct(fv, c) if fv else None, "buy_below": fv / (1 + hurdle / 100) if fv else None,
        "hz": "L" if long_term else "M", "target": target, "tgt_pct": pct(target, c) if target else None,
        "pe": c / f["eps"], "pe_n": c / eps, "pb": c / f["bvps"] if f["bvps"] and f["bvps"] > 0 else None,
    }


def research_checks(f, a, cap, fin, turnover, c, sma200, slot):
    """The entry checklist as [key, passed] pairs, quality first. `a` is research_assess's result."""
    m = RESEARCH_MIN
    growth = f["rev_c5"] if f["rev_c5"] is not None else f["rev_g"]
    q = [
        ["roe", a["roe"] >= (m["roe_fin"] if fin else m["roe"])],
        ["debt", True if fin else (f["de"] is not None and f["de"] <= (m["de_small"] if cap == "S" else m["de"])
                                   and (f["icov"] is None or f["icov"] >= m["icov"]))],
        ["growth", growth is not None and growth >= m["growth"] and (f["rev_g"] is None or f["rev_g"] >= 0)
                   and (f["eps_g"] is None or f["eps_g"] >= 0)],
        ["strength", True if fin else (f["pio"] is not None and f["pio"] >= m["pio"])],
        ["cash", (f["roa"] is not None and f["roa"] >= 1.0) if fin else
                 ((f["fcf"] is not None and f["fcf"] > 0) or (f["fcf"] is None and f["cfo"] is not None and f["cfo"] > 0))],
        ["liquid", turnover is not None and turnover >= m["turnover_cr"] and c <= slot],
    ]
    rest = [
        ["value", a["up"] is not None and a["up"] >= a["hurdle"]],
        ["trend", sma200 is not None and c > sma200],
        ["street", a["lens"]["street"] is None or f["tgt"] >= c],
    ]
    return q, rest


def hold_broken(f, fin):
    """Why a holding no longer passes the looser checks kept after buying, or None."""
    h = RESEARCH_HOLD
    if f["eps"] is not None and f["eps"] <= 0:
        return "earnings turned negative"
    if f["roe"] is not None and f["roe"] < h["roe"]:
        return f"return on equity fell to {f['roe']:.0f}%"
    if not fin and f["de"] is not None and f["de"] > h["de"]:
        return f"debt rose to {f['de']:.1f} times equity"
    if f["pio"] is not None and f["pio"] <= h["pio"]:
        return f"financial strength score fell to {f['pio']:.0f} of 9"
    return None


def research_track(p, eq, days, asof):
    """Move a research pick forward through the sessions since it was last looked at.

    Works from the raw day files one session at a time and keeps its own split factor, so a holding
    can be followed for two years without its whole price history being stored."""
    if p.get("done"):
        return
    for d in days:
        if d <= p["ld"] or d > asof:
            continue
        row = eq[d].get(p["s"])
        if not row or row[4] is None:
            continue
        pc, o, hi, lo, c = row[:5]
        if p["st"] == "new":  # the first session after the pick: bought at its open
            p.update({"st": "open", "ed": d, "e": o or c, "f": 1.0, "peak": 0.0, "low": 0.0})
        elif pc and p["last"] and abs(pc / p["last"] - 1) > 0.02:
            p["f"] *= pc / p["last"]  # a split or bonus: restate the buy price in today's shares
        base = p["e"] * p["f"]
        p["last"], p["ld"] = c, d
        p["ret"] = rnd(pct(c, base))
        p["peak"], p["low"] = rnd(max(p["peak"], pct(hi or c, base))), rnd(min(p["low"], pct(lo or c, base)))
        held = (date.fromisoformat(d) - date.fromisoformat(p["ed"])).days
        if p["ret"] >= p["tgt_pct"]:
            p.update({"st": "target", "xd": d, "done": True})
        elif p["ret"] <= -p["stop_pct"]:
            p.update({"st": "stopped", "xd": d, "done": True})
        elif held >= p["days"]:
            p.update({"st": "timeup", "xd": d, "done": True})
        if p.get("done"):
            break


def build_research(eq, days, adj, idx, meta, cfg, names, asof, make_picks):
    """Screen the Nifty 500, keep the research portfolio's log up to date, and name a new pick when a
    slot is free, one is due and a stock clears every check. Returns the app's "research" block."""
    R = cfg["research"]
    doc = jload(DATA / "fund.json", {})
    fund = fund_rows(doc)
    n500 = meta.get("nifty500") or meta.get("nifty100") or []
    capmap = dict(meta.get("cap") or {})
    large = set(meta.get("nifty100", []))
    # Where the mid and small lists did not arrive, market value decides: the 150 largest outside the Nifty 100 are mid caps.
    loose = sorted((s for s in n500 if capmap.get(s) is None and s not in large),
                   key=lambda s: -(fund.get(s, {}).get("mcap") or 0))
    for k, s in enumerate(loose):
        capmap[s] = "M" if k < 150 else "S"
    for s in n500:
        if s in large:
            capmap[s] = "L"
    slot = R["pot"] / R["max_positions"]
    idays = sorted(d for d in idx if idx[d].get("n500") or idx[d].get("nifty"))

    def index_on(d, key):  # index close on d, or on the last session before it
        k = bisect_right(idays, d)
        while k and not idx[idays[k - 1]].get(key):
            k -= 1
        return idx[idays[k - 1]][key] if k else None

    # Each stock's readings, valuation and checks.
    base = {}
    for s in n500:
        f, rows = fund.get(s), adj.get(s)
        if not f or not rows or rows[-1]["d"] != asof or not rows[-1]["c"]:
            continue
        c = rows[-1]["c"]
        if f["cur"] not in (None, "INR") or not f["px"] or abs(f["px"] / c - 1) > 0.03:
            continue  # the screener's price disagrees with NSE's close: don't trust its other numbers either
        base[s] = (f, c, names.get(s, {}).get("ind", "") == "Financial Services")
    by_group = {}
    for s, (f, c, fin) in base.items():
        if f["eps"] and f["eps"] > 0 and 0 < c / f["eps"] <= 80:
            for group in (("i", f["industry"]), ("s", f["sector"]), ("a", "")):
                by_group.setdefault(group, []).append(c / f["eps"])

    def median(xs):
        xs = sorted(xs)
        m = len(xs) // 2
        return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2

    def peers_pe(f):  # median P/E of the closest group with at least eight profitable peers
        for group in (("i", f["industry"]), ("s", f["sector"]), ("a", "")):
            if group[1] is not None and len(by_group.get(group, [])) >= 8:
                return median(by_group[group])
        return None

    cards, funnel = {}, {"universe": len(n500), "data": len(base), "valued": 0, "quality": 0, "trend": 0, "buy": 0}
    for s, (f, c, fin) in base.items():
        cap = capmap.get(s) or "S"
        a = research_assess(s, f, c, cap, fin, peers_pe(f), R)
        if not a or a["fv"] is None:
            continue
        funnel["valued"] += 1
        rows = adj[s]
        turn = sorted(x["tl"] / 100 for x in rows[-20:] if x["tl"])
        turnover = turn[len(turn) // 2] if turn else None
        closes = [x["c"] for x in rows[-200:] if x["c"]]
        sma200 = avg(closes) if len(closes) >= 200 else f["sma200"]
        p6m = pct(c, rows[-127]["c"]) if len(rows) >= 127 and rows[-127]["c"] else f["p6m"]
        pf = pick_features(rows, len(rows) - 1)
        q, rest = research_checks(f, a, cap, fin, turnover, c, sma200, slot)
        cash = f["roa"] if fin else (f["fcf"] / f["ni"] if f["fcf"] is not None and f["ni"] and f["ni"] > 0 else None)
        cards[s] = {"f": f, "a": a, "c": c, "cap": cap, "fin": fin, "q": q, "rest": rest, "sma200": sma200,
                    "turnover": turnover, "quality": all(ok for _, ok in q), "all": all(ok for _, ok in q + rest),
                    "read": {"up": a["up"], "roe": a["roe"], "pio": f["pio"], "cash": cash, "g": a["g"],
                             "eps_g": f["eps_g"], "p6m": p6m, "dl": pf["dl"] if pf else None}}
    good = sorted(s for s in cards if cards[s]["quality"])
    funnel["quality"] = len(good)
    funnel["trend"] = sum(1 for s in good if dict(cards[s]["rest"])["trend"])
    funnel["buy"] = sum(1 for s in good if cards[s]["all"])
    # Score the quality stocks against each other, 0-100.
    for key, w, _ in RESEARCH_PARTS:
        vals = [cards[s]["read"][key] for s in good if cards[s]["read"][key] is not None]
        ranked = sorted(vals)
        for s in good:
            v = cards[s]["read"][key]
            if v is None or len(ranked) < 2:
                q = 50.0  # no reading: neither helped nor hurt
            else:
                below = bisect_left(ranked, v)
                q = (below + (bisect_right(ranked, v) - below - 1) / 2) / (len(ranked) - 1) * 100
            cards[s].setdefault("p", []).append(q)
    for s in good:
        cards[s]["sc"] = sum(w * q for (_, w, _), q in zip(RESEARCH_PARTS, cards[s]["p"])) / 100

    def row(s):  # what the app shows for one stock
        x = cards[s]
        f, a = x["f"], x["a"]
        return {
            "s": s, "n": names.get(s, {}).get("n", s), "ind": names.get(s, {}).get("ind", ""), "cap": x["cap"], "fin": int(x["fin"]),
            "c": rnd(x["c"]), "fv": rnd(a["fv"]), "up": rnd(a["up"], 1), "bb": rnd(a["buy_below"]), "hurdle": a["hurdle"],
            "hz": a["hz"], "tgt": rnd(a["target"]), "tgt_pct": rnd(a["tgt_pct"], 1),
            "stop_pct": R["stop_" + CAPS[x["cap"]]], "sc": rnd(x.get("sc"), 1), "p": [whole(q) for q in x.get("p", [])],
            "lens": {k: rnd(v) for k, v in a["lens"].items()}, "g": rnd(a["g"], 1), "r": a["r"],
            "pe": rnd(a["pe"], 1), "pe_n": rnd(a["pe_n"], 1), "eps_n": rnd(a["eps"]), "roe_n": rnd(a["roe"], 1),
            "pb": rnd(a["pb"], 1), "roe": rnd(f["roe"], 1), "roa": rnd(f["roa"], 1),
            "de": rnd(f["de"]), "icov": rnd(f["icov"], 1), "pio": whole(f["pio"]), "dy": rnd(f["dy"], 1),
            "rev_c5": rnd(f["rev_c5"], 1), "eps_c5": rnd(f["eps_c5"], 1), "rev_g": rnd(f["rev_g"], 1), "eps_g": rnd(f["eps_g"], 1),
            "cash": rnd(x["read"]["cash"], 2), "p6m": rnd(x["read"]["p6m"], 1), "sma200": rnd(x["sma200"]),
            "turn": rnd(x["turnover"], 1), "street": rnd(f["tgt"]), "street_n": whole(f["tgt_n"]),
            "mcap": whole(f["mcap"] / 1e7) if f["mcap"] else None, "eps": rnd(f["eps"]),
            "q": [[k, int(ok)] for k, ok in x["q"]], "rest": [[k, int(ok)] for k, ok in x["rest"]],
        }

    # The log: follow open picks, then check each one's business still passes.
    log = jload(DATA / "research.json", {})
    picks = [p for p in log.get("picks", []) if p.get("d") and p.get("s")]
    fresh = bool(doc.get("d")) and (date.fromisoformat(asof) - date.fromisoformat(doc["d"])).days <= 7
    for p in picks:
        research_track(p, eq, days, asof)
        if p["st"] == "open" and fresh and p["s"] in fund:
            why = hold_broken(fund[p["s"]], p.get("fin"))
            if why:
                p.update({"st": "broken", "xd": asof, "done": True, "note": why})
        i0 = index_on(p["d"], p.get("ikey", "nifty"))
        i1 = index_on(p.get("xd") or asof, p.get("ikey", "nifty"))
        p["idx"] = rnd(pct(i1, i0)) if i0 and i1 and p["st"] != "new" else None
        if s_now := cards.get(p["s"]):
            p["fv_now"] = rnd(s_now["a"]["fv"])

    # A new pick: at most one every `every_days`, only into a free slot, only if a stock clears everything.
    open_now = [p for p in picks if not p.get("done")]
    last_d = max((p["d"] for p in picks), default=None)
    due = plus_days(last_d, R["every_days"]) if last_d else asof
    ready = bool(n500) and fresh and funnel["valued"] >= 0.5 * len(n500)
    note = None
    held = {p["s"] for p in open_now}
    sectors = {}
    for p in open_now:
        sectors[p.get("ind", "")] = sectors.get(p.get("ind", ""), 0) + 1
    smalls = sum(1 for p in open_now if p.get("cap") == "S")

    def allowed(s):
        x = cards[s]
        note_ = cfg["notes"].get(s)
        return (s not in held and not (note_ and note_["bias"] == -1)
                and sectors.get(names.get(s, {}).get("ind", ""), 0) < R["max_sector"]
                and not (x["cap"] == "S" and smalls >= R["max_small"]))

    buyable = sorted((s for s in good if cards[s]["all"]), key=lambda s: (-cards[s]["sc"], s))
    if not ready:
        note = ("Fundamentals for the Nifty 500 haven't arrived or are more than a week old, so no research pick is made. "
                "The screen resumes when the next snapshot comes in.")
    elif make_picks and asof >= due and len(open_now) < R["max_positions"]:
        s = next((s for s in buyable if allowed(s)), None)
        if s:
            x, r = cards[s], row(s)
            ikey = "n500" if idx.get(asof, {}).get("n500") else "nifty"
            picks.append({"d": asof, "s": s, "n": r["n"], "cap": x["cap"], "ind": r["ind"], "fin": x["fin"], "hz": r["hz"],
                          "c0": r["c"], "fv": r["fv"], "up": r["up"], "tgt_pct": max(r["tgt_pct"], r["hurdle"]),
                          "stop_pct": r["stop_pct"], "days": R["long_days"] if r["hz"] == "L" else R["medium_days"],
                          "sc": r["sc"], "why": r, "st": "new", "ld": asof, "last": x["c"], "ikey": ikey})
            due = plus_days(asof, R["every_days"])
    if ready and not note:
        if len([p for p in picks if not p.get("done")]) >= R["max_positions"]:
            note = f"All {R['max_positions']} slots are in use, so no new pick is made until one closes."
        elif not buyable and asof >= due:
            note = "No stock clears every check tonight. Holding cash is part of the plan; the screen looks again every night."
    jsave(DATA / "research.json", {"picks": sorted(picks, key=lambda p: p["d"])})

    done = [p for p in picks if p.get("done")]
    live = [p for p in picks if p["st"] == "open"]
    hits = [p for p in done if p["st"] == "target"]
    stats = {
        "n": len(picks), "open": len(live), "new": sum(1 for p in picks if p["st"] == "new"), "closed": len(done),
        "target": len(hits), "stopped": sum(1 for p in done if p["st"] == "stopped"),
        "broken": sum(1 for p in done if p["st"] == "broken"), "timeup": sum(1 for p in done if p["st"] == "timeup"),
        "hit": rnd(len(hits) / len(done) * 100, 1) if done else None,
        "avg": rnd(avg([p["ret"] for p in done])), "open_avg": rnd(avg([p["ret"] for p in live])),
        "vs": rnd(avg([p["ret"] - p["idx"] for p in done if p.get("idx") is not None])),
    }
    waiting = sorted((s for s in good if not cards[s]["all"]), key=lambda s: -(cards[s]["a"]["up"] or -999))
    return {
        "rules": R, "min": RESEARCH_MIN, "hold": RESEARCH_HOLD, "long": LONG_TERM, "pe_cap": PE_CAP,
        "parts": [[k, w, label] for k, w, label in RESEARCH_PARTS],
        "fund_d": doc.get("d"), "ready": ready, "note": note, "due": due, "slot": slot,
        "universe": "Nifty 500" if meta.get("nifty500") else "Nifty 100", "funnel": funnel,
        "buy": [row(s) for s in buyable[:10]], "watch": [row(s) for s in waiting[:15]],
        "picks": sorted(picks, key=lambda p: p["d"], reverse=True), "stats": stats,
    }


def build(make_picks=False):
    """Rebuild docs/data.json from the stored history. New picks are named only on the nightly update,
    never by a rebuild done by hand."""
    meta = jload(DATA / "meta.json", {})
    cfg = load_config()
    names = meta.get("names", {})
    n50, n100 = set(meta.get("nifty50", [])), set(meta.get("nifty100", []))
    universe = sorted(n50 | n100 | set(cfg["extra_symbols"]))
    eq = {p.stem: jload(p, {}).get("rows", {}) for p in sorted((DATA / "eq").glob("*.json"))}
    copies = holiday_copies(eq)  # never let a holiday copy count as a session, even if one is stored
    days = sorted(d for d in eq if eq[d] and d not in copies)
    if not days:
        sys.exit("No delivery data stored yet; run `python radar.py update` first.")
    fo = {p.stem: jload(p, {}) for p in (DATA / "fo").glob("*.json")}
    idx = {p.stem: jload(p, {}) for p in (DATA / "idx").glob("*.json")}
    deals = jload(DATA / "deals.json", [])
    flows = jload(DATA / "fiidii.json", {})
    part = {p.stem: jload(p, {}) for p in (DATA / "part").glob("*.json")}
    asof = days[-1]
    det_days = days[-DETAIL_DAYS:]

    # Split-adjusted history for every stored symbol; picked stocks that left the index are in here too.
    adj = {}
    for sym in sorted({s for d in days for s in eq[d]}):
        adj[sym] = adjusted_rows([(d, eq[d][sym]) for d in days if sym in eq[d]])
    picks, tonight = build_picks(adj, days, idx, meta, cfg, names, asof, make_picks)
    research = build_research(eq, days, adj, idx, meta, cfg, names, asof, make_picks)

    stocks = []
    for sym in universe:
        rows = adj.get(sym)
        if not rows or rows[-1]["d"] != asof:
            continue  # did not trade on the latest day
        st = stock_metrics(sym, rows, fo, deals, det_days, names, cfg["notes"])
        st["grp"] = 50 if sym in n50 else 100 if sym in n100 else 0  # Nifty 50, Next 50, or added by hand
        st["pk"] = tonight.get(sym)
        stocks.append(st)

    out = {
        "asof": asof,
        "generated": datetime.now(IST).isoformat(timespec="minutes"),
        "last_update": meta.get("last_update"),
        "dates": det_days,
        "signals": SIGNALS,
        "market": market_summary(idx, flows, stocks, asof),
        "fii": fii_activity(days, flows, part, fo, asof),
        "stocks": stocks,
        "picks": picks,
        "research": research,
        "universe": "Nifty 100" if len(n100) >= 90 else "Nifty 50",
        "deals": [x for x in deals if x["d"] >= det_days[0]][-80:],
        "have": {"fo": asof in fo, "idx": asof in idx, "flows": asof in flows, "part": "FII" in part.get(asof, {})},
        "mtf": {"stop_buffer_pct": STOP_BUFFER * 100, "min_stop_pct": MIN_STOP_PCT},
        "extra": [s for s in cfg["extra_symbols"] if s not in n50 | n100],
    }
    jsave(OUT, out)
    newest = next((x for x in picks["list"] if x["src"] == "live"), None)
    print(f"Built {OUT.relative_to(ROOT)}: {len(stocks)} stocks, data as of {asof}; "
          + (f"latest pick {newest['s']} ({newest['d']}), next due {picks['due']}" if newest else "no pick yet"))


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
