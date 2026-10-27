# Delivery Radar

A phone-friendly page that shows, for every Nifty 50 stock, the day's delivery percentage, its 5, 10 and 20-day
averages, delivered and traded quantity, volume against its 20-day average, average trade size, futures open-interest
buildup, bulk and block deals, and a six-signal accumulation score. A market band at the top applies the MTF regime
rule (red: cash only, amber: up to 1.5×, green: up to 2×).

It refreshes itself every weekday night from NSE's public end-of-day files, using GitHub's free scheduled jobs.

## One-time setup (about 10 minutes)

1. **Create the repository.** On github.com, make a new **public** repository called `delivery-radar`
   (GitHub Pages is free only for public repositories). Leave it empty.
2. **Add these files** to it, keeping the folders as they are (`radar.py`, `config.json`, `requirements.txt`,
   `docs/`, `.github/workflows/nightly.yml`, `tests/`).
3. **Turn on the page.** In the repository, open Settings → Pages and set *Source* to **GitHub Actions**.
4. **Run it once.** Open the Actions tab → *Nightly NSE update* → **Run workflow**. The first run fetches about five
   months of history and takes roughly five minutes.
5. **Open the app** at `https://<your-github-username>.github.io/delivery-radar/` and add it to your home screen.

After that it runs by itself at about 9:40 PM IST, Monday to Friday, with a catch-up run at about 11:10 PM for evenings
when NSE publishes late. GitHub can start scheduled jobs 5–30 minutes late, so expect fresh data by roughly 10 PM.

Changes to the page itself (`docs/index.html`) are published within a minute or two by the *Publish app page* job.

## The live strip

Above the regime band, the app shows GIFT Nifty, Brent crude in US$ (WTI underneath) and USD/INR. Your phone fetches
these itself every 20 seconds while the app is open, and pauses when it is in the background, so they don't depend on
the nightly job.

| Item | Contract shown | Delay |
|---|---|---|
| GIFT Nifty | The nearest monthly contract still trading (it switches to the next month at 3:30 PM on expiry day) | Real time |
| Brent, WTI | The most-traded contract, named after the label (Brent moves to the next month a few days before expiry) | 10 minutes |
| USD/INR | Spot rate | Real time |

Outside NSE hours, the line under the strip compares GIFT Nifty with the closing price of the NSE Nifty futures for the
same month (a gap within ±0.15% reads as a flat start). During NSE hours that line pauses, because NSE's free prices
are 15 minutes late. Quotes come from TradingView's public quote service; if it doesn't answer, CNBC (crude, USD/INR)
and Moneycontrol (GIFT Nifty) fill in and the strip says "backup feed". The last prices are kept on the phone, so the
strip still shows them, marked with their time, when you are offline.

## The MTF tab

The MTF tab runs the whole MTF plan on every stock each night and on every trade you log.

| Rule | What the app checks |
|---|---|
| Market regime | Red (FIIs sold over ₹10,000 cr in 5 sessions, India VIX above 18, or Nifty below its 50-day average): cash only, half size. Amber: up to 1.5×. Green (FIIs net buyers, Nifty above its 50- and 200-day averages): up to 2× |
| Entry | Footprint score 4+; close above the previous 10-day high with delivery % above its 20-day average; futures long buildup; stop within 5% of the close, placed 0.25% under the 5-session low |
| Personal limits | Not a stock you already own; no negative institutional note; at most 4 open trades and 2 per sector |
| Size | Risk 2% of the pot (₹2,000 on ₹1 lakh) ÷ stop distance, with no more than a quarter of the pot of your own money in one trade |
| Costs (Zerodha) | 0.04% a day on the funded amount, ₹15 + GST to pledge and to unpledge, brokerage ₹20 or 0.3% per MTF order, STT 0.1% each side, stamp duty 0.015% on buying, DP charge on selling |
| Exits | A close below the stop; not up 3% by day 10; day 20 at the latest |
| Kill switch | Logged trades down 10% of the pot: MTF off for 30 days |
| Scale-up | Pot to ₹2 lakh only after 10 closed trades with a positive average, still at 2× or less |

Every number in that table is a setting under *Your rules and holdings* in the app. Your settings, holdings and
logged trades are stored only in your phone's browser, never in this public repository; use *Back up or move your
trades* to copy them to another device.

Each ready stock shows the share quantity, your money and the funded amount, the stop, the loss if the stop is hit,
the day-10 and day-20 dates, and the cost and break-even move to each. On a monthly F&O expiry day the futures reading
is skipped, so no stock shows as ready that day.

**Institutional notes** live in `config.json` under `notes`: `"bias": 1` marks positive institutional buying, `-1`
keeps a stock out of MTF, `0` is information only. Update them when quarterly shareholding patterns come out (about
three weeks after each quarter ends) and after the monthly mutual fund portfolio disclosures (around the 10th).

## Adding stocks outside the Nifty 50

Edit `config.json` on GitHub and list NSE symbols, for example:

```json
{
  "extra_symbols": ["TMCV", "IRCTC"]
}
```

The next run picks them up and back-fills their history. Nifty 50 changes (new entrants, exits) are picked up
automatically from NSE's own list.

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

Data source: NSE public archives (sec_bhavdata_full, F&O UDiFF bhavcopy, ind_close_all, bulk.csv, block.csv) and the
NSE provisional FII/DII figures. For information only; not investment advice.
