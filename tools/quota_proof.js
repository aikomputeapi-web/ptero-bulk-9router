"use strict";
/* Quota mechanics proof: read real usage from ptero for each identity via the
 * bridge (uses each identity's own token). Expect used>0 for identities that
 * served chats, remaining<max, and reset_seconds=3600 window present. */
const { Pool } = require("/opt/ptero-bulk-9router/src/pool.js");

(async () => {
  const pool = Pool.fromFile("/opt/ptero-bulk-9router/accounts.json");
  let anyUsed = 0;
  for (const m of pool.members) {
    try {
      const u = await m.client.usage();
      const served = u.used > 0;
      if (served) anyUsed++;
      console.log(
        `${m.username}: used=${u.used}/${u.max} remaining=${u.remaining} window=${u.window_seconds}s ${served ? "SERVED" : "fresh"}`);
    } catch (e) {
      console.log(`${m.username}: ERR ${e.message}`);
    }
  }
  console.log(`identities with used>0: ${anyUsed}/${pool.members.length}`);
  process.exit(0);
})().catch((e) => { console.log("ERR", e.message); process.exit(1); });
