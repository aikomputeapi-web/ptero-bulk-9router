#!/usr/bin/env python3
"""Deep validation sweep against the live stack (external, from local machine).
1) all 6 models via 9Router, 2) concurrency 5x, 3) pool spread after."""
import concurrent.futures
import json
import urllib.request

BASE = "http://96.47.231.150:20128/v1"
KEY = "sk-3befa45e9cd1c91e-0bvvw8-6617de62"

MODELS = [
    "ptero/ling-3.0-flash:free",
    "ptero/deepseek-v4.1-flash:free",
    "ptero/mistral-nemo:minirouter",
    "ptero/glm-5.3-flash",
    "ptero/gpt-oss-20b",
    "ptero/apodex-1.1-mini:free",
]


def chat(model, content, timeout=150):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": content}],
    }).encode()
    req = urllib.request.Request(
        BASE + "/chat/completions", data=body, method="POST",
        headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
        # 9Router appends a stray 'data: [DONE]' after JSON in non-stream mode;
        # take the first JSON object only.
        end = raw.find("}")
        depth = raw.find("{")
        # find matching closing brace of the first object
        obj, _ = json.JSONDecoder().raw_decode(raw[raw.find("{"):])
        d = obj
        txt = d["choices"][0]["message"]["content"]
        return {"model": model, "ok": True, "len": len(txt), "snippet": txt[:60].replace("\n", " ")}
    except Exception as e:
        detail = ""
        try:
            detail = (e.read().decode()[:160])
        except Exception:
            detail = str(e)[:120]
        return {"model": model, "ok": False, "err": detail}


print("=== 1. model sweep ===")
results = [chat(m, "Reply with exactly one word: VALID") for m in MODELS]
for r in results:
    print(("PASS" if r["ok"] else "FAIL"), r["model"], "|", r.get("snippet") or r.get("err"))
empty_ok = [r for r in results if r["ok"]]
print(f"SWEEP: {len(empty_ok)}/{len(results)} returned 200")

print("=== 2. concurrency 5x parallel ===")
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
    futs = [ex.submit(chat, "ptero/glm-5.3-flash", f"Reply with the number {i} only") for i in range(1, 6)]
    cresults = [f.result() for f in futs]
for r in cresults:
    print(("PASS" if r["ok"] else "FAIL"), r.get("snippet") or r.get("err"))
okc = sum(1 for r in cresults if r["ok"])
print(f"CONCURRENCY: {okc}/5 succeeded")
