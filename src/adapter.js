"use strict";

/**
 * adapter.js — OpenAI-compatible HTTP server (modified 2026-10-20 for the
 * CF-blocked-VPS setup; upstream calls now go through the ptero-fetch bridge
 * via ptero.js/fetchViaBridge.js).
 *
 * Also fixes a crash in the original: withFailover retry after a stream had
 * already started (ERR_HTTP_HEADERS_SENT). Stream attempts are no longer
 * retried once headers are sent.
 *
 * Endpoints:
 *   GET  /v1/models        list ptero models
 *   POST /v1/chat/completions   OpenAI shape, stream + non-stream
 *   GET  /health           { ok, pool }
 *   GET  /pool             per-member health snapshot
 *   POST /pool/reload      reload accounts file
 */

const http = require("http");
const fs = require("fs");
const crypto = require("crypto");
const { Pool } = require("./pool.js");
const { MODELS, DEFAULT_MODEL } = require("./ptero.js");

const PORT = Number(process.env.ADAPTER_PORT || 8791);
const HOST = process.env.ADAPTER_HOST || "0.0.0.0";
const ACCOUNTS_FILE = process.env.ACCOUNTS_FILE || "";
const POOL_SIZE = Number(process.env.POOL_SIZE || 0);

let pool = ACCOUNTS_FILE ? Pool.fromFile(ACCOUNTS_FILE) : new (require("./pool.js").Pool)([]);

const resolveModel = (m) => {
  if (!m) return DEFAULT_MODEL;
  const q = String(m).replace(/^ptero\//, "").toLowerCase();
  const byId = MODELS.find((x) => x.id.toLowerCase() === q);
  if (byId) return byId.id;
  const byAlias = MODELS.find((x) => x.id.split(":")[0].toLowerCase() === q);
  return byAlias ? byAlias.id : DEFAULT_MODEL;
};

const readBody = (req) =>
  new Promise((resolve) => {
    let b = "";
    req.on("data", (c) => (b += c));
    req.on("end", () => resolve(b));
    req.on("error", () => resolve(""));
  });

function messagesToPrompt(messages) {
  const msgs = Array.isArray(messages) ? messages : [];
  const hist = [];
  for (let i = 0; i < msgs.length - 1; i++) {
    const m = msgs[i] || {};
    const c = typeof m.content === "string"
      ? m.content
      : Array.isArray(m.content)
        ? m.content.map((p) => (p && p.text) || "").join(" ")
        : "";
    if (c) hist.push({ role: m.role === "assistant" ? "assistant" : "user", text: c });
  }
  const last = msgs[msgs.length - 1] || {};
  const lastText = typeof last.content === "string"
    ? last.content
    : Array.isArray(last.content)
      ? last.content.map((p) => (p && p.text) || "").join(" ")
      : "";
  return { message: lastText, history: hist };
}

const cid = () => "chatcmpl-" + crypto.randomUUID().replace(/-/g, "").slice(0, 24);

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  const send = (code, obj, extra) => {
    if (res.headersSent) {
      try { res.end(); } catch (_) {}
      return;
    }
    res.writeHead(code, Object.assign({ "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }, extra));
    res.end(JSON.stringify(obj));
  };

  if (req.method === "OPTIONS") {
    res.writeHead(204, {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, Authorization",
    });
    return res.end();
  }

  if (url.pathname === "/health") {
    return send(200, { ok: pool.size > 0, pool: { size: pool.size } });
  }
  if (url.pathname === "/pool") return send(200, { size: pool.size, members: pool.snapshot() });

  if (url.pathname === "/pool/reload") {
    if (ACCOUNTS_FILE && fs.existsSync(ACCOUNTS_FILE)) pool = Pool.fromFile(ACCOUNTS_FILE);
    return send(200, { ok: true, size: pool.size });
  }

  if (url.pathname === "/v1/models" || url.pathname === "/models") {
    const now = Math.floor(Date.now() / 1000);
    return send(200, {
      object: "list",
      data: MODELS.map((m) => ({ id: "ptero/" + m.id, object: "model", created: now, owned_by: "ptero", label: m.label })),
    });
  }

  if (url.pathname === "/v1/chat/completions" || url.pathname === "/chat/completions") {
    let payload;
    try {
      payload = JSON.parse((await readBody(req)) || "{}");
    } catch (_) {
      return send(400, { error: { message: "invalid JSON body", type: "invalid_request_error" } });
    }
    const model = resolveModel(payload.model);
    const { message, history } = messagesToPrompt(payload.messages);
    const stream = !!payload.stream;
    const convId = payload.conversation_id || crypto.randomUUID();
    const completionId = cid();
    const created = Math.floor(Date.now() / 1000);

    const runStream = async (member) => {
      res.writeHead(200, {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
        "Access-Control-Allow-Origin": "*",
      });
      res.write(
        "data: " +
          JSON.stringify({ id: completionId, object: "chat.completion.chunk", created, model: "ptero/" + model, choices: [{ index: 0, delta: { role: "assistant" }, finish_reason: null }] }) +
          "\n\n"
      );
      for await (const ev of member.client.stream(message, { model, conversationId: convId, history })) {
        if (typeof ev.token === "string" && ev.token.length) {
          res.write(
            "data: " +
              JSON.stringify({ id: completionId, object: "chat.completion.chunk", created, model: "ptero/" + model, choices: [{ index: 0, delta: { content: ev.token }, finish_reason: null }] }) +
              "\n\n"
          );
        }
        if (ev.done) {
          res.write(
            "data: " +
              JSON.stringify({ id: completionId, object: "chat.completion.chunk", created, model: "ptero/" + model, choices: [{ index: 0, delta: {}, finish_reason: "stop" }] }) +
              "\n\n"
          );
        }
      }
      res.write("data: [DONE]\n\n");
      res.end();
    };

    try {
      if (stream) {
        try {
          await pool.withFailover(runStream);
        } catch (e) {
          if (!res.headersSent) return send(502, { error: { message: e.message, type: "upstream_error" } });
          try {
            res.write("data: " + JSON.stringify({ error: { message: e.message } }) + "\n\n");
            res.write("data: [DONE]\n\n");
            res.end();
          } catch (_) {}
          return;
        }
        return;
      }

      const out = await pool.withFailover((m) => m.client.chat(message, { model, conversationId: convId, history }));
      return send(200, {
        id: completionId,
        object: "chat.completion",
        created,
        model: "ptero/" + model,
        choices: [{ index: 0, message: { role: "assistant", content: out.text }, finish_reason: "stop" }],
        usage: { prompt_tokens: 0, completion_tokens: out.meta.usage_tokens || 0, total_tokens: out.meta.usage_tokens || 0 },
        ptero: { model_used: out.meta.model_used, conversation_id: out.meta.conversation_id },
      });
    } catch (e) {
      if (!res.headersSent) send(502, { error: { message: e.message, type: "upstream_error" } });
      else {
        try {
          res.end();
        } catch (_) {}
      }
    }
  }

  return send(404, { error: { message: "not found" } });
});

server.listen(PORT, HOST, () => {
  console.log(`[adapter] listening on http://${HOST}:${PORT}  pool=${pool.size}  models=${MODELS.length}`);
});

module.exports = { server };
