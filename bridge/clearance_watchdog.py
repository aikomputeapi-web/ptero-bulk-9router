#!/usr/bin/env python3
"""Clearance watchdog: every 10 minutes check bridge health; if clearance is
dead, drive the xvfb browser to re-solve the CF challenge. Logs to stdout."""
import json
import subprocess
import sys
import time
import urllib.request

BRIDGE = "http://127.0.0.1:8765"
CHECK_INTERVAL = 600
REFRESH_COOLDOWN = 900  # don't refresh more often than every 15 min
LAST_REFRESH = 0.0


def bridge_health():
    try:
        with urllib.request.urlopen(BRIDGE + "/health", timeout=45) as r:
            return json.load(r)
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def refresh_clearance():
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
    h = bridge_health()
    print(f"[watchdog] after refresh: ok={h.get('ok')}", flush=True)
    return h.get("ok")


def main():
    print("[watchdog] started", flush=True)
    while True:
        h = bridge_health()
        if h.get("ok"):
            print(f"[watchdog] {time.strftime('%H:%M:%S')} healthy", flush=True)
        else:
            if time.time() - LAST_REFRESH >= REFRESH_COOLDOWN:
                ok = refresh_clearance()
                if not ok:
                    print("[watchdog] refresh FAILED; retrying next cycle", flush=True)
            else:
                print(f"[watchdog] unhealthy but in cooldown ({int(REFRESH_COOLDOWN - (time.time() - LAST_REFRESH))}s left)", flush=True)
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
