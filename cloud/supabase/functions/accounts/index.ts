// @ts-nocheck
// DiBeKho Edge Function `accounts`: create an account and reset a password. Called by the owner from the web page
// (Cài đặt → Tài khoản). Only these two jobs need Supabase's admin API, whose key must never reach a browser; listing
// accounts, changing a role and taking a role away are plain SQL (cloud/supabase/011_accounts.sql).
//
// How it stays safe (the gateway's own "Verify JWT" switch may be on or off, this code does not depend on it):
//   * the caller's token is checked with the Auth server (getUser), then the role is read from public.profiles by the
//     user id. Nothing the browser says about itself (body, claims) is trusted.
//   * only a 'desktop' (owner) account may do anything here.
//   * a password is never logged and never sent back.
//   * every business answer is HTTP 200 with {ok: true, ...} or {ok: false, error: "<plain Vietnamese>"} so the page can
//     show it; only a broken request or a missing key is another status.
//
// The logic is `makeHandler(deps)` with everything outside injected, so tests/test_accounts_function.py runs this very
// file in Node against a fake. Deno wiring is at the bottom.

const DOMAIN = "dibekho.local";
const ROLES = ["desktop", "editor", "viewer"];
const USERNAME = /^[a-z0-9._-]{3,30}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const MIN_PASSWORD = 8;
const MAX_PASSWORD = 72; // bcrypt (Supabase's password hash) only looks at the first 72 bytes

const CORS = {
  "Access-Control-Allow-Origin": "*", // the check is a bearer token, not a cookie
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

function reply(status, body) {
  return new Response(body === null ? null : JSON.stringify(body), {
    status,
    headers: { ...CORS, ...(body === null ? {} : { "Content-Type": "application/json" }) },
  });
}

const fail = (message) => reply(200, { ok: false, error: message });

function cleanText(value, max) {
  return String(value ?? "").normalize("NFC").replace(/\s+/g, " ").trim().slice(0, max);
}

function checkPassword(password) {
  if (typeof password !== "string" || password.length < MIN_PASSWORD) {
    return `Mật khẩu phải có ít nhất ${MIN_PASSWORD} ký tự (nên từ 10 ký tự, có cả chữ và số).`;
  }
  if (new TextEncoder().encode(password).length > MAX_PASSWORD) return `Mật khẩu dài quá (tối đa ${MAX_PASSWORD} ký tự).`;
  return "";
}

/** Supabase's own refusal, in plain Vietnamese; its English text is kept after the colon when it adds something. */
function authMessage(error, fallback) {
  const text = String(error?.message || "");
  const code = String(error?.code || "");
  if (code === "email_exists" || code === "user_already_exists" || /already (been )?registered|already exists/i.test(text)) {
    return "Tên đăng nhập này đã có người dùng. Hãy chọn tên khác.";
  }
  if (code === "weak_password" || /password/i.test(text)) {
    return `Supabase không chấp nhận mật khẩu này (${text || "quá yếu"}). Hãy chọn mật khẩu dài và khó đoán hơn.`;
  }
  return `${fallback}${text ? ` (${text})` : ""}`;
}

/**
 * deps = {
 *   getUserId(token) -> uuid | null            // checks the token with the Auth server
 *   roleOf(userId) -> 'desktop' | 'editor' | 'viewer' | ''
 *   emailOf(userId) -> string                  // only ADMIN_EMAIL manages accounts
 *   createUser({email, password}) -> {id} | throws {message, code}
 *   deleteUser(id), setPassword(id, password) -> throws {message, code}
 *   insertProfile({user_id, display_name, role}) -> throws
 *   userExists(id) -> boolean
 * }
 */
// the one login allowed to create accounts and reset passwords (customer's decision 13/11/2026)
const ADMIN_EMAIL = "maychinh@dibekho.local";

function makeHandler(deps) {
  return async function handle(request) {
    if (request.method === "OPTIONS") return reply(204, null);
    if (request.method !== "POST") return reply(405, { ok: false, error: "Chỉ nhận yêu cầu POST." });

    const header = request.headers.get("authorization") || "";
    const token = header.toLowerCase().startsWith("bearer ") ? header.slice(7).trim() : "";
    if (!token) return reply(401, { ok: false, error: "Chưa đăng nhập." });

    let body;
    try {
      body = await request.json();
    } catch (e) {
      return reply(400, { ok: false, error: "Yêu cầu không đọc được." });
    }

    let caller = null;
    try {
      caller = await deps.getUserId(token);
    } catch (e) {
      caller = null;
    }
    if (!caller) return reply(401, { ok: false, error: "Phiên đăng nhập hết hạn. Hãy đăng nhập lại trên trang web." });
    let role = "";
    try {
      role = await deps.roleOf(caller);
    } catch (e) {
      return fail("Không kiểm tra được quyền của tài khoản này. Thử lại sau.");
    }
    let email = "";
    try {
      email = role === "desktop" ? String((await deps.emailOf(caller)) || "").toLowerCase() : "";
    } catch (e) {
      return fail("Không kiểm tra được quyền của tài khoản này. Thử lại sau.");
    }
    if (role !== "desktop" || email !== ADMIN_EMAIL) return fail("Chỉ tài khoản của chủ mới tạo hoặc đổi mật khẩu cho tài khoản khác được.");

    if (body?.action === "create") return create(body);
    if (body?.action === "reset_password") return resetPassword(body);
    if (body?.action === "delete") return deleteAccount(body, caller);
    return reply(400, { ok: false, error: "Yêu cầu không hợp lệ." });
  };

  async function create(body) {
    const username = cleanText(body.username, 60).toLowerCase();
    if (username.includes("@")) return fail(`Chỉ gõ tên ngắn (ví dụ nhanvien1), không gõ @${DOMAIN}.`);
    if (!USERNAME.test(username)) {
      return fail("Tên đăng nhập gồm 3–30 ký tự: chữ thường không dấu, số, dấu chấm, gạch dưới hoặc gạch ngang (ví dụ nhanvien1).");
    }
    const bad = checkPassword(body.password);
    if (bad) return fail(bad);
    if (!ROLES.includes(body.role)) return fail("Hãy chọn vai trò cho tài khoản.");
    const name = cleanText(body.display_name, 60) || username;

    let created;
    try {
      created = await deps.createUser({ email: `${username}@${DOMAIN}`, password: body.password });
    } catch (e) {
      return fail(authMessage(e, "Không tạo được tài khoản."));
    }
    const id = created?.id;
    if (!id) return fail("Không tạo được tài khoản (Supabase không trả về mã tài khoản).");
    try {
      await deps.insertProfile({ user_id: id, display_name: name, role: body.role });
    } catch (e) {
      // no half-made account: a login without a role would sign in to an empty page
      let removed = true;
      try {
        await deps.deleteUser(id);
      } catch (e2) {
        removed = false;
      }
      return fail(`Không cấp được vai trò cho tài khoản mới${removed ? ", nên chưa tạo gì cả" : ", và tài khoản vừa tạo chưa xoá được (vào Authentication → Users để xoá)"}.`);
    }
    return reply(200, { ok: true, id, username, role: body.role });
  }

  async function deleteAccount(body, caller) {
    const id = String(body.user_id || "").toLowerCase();
    if (!UUID.test(id)) return fail("Không rõ tài khoản cần xoá.");
    if (id === caller) return fail("Không tự xoá tài khoản của chính mình được.");
    let exists = false;
    try {
      exists = await deps.userExists(id);
    } catch (e) {
      exists = false;
    }
    if (!exists) return fail("Không tìm thấy tài khoản này (có thể đã xoá rồi).");
    try {
      await deps.deleteUser(id);
    } catch (e) {
      return fail(authMessage(e, "Không xoá được tài khoản."));
    }
    return reply(200, { ok: true, id });
  }

  async function resetPassword(body) {
    const id = String(body.user_id || "").toLowerCase();
    if (!UUID.test(id)) return fail("Không rõ tài khoản cần đặt lại mật khẩu.");
    const bad = checkPassword(body.password);
    if (bad) return fail(bad);
    let exists = false;
    try {
      exists = await deps.userExists(id);
    } catch (e) {
      exists = false;
    }
    if (!exists) return fail("Không tìm thấy tài khoản này.");
    try {
      await deps.setPassword(id, body.password);
    } catch (e) {
      return fail(authMessage(e, "Không đổi được mật khẩu."));
    }
    return reply(200, { ok: true, id });
  }
}

export { makeHandler, checkPassword, authMessage };

// ---- Deno / Supabase wiring (skipped when Node imports this file for the tests) --------------------------------------
if (typeof Deno !== "undefined" && typeof Deno.serve === "function") {
  const { createClient } = await import("jsr:@supabase/supabase-js@2");
  const url = Deno.env.get("SUPABASE_URL");
  // Supabase is renaming this variable: take either
  const adminKey = Deno.env.get("SUPABASE_SECRET_KEY") ?? Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!url || !adminKey) {
    Deno.serve((request) =>
      request.method === "OPTIONS"
        ? reply(204, null)
        : reply(500, {
            ok: false,
            error: "Edge Function chưa có khoá quản trị: không thấy SUPABASE_SECRET_KEY lẫn SUPABASE_SERVICE_ROLE_KEY. Hãy báo người cài đặt.",
          }));
  } else {
    const admin = createClient(url, adminKey, { auth: { persistSession: false, autoRefreshToken: false } });
    const must = (r) => {
      if (r.error) throw r.error;
      return r.data;
    };
    Deno.serve(makeHandler({
      getUserId: async (token) => (await admin.auth.getUser(token)).data?.user?.id ?? null,
      roleOf: async (id) => must(await admin.from("profiles").select("role").eq("user_id", id).maybeSingle())?.role ?? "",
      emailOf: async (id) => (await admin.auth.admin.getUserById(id)).data?.user?.email ?? "",
      createUser: async ({ email, password }) => must(await admin.auth.admin.createUser({ email, password, email_confirm: true })).user,
      deleteUser: async (id) => must(await admin.auth.admin.deleteUser(id)),
      setPassword: async (id, password) => must(await admin.auth.admin.updateUserById(id, { password })),
      insertProfile: async (row) => must(await admin.from("profiles").insert(row)),
      userExists: async (id) => !!(await admin.auth.admin.getUserById(id)).data?.user,
    }));
  }
}
