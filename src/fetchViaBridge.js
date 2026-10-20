"use strict";

/**
 * fetchViaBridge — routes ptero.pro HTTP calls through the local ptero-fetch
 * bridge (127.0.0.1:8765) which applies the working CF recipe:
 * curl_cffi TLS impersonation + residential proxy + cf_clearance + Chrome 155
 * client hints. Falls back to direct fetch when the bridge is down.
 *
 * Response shape mirrors the global fetch Response subset used by ptero.js:
 * { ok, status, headers: { get(name) }, text(), json(), body reader for SSE }
 */

const BRIDGE = process.env.PTERO_BRIDGE_URL || "http://127.0.0.1:8765/fetch";

class BridgeResponse {
  constructor(status, headerObj, bodyText) {
    this.status = status;
    this.ok = status >= 200 && status < 300;
    this._headers = headerObj || {};
    this._text = bodyText;
    this._json = null;
  }
  headers_get(name) {
    return this._headers[String(name).toLowerCase()] || null;
  }
  get headers() {
    const self = this;
    return { get: (n) => self.headers_get(n) };
  }
  async text() {
    return this._text;
  }
  async json() {
    if (this._json === null) this._json = JSON.parse(this._text);
    return this._json;
  }
}

class BridgeStreamResponse {
  constructor(status, headerObj, res) {
    this.status = status;
    this.ok = status >= 200 && status < 300;
    this._headers = headerObj || {};
    this._res = res;
  }
  get headers() {
    const self = this;
    return { get: (n) => self._headers[String(n).toLowerCase()] || null };
  }
  get body() {
    const res = this._res;
    return {
      async *[Symbol.asyncIterator]() {
        for await (const chunk of res.body) {
          yield chunk;
        }
      },
    };
  }
  async text() {
    const chunks = [];
    for await (const c of this._res.body) chunks.push(c);
    return Buffer.concat(chunks).toString("utf-8");
  }
  async json() {
    return JSON.parse(await this.text());
  }
}

async function fetchViaBridge(url, opts = {}) {
  const u = new URL(url);
  const payload = {
    path: u.pathname + u.search,
    method: opts.method || "GET",
    headers: opts.headers || {},
    body: opts.body ? String(opts.body) : undefined,
    stream: true,
  };
  try {
    const res = await fetch(BRIDGE, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const ct = res.headers.get("content-type") || "";
    if (!res.ok || ct.includes("application/json")) {
      // bridge-level error or JSON reply -> wrap
      const text = await res.text();
      if (res.status === 502) {
        // bridge error: return a fake 503 response so callers see failure
        return new BridgeResponse(503, { "content-type": "application/json" }, text);
      }
      // Streamed SSE or proxied response: bridge relays upstream status via
      // X-Bridge-Status header (set below in bridge). Simpler: bridge returns
      // upstream body verbatim with its status line; undici exposes it via
      // res.status. So just pass through:
      return new BridgeResponse(res.status, Object.fromEntries(res.headers), text);
    }
    return new BridgeStreamResponse(res.status, Object.fromEntries(res.headers), res);
  } catch (e) {
    // bridge down -> direct fetch (will likely 403 but keeps behavior sane)
    return fetch(url, opts);
  }
}

module.exports = { fetchViaBridge };
