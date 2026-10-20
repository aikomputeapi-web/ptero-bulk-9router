"use strict";
/* Verify all identities via pool.healthCheckAll (through the bridge). */
const { Pool } = require("/opt/ptero-bulk-9router/src/pool.js");

(async () => {
  const pool = Pool.fromFile("/opt/ptero-bulk-9router/accounts.json");
  const res = await pool.healthCheckAll();
  const ok = res.filter((r) => r.ok).length;
  console.log("healthCheckAll:", ok + "/" + res.length, "healthy");
  for (const r of res) {
    if (!r.ok) console.log("  UNHEALTHY:", r.username, r.error);
  }
  process.exit(0);
})().catch((e) => {
  console.log("ERR", e.message);
  process.exit(1);
});
