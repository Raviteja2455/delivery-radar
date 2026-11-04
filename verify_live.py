"""Temporary: check the published Delivery Radar page for swing plan v2 and save screenshots."""
import json, time
from playwright.sync_api import sync_playwright

URL = "https://raviteja2455.github.io/delivery-radar/"
V1 = {"settings": {"pot": 100000, "maxLev": 2, "holdings": []}, "positions": [], "closed": [], "killUntil": None}
out = []
with sync_playwright() as pw:
    b = pw.chromium.launch()
    for name, book, dark in (("fresh", None, False), ("v1-book", V1, True)):
        ctx = b.new_context(viewport={"width": 390, "height": 900}, device_scale_factor=2, timezone_id="Asia/Kolkata",
                            color_scheme="dark" if dark else "light")
        if book:
            ctx.add_init_script("if (!sessionStorage.getItem('s')) { localStorage.setItem('dr-mtf', %s); sessionStorage.setItem('s', '1'); }" % json.dumps(json.dumps(book)))
        p = ctx.new_page(); errs = []
        p.on("pageerror", lambda e: errs.append(str(e)))
        for attempt in range(6):
            p.goto(URL + "?v=%d#mtf" % time.time(), wait_until="networkidle")
            p.wait_for_selector("#mtf-view:not([hidden]) .regime", timeout=20000)
            if "did better in both" in p.inner_text("#mtf-view .regime"):
                break
            time.sleep(30)
        out.append(f"[{name}] tabs: {p.inner_text('nav.tabs')!r}")
        out.append(f"[{name}] mode: {p.inner_text('#mtf-view .regime .verdict')!r}")
        out.append(f"[{name}] why: {p.inner_text('#mtf-view .regime .why')!r}")
        lev = p.evaluate("() => [...document.querySelectorAll('#mtf-view label')].filter(l => l.textContent.startsWith('Leverage cap')).map(l => l.querySelector('input').value)")
        out.append(f"[{name}] leverage cap input: {lev}")
        stopmax = p.evaluate("() => [...document.querySelectorAll('#mtf-view label')].filter(l => l.textContent.startsWith('Widest stop')).map(l => l.querySelector('input').value)")
        out.append(f"[{name}] widest stop input: {stopmax}")
        out.append(f"[{name}] ready: {p.evaluate('() => [...document.querySelectorAll(\"#mtf-view article.cand h3 span:first-child\")].map(e => e.textContent)')}")
        p.screenshot(path=f"live-{name}-swing.png")
        p.evaluate("() => document.querySelectorAll('#mtf-view details').forEach(d => d.open = true)")
        rules = p.locator("#mtf-view details:has(summary:text('The rules this tab applies'))")
        out.append(f"[{name}] rules first item: {rules.locator('li').first.inner_text()[:160]!r}")
        out.append(f"[{name}] rules count: {rules.locator('li').count()}")
        p.goto(URL + "?v=%d" % time.time(), wait_until="networkidle")
        p.wait_for_selector("#regime:not([hidden]) .verdict", timeout=20000)
        out.append(f"[{name}] band: {p.inner_text('#regime .verdict')!r}")
        out.append(f"[{name}] fii line: {p.inner_text('#regime .fii .view') if p.locator('#regime .fii .view').count() else p.inner_text('#regime').splitlines()[-3:]!r}")
        p.locator("#regime").screenshot(path=f"live-{name}-band.png")
        out.append(f"[{name}] hscroll: {p.evaluate('() => document.documentElement.scrollWidth > innerWidth')}, errors: {errs}")
        ctx.close()
    b.close()
open("live_report.txt", "w").write("\n".join(out) + "\n")
print("\n".join(out))
