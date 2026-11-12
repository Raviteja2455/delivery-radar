"""Write synthetic NSE end-of-day files, in NSE's exact layouts, for offline testing of radar.py.

    python tests/make_sample.py OUT_DIR LAST_DATE   (e.g. sample 2026-10-23)

The numbers are random. They only exercise the parser and the maths; they are not market data.
"""
import csv
import io
import json
import random
import shutil
import sys
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SYMBOLS = {  # symbol: (company, industry, starting price)
    "ADANIENT": ("Adani Enterprises Ltd.", "Metals & Mining", 2300), "ADANIPORTS": ("Adani Ports and Special Economic Zone Ltd.", "Services", 1350),
    "APOLLOHOSP": ("Apollo Hospitals Enterprise Ltd.", "Healthcare", 6900), "ASIANPAINT": ("Asian Paints Ltd.", "Consumer Durables", 2400),
    "AXISBANK": ("Axis Bank Ltd.", "Financial Services", 1050), "BAJAJ-AUTO": ("Bajaj Auto Ltd.", "Automobile and Auto Components", 8200),
    "BAJFINANCE": ("Bajaj Finance Ltd.", "Financial Services", 880), "BAJAJFINSV": ("Bajaj Finserv Ltd.", "Financial Services", 1900),
    "BEL": ("Bharat Electronics Ltd.", "Capital Goods", 400), "BHARTIARTL": ("Bharti Airtel Ltd.", "Telecommunication", 1750),
    "BSE": ("BSE Ltd.", "Financial Services", 2400), "CIPLA": ("Cipla Ltd.", "Healthcare", 1500),
    "COALINDIA": ("Coal India Ltd.", "Oil Gas & Consumable Fuels", 414), "DRREDDY": ("Dr. Reddy's Laboratories Ltd.", "Healthcare", 1250),
    "EICHERMOT": ("Eicher Motors Ltd.", "Automobile and Auto Components", 6500), "ETERNAL": ("Eternal Ltd.", "Consumer Services", 290),
    "GRASIM": ("Grasim Industries Ltd.", "Construction Materials", 2700), "HCLTECH": ("HCL Technologies Ltd.", "Information Technology", 1400),
    "HDFCBANK": ("HDFC Bank Ltd.", "Financial Services", 690), "HDFCLIFE": ("HDFC Life Insurance Company Ltd.", "Financial Services", 720),
    "HINDALCO": ("Hindalco Industries Ltd.", "Metals & Mining", 700), "HINDUNILVR": ("Hindustan Unilever Ltd.", "Fast Moving Consumer Goods", 2450),
    "ICICIBANK": ("ICICI Bank Ltd.", "Financial Services", 1350), "INDIGO": ("InterGlobe Aviation Ltd.", "Services", 5600),
    "INFY": ("Infosys Ltd.", "Information Technology", 1170), "ITC": ("ITC Ltd.", "Fast Moving Consumer Goods", 262),
    "JIOFIN": ("Jio Financial Services Ltd.", "Financial Services", 300), "JSWSTEEL": ("JSW Steel Ltd.", "Metals & Mining", 1050),
    "KOTAKBANK": ("Kotak Mahindra Bank Ltd.", "Financial Services", 2050), "LT": ("Larsen & Toubro Ltd.", "Construction", 3500),
    "M&M": ("Mahindra & Mahindra Ltd.", "Automobile and Auto Components", 3200), "MARUTI": ("Maruti Suzuki India Ltd.", "Automobile and Auto Components", 15000),
    "MAXHEALTH": ("Max Healthcare Institute Ltd.", "Healthcare", 1100), "NTPC": ("NTPC Ltd.", "Power", 330),
    "ONGC": ("Oil & Natural Gas Corporation Ltd.", "Oil Gas & Consumable Fuels", 240), "POWERGRID": ("Power Grid Corporation of India Ltd.", "Power", 290),
    "RELIANCE": ("Reliance Industries Ltd.", "Oil Gas & Consumable Fuels", 1230), "SBILIFE": ("SBI Life Insurance Company Ltd.", "Financial Services", 1800),
    "SBIN": ("State Bank of India", "Financial Services", 780), "SHRIRAMFIN": ("Shriram Finance Ltd.", "Financial Services", 620),
    "SUNPHARMA": ("Sun Pharmaceutical Industries Ltd.", "Healthcare", 1650), "TATACONSUM": ("Tata Consumer Products Ltd.", "Fast Moving Consumer Goods", 1080),
    "TMPV": ("Tata Motors Passenger Vehicles Ltd.", "Automobile and Auto Components", 273), "TATASTEEL": ("Tata Steel Ltd.", "Metals & Mining", 160),
    "TCS": ("Tata Consultancy Services Ltd.", "Information Technology", 2070), "TECHM": ("Tech Mahindra Ltd.", "Information Technology", 1450),
    "TITAN": ("Titan Company Ltd.", "Consumer Durables", 3400), "TRENT": ("Trent Ltd.", "Consumer Services", 4900),
    "ULTRACEMCO": ("UltraTech Cement Ltd.", "Construction Materials", 11800), "WIPRO": ("Wipro Ltd.", "Information Technology", 240),
}
NEXT50 = {  # Nifty Next 50 names, to exercise the Nifty 100 list and the three-month pick
    "ABB": ("ABB India Ltd.", "Capital Goods", 5600), "ADANIENSOL": ("Adani Energy Solutions Ltd.", "Power", 900),
    "ADANIGREEN": ("Adani Green Energy Ltd.", "Power", 1000), "ADANIPOWER": ("Adani Power Ltd.", "Power", 150),
    "AMBUJACEM": ("Ambuja Cements Ltd.", "Construction Materials", 560), "BAJAJHLDNG": ("Bajaj Holdings & Investment Ltd.", "Financial Services", 12000),
    "BAJAJHFL": ("Bajaj Housing Finance Ltd.", "Financial Services", 110), "BANKBARODA": ("Bank of Baroda", "Financial Services", 260),
    "BPCL": ("Bharat Petroleum Corporation Ltd.", "Oil Gas & Consumable Fuels", 340), "BOSCHLTD": ("Bosch Ltd.", "Automobile and Auto Components", 36000),
    "BRITANNIA": ("Britannia Industries Ltd.", "Fast Moving Consumer Goods", 5800), "CGPOWER": ("CG Power and Industrial Solutions Ltd.", "Capital Goods", 720),
    "CANBK": ("Canara Bank", "Financial Services", 125), "CHOLAFIN": ("Cholamandalam Investment and Finance Company Ltd.", "Financial Services", 1600),
    "DLF": ("DLF Ltd.", "Realty", 760), "DABUR": ("Dabur India Ltd.", "Fast Moving Consumer Goods", 500),
    "DIVISLAB": ("Divi's Laboratories Ltd.", "Healthcare", 6200), "GAIL": ("GAIL (India) Ltd.", "Oil Gas & Consumable Fuels", 180),
    "GODREJCP": ("Godrej Consumer Products Ltd.", "Fast Moving Consumer Goods", 1150), "HAVELLS": ("Havells India Ltd.", "Consumer Durables", 1500),
    "HAL": ("Hindustan Aeronautics Ltd.", "Capital Goods", 4700), "HYUNDAI": ("Hyundai Motor India Ltd.", "Automobile and Auto Components", 2400),
    "ICICIGI": ("ICICI Lombard General Insurance Company Ltd.", "Financial Services", 1950), "IOC": ("Indian Oil Corporation Ltd.", "Oil Gas & Consumable Fuels", 150),
    "IRFC": ("Indian Railway Finance Corporation Ltd.", "Financial Services", 125), "NAUKRI": ("Info Edge (India) Ltd.", "Consumer Services", 1350),
    "JINDALSTEL": ("Jindal Steel Ltd.", "Metals & Mining", 1000), "JSWENERGY": ("JSW Energy Ltd.", "Power", 520),
    "LICI": ("Life Insurance Corporation of India", "Financial Services", 900), "LODHA": ("Lodha Developers Ltd.", "Realty", 1150),
    "LTIM": ("LTIMindtree Ltd.", "Information Technology", 5600), "PIDILITIND": ("Pidilite Industries Ltd.", "Chemicals", 1500),
    "PFC": ("Power Finance Corporation Ltd.", "Financial Services", 400), "PNB": ("Punjab National Bank", "Financial Services", 115),
    "RECLTD": ("REC Ltd.", "Financial Services", 370), "MOTHERSON": ("Samvardhana Motherson International Ltd.", "Automobile and Auto Components", 105),
    "SHREECEM": ("Shree Cement Ltd.", "Construction Materials", 28000), "SIEMENS": ("Siemens Ltd.", "Capital Goods", 3100),
    "SOLARINDS": ("Solar Industries India Ltd.", "Chemicals", 14000), "TVSMOTOR": ("TVS Motor Company Ltd.", "Automobile and Auto Components", 3500),
    "TATAPOWER": ("Tata Power Company Ltd.", "Power", 390), "TORNTPHARM": ("Torrent Pharmaceuticals Ltd.", "Healthcare", 3600),
    "UNITDSPR": ("United Spirits Ltd.", "Fast Moving Consumer Goods", 1350), "VBL": ("Varun Beverages Ltd.", "Fast Moving Consumer Goods", 470),
    "VEDL": ("Vedanta Ltd.", "Metals & Mining", 470), "ZYDUSLIFE": ("Zydus Lifesciences Ltd.", "Healthcare", 980),
    "CUMMINSIND": ("Cummins India Ltd.", "Capital Goods", 4000), "INDHOTEL": ("The Indian Hotels Company Ltd.", "Consumer Services", 740),
    "MAZDOCK": ("Mazagon Dock Shipbuilders Ltd.", "Capital Goods", 2800), "ENRIN": ("Siemens Energy India Ltd.", "Capital Goods", 3300),
}
MIDCAPS = {  # a few Nifty Midcap 150 and Smallcap 250 names, to exercise the research screen's cap classes
    "POLYCAB": ("Polycab India Ltd.", "Capital Goods", 7200), "PERSISTENT": ("Persistent Systems Ltd.", "Information Technology", 5600),
    "COFORGE": ("Coforge Ltd.", "Information Technology", 1700), "DIXON": ("Dixon Technologies (India) Ltd.", "Consumer Durables", 15000),
    "FEDERALBNK": ("The Federal Bank Ltd.", "Financial Services", 210), "MUTHOOTFIN": ("Muthoot Finance Ltd.", "Financial Services", 2900),
    "PIIND": ("PI Industries Ltd.", "Chemicals", 3700), "SUPREMEIND": ("Supreme Industries Ltd.", "Capital Goods", 4200),
    "ASTRAL": ("Astral Ltd.", "Capital Goods", 1400), "PAGEIND": ("Page Industries Ltd.", "Textiles", 44000),
}
SMALLCAPS = {
    "CDSL": ("Central Depository Services (India) Ltd.", "Financial Services", 1500), "RADICO": ("Radico Khaitan Ltd.", "Fast Moving Consumer Goods", 2900),
    "AMBER": ("Amber Enterprises India Ltd.", "Consumer Durables", 7600), "CAMS": ("Computer Age Management Services Ltd.", "Financial Services", 3900),
    "KARURVYSYA": ("Karur Vysya Bank Ltd.", "Financial Services", 250), "NATCOPHARM": ("Natco Pharma Ltd.", "Healthcare", 850),
    "ZENSARTECH": ("Zensar Technologies Ltd.", "Information Technology", 780), "CYIENT": ("Cyient Ltd.", "Information Technology", 1200),
    "TRIVENI": ("Triveni Engineering & Industries Ltd.", "Fast Moving Consumer Goods", 360), "ARE&M": ("Amara Raja Energy & Mobility Ltd.", "Automobile and Auto Components", 1000),
}
NIFTY50 = list(SYMBOLS)
SYMBOLS.update(NEXT50)
NIFTY100 = list(SYMBOLS)
SYMBOLS.update(MIDCAPS)
SYMBOLS.update(SMALLCAPS)
HOLIDAYS = {date(2026, 1, 26), date(2026, 10, 2), date(2026, 10, 20)}
# NSE answers some holiday addresses with the previous session's file instead of "not found";
# these holidays reproduce that, so the pipeline must notice the date inside the file.
SERVED_AS_COPY = {date(2026, 10, 2), date(2026, 10, 20)}
SPECIAL = {date(2026, 9, 6)}  # a Sunday session, like Budget day or Diwali's Muhurat trading
SPLIT = ("BEL", date(2026, 9, 15), 2)  # 1:2 split: price halves, quantities double
EXPIRIES = [date(2025, 12, 30)] + [date(2026, m, d) for m, d in
            [(1, 27), (2, 24), (3, 31), (4, 28), (5, 26), (6, 30), (7, 28), (8, 25), (9, 29), (10, 27), (11, 24), (12, 29)]]
FO_COLS = ["TradDt", "BizDt", "Sgmt", "Src", "FinInstrmTp", "FinInstrmId", "ISIN", "TckrSymb", "SctySrs", "XpryDt",
           "FininstrmActlXpryDt", "StrkPric", "OptnTp", "FinInstrmNm", "OpnPric", "HghPric", "LwPric", "ClsPric", "LastPric",
           "PrvsClsgPric", "UndrlygPric", "SttlmPric", "OpnIntrst", "ChngInOpnIntrst", "TtlTradgVol", "TtlTrfVal",
           "TtlNbOfTxsExctd", "SsnId", "NewBrdLotQty", "Rmks", "Rsvd1", "Rsvd2", "Rsvd3", "Rsvd4"]


def main(out, last):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(7)
    start = date(2025, 12, 1)
    days = [start + timedelta(n) for n in range((last - start).days + 1)]
    days = [d for d in days if (d.weekday() < 5 and d not in HOLIDAYS) or d in SPECIAL]

    with open(out / "ind_nifty50list.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Company Name", "Industry", "Symbol", "Series", "ISIN Code"])
        for s in NIFTY50:
            w.writerow([SYMBOLS[s][0], SYMBOLS[s][1], s, "EQ", "INE000000000"])
    for fname, members in (("ind_nifty100list.csv", NIFTY100), ("ind_niftymidcap150list.csv", list(MIDCAPS)),
                           ("ind_niftysmallcap250list.csv", list(SMALLCAPS))):
        with open(out / fname, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Company Name", "Industry", "Symbol", "Series", "ISIN Code"])
            for s in members:
                w.writerow([SYMBOLS[s][0], SYMBOLS[s][1], s, "EQ", "INE000000000"])
    with open(out / "ind_nifty500list.csv", "w", newline="") as f:  # a short stand-in for the 500 names
        w = csv.writer(f)
        w.writerow(["Company Name", "Industry", "Symbol", "Series", "ISIN Code"])
        for s, (n, ind, _) in SYMBOLS.items():
            w.writerow([n, ind, s, "EQ", "INE000000000"])

    price = {s: v[2] * (0.9 + 0.2 * rnd.random()) for s, v in SYMBOLS.items()}
    base_vol = {s: rnd.uniform(1e6, 2.5e7) for s in SYMBOLS}
    base_dp = {s: rnd.uniform(30, 62) for s in SYMBOLS}
    oi = {}  # (symbol, expiry) -> OI
    nifty, vix = 24500.0, 14.0
    # participant OI: index fut long/short, stock fut long/short, index call long, put long, call short, put short
    part = {"Client": [300000, 60000, 3200000, 270000, 2700000, 2680000, 2610000, 3180000],
            "DII": [49000, 7000, 300000, 4500000, 14000, 113000, 700, 200],
            "FII": [35000, 220000, 3600000, 2560000, 658000, 1060000, 880000, 640000],
            "Pro": [29000, 35000, 690000, 450000, 997000, 1095000, 880000, 1130000]}
    for d in days:
        prev = dict(price)
        rets = {s: rnd.gauss(-0.0004, 0.014) for s in SYMBOLS}
        rows = []
        for s in SYMBOLS:
            if s == SPLIT[0] and d == SPLIT[1]:
                prev[s] = prev[s] / SPLIT[2]
                price[s] = prev[s]
                base_vol[s] *= SPLIT[2]
            price[s] = prev[s] * (1 + rets[s])
            c = round(price[s], 2)
            hi, lo = round(max(prev[s], c) * (1 + rnd.random() * 0.01), 2), round(min(prev[s], c) * (1 - rnd.random() * 0.01), 2)
            spike = rnd.random() < 0.05
            v = int(base_vol[s] * rnd.lognormvariate(0, 0.35) * (2.2 if spike else 1))
            dp = min(95.0, max(8.0, base_dp[s] + rnd.gauss(0, 7) + (15 if spike and rets[s] > 0 else 0)))
            dq = int(v * dp / 100)
            ap = (hi + lo + c) / 3
            trades = max(1, int(v / rnd.uniform(60, 140)))
            rows.append([s, "EQ", d.strftime("%d-%b-%Y"), f"{prev[s]:.2f}", f"{prev[s]:.2f}", f"{hi:.2f}", f"{lo:.2f}", f"{c:.2f}",
                         f"{c:.2f}", f"{ap:.2f}", str(v), f"{v * ap / 1e5:.2f}", str(trades), str(dq), f"{dq / v * 100:.2f}"])
            price[s] = c
        rows.append(["20MICRONS", "EQ", d.strftime("%d-%b-%Y"), "210.50", "211.00", "215.40", "209.10", "213.00", "213.25", "212.78",
                     "123456", "262.71", "2345", "56789", "46.00"])
        rows.append(["ITC", "BL", d.strftime("%d-%b-%Y"), "260.00", "260.00", "260.00", "260.00", "260.00", "260.00", "260.00",
                     "1000000", "2600.00", "1", "-", "-"])
        with open(out / f"sec_bhavdata_full_{d:%d%m%Y}.csv", "w", newline="") as f:
            f.write("SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, AVG_PRICE, "
                    "TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER\n")
            for r in rows:
                f.write(", ".join(r) + "\n")

        nret = sum(rets.values()) / len(rets)
        new_nifty = nifty * (1 + nret)
        new_vix = max(9.0, vix * (1 + rnd.gauss(0, 0.05) - 2 * nret))
        with open(out / f"ind_close_all_{d:%d%m%Y}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Index Name", "Index Date", "Open Index Value", "High Index Value", "Low Index Value", "Closing Index Value",
                        "Points Change", "Change(%)", "Volume", "Turnover (Rs. Cr.)", "P/E", "P/B", "Div Yield"])
            for name, old, new in (("Nifty 50", nifty, new_nifty), ("Nifty Bank", nifty * 2.4, new_nifty * 2.4), ("India VIX", vix, new_vix)):
                w.writerow([name, d.strftime("%d-%m-%Y"), f"{old:.2f}", f"{max(old, new):.2f}", f"{min(old, new):.2f}", f"{new:.2f}",
                            f"{new - old:.2f}", f"{(new / old - 1) * 100:.2f}", "-", "-", "-", "-", "-"])
        nifty, vix = new_nifty, new_vix

        live = [e for e in EXPIRIES if e >= d][:3]
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(FO_COLS)
        for s in SYMBOLS:
            for k, e in enumerate(live):
                key = (s, e)
                days_left = (e - d).days
                old = oi.get(key, 0)
                if k == 0:
                    new = old * (1 + rnd.gauss(0, 0.04)) if old else base_vol[s] * 3
                    if days_left < 6:
                        new *= 0.75  # roll-over out of the near month
                elif k == 1:
                    new = (old or base_vol[s] * 0.2) * (1.12 if days_left < 36 else 1.01) * (1 + rnd.gauss(0, 0.02))
                else:
                    new = (old or base_vol[s] * 0.02) * (1 + rnd.gauss(0.01, 0.02))
                new = int(new)
                if s == SPLIT[0] and d == SPLIT[1]:
                    old = old * SPLIT[2]
                oi[key] = new
                fc = round(price[s] * (1 + 0.004 * (k + 1)), 2)
                row = {c: "" for c in FO_COLS}
                row.update({"TradDt": d.isoformat(), "BizDt": d.isoformat(), "Sgmt": "FO", "Src": "NSE", "FinInstrmTp": "STF",
                            "TckrSymb": s, "XpryDt": e.isoformat(), "FininstrmActlXpryDt": e.isoformat(),
                            "FinInstrmNm": f"{s}{e:%y%b}FUT".upper(), "ClsPric": f"{fc:.2f}", "PrvsClsgPric": f"{prev[s]:.2f}",
                            "OpnIntrst": str(new), "ChngInOpnIntrst": str(new - int(old)), "TtlTradgVol": str(int(base_vol[s] / 3))})
                w.writerow([row[c] for c in FO_COLS])
        for e in live[:1]:  # index futures and a stock option row, which the parser must ignore
            w.writerow([d.isoformat(), d.isoformat(), "FO", "NSE", "IDF", "", "", "NIFTY", "", e.isoformat(), e.isoformat(), "", "",
                        "NIFTYFUT", "", "", "", f"{nifty:.2f}", "", "", "", "", "15000000", "250000", "", "", "", "", "", "", "", "", "", ""])
            w.writerow([d.isoformat(), d.isoformat(), "FO", "NSE", "STO", "", "", "ITC", "", e.isoformat(), e.isoformat(), "260", "CE",
                        "ITC260CE", "", "", "", "4.10", "", "", "", "", "900000", "50000", "", "", "", "", "", "", "", "", "", ""])
        weekly = d + timedelta((1 - d.weekday()) % 7)  # Nifty options expire every Tuesday
        w.writerow([d.isoformat(), d.isoformat(), "FO", "NSE", "IDO", "", "", "NIFTY", "", weekly.isoformat(), weekly.isoformat(),
                    "24500", "CE", "NIFTY24500CE", "", "", "", "120.5", "", "", "", "", "650000", "13000", "", "", "", "", "", "", "",
                    "", "", ""])
        name = f"BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000"
        with zipfile.ZipFile(out / f"{name}.csv.zip", "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(f"{name}.csv", buf.getvalue())

        # Participant-wise open interest: a title line, then contracts held long and short by each category.
        for k in part:
            part[k] = [max(1000, int(v * (1 + rnd.gauss(0, 0.04)))) for v in part[k]]
        with open(out / f"fao_participant_oi_{d:%d%m%Y}.csv", "w", newline="") as f:
            f.write(f'""Participant wise Open Interest (no. of contracts) in Equity Derivatives as on {d:%b %d, %Y}"",'
                    + "," * 13 + "\r\n")
            f.write("Client Type,Future Index Long,Future Index Short,Future Stock Long,Future Stock Short       ,"
                    "Option Index Call Long,Option Index Put Long,Option Index Call Short,Option Index Put Short,"
                    "Option Stock Call Long,Option Stock Put Long,Option Stock Call Short,Option Stock Put Short,"
                    "Total Long Contracts      ,Total Short Contracts\r\n")
            total = [0] * 12
            for k, v in part.items():
                fl, fs, sl, ss, cl, pl, cs, ps = v
                cells = [fl, fs, sl, ss, cl, pl, cs, ps, sl // 3, sl // 4, ss // 3, ss // 4]
                total = [a + b for a, b in zip(total, cells)]
                f.write(",".join([k] + [str(c) for c in cells] + [str(fl + sl + cl + pl), str(fs + ss + cs + ps)]) + "\r\n")
            f.write(",".join(["TOTAL"] + [str(c) for c in total] + ["0", "0"]) + "\r\n")

    # TradingView screener answer, in the offline form radar.py's Source reads: fundamentals that are
    # consistent with the last price, with about one stock in six made cheap and strong on purpose.
    frnd = random.Random(11)
    tv = {"unknown": ["price_target_median"], "rows": {}}
    for s in SYMBOLS:
        gem = frnd.random() < 0.17
        fin = SYMBOLS[s][1] == "Financial Services"
        c = round(price[s], 2)
        pe = frnd.uniform(8, 14) if gem else frnd.uniform(14, 70)
        roe = frnd.uniform(18, 30) if gem else frnd.uniform(4, 32)
        g5 = frnd.uniform(12, 22) if gem else frnd.uniform(-2, 24)
        eps = c / pe
        ni = eps * frnd.uniform(2e7, 4e8)
        row = {
            "close": c, "currency": "INR", "fundamental_currency_code": "INR", "market_cap_basic": c * frnd.uniform(5e7, 5e9),
            "sector": "Finance" if fin else "Producer Manufacturing", "industry": SYMBOLS[s][1],
            "earnings_per_share_diluted_ttm": eps if frnd.random() > 0.03 else -eps, "price_earnings_ttm": pe,
            "book_value_per_share_fq": eps / (roe / 100), "return_on_equity": roe,
            "return_on_assets": frnd.uniform(0.6, 2.5) if fin else roe * 0.6,
            "debt_to_equity": frnd.uniform(3, 8) if fin else frnd.uniform(0, 0.5 if gem else 1.6),
            "interst_cover_ttm": None if fin else frnd.uniform(1.5, 40),
            "total_revenue_yoy_growth_ttm": g5 + frnd.uniform(-6, 6) + (4 if gem else 0), "total_revenue_cagr_5y": g5,
            "earnings_per_share_diluted_yoy_growth_ttm": g5 + frnd.uniform(-15, 20) + (12 if gem else 0),
            "earnings_per_share_basic_cagr_5y": g5 + frnd.uniform(-4, 8),
            "net_income_ttm": ni, "free_cash_flow_ttm": None if fin else ni * frnd.uniform(-0.3 if not gem else 0.4, 1.2),
            "cash_f_operating_activities_ttm": ni * frnd.uniform(0.2, 1.4),
            "dividends_yield_current": frnd.uniform(0, 3), "piotroski_f_score_ttm": frnd.randint(7, 9) if gem else frnd.randint(2, 9),
            "price_target_average": c * frnd.uniform(1.15 if gem else 0.9, 1.45), "recommendation_total": frnd.randint(0, 40),
            "SMA200": c * (frnd.uniform(0.85, 0.99) if gem else frnd.uniform(0.85, 1.15)), "Perf.6M": frnd.uniform(-20, 35),
            "sloan_ratio_fy": frnd.uniform(-5, 14) if gem else frnd.uniform(-8, 32),
            # next results: a Unix time some days either side of the last sample day
            "earnings_release_next_date": int(datetime(last.year, last.month, last.day, 12, tzinfo=timezone.utc).timestamp())
                                          + 86400 * (frnd.randint(8, 70) if gem else frnd.randint(-20, 70)),
        }
        tv["rows"]["NSE:" + "".join(ch if ch.isalnum() else "_" for ch in s)] = row
    (out / "tv_scan.json").write_text(json.dumps(tv))

    d = days[-1]
    head = ["Date", "Symbol", "Security Name", "Client Name", "Buy/Sell", "Quantity Traded", "Trade Price / Wght. Avg. Price", "Remarks"]
    blk = round(price["ITC"] * 0.985, 2)
    hdb = round(price["HDFCBANK"] * 0.97, 2)   # a promoter's block at a 3% discount, taken by two FIIs
    ds = d.strftime("%d-%b-%Y")
    for fname, rows in (("block.csv", [[ds, "ITC", "ITC LTD", "SOME GLOBAL FUND", "SELL", "36,50,00,000", f"{blk}", "-"],
                                        [ds, "ITC", "ITC LTD", "A MUTUAL FUND A/C LARGE CAP", "BUY", "36,50,00,000", f"{blk}", "-"],
                                        [ds, "HDFCBANK", "HDFC BANK LTD", "GOLDMAN SACHS BANK EUROPE SE", "BUY", "50,00,000", f"{hdb}", "-"],
                                        [ds, "HDFCBANK", "HDFC BANK LTD", "SOCIETE GENERALE - ODI", "BUY", "30,00,000", f"{hdb}", "-"],
                                        [ds, "HDFCBANK", "HDFC BANK LTD", "SOME PROMOTER HOLDINGS LIMITED", "SELL", "80,00,000", f"{hdb}", "-"]]),
                        ("bulk.csv", [[ds, "M&M", "MAHINDRA & MAHINDRA LTD", "<b>ODD NAME & CO</b>", "BUY", "65,00,000",
                                       f"{price['M&M']:.2f}", "-"],
                                      [ds, "20MICRONS", "20 MICRONS LTD", "SOMEONE", "BUY", "1,00,000", "213.00", "-"],
                                      # an FII in a stock outside every index list: kept, priced from the full delivery file
                                      [ds, "20MICRONS", "20 MICRONS LTD", "MORGAN STANLEY ASIA (SINGAPORE) PTE.", "BUY", "2,00,000", "212.00", "-"],
                                      # the HDFC Bank block again in the bulk list: counted once
                                      [ds, "HDFCBANK", "HDFC BANK LTD", "GOLDMAN SACHS BANK EUROPE SE", "BUY", "50,00,000", f"{hdb}", "-"],
                                      # a trading desk buying and selling the same stock in one session
                                      [ds, "RELIANCE", "RELIANCE INDUSTRIES LTD", "INTEGRATED CORE STRATEGIES (ASIA) PTE. LTD.", "BUY", "10,00,000",
                                       f"{price['RELIANCE']:.2f}", "-"],
                                      [ds, "RELIANCE", "RELIANCE INDUSTRIES LTD", "INTEGRATED CORE STRATEGIES (ASIA) PTE. LTD.", "SELL", "9,80,000",
                                       f"{price['RELIANCE'] * 1.001:.2f}", "-"]])):
        with open(out / fname, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(head)
            w.writerows(rows)
    # NSE's deal history (the Large Deals page's API): earlier sessions, plus tonight's HDFC Bank block again
    def api(day, sym, name, client, side, q, p):
        return {"BD_DT_DATE": day.strftime("%d-%b-%Y").upper(), "BD_DT_ORDER": day.isoformat() + "T18:30:00.000+00:00",
                "BD_SYMBOL": sym, "BD_SCRIP_NAME": name, "BD_CLIENT_NAME": client, "BD_BUY_SELL": side,
                "BD_QTY_TRD": q, "BD_TP_WATP": p, "BD_REMARKS": "-"}
    d5, d12 = days[-5], days[-12]
    hist = {"block": [api(d, "HDFCBANK", "HDFC Bank Ltd", "GOLDMAN SACHS BANK EUROPE SE", "BUY", 5000000, hdb),
                      api(d5, "AXISBANK", "Axis Bank Ltd", "NORGES BANK ON ACCOUNT OF THE GOVERNMENT PENSION FUND GLOBAL", "BUY", 4000000, 1060.5),
                      api(d5, "AXISBANK", "Axis Bank Ltd", "SOME PE FUND MAURITIUS", "SELL", 4000000, 1060.5),
                      api(d12, "SBIN", "State Bank of India", "GQG PARTNERS EMERGING MARKETS EQUITY FUND", "SELL", 9000000, 775.0),
                      api(d12, "SBIN", "State Bank of India", "SBI MUTUAL FUND", "BUY", 9000000, 775.0)],
            "bulk": [api(d12, "LENSKART", "Lenskart Solutions Ltd", "GOLDMAN SACHS INVESTMENTS MAURITIUS I LIMITED", "BUY", 4440000, 697.15),
                     api(d12, "LENSKART", "Lenskart Solutions Ltd", "SVF II LIGHTBULB (CAYMAN) LIMITED", "SELL", 27200000, 697.15),
                     api(d12, "ZZSME", "Some SME Ltd", "SOMEBODY", "BUY", 100000, 12.0)]}
    for kind, rows in hist.items():
        (out / f"deals_api_{kind}.json").write_text(json.dumps({"data": rows}))
    flows = [{"category": "DII **", "date": d.strftime("%d-%b-%Y"), "buyValue": "13402.08", "sellValue": "12220.04", "netValue": "1182.04"},
             {"category": "FII/FPI *", "date": d.strftime("%d-%b-%Y"), "buyValue": "16314.46", "sellValue": "15111.32", "netValue": "-4203.14"}]
    (out / "fiidiiTradeReact.json").write_text(json.dumps(flows))
    for h in sorted(x for x in SERVED_AS_COPY if x <= last):
        p = max(x for x in days if x < h)
        for name in ("sec_bhavdata_full_{:%d%m%Y}.csv", "ind_close_all_{:%d%m%Y}.csv"):
            shutil.copyfile(out / name.format(p), out / name.format(h))
    print(f"Wrote {len(days)} trading days to {out}")


if __name__ == "__main__":
    main(sys.argv[1], date.fromisoformat(sys.argv[2]))
