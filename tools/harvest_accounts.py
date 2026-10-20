#!/usr/bin/env python3
"""Production ptero identity harvester.

Follows the proven recipe (warm profile + real Chrome + xvfb + residential
proxy + human pacing). Creates N identities via the site's username flow and
saves them in the repo's accounts.json format:
  [{"username": "...", "token": "...", "cookie": "mlp_ai_guest_token=...",
    "identity": {...}}, ...]

Reuses ONE browser session for all accounts: once cf_clearance is in the warm
profile, each new identity is just a fresh localStorage token (page context).
"""
import asyncio
import json
import os
import random
import sys
import nodriver as uc
from nodriver.core.util import ProxyForwarder

PROFILE = "/home/stealth/ptero-profile"
OUT = "/opt/ptero-bulk-9router/accounts.json"
COUNT = int(sys.argv[1]) if len(sys.argv) > 1 else 10
UPSTREAM = ("http://7zumew4mpo-country-us-session-pterostk1-lifetime-24h:"
            "d3tvw2sx5o@geofast.hellworld.io:6969")

FIRST = ["Alex", "Jordan", "Sky", "Milo", "Nova", "Riley", "Casey", "Kai", "Luna",
         "Theo", "Ivy", "Mason", "Zara", "Leo", "Ava", "Finn", "Maya", "Noah",
         "Ruby", "Ezra", "Cole", "Wren", "Tess", "Reid", "Nell"]
LAST = ["Reed", "Stone", "Vale", "Brooks", "Hart", "Wells", "Kings", "Lane",
        "Cross", "Frost", "Parker", "Hale", "Marsh", "Quinn", "Rowe", "Blake",
        "Dane", "Fenn", "Grove", "Sawyer", "Mercer", "Voss", "Kane", "Ashby"]

rng = random.Random()


def rand_username():
    return f"{rng.choice(FIRST)} {rng.choice(LAST)}"


async def human_drift(tab, seconds):
    end = asyncio.get_event_loop().time() + seconds
    x, y = rng.uniform(300, 900), rng.uniform(200, 600)
    while asyncio.get_event_loop().time() < end:
        await tab.sleep(rng.uniform(0.2, 0.5))
        x = max(5, min(1270, x + rng.gauss(0, 45)))
        y = max(5, min(880, y + rng.gauss(0, 35)))
        try:
            await tab.mouse_move(x, y)
        except Exception:
            pass


async def main():
    from nodriver.core.util import ProxyForwarder
    fw = ProxyForwarder(proxy_server=UPSTREAM)
    await asyncio.sleep(0.5)

    browser = await uc.start(
        browser_executable_path="/usr/bin/google-chrome",
        user_data_dir=PROFILE,
        browser_args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--window-size=1366,900",
            f"--proxy-server={fw.proxy_server}",
            "--lang=en-US",
        ],
        headless=False,
        lang="en-US",
    )
    print("BROWSER_UP", flush=True)
    tab = await browser.get("about:blank")
    await tab.sleep(1)

    nav = asyncio.ensure_future(tab.get("https://ptero.pro/"))
    drift = asyncio.ensure_future(human_drift(tab, rng.uniform(2.5, 4.0)))
    await asyncio.wait_for(nav, timeout=60)
    try:
        await asyncio.wait_for(drift, timeout=10)
    except Exception:
        pass

    # wait out the challenge (warm profile usually passes in <=30s)
    for i in range(16):
        await tab.sleep(5)
        title = await tab.evaluate("document.title")
        print(f"t={(i+1)*5}s title={title!r}", flush=True)
        if title and "moment" not in title.lower():
            break
        try:
            await tab.mouse_move(rng.uniform(200, 1000), rng.uniform(200, 700))
        except Exception:
            pass

    title = await tab.evaluate("document.title")
    if not title or "moment" in title.lower():
        print("CF_STILL_BLOCKED", flush=True)
        await browser.stop()
        sys.exit(2)
    print("SITE_LOADED", flush=True)

    # dismiss welcome modal if present
    try:
        await tab.evaluate(
            "(() => { const b=[...document.querySelectorAll('button')].find("
            "x=>/^(x|dismiss|close|got it|ok|later)$/i.test(x.innerText.trim()));"
            " if (b) b.click(); return !!b; })()")
        await tab.sleep(1.5)
    except Exception:
        pass

    accounts = []
    if os.path.exists(OUT):
        with open(OUT) as f:
            try:
                accounts = json.load(f)
            except Exception:
                accounts = []
    have = {a.get("token") for a in accounts}

    for n in range(COUNT):
        username = rand_username()
        try:
            # mint a fresh identity inside the page's own JS (same pattern the
            # site itself uses: uuid-hex token saved to localStorage)
            res = await tab.evaluate(
                """(() => {
                  const t = crypto.randomUUID().replace(/-/g, '');
                  const u = %s;
                  localStorage.setItem('mlp_ai_chat_identity',
                    JSON.stringify({username: u, token: t}));
                  return t;
                })()""" % json.dumps(username))
            token = str(res or "").strip().strip('"')
            print(f"[dbg] mint raw={res!r}", flush=True)
            if not token or len(token) != 32:
                print(f"[{n+1}/{COUNT}] mint failed: {res!r}", flush=True)
                continue

            # verify the new identity: fetch usage in the CURRENT page (no
            # navigation needed - localStorage identity is read per-request).
            # Pattern proven in probe_eval.py: kick fetch, then poll a window var.
            await tab.evaluate(
                "window.__ptu='p';"
                "fetch('/wp-json/mlp/v1/usage')"
                ".then(r=>r.text().then(t=>{window.__ptu=r.status+':'+t.slice(0,120);}))")
            usage = ""
            for _k in range(6):
                await tab.sleep(1.5)
                v = await tab.evaluate("window.__ptu")
                if v and v != "p":
                    usage = str(v)
                    break
            print(f"[dbg] usage raw={usage[:100]!r}", flush=True)
            ok = isinstance(usage, str) and usage.startswith("200:")
            print(f"[{n+1}/{COUNT}] {username} token={token[:10]}… usage={usage[:80]}", flush=True)
            if ok and token not in have:
                accounts.append({
                    "username": username,
                    "token": token,
                    "cookie": f"mlp_ai_guest_token={token}",
                    "identity": {"username": username, "token": token},
                })
                have.add(token)
                with open(OUT, "w") as f:
                    json.dump(accounts, f, indent=1)
            await tab.sleep(rng.uniform(2.0, 4.0))
        except Exception as e:
            print(f"[{n+1}/{COUNT}] ERROR {str(e)[:120]}", flush=True)
            await tab.sleep(5)

    print(f"DONE total_saved={len(accounts)}", flush=True)


asyncio.run(uc.loop().run_until_complete(main()))
