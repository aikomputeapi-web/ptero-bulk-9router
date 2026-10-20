import concurrent.futures
import json
import urllib.request

BASE = "http://96.47.231.150:20128/v1"
KEY = "sk-3befa45e9cd1c91e-0bvvw8-6617de62"


def chat(i):
    body = json.dumps({
        "model": "ptero/glm-5.3-flash",
        "messages": [{"role": "user", "content": f"Reply with the number {i} only"}],
    }).encode()
    req = urllib.request.Request(
        BASE + "/chat/completions", data=body, method="POST",
        headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=150) as r:
            raw = r.read().decode("utf-8", "replace")
        obj, _ = json.JSONDecoder().raw_decode(raw[raw.find("{"):])
        return obj["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return "ERR:" + str(e)[:80]


with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
    res = list(ex.map(chat, range(1, 6)))
print("CONCURRENCY RESULTS:", res)
print("OK:", sum(1 for r in res if r.isdigit()), "/5")
