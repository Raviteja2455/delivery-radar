"""Checks on how bulk and block deals are read and who is taken for an FII. Run with:  python tests/test_deals.py

They use made-up deals only, so they need no NSE files and no network.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import radar  # noqa: E402

WHO = radar.deal_classifier({})


def deal(d, s, k, cl, bs, q, p):
    return {"d": d, "s": s, "k": k, "cl": cl, "bs": bs, "q": float(q), "p": float(p)}


def test_who():
    fii = ["GOLDMAN SACHS BANK EUROPE SE", "SOCIETE GENERALE - ODI", "MORGAN STANLEY ASIA (SINGAPORE) PTE.",
           "BNP PARIBAS FINANCIAL MARKETS", "COPTHALL MAURITIUS INVESTMENT LIMITED", "GHISALLO MASTER FUND LP",
           "NORGES BANK ON ACCOUNT OF THE GOVERNMENT PENSION FUND GLOBAL", "SMALLCAP WORLD FUND, INC",
           "COMMONWEALTH OF PENNSYLVANIA PUBLIC SCHOOL EMPLOYEES RETIREMENT SYSTEM", "MORGAN STANLEY IFSC FUND",
           "INTEGRATED CORE STRATEGIES (ASIA) PTE. LTD.", "GQG PARTNERS EMERGING MARKETS EQUITY FUND"]
    fund = ["MOTILAL OSWAL MUTUAL FUND", "HSBC MUTUAL FUND", "INVESCO MUTUAL FUND", "NIPPON INDIA MF",
            "HDFC LIFE INSURANCE COMPANY LIMITED", "ADITYA BIRLA SUN LIFE INSURANCE COMPANY LIMITED", "NATIONAL PENSION SYSTEM TRUST"]
    other = ["GRAVITON RESEARCH CAPITAL LLP", "HRTI PRIVATE LIMITED", "DIXON TECHNOLOGIES (INDIA) LIMITED",
             "GOLDMAN SACHS (INDIA) SECURITIES PRIVATE LIMITED", "MORGAN STANLEY INDIA COMPANY PRIVATE LIMITED",
             "JASUB PROPERTY HOLDINGS LLP", "<b>ODD NAME & CO</b>"]
    venture = ["SVF II LIGHTBULB (CAYMAN) LIMITED", "TENCENT CLOUD EUROPE B.V.", "PEAK XV PARTNERS INVESTMENTS VI-1",
               "ACCEL INDIA IV (MAURITIUS) LIMITED", "SAGILITY B.V."]
    for names, t in ((fii, "F"), (venture, "V"), (fund, "D"), (other, "O")):
        for n in names:
            assert WHO(n) == t, (n, WHO(n), t)
    # config.json can overrule the patterns either way
    who = radar.deal_classifier({"deal_names": {"fii": ["ACME HOLDINGS"], "not_fii": ["SINGAPORE TRADERS"]}})
    assert who("Acme Holdings Ltd") == "F" and who("Singapore Traders Pvt Ltd") == "O"


def test_api_parse():
    keep = radar.deal_keeper({"HDFCBANK"}, WHO)
    text = json.dumps({"data": [
        {"BD_DT_DATE": "11-NOV-2026", "BD_SYMBOL": "HDFCBANK", "BD_SCRIP_NAME": "HDFC Bank Ltd", "BD_CLIENT_NAME": "SOME PERSON",
         "BD_BUY_SELL": "BUY", "BD_QTY_TRD": 100000, "BD_TP_WATP": 700.5, "BD_REMARKS": None},
        {"BD_DT_DATE": "11-NOV-2026", "BD_SYMBOL": "SMALLCO", "BD_SCRIP_NAME": "Small Co Ltd", "BD_CLIENT_NAME": "GOLDMAN SACHS BANK EUROPE SE",
         "BD_BUY_SELL": "BUY", "BD_QTY_TRD": 500000, "BD_TP_WATP": 120, "BD_REMARKS": "-"},
        {"BD_DT_DATE": "11-NOV-2026", "BD_SYMBOL": "SMALLCO", "BD_SCRIP_NAME": "Small Co Ltd", "BD_CLIENT_NAME": "A TRADING FIRM",
         "BD_BUY_SELL": "SELL", "BD_QTY_TRD": 500000, "BD_TP_WATP": 120, "BD_REMARKS": "-"}]})
    rows = radar.parse_deals_api(text, "BULK", keep)
    # a tracked stock keeps every deal; an untracked one only the FII's, with the company's name
    assert [(x["s"], x["cl"]) for x in rows] == [("HDFCBANK", "SOME PERSON"), ("SMALLCO", "GOLDMAN SACHS BANK EUROPE SE")], rows
    assert rows[0]["d"] == "2026-11-11" and rows[0]["p"] == 700.5 and "n" not in rows[0] and rows[1]["n"] == "Small Co Ltd"
    assert radar.parse_deals_api("<html>blocked</html>", "BULK", keep) is None
    assert radar.parse_deals_api('{"msg": "no data"}', "BULK", keep) is None
    # the same deal from the API and from bulk.csv is stored once
    csv_row = dict(rows[1], p=120.0, q=500000.0, cl="GOLDMAN  SACHS BANK EUROPE SE ")
    assert radar.deal_key(csv_row) == radar.deal_key(rows[1])


def test_csv_parse():
    keep = radar.deal_keeper({"SAGILITY"}, WHO)
    text = ('"Date","Symbol","Security Name","Client Name","Buy / Sell","Quantity Traded","Trade Price / Wght. Avg. Price","Remarks"\n'
            '"30-OCT-2026","SAGILITY","Sagility Limited","SAGILITY B.V.","SELL","56,00,00,000","42.76","-"\n'
            '"30-OCT-2026","SAGILITY","Sagility Limited","SOCIETE GENERALE","BUY","4,75,06,626","42.75","-"\n'
            '"30-OCT-2026","SMEXYZ","Sme Xyz Ltd","SOMEONE","BUY","1,000","10","-"\n')
    rows, raw = radar.parse_deals_table(text, "BULK", keep)
    assert raw == 3 and [(x["cl"], x["q"]) for x in rows] == [("SAGILITY B.V.", 56e7), ("SOCIETE GENERALE", 47506626.0)], rows
    assert radar.parse_deals_table('{"data": []}', "BULK", keep) == (None, 0)    # JSON is not this table


def test_merge_bulk_block():
    d = "2026-11-11"
    # the block trade listed again among the bulk deals: counted once
    out = radar.merge_bulk_block([deal(d, "X", "BLOCK", "GS", "BUY", 5e6, 100), deal(d, "X", "BULK", "GS", "BUY", 5e6, 100)])
    assert [x["k"] for x in out] == ["BLOCK"], out
    # the bulk row also holds 1e6 shares bought in the market at 110: only those are added
    out = radar.merge_bulk_block([deal(d, "X", "BLOCK", "GS", "BUY", 5e6, 100), deal(d, "X", "BULK", "GS", "BUY", 6e6, (5e6 * 100 + 1e6 * 110) / 6e6)])
    bulk = [x for x in out if x["k"] == "BULK"][0]
    assert round(bulk["q"]) == 1e6 and abs(bulk["p"] - 110) < 1e-6, bulk


def test_deals_block():
    d = "2026-11-11"
    deals = [deal(d, "X", "BLOCK", "GOLDMAN SACHS BANK EUROPE SE", "BUY", 5e6, 100),
             deal(d, "X", "BLOCK", "SOCIETE GENERALE - ODI", "BUY", 3e6, 100),
             deal(d, "X", "BLOCK", "SOME PROMOTER LIMITED", "SELL", 8e6, 100),
             deal(d, "Y", "BULK", "INTEGRATED CORE STRATEGIES (ASIA) PTE. LTD.", "BUY", 1e6, 50),
             deal(d, "Y", "BULK", "INTEGRATED CORE STRATEGIES (ASIA) PTE. LTD.", "SELL", 9.8e5, 50.1),
             deal(d, "Z", "BULK", "SOME PERSON", "BUY", 1e6, 10)]
    meta = {"nifty50": ["X"], "nifty100": ["X"], "nifty500": ["X", "Y"], "names": {"X": {"n": "X Ltd"}}, "cap": {"X": "L"}}
    adj = {"X": [{"d": d, "c": 105.0, "pc": 100.0}]}
    out = radar.deals_block(deals, [d], adj, {d: {"X": [100, 0, 0, 0, 105]}}, meta, WHO, d)
    rows = {(r["s"], r["cl"]): r for r in out["rows"]}
    assert ("Z", "SOME PERSON") not in rows                                   # not an FII or a fund
    gs = rows[("X", "GOLDMAN SACHS BANK EUROPE SE")]
    assert gs["t"] == "F" and gs["x"] == [["SOME PROMOTER LIMITED", "O"]] and "rt" not in gs, gs
    assert rows[("Y", "INTEGRATED CORE STRATEGIES (ASIA) PTE. LTD.")]["rt"] == 1   # bought and sold the same day
    assert out["px"] == {"X": [105.0, 5.0]} and out["g"] == {"X": 50, "Y": 500} and out["cap"] == {"X": "L"}


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
