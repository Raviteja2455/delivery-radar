"""End-to-end check of Delivery Radar's live strip on a GitHub runner: real fonts, real quote sources.

python e2e.py <docs_dir> <out_dir> <local|live>
  local: the browser loads https://raviteja2455.github.io/delivery-radar/ but the page files come from <docs_dir>,
         so the quote sources see the same Origin as the phone does, before anything is published.
  live:  the browser loads the published site as is.
"""
import json
import mimetypes
import time
from pathlib import Path
import sys

from playwright.sync_api import sync_playwright

DOCS, OUT, MODE = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
OUT.mkdir(parents=True, exist_ok=True)
BASE = "https://raviteja2455.github.io/delivery-radar/"
HOSTS = ("scanner.tradingview.com", "quote.cnbc.com", "priceapi.moneycontrol.com")
UA = ("Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) "
      "SamsungBrowser/27.0 Chrome/125.0.0.0 Mobile Safari/537.36")
REPORT = []
# Cross-check: ask Moneycontrol, from the page itself, for the contracts the strip is showing.
CROSS = """async () => {
  const c = JSON.parse(localStorage.getItem('dr-live') || 'null');
  if (!c) return null;
  const iso = (e) => `${Math.floor(e / 1e4)}-${String(Math.floor(e / 100) % 100).padStart(2, '0')}-${String(e % 100).padStart(2, '0')}`;
  const res = { src: c.src, mcxExp: c.mcxExp };
  for (const m of ['gold', 'silver']) {
    const x = c[m];
    if (!x || !x.exp) { res[m] = { shown: x || null }; continue; }
    try {
      const j = await (await fetch(`https://priceapi.moneycontrol.com/pricefeed/mcx/commodityfutures/${m.toUpperCase()}?expiry=${iso(x.exp)}`, { cache: 'no-store' })).json();
      res[m] = { shown: x.v, mon: x.mon, exp: x.exp, mc: j.data && +j.data.lastPrice, mcMonth: j.data && j.data.contractMonth,
                 mcUpd: j.data && j.data.lastupd };
    } catch (e) { res[m] = { shown: x.v, error: String(e) }; }
  }
  return res;
}"""


def serve_local(route):
    path = route.request.url.split("?")[0][len(BASE):] or "index.html"
    f = DOCS / path
    if not f.is_file():
        route.fulfill(status=404, body="not found")
        return
    ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
    route.fulfill(status=200, body=f.read_bytes(), headers={"content-type": ctype, "cache-control": "no-store"})


def scenario(pw, name, width=390, dark=False, block=(), wait=r"^(Live|Markets closed)", watch_refresh=False,
             full=False, cross=False):
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={"width": width, "height": 900}, device_scale_factor=3, is_mobile=True,
                              has_touch=True, user_agent=UA, color_scheme="dark" if dark else "light",
                              timezone_id="Asia/Kolkata")
    page = ctx.new_page()
    log = {"scenario": name, "width": width, "dark": dark, "blocked": list(block), "requests": [], "errors": []}
    page.on("console", lambda m: m.type in ("error", "warning") and log["errors"].append(m.text[:200]))
    page.on("pageerror", lambda e: log["errors"].append("pageerror: " + str(e)[:200]))
    page.on("requestfailed", lambda r: any(h in r.url for h in HOSTS) and log["requests"].append(
        {"host": r.url.split("/")[2], "path": r.url.split("/", 3)[-1][:90], "failed": r.failure}))
    page.on("response", lambda r: any(h in r.url for h in HOSTS) and log["requests"].append(
        {"host": r.url.split("/")[2], "path": r.url.split("/", 3)[-1][:90], "status": r.status,
         "acao": r.headers.get("access-control-allow-origin")}))
    if MODE == "local":
        page.route(BASE + "**", serve_local)
    for host in block:
        page.route(f"https://{host}/**", lambda r: r.abort())
    t0 = time.time()
    try:
        page.goto(BASE, wait_until="domcontentloaded")
        page.wait_for_function("re => new RegExp(re).test(document.querySelector('#live .when').textContent.trim())",
                               arg=wait, timeout=25000)
        log["seconds_to_quotes"] = round(time.time() - t0, 1)
        page.wait_for_timeout(2500)
        log["fonts"] = page.evaluate("""() => ({barlow: document.fonts.check('400 15px Barlow'),
            semi: document.fonts.check('600 18px "Barlow Semi Condensed"')})""")
        log["text"] = page.inner_text("#live")
        log["tiles"] = page.evaluate("() => [...document.querySelectorAll('#live .lf[aria-label]')].map(e => e.getAttribute('aria-label'))")
        log["clipped"] = page.evaluate("""() => [...document.querySelectorAll('#live .lf > div, #live .when')]
            .filter(e => e.scrollWidth > e.clientWidth + 1).map(e => e.textContent)""")
        log["page_hscroll"] = page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth")
        shot = OUT / f"{name}.png"
        if full:
            page.screenshot(path=str(shot))
        else:
            page.locator("#apphead").screenshot(path=str(shot))
        page.wait_for_selector("#regime:not([hidden])", timeout=15000)
        page.locator("#regime").screenshot(path=str(OUT / f"{name}-regime.png"))
        log["regime_text"] = page.inner_text("#regime")
        log["regime_clipped"] = page.evaluate("""() => [...document.querySelectorAll('#regime td, #regime th, #regime .fig .v, #regime .fig .s')]
            .filter(e => e.scrollWidth > e.clientWidth + 1).map(e => e.textContent)""")
        log["table_scrolls"] = page.evaluate("() => { const t = document.querySelector('#regime .fii .tbl'); return t ? t.scrollWidth > t.clientWidth + 1 : null }")
        if cross:
            log["cross_check"] = page.evaluate(CROSS)
        if watch_refresh:
            first = page.inner_text("#live .when")
            page.wait_for_timeout(23000)
            log["after_23s"] = page.inner_text("#live .when")
            log["refreshed"] = page.inner_text("#live .when") != first
    except Exception as e:  # noqa: BLE001
        log["failure"] = repr(e)[:400]
        try:
            log["text"] = page.inner_text("#live")
            page.screenshot(path=str(OUT / f"{name}-FAILED.png"))
        except Exception:  # noqa: BLE001
            pass
    log["tv_calls"] = sum(1 for r in log["requests"] if r["host"] == HOSTS[0])
    browser.close()
    REPORT.append(log)
    print(json.dumps(log, ensure_ascii=False))


with sync_playwright() as pw:
    scenario(pw, "1-live-390-light")
    scenario(pw, "2-live-390-dark", dark=True)
    scenario(pw, "3-live-360", width=360)
    scenario(pw, "4-live-412", width=412)
    if MODE == "local":
        scenario(pw, "5-tradingview-blocked", block=(HOSTS[0],), cross=True)
        scenario(pw, "6-all-blocked", block=HOSTS, wait=r"reachable")

(OUT / "report.json").write_text(json.dumps(REPORT, indent=1, ensure_ascii=False))
