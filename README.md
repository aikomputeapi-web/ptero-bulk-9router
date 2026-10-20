# ptero-bulk-9router (VPS-hardened fork)

**Fork of [0xgetz/ptero-bulk-9router](https://github.com/0xgetz/ptero-bulk-9router)** — bulk-create
[ptero.pro](https://ptero.pro) anonymous accounts, pool them, and serve them to
[9Router](https://9router.com) as an OpenAI-compatible endpoint.

**Why this fork exists:** the upstream setup no longer works on any VPS. ptero.pro moved behind a
Cloudflare **managed challenge**, so every plain-HTTP request from a datacenter IP gets `403` before
it ever reaches the ptero API. This fork documents the failure and ships a working, self-healing
bypass. Deployed and verified end-to-end on a fresh Ubuntu 24.04 VPS (2 GB RAM, no GPU) on
2026-10-20, including a full reboot-persistence test.

---

## TL;DR — what changed

| | upstream | this fork |
|---|---|---|
| ptero.pro access | direct `fetch()` from Node | **ptero-fetch bridge**: curl_cffi TLS impersonation + residential proxy + replayed `cf_clearance` |
| account creation | pure HTTP, instant | **browser harvest** (nodriver + real Chrome, headful under xvfb) |
| CF challenge handling | none (worked pre-challenge) | **watchdog** re-solves it automatically |
| 9Router service | manual `9router` CLI | **systemd unit** running the Next server directly |
| adapter | `0.0.0.0`, crash on stream failover | **127.0.0.1** + crash fixed |
| services | manual, no persistence | 4 systemd units, enabled at boot |

---

## 1. Why the original setup fails (verified 2026-10-20)

The upstream repo was published 2026-10-16 and verified working then. Between Oct 16 and Oct 20,
ptero.pro enabled a **Cloudflare managed challenge** (`cType: 'managed'`, served via
`/cdn-cgi/challenge-platform/...`). Everything the upstream repo does now fails:

### Failure 1: every HTTP client gets 403 — even with a browser fingerprint

Tested from three egresses (fresh VPS IP, second datacenter IP, residential Windows machine):

| attempt | result |
|---|---|
| plain `curl` | 403 "Just a moment..." |
| `curl` with full Chrome 131 header set + HTTP/2 | 403 |
| `curl_cffi` with `chrome131` / `chrome124` / `safari184` TLS impersonation | 403 |
| same, through a **US residential proxy** | 403 |
| Node's `fetch` (what `src/ptero.js` uses) | 403 |
| headless Chrome (`--headless=new`, real 20 s wait) | challenge loop |
| even the site homepage from a browserless client | 403 |

The challenge is a managed JS challenge — TLS fingerprint and header spoofing alone don't pass.
Only a **real browser** that executes the challenge JS gets through.

### Failure 2: the upstream "browser fallback" doesn't help on a VPS

The repo has `HARVEST_VIA_BROWSER=1` (nodriver + local Chromium). Two problems:

1. It's only used for *proving a session* — the actual adapter still talks plain HTTP, which CF
   blocks regardless of how the accounts were made.
2. The naive browser launch (fresh profile, root user, `--no-sandbox`, no proxy, no warmup) stays
   stuck in the "Verifying..." Turnstile loop forever. Details in section 2.

### Failure 3: `9router` CLI cannot run as a service

Upstream's `run.sh` ends with `node src/connect-9router.js` against a manually-started `9router`.
That CLI is built for interactive terminals: when stdin is not a TTY, its interface menu resolves
"exit" and the supervisor kills the server child. Under systemd it exits within ~20 s, every time.

### Failure 4: adapter crash on stream failover

`src/adapter.js` (upstream) calls `pool.withFailover(runStream)`. If the first member fails *after*
SSE headers were already written, the failover retry calls `writeHead` again →
`ERR_HTTP_HEADERS_SENT` → process dies.

### Failure 5: adapter binds `0.0.0.0` with zero auth

Anyone on the internet could burn your pool quota.

---

## 2. What actually passes the Cloudflare challenge (the recipe)

Found empirically by testing one variable at a time. The combination that works:

```
real Chrome 155 (installed via .deb), headful under Xvfb
  + NON-ROOT user (no --no-sandbox; the flag itself increases detection)
  + persistent profile directory, reused across runs (cold profile = challenge loop)
  + sticky US residential proxy (hellworld session grammar, SAME session id every time)
  + host timezone matching the proxy egress (America/New_York)
  + fonts + mesa installed so rendering looks real
  + mouse movement DURING page load (idle drift), not after settle
  + patience: challenge passes at t≈25-60s on 2nd+ run (warm cookies)
  + 2-5 min spacing between attempts (CF has a per-IP cooldown after failures)
```

What does **NOT** work (all tested): TLS impersonation alone, residential proxy alone,
headless Chrome, `curl_cffi` with any browser profile, replaying `cf_clearance` from a different
IP or without the matching UA/client-hint headers.

### The second half: replaying clearance from non-browser code

Once a real browser solves the challenge, the resulting `cf_clearance` cookie **can** be replayed
from `curl_cffi` if and only if every layer matches:

- **same sticky proxy session** → same egress IP (the cookie is IP-bound)
- `impersonate="chrome131"` (curl_cffi TLS/h2 fingerprint)
- exact `User-Agent: ...Chrome/155.0...` matching the solving browser
- `sec-ch-ua` client hints matching 155
- `Origin: https://ptero.pro` header
- **NO `X-WP-Nonce` header** — the site's own browser sends a nonce, but replaying a stale one
  returns REST 403 `rest_cookie_invalid_nonce`. Omitting it works; the guest-token headers carry
  the identity.

With that, `GET /wp-json/mlp/v1/status` → 200, `POST /wp-json/mlp/v1/chat-stream` → 200 SSE.

---

## 3. The architecture in this fork

```
clients (OpenAI shape, key-auth)
      │
      ▼
9Router :20128  (systemd; Next server run DIRECTLY, bypassing the interactive CLI)
      │
      ▼
ptero adapter :8791  (systemd; binds 127.0.0.1; round-robin pool of N identities)
      │
      ▼
ptero-fetch bridge :8765  (systemd; Python + curl_cffi)
  • injects cf_clearance + Chrome-155 UA/client-hints + Origin into every ptero call
  • routes egress through the sticky residential proxy
  • on 403-challenge: transparently triggers a clearance refresh and retries
      │
      ▼
clearance watchdog (systemd; every 3 min, min 4 min between re-solves)
  • bridge /health does a real status call with the full winning header set
  • if dead → re-launches headful Chrome under xvfb (warm profile), re-solves, saves cookies
```

All four services are systemd units (`systemd/`), enabled at boot, verified across a real reboot.

New/changed files:

| file | what |
|---|---|
| `src/fetchViaBridge.js` | NEW — Node shim that mirrors the `fetch` Response API but routes through the bridge |
| `src/ptero.js` | PATCHED — all HTTP goes through the bridge (drop-in; CLI unchanged) |
| `src/adapter.js` | PATCHED — headers-sent crash fixed; default bind `127.0.0.1` |
| `bridge/ptero_bridge.py` | NEW — the local bridge service (Python, curl_cffi, zero npm deps) |
| `bridge/clearance_watchdog.py` | NEW — auto re-solve loop |
| `tools/get_cf_cookie.py` | NEW — one-shot browser clearance harvester |
| `tools/harvest_accounts.py` | NEW — browser-based bulk identity creator/verifier (replaces pure-HTTP `create`) |
| `tools/test_nodriver.py` | NEW — single-variable recipe test harness |
| `systemd/*.service` | NEW — 9router, ptero-bridge, ptero-adapter, ptero-watchdog units |

---

## 4. Deploy (Ubuntu 24.04, 2 GB RAM is enough)

```bash
# 1. base packages
apt-get install -y nodejs python3-pip curl_cffi google-chrome-stable xvfb fonts-liberation \
  fonts-noto-core fonts-noto-color-emoji mesa-utils libgl1-mesa-dri   # nodejs via nodesource_20.x
pip3 install --break-system-packages curl_cffi nodriver

# 2. non-root stealth user (browser must NOT run as root)
useradd -m -s /bin/bash stealth
timedatectl set-timezone America/New_York        # match your proxy egress

# 3. clone + configure
git clone https://github.com/aikomputeapi-web/ptero-bulk-9router /opt/ptero-bulk-9router
#   edit bridge/ptero_bridge.py + tools/get_cf_cookie.py: put your proxy URL in UPSTREAM/PX_BASE
#   edit systemd/9router.service: set your INITIAL_PASSWORD env (see /opt/9router/.env)

# 4. solve the challenge once + create accounts (as stealth, headful under xvfb)
su stealth -c 'xvfb-run -a /home/stealth/nodvenv/bin/python tools/get_cf_cookie.py'
su stealth -c 'xvfb-run -a /home/stealth/nodvenv/bin/python tools/harvest_accounts.py 10'

# 5. services
cp systemd/*.service /etc/systemd/system/ && systemctl daemon-reload
systemctl enable --now 9router ptero-bridge ptero-adapter ptero-watchdog
```

Full command reference and the exact env files we used: see `MY-COMMANDS.md` section
"ptero-bulk-9router stack" in the deployment machine's docs (also summarized in
`systemd/*.service` comments).

## 5. Verification evidence (2026-10-20, live)

| test | result |
|---|---|
| 10 identities created + usage-verified (1,000,000 tokens each) | ✅ |
| `GET /v1/models` via 9Router (external, from a residential client) | ✅ 6 ptero models |
| non-stream chat via 9Router → adapter → bridge → ptero | ✅ `EXTERNAL_E2E_OK` |
| SSE streaming chat | ✅ chunked deltas + `[DONE]` |
| round-robin | ✅ 10/10 identities received requests |
| full VPS reboot → all 4 services auto-start → external chat | ✅ `POST_REBOOT_EXTERNAL_OK` |
| adapter/bridge exposure | ✅ 127.0.0.1 only; 9Router is the only public surface (key-auth) |
| all 6 models via 9Router (external) | ✅ 6/6 HTTP 200 (gpt-oss-20b may reply empty — upstream quirk) |
| 5 concurrent external chats | ✅ 5/5 correct ordered replies |
| per-identity quota counters on ptero.pro | ✅ 10/10 identities show `used>0`, 1M cap, 3600s window |
| watchdog functional test (corrupt clearance → auto-recover) | ✅ detected + re-solved in ~2 min (v2) |
| 20-min soak: 2 natural clearance deaths → both auto-recovered | ✅ watchdog refreshed at 05:23 + 05:30, healthy at every 3-min check after each |
| post-soak: pool 10/10 healthy + external E2E + 5/5 concurrency | ✅ `SOAK_PASSED` |
| cross-client E2E (curl.exe + PowerShell, independent of test scripts) | ✅ `CURL_CLIENT_OK` + `PS_CLIENT_OK` |

## 6. Operational notes / gotchas

- **Clearance lifetime:** observed to vary widely — from under 10 minutes to 1h+. The watchdog
  (v2) checks every 3 min and re-solves when dead (min 4 min between attempts, CF rate-limit).
  Worst case, requests 502 for a few minutes during a re-solve.
- **Watchdog v1 bug (fixed here):** the original 10-min-check / 15-min-cooldown watchdog refused
  to refresh a clearance that died 5–10 min after solving, leaving the stack down until the
  cooldown expired. v2 tightens both intervals; functional corrupt→recover test passed in ~2 min.
- **9Router non-stream quirk:** 9Router appends a stray `data: [DONE]` after the JSON body in
  non-stream responses. Strict JSON parsers choke; use `JSONDecoder().raw_decode` (see
  `tools/deep_validate.py` for the pattern).
- **Sticky session is sacred:** if your proxy's egress IP rotates, the clearance dies. Use one
  session id forever (`...-session-<id>-lifetime-24h` grammar for hellworld).
- **Keep the warm profile:** `/home/stealth/ptero-profile` accumulates trust; don't wipe it.
- **gpt-oss-20b** sometimes returns empty content (upstream model quirk, not ours).
- **9Router CLI + systemd:** never run `9router` directly under systemd (interactive menu exits
  without TTY). Run `node /usr/lib/node_modules/9router/app/server.js` directly.

## 7. Security & privacy

Same anonymous-identity model as upstream: tokens are random, no personal data. This fork adds:
adapter + bridge are localhost-only; 9Router is the single key-authenticated public surface.
Treat `accounts.json` as a credential file (chmod 600). Only automate services you're permitted to.

## License

MIT (inherits upstream).
