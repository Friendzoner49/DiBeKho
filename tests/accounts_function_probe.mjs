// Runs the REAL cloud/supabase/functions/accounts/index.ts under Node against a fake Supabase, for
// tests/test_accounts_function.py. Prints one JSON object: case name -> what the handler answered and what it touched.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "accounts-fn-"));
const copy = path.join(tmp, "index.mjs"); // the file is plain JavaScript with a .ts name: Node only needs another name
fs.copyFileSync(process.argv[2], copy);
const { makeHandler } = await import(pathToFileURL(copy).href);

const OWNER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const STAFF = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const TARGET = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee";
const SECRET = "Sup3r-Secret-Pass";

// everything printed while the handler runs is collected: a password must never be in it
const printed = [];
for (const k of ["log", "error", "warn", "info", "debug"]) console[k] = (...a) => printed.push(a.map(String).join(" "));

function fake(over = {}) {
  const calls = [];
  const deps = {
    tokens: { "owner-token": OWNER, "staff-token": STAFF },
    roles: { [OWNER]: "desktop", [STAFF]: "editor" },
    users: new Set([TARGET]),
    async getUserId(t) { calls.push(["getUserId"]); if (over.tokenThrows) throw new Error("auth down"); return this.tokens[t] ?? null; },
    async roleOf(id) { calls.push(["roleOf", id]); if (over.roleThrows) throw new Error("db down"); return this.roles[id] ?? ""; },
    async createUser(a) { calls.push(["createUser", a.email, a.password]); if (over.createThrows) throw over.createThrows; return { id: "11111111-1111-4111-8111-111111111111" }; },
    async deleteUser(id) { calls.push(["deleteUser", id]); if (over.deleteThrows) throw new Error("x"); },
    async setPassword(id, p) { calls.push(["setPassword", id, p]); if (over.setThrows) throw over.setThrows; },
    async insertProfile(r) { calls.push(["insertProfile", r.user_id, r.display_name, r.role]); if (over.profileThrows) throw new Error("db"); },
    async userExists(id) { calls.push(["userExists", id]); return this.users.has(id); },
  };
  return { deps, calls };
}

async function ask(over, { method = "POST", token = "owner-token", body, raw } = {}) {
  const { deps, calls } = fake(over);
  const headers = new Headers();
  if (token) headers.set("authorization", `Bearer ${token}`);
  const init = { method, headers };
  if (method === "POST") init.body = raw ?? JSON.stringify(body);
  const res = await makeHandler(deps)(new Request("https://x.test/accounts", init));
  const text = await res.text();
  let json = null;
  try { json = JSON.parse(text); } catch (e) { /* empty body */ }
  return { status: res.status, json, text, cors: res.headers.get("access-control-allow-origin"),
           allowHeaders: res.headers.get("access-control-allow-headers"), calls };
}

const create = (extra = {}) => ({ body: { action: "create", username: "nhanvien1", password: SECRET, role: "editor", ...extra } });
const out = {};

out.options = await ask({}, { method: "OPTIONS", token: "" });
out.get = await ask({}, { method: "GET" });
out.noAuth = await ask({}, { token: "", ...create() });
out.badToken = await ask({}, { token: "nope", ...create() });
out.tokenCheckThrows = await ask({ tokenThrows: true }, create());
out.roleCheckThrows = await ask({ roleThrows: true }, create());
out.badJson = await ask({}, { raw: "{not json" });
out.unknownAction = await ask({}, { body: { action: "delete_everything" } });
out.staffCreates = await ask({}, { token: "staff-token", ...create() });
out.staffResets = await ask({}, { token: "staff-token", body: { action: "reset_password", user_id: TARGET, password: SECRET } });
out.created = await ask({}, create({ username: "  NhanVien1 ", display_name: "  Lan   kho " }));
out.createdNoName = await ask({}, create());
out.createdOwnerRole = await ask({}, create({ role: "desktop", username: "quanly" }));
for (const [k, u] of Object.entries({ short: "ab", accents: "Nguyễn", space: "a b", email: "x@y.com", long: "a".repeat(31), empty: "" })) {
  out[`badUser_${k}`] = await ask({}, create({ username: u }));
}
out.badPwShort = await ask({}, create({ password: "1234567" }));
out.badPwLong = await ask({}, create({ password: "p".repeat(73) }));
out.badPwMissing = await ask({}, create({ password: undefined }));
out.badRole = await ask({}, create({ role: "admin" }));
out.noRole = await ask({}, create({ role: undefined }));
out.duplicate = await ask({ createThrows: { code: "email_exists", message: "A user with this email address has already been registered" } }, create());
out.weak = await ask({ createThrows: { code: "weak_password", message: "Password should contain letters and digits" } }, create());
out.authDown = await ask({ createThrows: { message: "fetch failed" } }, create());
out.profileFails = await ask({ profileThrows: true }, create());
out.profileAndDeleteFail = await ask({ profileThrows: true, deleteThrows: true }, create());
out.reset = await ask({}, { body: { action: "reset_password", user_id: TARGET, password: SECRET } });
out.resetBadId = await ask({}, { body: { action: "reset_password", user_id: "not-a-uuid", password: SECRET } });
out.resetUnknown = await ask({}, { body: { action: "reset_password", user_id: "99999999-9999-4999-8999-999999999999", password: SECRET } });
out.resetShort = await ask({}, { body: { action: "reset_password", user_id: TARGET, password: "short" } });
out.resetFails = await ask({ setThrows: { code: "weak_password", message: "too weak" } }, { body: { action: "reset_password", user_id: TARGET, password: SECRET } });

out.printedLines = printed.length;
out.passwordPrinted = printed.some((l) => l.includes(SECRET));
fs.rmSync(tmp, { recursive: true, force: true });
process.stdout.write(JSON.stringify({ ...out, SECRET }));
