"""Checks on the three-month swing pick rule. Run with:  python tests/test_picks.py

A stock is named on the night it meets the criteria, with no waiting period between picks. The checks
use made-up prices only, so they need no NSE files and no network.
"""
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import radar  # noqa: E402

RULES = dict(radar.PICK_DEFAULTS)
SESSIONS = 70


def sessions(n, start=(2026, 1, 5)):
    out, d = [], date(*start)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


DAYS = sessions(SESSIONS)


def series(drift, dp_then=50.0, dp_now=50.0, dip=None):
    """Rows for one stock: a steady daily drift, delivery % of dp_then until the last 10 sessions and dp_now
    in them, and optionally one session (`dip`) that closes 12% lower before the trend resumes."""
    rows, prev = [], 100.0
    for i, d in enumerate(DAYS):
        trend = 100.0 * (1 + drift) ** (i + 1)
        c = trend * 0.88 if i == dip else trend
        rows.append({"d": d, "pc": prev, "o": prev, "h": max(prev, c) * 1.002, "l": min(prev, c) * 0.998, "c": c,
                     "dp": dp_now if i >= SESSIONS - 10 else dp_then})
        prev = c
    return rows


def market(dip=SESSIONS - 2):
    """100 stocks. S000-S097 drift between -0.1% and +0.1% a day on flat delivery. LEAD climbs 0.25% a day
    on rising delivery. NEXT does the same a little slower, and closes under its 50-day average for the one
    session `dip`."""
    adj = {f"S{k:03d}": series(-0.001 + 0.00002 * k, 45.0 + k % 10, 45.0 + k % 10) for k in range(98)}
    adj["LEAD"] = series(0.0025, 40.0, 60.0)
    adj["NEXT"] = series(0.0024, 40.0, 60.0, dip=dip)
    return adj


def run(adj, upto, make_picks, data_dir):
    """build_picks as the nightly job calls it on session number `upto`, with its pick log kept in data_dir."""
    radar.DATA = Path(data_dir)
    days = DAYS[:upto + 1]
    cut = {s: rows[:upto + 1] for s, rows in adj.items()}
    idx = {d: {"nifty": 20000.0 + 10 * i} for i, d in enumerate(days)}
    cfg = {"pick": dict(RULES), "notes": {}}
    block, tonight = radar.build_picks(cut, days, idx, {"nifty100": sorted(adj)}, cfg, {}, days[-1], make_picks)
    live = [(x["d"], x["s"]) for x in sorted(block["list"], key=lambda x: x["d"]) if x["src"] == "live"]
    return block, tonight, live


def test_matches():
    feats = {"A": {"sc": 93.0, "ok": 1}, "B": {"sc": 89.96, "ok": 1}, "C": {"sc": 95.0, "ok": 0}, "D": {"sc": 91.0, "ok": 1},
             "E": {"sc": 89.94, "ok": 1}, "F": {"sc": 97.0, "ok": 1}, "G": {"sc": 92.0, "ok": 1}, "H": {"sc": 60.0, "ok": 1}}
    order = sorted(feats, key=lambda s: -feats[s]["sc"])
    notes = {"F": {"bias": -1, "as_of": "2026-03-01", "text": "sold"}}
    got = radar.pick_matches(feats, order, "2026-04-01", {"G"}, notes, 90.0)
    assert got == ["A", "D", "B"], got                    # every stock at the bar or above, best first; 89.96 shows as 90.0
    assert "C" not in got and "F" not in got and "G" not in got   # fails a trend check; negative note; picked inside the window
    assert "F" in radar.pick_matches(feats, order, "2026-02-01", {"G"}, notes, 90.0)   # the note is dated after that night
    assert radar.pick_matches(feats, order, "2026-04-01", set(), {}, 98.0) == []       # nothing at the bar: no pick that night
    assert radar.pick_matches(feats, order, "2026-04-01", {"G"}, notes, 0)[0] == "A"   # bar of 0: the best stock still waiting


def test_named_the_night_it_qualifies():
    adj, n1, n2 = market(), SESSIONS - 2, SESSIONS - 1
    with tempfile.TemporaryDirectory() as tmp:
        block, tonight, live = run(adj, n1, True, tmp)
        assert live == [(DAYS[n1], "LEAD")], live                   # NEXT is under its 50-day average tonight
        assert tonight["NEXT"]["ok"] == 0 and tonight["LEAD"]["sc"] >= RULES["min_score"]
        assert block["next"]["sc"] < RULES["min_score"] and "due" not in block   # nothing else at the bar, and no next-pick date
        block, tonight, live = run(adj, n2, True, tmp)
        assert live == [(DAYS[n1], "LEAD"), (DAYS[n2], "NEXT")], live   # named the very next night: no waiting period
        assert tonight["NEXT"]["ok"] == 1 and tonight["NEXT"]["sc"] >= RULES["min_score"]
        assert run(adj, n2, True, tmp)[2] == live                    # the catch-up run on the same night adds nothing
        assert block["rules"]["min_score"] == RULES["min_score"] and "every_days" not in block["rules"]


def test_several_on_one_night():
    adj, last = market(dip=None), SESSIONS - 1
    with tempfile.TemporaryDirectory() as tmp:
        block, _, live = run(adj, last, False, tmp)
        assert live == [] and block["next"]["s"] in ("LEAD", "NEXT")   # a rebuild by hand names nothing
        assert block["next"]["sc"] >= RULES["min_score"]               # ...though it shows a stock is at the bar
        block, _, live = run(adj, last, True, tmp)
        assert sorted(live) == [(DAYS[last], "LEAD"), (DAYS[last], "NEXT")], live   # both qualify together, so both are named
        scores = [x["why"]["sc"] for x in block["list"] if x["src"] == "live"]
        assert scores == sorted(scores, reverse=True), scores          # best score first
        assert block["next"]["s"] not in ("LEAD", "NEXT")              # they are no longer waiting


def test_replay_names_each_stock_once():
    adj, last = market(dip=None), SESSIONS - 1
    with tempfile.TemporaryDirectory() as tmp:
        block, _, _ = run(adj, last, False, tmp)
        bt = [(x["d"], x["s"]) for x in block["list"] if x["src"] == "bt"]
        first = DAYS[radar.PICK_HISTORY]                             # the first night with enough history to rank
        assert sorted(bt) == [(first, "LEAD"), (first, "NEXT")], bt  # counted on the first night, not on every night after
        assert block["stats"]["bt"]["n"] == 2 and block["stats"]["bt"]["open"] == 2   # bought at the next open, still held


if __name__ == "__main__":
    data = radar.DATA
    try:
        for name, fn in sorted(globals().items()):
            if name.startswith("test_") and callable(fn):
                fn()
                print("ok", name)
    finally:
        radar.DATA = data
