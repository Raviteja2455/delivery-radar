# Delivery Radar

A phone-friendly page that shows, for every Nifty 100 stock, the day's delivery percentage, its 5, 10 and 20-day
averages, delivered and traded quantity, volume against its 20-day average, average trade size, futures open-interest
buildup, bulk and block deals, and a six-signal accumulation score. A market band at the top sets the size of swing
trades (green: half size; amber and red: full size; always in cash). A Picks tab names one three-month swing pick
every ten days and tracks how every pick did.

It refreshes itself every weekday night from NSE's public end-of-day files, using GitHub's free scheduled jobs.

## One-time setup (about 10 minutes)

1. **Create the repository.** On github.com, make a new **public** repository called `delivery-radar`
   (GitHub Pages is free only for public repositories). Leave it empty.
2. **Add these files** to it, keeping the folders as they are (`radar.py`, `config.json`, `requirements.txt`,
   `docs/`, `.github/workflows/nightly.yml`, `tests/`).
3. **Turn on the page.** In the repository, open Settings → Pages and set *Source* to **GitHub Actions**.
4. **Run it once.** Open the Actions tab → *Nightly NSE update* → **Run workflow**. The first run fetches about nine
   months of history and takes roughly ten minutes. If NSE stops answering part-way, the run keeps what arrived and
   the next one carries on.
5. **Open the app** at `https://<your-github-username>.github.io/delivery-radar/` and add it to your home screen.

After that it runs by itself at about 9:40 PM IST, Monday to Friday, with a catch-up run at about 11:10 PM for evenings
when NSE publishes late. GitHub can start scheduled jobs 5–30 minutes late, so expect fresh data by roughly 10 PM.

Changes to the page itself (`docs/index.html`) are published within a minute or two by the *Publish app page* job.

## The live strip

Above the regime band, the app shows GIFT Nifty, Brent crude in US$ (WTI underneath) and USD/INR, with MCX gold and
silver on a second row. Your phone fetches these itself every 20 seconds while the app is open, and pauses when it is in
the background, so they don't depend on the nightly job.

| Item | Contract shown | Delay |
|---|---|---|
| GIFT Nifty | The nearest monthly contract still trading (it switches to the next month at 3:30 PM on expiry day) | Real time |
| Brent, WTI | The most-traded contract, named after the label (Brent moves to the next month a few days before expiry) | 10 minutes |
| USD/INR | Spot rate | Real time |
| MCX Gold | The most-traded contract of the 1 kg Gold future, in ₹ per 10 g, month named after the label | Real time |
| MCX Silver | The most-traded contract of the 30 kg Silver future, in ₹ per kg, month named after the label | Real time |

Outside NSE hours, the line under the strip compares GIFT Nifty with the closing price of the NSE Nifty futures for the
same month (a gap within ±0.15% reads as a flat start). During NSE hours that line pauses, because NSE's free prices
are 15 minutes late. Quotes come from TradingView's public quote service; if it doesn't answer, CNBC (crude, USD/INR)
and Moneycontrol (GIFT Nifty, MCX) fill in and the strip says "backup feed". The last prices are kept on the phone, so
the strip still shows them, marked with their time, when you are offline.

For MCX, the app follows TradingView's continuous contract, which moves to the next month as trading shifts there ahead
of expiry; the label then changes month and the price shifts by the gap between the two contracts. It never shows
TradingView's price for a quieter month directly, because those can lag well behind the exchange. The Moneycontrol backup
asks for the next two contracts and shows the one with more open interest.

## FII activity

Inside the regime band, a table shows what foreign investors (FIIs) did in each of the last six sessions:

| Column | What it shows | Source |
|---|---|---|
| Cash | Net buying (+) or selling (−) in ₹ crore | NSE provisional FII/DII figures |
| Index fut | Change in FIIs' net index-futures contracts (long minus short) | NSE participant-wise open interest |
| Calls | Change in their net index call contracts | same |
| Puts | Change in their net index put contracts; a fall is the bullish side | same |

Green marks the side that is bullish for Nifty. Under the table, one line gives the verdict on the latest session: bullish
or bearish when cash, futures and options all agree, otherwise it leans with the majority. It also says how short or long
FIIs are in index futures; the tile beside India VIX shows that as "% long". On Nifty's weekly expiry (marked *), the day's
option changes include contracts that simply expired, so the verdict leaves options out that day.

The participant file only splits open interest by category (FII, DII, Pro, Client); no public NSE file shows individual
accounts. The regime rule still uses FIIs' 5-session cash total.

## The Swing tab (plan v2, November 2026)

The Swing tab (it was the MTF tab) runs the swing plan on every stock each night and on every trade you log.

| Rule | What the app checks |
|---|---|
| Core | Not a check: long-term money sits in a Nifty 50 index fund or ETF. HDFC Bank, ICICI Bank, Reliance and Bharti Airtel are about a third of the index, so it catches the gap and short-covering rallies this tab can't |
| Leverage | None. Cash delivery only (leverage cap 1×). If you raise the cap, MTF applies in amber and red only, up to 1.5× |
| Market regime | Green (FIIs net buyers, Nifty above its 50- and 200-day averages): half size. Amber: full size. Red (FIIs sold over ₹10,000 cr in 5 sessions, India VIX above 18, or Nifty below its 50-day average): full size |
| Entry | Footprint score 4+; close above the previous 10-day high with delivery % above its 20-day average; futures long buildup; stop within 10% of the close (was 5%), placed 0.25% under the 5-session low |
| Personal limits | Not a stock you already own; no negative institutional note; at most 4 open trades and 2 per sector |
| Size | Risk 2% of the pot (₹2,000 on ₹1 lakh) ÷ stop distance, with no more than a quarter of the pot in one trade; both halve in green |
| Costs (Zerodha) | Delivery brokerage is free; STT 0.1% each side, stamp duty 0.015% on buying, DP charge on selling. MTF would add 0.04% a day on the funded amount, ₹15 + GST to pledge and to unpledge, brokerage ₹20 or 0.3% per order |
| Exits | A close below the stop; not up 3% by day 10; day 20 at the latest |
| Kill switch | Logged trades down 10% of the pot: half size for 30 days |
| Scale-up | Pot to ₹2 lakh only after 10 closed trades with a positive average, still in cash |

Saved settings from plan v1 keep everything except the leverage cap and the stop limit, which reset to 1× and 10% once.

Every number in the rules table is a setting under *Your rules and holdings* in the app. Your settings, holdings and
logged trades are stored only in your phone's browser, never in this public repository; use *Back up or move your
trades* to copy them to another device.

Each ready stock shows the share quantity, your money (and any funded amount), the stop, the loss if the stop is hit,
the day-10 and day-20 dates, and the cost and break-even move to each. On a monthly F&O expiry day the futures reading
is skipped, so no stock shows as ready that day.

**Institutional notes** live in `config.json` under `notes`: `"bias": 1` marks positive institutional buying, `-1`
keeps a stock out of swing trades, `0` is information only. Update them when quarterly shareholding patterns come out (about
three weeks after each quarter ends) and after the monthly mutual fund portfolio disclosures (around the 10th).

### Why plan v2

In the late-October rally the old rules took none of the stocks people noticed:

| Stock | Move | What blocked it |
|---|---|---|
| Reliance | +12.5% (30 Oct to 4 Nov), +11.6% of it on 2 Nov, which opened 5.4% higher | The gap put the stop 11.6–12.3% away (limit 5%) on 2, 3 and 4 Nov; 2 Nov was short covering, and on 3 Nov the stop alone blocked it |
| Bharti Airtel | +9.3% (23 Oct to 4 Nov) | Broke out on 27 Oct (monthly expiry, so no futures reading; stop 6.2%), then 2 and 3 Nov, both on short covering rather than a long buildup |
| HDFC Bank | +8.3% (27 Oct to 4 Nov) | Broke out only on 4 Nov, on short covering, with an 8.2% stop |
| ICICI Bank | +3.4% (28 Oct to 4 Nov) | Never closed above its 10-day high |

The question was whether different rules would have done better over time. Backtest on Nifty 50 stocks (the January
2020 list for 2020–24, so the test isn't only today's winners), a ₹1 lakh pot, signals at the close, entries at the next
open, Zerodha charges and MTF interest included. Each step adds one change; brackets show the worst drop from a peak:

| Step | Apr 2020 – Jul 2024 (Nifty +195%) | Oct 2024 – Nov 2026 (Nifty −7.1%) |
|---|---|---|
| Old MTF rules | +1.9% (19.8%) | −29.9% (37.2%) |
| 1. Cash instead of MTF | +14.7% (10.9%) | −7.4% (12.6%) |
| 2. Half size in green | +13.8% (7.3%) | −1.2% (6.4%) |
| 3. Stops up to 10% instead of 5% = **plan v2** | **+66.2% (14.1%)** | **+3.8% (8.6%)** |

Plan v2 beat the old rules in four of five sub-periods and nearly tied the fifth: +30.9% vs −9.4% (Apr 2020–Dec 2021),
+16.6% vs −1.0% (2022–Mar 2023), +10.9% vs +11.5% (Apr 2023–Jul 2024), −2.1% vs −18.0% (Oct 2024–Sep 2025) and
+5.1% vs −11.4% (Oct 2025–Nov 2026).

Changes tested on top of plan v2 and rejected:

| Change | Apr 2020 – Jul 2024 | Oct 2024 – Nov 2026 |
|---|---|---|
| Accept short covering as well as long buildup (would have caught Airtel and HDFC Bank) | +28.4% (14.8%) | −1.0% (15.2%) |
| MTF 1.5× in amber and red | +63.6% (20.0%) | −4.4% (12.9%) |
| Full size in green too | +80.4% (14.1%) | −9.9% (13.3%) |
| Skip green entirely | +50.3% (14.1%) | +3.8% (7.9%) |
| No day-10 check | +51.3% (11.0%) | −0.9% (12.0%) |
| Hard exit at day 30 | +76.5% (11.7%) | −11.0% (14.7%) |

Why the stop limit mattered: the old 5% cap threw out the strongest breakouts, whose 5-session low sits further away.
Trades with 5–10% stops won 60% of the time (+2.17% average) in 2020–24 and 45% (+0.48%) in 2024–26, against 55%
(+1.16%) and 39% (−0.29%) for stops under 5%. Sizing by risk keeps the loss at the stop the same either way.

Same signals in cash at full size, split by the market regime on the signal day:

| Window | Green | Amber | Red |
|---|---|---|---|
| Apr 2020 – Jul 2024 | 99 trades, 57% winners, +₹28,048 | 1 trade | 116 trades, 60% winners, +₹50,454 |
| Oct 2024 – Nov 2026 | 41 trades, 34% winners, −₹14,731 | 17 trades, 59% winners, +₹11,324 | 57 trades, 44% winners, −₹6,446 |

Trailing stops and intraday stop orders came out about the same as the closing-basis stop, so the exits are unchanged.
The backtest's regime leaves out the FII cash leg (no history), and July to September 2024 is used to warm up the
indicators. Results shift by several points with which trades fill the four slots, so read the direction, not the
decimals. Past results don't promise future ones; this is not investment advice.

## The Picks tab (November 2026)

Every night the job ranks all Nifty 100 stocks. Every ten days it names one pick, aiming for at least +5% within three
months, and it keeps score on every pick.

| Step | Rule |
|---|---|
| Trend checks | Close above a rising 50-day average; not more than 8% above the 20-day average, and not up more than 8% in 5 sessions |
| Score (0–100) | Percentile among the ranked stocks on: 3-month return (30), 1-month return (15), delivery % of the last 10 sessions against the 50 before (25), up days minus down days on above-average delivery over 20 sessions (15), closeness to the 3-month high (15) |
| Pick | The best score that passes the checks, has no negative institutional note, and was not picked in the last 91 days. If nothing passes, the rule looks again the next night |
| Trade | Buy at the next session's open; sell at +5%; exit on the first close 8% or more below the buy price, or 91 days after buying |

The four numbers (10 days, +5%, 91 days, −8%) are the `pick` block in `config.json`. A live pick keeps the numbers it
was made with. Live picks are saved in `data/picks.json`, so they stay on record after the day files they were scored
from are deleted, and a picked stock keeps being downloaded even if it leaves the index.

**The screener** lists every pick with its buy price, last or exit price, result, best and worst point, days held,
result against the Nifty 50 and status (open, target hit, stopped out, time up). It has two sets:

- **Live picks**: what the nightly run actually published.
- **Back-test**: the same rule replayed on the stored history (about nine months, growing to fourteen), on the same
  ten-day grid counted back from the first live pick. It uses today's Nifty 100 list throughout, and nobody traded it.

Each set shows a comparison line: every ranked stock bought on the same dates with the same exits. A large-cap stock
touches +5% at some point in three months more often than not, so the rule is only worth following if it beats that
line. With a +5% target and a −8% stop, about 62% of closed picks must reach the target just to break even. Charges are
not deducted (about 0.25% for a delivery round trip). The rule itself has no long back-test behind it yet; the replay
and the live record are its evidence.

The Swing tab still runs only on the Nifty 50, the stocks plan v2 was tested on. Each stock's page shows its pick
score and rank, and the Stocks tab can be sorted by it.

## Adding stocks outside the Nifty 100

Edit `config.json` on GitHub and list NSE symbols, for example:

```json
{
  "extra_symbols": ["TMCV", "IRCTC"]
}
```

The next run picks them up and back-fills their history. Nifty 50 and Nifty 100 changes (new entrants, exits) are
picked up automatically from NSE's own lists. Added stocks are not ranked for picks.

## What each number means

| Item | Definition |
|---|---|
| Delivery % | NSE's deliverable quantity ÷ traded quantity for the day (EQ series) |
| 5D / 10D / 20D average | Simple average of daily delivery % over the last 5, 10, 20 sessions, today included |
| Delivered qty vs 5-day avg | Today's deliverable quantity ÷ average of the previous 5 sessions |
| Volume × | Today's traded quantity ÷ average of the previous 20 sessions |
| Average trade | Turnover ÷ number of trades; larger tickets suggest bigger participants |
| Accumulation / distribution day | Up / down day with delivery % above its previous 20-session average |
| Futures buildup | Price change against the change in futures open interest summed over all live expiries; skipped on expiry day |
| Deal "held" | Close is at or above the latest bulk/block deal price in the last 10 sessions |

The six score signals: delivery % above its 20-day average; more accumulation than distribution days in the last 10;
futures long buildup; close above its 20-day average price; close above the previous 10-day high; delivered quantity at
least 1.5× its 5-day average.

Prices and quantities are adjusted for splits and bonuses using NSE's adjusted previous close.

## If a nightly run fails

GitHub emails you when a scheduled run fails. The usual cause is NSE refusing GitHub's servers for a while; the next
run usually succeeds, and any missed days are filled in automatically. If NSE keeps refusing, the same script runs on
any computer with Python: `pip install -r requirements.txt` then `python radar.py update`, and open `docs/index.html`
through a local web server (`python -m http.server -d docs`).

## For developers

`python tests/make_sample.py sample 2026-10-23` writes made-up files in NSE's exact layouts, and
`python radar.py update --source-dir sample --today 2026-10-23` runs the whole pipeline offline against them.

Data source: NSE public archives (sec_bhavdata_full, F&O UDiFF bhavcopy, ind_close_all, bulk.csv, block.csv,
fao_participant_oi) and the NSE provisional FII/DII figures. For information only; not investment advice.
