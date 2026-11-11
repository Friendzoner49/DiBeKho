/* Dev-only: a Postgres (PGlite) that stays up for a whole test, so Python can interleave its own steps (two machines
   syncing) with SQL. argv: SQL files to load. stdin: one JSON request per line {"sql", "params"?, "sub"?};
   stdout: one JSON answer per line {"rows"} or {"error"}. See run.mjs for the Supabase stubs. */

import { readFileSync } from "node:fs";
import { createInterface } from "node:readline";
import { PGlite } from "@electric-sql/pglite";
import { PRELUDE } from "./prelude.mjs";

const db = new PGlite();
await db.exec(PRELUDE);
for (const f of process.argv.slice(2)) await db.exec(readFileSync(f, "utf8"));
process.stdout.write(JSON.stringify({ ready: true }) + "\n");

const rl = createInterface({ input: process.stdin });
for await (const line of rl) {
  if (!line.trim()) continue;
  const s = JSON.parse(line);
  let answer;
  try {
    if (s.sub) {
      await db.exec("set role authenticated");
      await db.query("select set_config('request.jwt.claim.sub', $1, false)", [s.sub]);
    }
    try {
      answer = { rows: (await db.query(s.sql, s.params || [])).rows };
    } finally {
      if (s.sub) await db.exec("reset role; select set_config('request.jwt.claim.sub', '', false)");
    }
  } catch (e) {
    answer = { error: String(e.message || e) };
  }
  process.stdout.write(JSON.stringify(answer) + "\n");
}
