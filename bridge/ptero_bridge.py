#!/usr/bin/env python3
"""ptero-fetch bridge: local HTTP service that performs ptero.pro API calls
with the working recipe: curl_cffi chrome TLS impersonation + residential
proxy + cf_clearance cookie + Chrome 155 client hints.

The Node adapter forwards its upstream calls here.

  POST http://127.0.0.1:8765/fetch
  body: {"path": "/wp-json/mlp/v1/chat-stream", "method": "POST",
         "headers": {...}, "body": "...", "stream": true}
  -> upstream status/headers + body (chunked when stream=true)

Cookie refresh: POST /refresh_clearance drives the xvfb browser to renew
cf_clearance when the current one starts failing (checked by /health).
"""
import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from curl_cffi import requests as ccr

PTERO = "https://ptero.pro"
COOKIE_FILE = "/home/stealth/cf_cookies.json"
HARVEST_SCRIPT = "/home/stealth/get_cf_cookie.py"
PX_BASE = "http://7zumew4mpo-country-us-session-pterostk1-lifetime-24h:d3tvw2sx5o@geofast.hellworld.io:6969"
IMPERSONATE = "chrome131"

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36")
CLIENT_HINTS = {
    "sec-ch-ua": '"Chromium";v="155", "Not=A?Brand";v="24", "Google Chrome";v="155"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Linux"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://ptero.pro/",
}

_lock = threading.Lock()
_last_refresh = 0.0


def load_jar():
    try:
        with open(COOKIE_FILE) as f:
            return {c["name"]: c["value"] for c in json.load(f)}
    except Exception:
        return {}


def do_refresh_clearance():
    """Drive the warm xvfb browser to (re)solve the challenge."""
    global _last_refresh
    subprocess.run(
        ["su", "stealth", "-c",
         f"xvfb-run -a /home/stealth/nodvenv/bin/python {HARVEST_SCRIPT}"],
        timeout=240, capture_output=True)
    _last_refresh = time.time()
    return os.path.exists(COOKIE_FILE)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # quiet

    def _json(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            jar = load_jar()
            has_cf = "cf_clearance" in jar
            ok = False
            if has_cf:
                try:
                    r = ccr.get(f"{PTERO}/wp-json/mlp/v1/status",
                                headers={"X-MLP-Guest-Token": "healthcheck",
                                         "X-MLP-Guest-Username": "Health Check",
                                         "User-Agent": UA,
                                         **CLIENT_HINTS},
                                cookies=jar, impersonate=IMPERSONATE,
                                proxies={"http": PX_BASE, "https": PX_BASE},
                                timeout=30)
                    ok = r.status_code == 200
                except Exception:
                    ok = False
            self._json(200, {"ok": ok, "has_clearance": has_cf})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/refresh_clearance":
            with _lock:
                ok = do_refresh_clearance()
            self._json(200, {"refreshed": ok})
            return
        if self.path != "/fetch":
            self._json(404, {"error": "not found"})
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception as e:
            self._json(400, {"error": f"bad request: {e}"})
            return

        path = req.get("path", "/")
        method = (req.get("method") or "GET").upper()
        extra = req.get("headers") or {}
        body = req.get("body")
        stream = bool(req.get("stream"))

        headers = {**CLIENT_HINTS, "User-Agent": UA, "Origin": PTERO}
        # IMPORTANT (empirically verified): sending X-WP-Nonce causes REST 403
        # "Cookie check failed" when replaying without the full browser session.
        # The site's own browser fetch does send a nonce, but server accepts the
        # request fine without one as long as guest token headers are present.
        for k, v in extra.items():
            if k.lower() in ("host", "content-length", "connection", "x-wp-nonce"):
                continue
            headers[k] = v

        jar = load_jar()
        try:
            r = ccr.request(
                method, PTERO + path, headers=headers, cookies=jar,
                data=body.encode("utf-8") if isinstance(body, str) else body,
                impersonate=IMPERSONATE,
                proxies={"http": PX_BASE, "https": PX_BASE},
                timeout=300, stream=stream,
            )
        except Exception as e:
            self._json(502, {"bridge_error": str(e)[:300]})
            return

        # 403 with challenge = clearance dead -> refresh once and retry
        if r.status_code == 403 and "Just a moment" in r.text[:600]:
            with _lock:
                if time.time() - _last_refresh > 120:
                    do_refresh_clearance()
            jar = load_jar()
            try:
                r2 = ccr.request(
                    method, PTERO + path, headers=headers, cookies=jar,
                    data=body.encode("utf-8") if isinstance(body, str) else body,
                    impersonate=IMPERSONATE,
                    proxies={"http": PX_BASE, "https": PX_BASE},
                    timeout=300, stream=stream)
                if r2.status_code == 200 or "Just a moment" not in r2.text[:600]:
                    r = r2
            except Exception:
                pass

        self.send_response(r.status_code)
        for hk in ("content-type", "x-wp-nonce"):
            if hk in r.headers:
                self.send_header(hk, r.headers[hk])
        if stream:
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            try:
                for chunk in r.iter_content(chunk_size=1024):
                    if not chunk:
                        continue
                    self.wfile.write(b"%x\r\n" % len(chunk))
                    self.wfile.write(chunk)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()
            except Exception:
                pass
            try:
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except Exception:
                pass
        else:
            data = r.content
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    print("[bridge] ptero-fetch bridge on 127.0.0.1:8765", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
