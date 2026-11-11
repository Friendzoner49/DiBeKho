/* Dev-only: run cloud/supabase/*.sql on a real Postgres (PGlite, in memory) for the tests.
   stdin: {"files": ["cloud/supabase/001_init.sql", ...], "steps": [{"sql": "...", "params": [...], "sub": "<uuid>"}]}
   A step with "sub" runs as the Supabase role `authenticated` whose auth.uid() is that uuid; otherwise as the owner.
   stdout: {"results": [[row, ...], ...]} or {"error": "...", "step": n}. */

import { readFileSync } from "node:fs";
import { PGlite } from "@electric-sql/pglite";
import { PRELUDE } from "./prelude.mjs";

const input = JSON.parse(readFileSync(0, "utf8"));
const db = new PGlite();
const out = { results: [] };
let step = -1;
try {
  await db.exec(PRELUDE);
  for (const f of input.files || []) await db.exec(readFileSync(f, "utf8"));
  for (step = 0; step < (input.steps || []).length; step++) {
    const s = input.steps[step];
    if (s.sub) {
      await db.exec("set role authenticated");
      await db.query("select set_config('request.jwt.claim.sub', $1, false)", [s.sub]);
    }
    try {
      const r = await db.query(s.sql, s.params || []);
      out.results.push(r.rows);
    } finally {
      if (s.sub) await db.exec("reset role; select set_config('request.jwt.claim.sub', '', false)");
    }
  }
} catch (e) {
  out.error = String(e.message || e);
  out.step = step;
}
process.stdout.write(JSON.stringify(out));
