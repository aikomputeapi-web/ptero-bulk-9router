#!/usr/bin/env python3
"""Test: nodriver + real Chrome (xvfb headed) + authenticated residential proxy
via nodriver's ProxyForwarder + --proxy-server flag, against ptero.pro CF."""
import asyncio
import json
import nodriver as uc
from nodriver.core.util import ProxyForwarder

PROFILE = "/root/ptero-chrome-profile"
UPSTREAM = "http://7zumew4mpo-country-us-session-pterostk1-lifetime-24h:d3tvw2sx5o@geofast.hellworld.io:6969"


async def main():
    fw = ProxyForwarder(proxy_server=UPSTREAM)
    await asyncio.sleep(0.5)  # let the local listener bind
    local_proxy = fw.proxy_server
    print("LOCAL_RELAY:", local_proxy, flush=True)

    browser = await uc.start(
        browser_executable_path="/usr/bin/google-chrome",
        user_data_dir=PROFILE,
        browser_args=[
            "--disable-dev-shm-usage",
            "--window-size=1280,900",
            f"--proxy-server={local_proxy}",
        ],
        headless=False,
    )
    print("BROWSER_UP", flush=True)
    tab = await browser.get("https://ptero.pro/")
    for i in range(10):
        await tab.sleep(5)
        title = await tab.evaluate("document.title")
        print(f"t={(i+1)*5}s title={title!r}", flush=True)
        if title and "moment" not in title.lower():
            break
    title = await tab.evaluate("document.title")
    body = await tab.evaluate("document.body ? document.body.innerText.slice(0,200) : 'NOBODY'")
    ident = await tab.evaluate("localStorage.getItem('mlp_ai_chat_identity')")
    cookies = await browser.cookies.get_all()
    ptero = [c for c in cookies if c.domain and "ptero" in c.domain]
    names = {c.name: c.value[:22] + "..." for c in ptero}
    print("TITLE:", title)
    print("BODY:", json.dumps(body)[:250])
    print("IDENTITY:", ident)
    print("PTERO_COOKIES:", json.dumps(names, indent=1))
    res = await tab.evaluate(
        "fetch('/wp-json/mlp/v1/status',{headers:{'Content-Type':'application/json'}})"
        ".then(r=>r.text().then(t=>r.status+'|'+t.slice(0,220)))"
        ".catch(e=>'FETCHERR '+e.message)"
    )
    print("PAGE_FETCH:", res)
    dump = [{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path} for c in ptero]
    with open("/root/ptero_cookies.json", "w") as f:
        json.dump(dump, f, indent=1)
    print("COOKIES_SAVED", len(dump))


asyncio.run(uc.loop().run_until_complete(main()))
