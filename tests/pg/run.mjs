/* Dev-only: run cloud/supabase/*.sql on a real Postgres (PGlite, in memory) for the tests.
   stdin: {"files": ["cloud/supabase/001_init.sql", ...], "steps": [{"sql": "...", "params": [...], "sub": "<uuid>"}]}
   A step with "sub" runs as the Supabase role `authenticated` whose auth.uid() is that uuid; otherwise as the owner.
   stdout: {"results": [[row, ...], ...]} or {"error": "...", "step": n}. */

import { readFileSync } from "node:fs";
import { PGlite } from "@electric-sql/pglite";

// The bits of Supabase the project's SQL relies on (auth schema, roles, storage stub).
const PRELUDE = `
create schema auth;
create table auth.users (id uuid primary key, email text);
create function auth.uid() returns uuid language sql stable as
  $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
create role authenticated nologin;
create role anon nologin;
grant usage on schema public to authenticated, anon;
alter default privileges in schema public grant select, insert, update, delete on tables to authenticated;
alter default privileges in schema public grant usage, select on sequences to authenticated;
alter default privileges in schema public grant execute on functions to authenticated, anon;
`;

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
