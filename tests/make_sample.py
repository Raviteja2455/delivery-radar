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
from datetime import date, timedelta
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
HOLIDAYS = {date(2026, 1, 26), date(2026, 10, 2), date(2026, 10, 20)}
# NSE answers some holiday addresses with the previous session's file instead of "not found";
# these holidays reproduce that, so the pipeline must notice the date inside the file.
SERVED_AS_COPY = {date(2026, 10, 2), date(2026, 10, 20)}
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
    days = [d for d in days if d.weekday() < 5 and d not in HOLIDAYS]

    with open(out / "ind_nifty50list.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Company Name", "Industry", "Symbol", "Series", "ISIN Code"])
        for s, (n, ind, _) in SYMBOLS.items():
            w.writerow([n, ind, s, "EQ", "INE000000000"])

    price = {s: v[2] * (0.9 + 0.2 * rnd.random()) for s, v in SYMBOLS.items()}
    base_vol = {s: rnd.uniform(1e6, 2.5e7) for s in SYMBOLS}
    base_dp = {s: rnd.uniform(30, 62) for s in SYMBOLS}
    oi = {}  # (symbol, expiry) -> OI
    nifty, vix = 24500.0, 14.0
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
        name = f"BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000"
        with zipfile.ZipFile(out / f"{name}.csv.zip", "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(f"{name}.csv", buf.getvalue())

    d = days[-1]
    head = ["Date", "Symbol", "Security Name", "Client Name", "Buy/Sell", "Quantity Traded", "Trade Price / Wght. Avg. Price", "Remarks"]
    blk = round(price["ITC"] * 0.985, 2)
    for fname, rows in (("block.csv", [[d.strftime("%d-%b-%Y"), "ITC", "ITC LTD", "SOME GLOBAL FUND", "SELL", "36,50,00,000", f"{blk}", "-"],
                                        [d.strftime("%d-%b-%Y"), "ITC", "ITC LTD", "A MUTUAL FUND A/C LARGE CAP", "BUY", "36,50,00,000", f"{blk}", "-"]]),
                        ("bulk.csv", [[d.strftime("%d-%b-%Y"), "M&M", "MAHINDRA & MAHINDRA LTD", "<b>ODD NAME & CO</b>", "BUY", "65,00,000",
                                       f"{price['M&M']:.2f}", "-"],
                                      [d.strftime("%d-%b-%Y"), "20MICRONS", "20 MICRONS LTD", "SOMEONE", "BUY", "1,00,000", "213.00", "-"]])):
        with open(out / fname, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(head)
            w.writerows(rows)
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
