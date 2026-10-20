#!/usr/bin/env python3
"""Clearance watchdog v2: check bridge health every 3 minutes; if clearance is
dead, re-solve immediately (cooldown only protects against challenge-rate-limit
loops: 4 min between refresh attempts).

v2 changes (after live incident 2026-10-20 05:0x EDT):
- check interval 600s -> 180s (clearances observed dying in <15 min)
- refresh cooldown 900s -> 240s (CF needs ~2-5 min spacing between solves)
- after a refresh, re-verify up to 3 times before declaring failure
"""
import json
import subprocess
import sys
import time
import urllib.request

BRIDGE = "http://127.0.0.1:8765"
CHECK_INTERVAL = 180        # every 3 min
REFRESH_COOLDOWN = 240      # min spacing between refresh ATTEMPTS (CF rate limit)
LAST_REFRESH = 0.0


def bridge_health():
    try:
        with urllib.request.urlopen(BRIDGE + "/health", timeout=45) as r:
            return json.load(r)
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def refresh_clearance():
    """Run the browser solver; verify health afterwards with one retry."""
    global LAST_REFRESH
    print(f"[watchdog] {time.strftime('%H:%M:%S')} refreshing cf_clearance...", flush=True)
    try:
        subprocess.run(
            ["su", "stealth", "-c",
             "xvfb-run -a /home/stealth/nodvenv/bin/python /home/stealth/get_cf_cookie.py"],
            timeout=300, capture_output=True)
    except Exception as e:
        print(f"[watchdog] refresh error: {e}", flush=True)
    LAST_REFRESH = time.time()
    for attempt in range(3):
        h = bridge_health()
        if h.get("ok"):
            print(f"[watchdog] after refresh (verify {attempt+1}): ok=True", flush=True)
            return True
        time.sleep(20)
    print(f"[watchdog] after refresh: still unhealthy", flush=True)
    return False


def main():
    print("[watchdog v2] started", flush=True)
    while True:
        h = bridge_health()
        if h.get("ok"):
            print(f"[watchdog] {time.strftime('%H:%M:%S')} healthy", flush=True)
        elif time.time() - LAST_REFRESH >= REFRESH_COOLDOWN:
            refresh_clearance()
        else:
            left = int(REFRESH_COOLDOWN - (time.time() - LAST_REFRESH))
            print(f"[watchdog] unhealthy, cooldown {left}s left", flush=True)
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
