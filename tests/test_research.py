"""Checks on the research screen's arithmetic. Run with:  python tests/test_research.py

They use made-up numbers only, so they need no NSE files and no network.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import radar  # noqa: E402

R = dict(radar.RESEARCH_DEFAULTS)


def rows(prices, start=(2026, 1, 5), splits=None):
    """Adjusted-history rows for a list of (open, high, low, close); weekdays only."""
    from datetime import date, timedelta
    out, d, prev = [], date(*start), prices[0][3]
    for o, h, lo, c in prices:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out.append({"d": d.isoformat(), "pc": prev, "o": o, "h": h, "l": lo, "c": c, "v": 1e6, "dq": 5e5, "tl": 1e4, "nt": 1e4, "dp": 50.0})
        prev, d = c, d + timedelta(days=1)
    return out


def pick(day, close, **kw):
    p = {"d": day, "s": "TEST", "c0": close, "fv": 150.0, "bb": 120.0, "tgt": 150.0, "stop_pct": 15.0, "days": 365, "st": "new", "ld": day, "last": close}
    p.update(kw)
    return p


def fundamentals(**kw):
    f = {"px": 100.0, "cur": "INR", "mcap": 5e11, "sector": "X", "industry": "Y", "eps": 10.0, "bvps": 40.0, "roe": 25.0, "roa": 15.0,
         "de": 0.1, "icov": 30.0, "rev_g": 15.0, "rev_c5": 15.0, "eps_g": 15.0, "eps_c5": 18.0, "sgr": 20.0, "ni": 1e10, "fcf": 8e9,
         "cfo": 1e10, "dy": 1.0, "pio": 7.0, "eps_f": 11.5, "tgt": 150.0, "tgt_n": 12.0, "sma200": 90.0, "p6m": 5.0, "sloan": 5.0, "next": None}
    f.update(kw)
    return f


def test_dcf():
    base = radar.dcf_value(10, 25, 12, 12, 5)
    assert 120 < base < 200, base                                  # a 12% grower with a 25% return on equity: 12-20 times earnings
    assert radar.dcf_value(10, 25, 15, 12, 5) > base               # more growth is worth more when it earns above its cost
    assert radar.dcf_value(10, 25, 12, 14.5, 5) < base             # a higher return demanded is worth less
    assert radar.dcf_value(10, 40, 12, 12, 5) > base               # the same growth needs less reinvestment at a higher return
    assert radar.dcf_value(10, 10, 12, 12, 5) < base * 0.6         # growth that earns less than it costs is worth little


def test_growth_and_earnings():
    f = fundamentals(rev_c5=20.0, eps_c5=30.0, rev_g=10.0)
    assert radar.research_growth(f, 15.0) == 15.0                  # the lower five-year rate, pulled toward a slower last year, then capped
    assert radar.research_growth(fundamentals(rev_c5=10.0, eps_c5=30.0, rev_g=4.0), 15.0) == 7.0
    assert radar.research_growth(fundamentals(rev_c5=-3.0), 15.0) == 0.0
    assert radar.research_growth(fundamentals(sgr=6.0), 12.0, fin=True) == 6.0   # a lender can't outgrow its retained profit
    boom = fundamentals(eps=20.0, eps_g=100.0)                     # earnings doubled in a year
    assert abs(radar.normal_eps(boom, 10.0) - 11.0) < 1e-9         # valued on last year's 10 grown at 10%, not on 20
    assert radar.normal_eps(fundamentals(eps_f=8.0), 15.0) == 8.0  # never more than analysts expect next year


def test_fair_value_and_margin():
    f = fundamentals()
    a = radar.research_assess("T", f, 100.0, "L", False, 20.0, R)
    lens = sorted(v for v in a["lens"].values() if v)
    assert len(lens) == 4 and a["fv"] == lens[1]                   # the second-lowest of the four methods
    assert abs(a["buy_below"] - a["fv"] * (1 - R["discount_large"] / 100)) < 1e-9
    small = radar.research_assess("T", f, 100.0, "S", False, 20.0, R)
    assert small["buy_below"] / small["fv"] < a["buy_below"] / a["fv"]   # a small cap needs a bigger margin of safety
    assert small["lens"]["dcf"] < a["lens"]["dcf"]                 # and is discounted at a higher rate
    wild = radar.research_assess("T", fundamentals(tgt=900.0, dy=30.0), 100.0, "L", False, 80.0, R)
    assert wild["fv"] <= 200.0                                     # no method may put fair value above twice the price
    assert radar.research_assess("T", fundamentals(eps=-1.0), 100.0, "L", False, 20.0, R) is None
    assert radar.research_assess("T", fundamentals(tgt_n=2.0), 100.0, "L", False, None, R)["fv"] is None  # only two methods: no fair value


def test_checks():
    f = fundamentals()
    a = radar.research_assess("T", f, 100.0, "L", False, 20.0, R)
    a["buy_below"] = 110.0
    q, rest = radar.research_checks(f, a, "L", False, 50.0, 100.0, 90.0, 20000.0, "2026-11-11")
    assert all(ok for _, ok in q + rest)
    fail = lambda key, **kw: dict(sum(radar.research_checks(fundamentals(**kw), a, kw.pop("cap", "L"), False, 50.0, 100.0, 90.0, 20000.0, "2026-11-11"), []))[key]
    assert not fail("debt", de=1.2) and not fail("debt", icov=2.0)
    assert not fail("growth", rev_c5=5.0) and not fail("growth", eps_g=-4.0)
    assert not fail("strength", pio=4.0)
    assert not fail("cash", fcf=-1.0) and not fail("cash", sloan=31.0)
    assert not fail("results", next="2026-11-13") and fail("results", next="2026-11-20") and fail("results", next="2026-11-01")
    assert not dict(radar.research_checks(f, a, "L", False, 50.0, 100.0, 105.0, 20000.0, "2026-11-11")[1])["trend"]   # below its 200-day average
    assert not dict(radar.research_checks(f, a, "L", False, 50.0, 111.0, 90.0, 20000.0, "2026-11-11")[1])["value"]    # above the buy-below price
    assert not dict(radar.research_checks(f, a, "L", False, 2.0, 100.0, 90.0, 20000.0, "2026-11-11")[0])["liquid"]    # too thinly traded
    lender = fundamentals(tgt_n=3.0, roa=1.4)
    assert not dict(radar.research_checks(lender, a, "L", True, 50.0, 100.0, 90.0, 20000.0, "2026-11-11")[0])["strength"]


def test_tracking():
    flat = [(100, 101, 99, 100)]
    # bought at the next open, then the target is reached on a close
    r = rows(flat + [(101, 103, 100, 102), (104, 150, 103, 149), (149, 156, 148, 155), (155, 160, 150, 158)])
    p = pick(r[0]["d"], 100.0)
    radar.research_track(p, r, r[-1]["d"])
    assert (p["st"], p["e"], p["xd"], p["ret"]) == ("target", 101, r[3]["d"], round((155 / 101 - 1) * 100, 2)), p
    # the same history seen one day earlier: still open, a high above the target doesn't count, only a close
    p = pick(r[0]["d"], 100.0)
    radar.research_track(p, r, r[2]["d"])
    assert p["st"] == "open" and not p.get("done") and p["peak"] > 48, p
    # stopped out on a close 15% under the buy price
    r = rows(flat + [(100, 100, 95, 96), (96, 97, 84, 86), (86, 87, 80, 84)])
    p = pick(r[0]["d"], 100.0)
    radar.research_track(p, r, r[-1]["d"])
    assert (p["st"], p["xd"]) == ("stopped", r[3]["d"]) and p["ret"] == -16.0, p
    # opened above the buy-below price: the pick lapses and nothing is bought
    r = rows(flat + [(125, 126, 120, 121), (121, 122, 119, 120)])
    p = pick(r[0]["d"], 100.0)
    radar.research_track(p, r, r[-1]["d"])
    assert p["st"] == "lapsed" and p["done"] and p["ret"] is None, p
    # time runs out
    r = rows(flat + [(100, 101, 99, 100)] * 30)
    p = pick(r[0]["d"], 100.0, days=20)
    radar.research_track(p, r, r[-1]["d"])
    assert p["st"] == "timeup", p
    # the entry session has not traded yet
    r = rows(flat)
    p = pick(r[0]["d"], 100.0)
    radar.research_track(p, r, r[-1]["d"])
    assert p["st"] == "new" and "e" not in p
    # a 1:2 split after the pick: history is restated at half, so the pick's prices are too
    r = rows([(50, 50.5, 49.5, 50), (50.5, 51.5, 50, 51), (51, 76, 50.5, 75.5)])
    p = pick(r[0]["d"], 100.0)
    radar.research_track(p, r, r[-1]["d"])
    assert p["k"] == 0.5 and p["tgt_px"] == 75.0 and p["e"] == 50.5 and p["st"] == "target", p


def test_hold():
    assert radar.hold_broken(fundamentals(), False) is None
    assert "negative" in radar.hold_broken(fundamentals(eps=-2.0), False)
    assert "return on equity" in radar.hold_broken(fundamentals(roe=8.0), False)
    assert "debt" in radar.hold_broken(fundamentals(de=1.8), False)
    assert radar.hold_broken(fundamentals(de=6.0), True) is None   # borrowing is a lender's raw material


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
