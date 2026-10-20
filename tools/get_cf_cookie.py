import asyncio
import json
import nodriver as uc
from nodriver.core.util import ProxyForwarder


async def main():
    fw = ProxyForwarder(proxy_server=(
        "http://7zumew4mpo-country-us-session-pterostk1-lifetime-24h:"
        "d3tvw2sx5o@geofast.hellworld.io:6969"))
    await asyncio.sleep(0.5)
    browser = await uc.start(
        browser_executable_path="/usr/bin/google-chrome",
        user_data_dir="/home/stealth/ptero-profile",
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
    tab = await browser.get("https://ptero.pro/")
    for i in range(14):
        await tab.sleep(5)
        t = await tab.evaluate("document.title")
        print(f"t={(i+1)*5}s {t!r}", flush=True)
        if t and "moment" not in t.lower():
            break
    cookies = await browser.cookies.get_all()
    out = [{"name": c.name, "value": c.value, "domain": c.domain}
           for c in cookies if c.domain and "ptero" in (c.domain or "")]
    with open("/home/stealth/cf_cookies.json", "w") as f:
        json.dump(out, f, indent=1)
    print("COOKIES:", json.dumps(out)[:300], flush=True)
    await browser.stop()


asyncio.run(uc.loop().run_until_complete(main()))
