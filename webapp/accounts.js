/* DiBeKho web: Cài đặt → Tài khoản (the maychinh login only). It creates accounts for staff and managers, changes a
   role, resets a password, takes a role away. Creating an account and setting a password go through the Edge Function
   `accounts` (cloud/supabase/functions/accounts), the only place that holds Supabase's admin key; the rest is SQL
   (cloud/supabase/011_accounts.sql). The page never stores or shows a password again after it is sent. */

"use strict";

const ACC_DOMAIN = "dibekho.local";
const ACC_USERNAME = /^[a-z0-9._-]{3,30}$/;
const ACC_MIN_PASSWORD = 8;
const accRoleName = (role) => tr(`role.acc_${role || "none"}`);
let accounts = [];

const accShort = (email) => String(email || "").endsWith(`@${ACC_DOMAIN}`) ? String(email).slice(0, -(ACC_DOMAIN.length + 1)) : String(email || "");

function accRpcMessage(error) {
  const text = String(error.message || "");
  if (error.code === "PGRST202" || /could not find the function|does not exist/i.test(text)) return tr("acc.no_sql");
  return text || tr("acc.unknown");
}

async function accRpc(fn, args) {
  const { data, error } = await sb.rpc(fn, args);
  if (error) fail(accRpcMessage(error));
  return data;
}

/** The Edge Function answers {ok, error}; a status that is not 200 is read as far as possible and explained. */
async function accFunction(body) {
  const { data, error } = await sb.functions.invoke("accounts", { body });
  if (error) {
    const status = error.context && error.context.status;
    let detail = "";
    try { detail = (await error.context.json()).error || ""; } catch (e) { /* not our JSON: the gateway answered */ }
    if (detail) fail(detail);
    if (status === 404) fail(tr("acc.no_function"));
    if (status === 401) fail(tr("acc.jwt"));
    fail(tr("acc.no_call"));
  }
  if (!data || data.ok !== true) fail((data && data.error) || tr("acc.odd_answer"));
  return data;
}

async function loadAccounts() {
  $("acc-msg").textContent = tr("acc.loading");
  try {
    accounts = (await accRpc("web_accounts_list", {})) || [];
    $("acc-msg").textContent = tr("acc.loaded", { n: accounts.length });
  } catch (e) {
    accounts = [];
    $("acc-msg").textContent = e.message;
  }
  renderAccounts();
}

function renderAccounts() {
  buildTable("acc-table", [
    { label: tr("acc.col_user"), get: (a) => accShort(a.email) + (a.id === currentUserId ? tr("acc.you") : "") },
    { label: tr("acc.col_name"), get: (a) => a.display_name },
    { label: tr("acc.col_role"), get: (a) => accRoleName(a.role) },
  ], accounts, { select: "one", rowClass: (a) => (a.role ? "" : "closed") });
}

function accPicked() {
  const [id] = selected("acc-table");
  const found = accounts.find((a) => a.id === id);
  if (!found) fail(tr("acc.pick_first"));
  return found;
}

const accRoleOptions = (current) => ["editor", "viewer", "desktop"]
  .map((r) => `<option value="${r}" ${r === current ? "selected" : ""}>${esc(accRoleName(r))}</option>`).join("");

const accPasswordFields = () =>
  `<label>${esc(tr("acc.password"))}</label><input id="acc-pw" type="password" autocomplete="new-password" placeholder="${esc(tr("acc.password_ph", { n: ACC_MIN_PASSWORD }))}">
   <label>${esc(tr("acc.password2"))}</label><input id="acc-pw2" type="password" autocomplete="new-password">
   <span></span><label class="check"><input id="acc-show" type="checkbox"> ${esc(tr("acc.show"))}</label>`;

function accWireShow(body) {
  $("acc-show").addEventListener("change", (e) => {
    for (const id of ["acc-pw", "acc-pw2"]) body.querySelector(`#${id}`).type = e.target.checked ? "text" : "password";
  });
}

/** The same rules as the function (which checks again): a mistake is caught before anything is sent. */
function accCheckPassword() {
  const pw = $("acc-pw").value;
  if (pw.length < ACC_MIN_PASSWORD) fail(tr("acc.too_short", { n: ACC_MIN_PASSWORD }));
  if (pw !== $("acc-pw2").value) fail(tr("acc.mismatch"));
  return pw;
}

function accClearPasswords() {
  for (const id of ["acc-pw", "acc-pw2"]) { const el = $(id); if (el) el.value = ""; }
}

function accCreateDialog() {
  const body = openDialog(tr("acc.create_title"),
    `<p class="hint">${esc(tr("acc.create_hint"))}</p>
     <div class="form2">
       <label>${esc(tr("acc.user"))}</label><span class="row"><input id="acc-user" class="grow" autocomplete="off" placeholder="${esc(tr("acc.user_ph"))}"><span class="hint">@${ACC_DOMAIN}</span></span>
       <label>${esc(tr("acc.name"))}</label><input id="acc-name" autocomplete="off" placeholder="${esc(tr("acc.name_ph"))}">
       <label>${esc(tr("acc.role_label"))}</label><select id="acc-role">${accRoleOptions("editor")}</select>
       ${accPasswordFields()}
     </div>
     <p class="hint">${esc(tr("acc.user_rule"))}</p>`,
    [{ label: tr("acc.create_do"), primary: true, run: async () => {
      const username = $("acc-user").value.trim().toLowerCase();
      if (username.includes("@")) fail(tr("acc.no_at", { domain: ACC_DOMAIN }));
      if (!ACC_USERNAME.test(username)) fail(tr("acc.bad_user"));
      const role = $("acc-role").value;
      const password = accCheckPassword();
      if (role === "desktop" && !confirm(`${tr("acc.owner_warning")}\n\n${tr("acc.owner_create", { user: username })}`)) return false;
      try {
        await accFunction({ action: "create", username, password, role, display_name: $("acc-name").value.trim() });
      } finally { accClearPasswords(); }
      alert(tr("acc.created", { user: username, role: accRoleName(role) }));
      await loadAccounts();
      return true;
    } }]);
  accWireShow(body);
}

function accRoleDialog() {
  const a = accPicked();
  const mine = a.id === currentUserId;
  openDialog(tr("acc.role_title", { user: accShort(a.email) }),
    `<p class="hint">${esc(tr(mine ? "acc.role_mine" : "acc.role_hint"))}</p>
     <div class="form2">
       <label>${esc(tr("acc.name"))}</label><input id="acc-name" value="${esc(a.display_name)}" autocomplete="off">
       <label>${esc(tr("acc.role_label"))}</label><select id="acc-role" ${mine ? "disabled" : ""}>${accRoleOptions(a.role || "viewer")}</select>
     </div>`,
    [{ label: tr("btn.save"), primary: true, run: async () => {
      const role = mine ? "desktop" : $("acc-role").value;
      if (role === "desktop" && a.role !== "desktop" && !confirm(`${tr("acc.owner_warning")}\n\n${tr("acc.owner_make", { user: accShort(a.email) })}`)) return false;
      if (a.role === "desktop" && role !== "desktop" && !confirm(tr("acc.owner_lower", { user: accShort(a.email) }))) return false;
      await accRpc("web_account_set_role", { p_user: a.id, p_role: role, p_name: $("acc-name").value.trim() || null });
      await loadAccounts();
      return true;
    } }]);
}

function accPasswordDialog() {
  const a = accPicked();
  const body = openDialog(tr("acc.pass_title", { user: accShort(a.email) }),
    `<p class="hint">${esc((a.role === "desktop" ? tr("acc.pass_owner") + " " : "") + tr("acc.pass_hint"))}</p>
     <div class="form2">${accPasswordFields()}</div>`,
    [{ label: tr("acc.pass_do"), primary: true, run: async () => {
      const password = accCheckPassword();
      try {
        await accFunction({ action: "reset_password", user_id: a.id, password });
      } finally { accClearPasswords(); }
      alert(tr("acc.pass_done", { user: accShort(a.email) }));
      return true;
    } }]);
  accWireShow(body);
}

async function accRevoke() {
  const a = accPicked();
  if (a.id === currentUserId) fail(tr("acc.revoke_self"));
  if (!a.role) fail(tr("acc.revoke_none"));
  const extra = a.role === "desktop" ? "\n\n" + tr("acc.owner_sync") : "";
  if (!confirm(tr("acc.revoke_ask", { user: accShort(a.email) }) + extra)) return;
  await accRpc("web_account_revoke", { p_user: a.id });
  await loadAccounts();
}

async function accDelete() {
  const a = accPicked();
  if (a.id === currentUserId) fail(tr("acc.delete_self"));
  const extra = a.role === "desktop" ? "\n\n" + tr("acc.owner_sync") : "";
  if (!confirm(tr("acc.delete_ask", { user: accShort(a.email) }) + extra)) return;
  await accFunction({ action: "delete", user_id: a.id });
  await loadAccounts();
}

document.querySelector('[data-stab="accounts"]').addEventListener("click", loadAccounts);
$("acc-btn-add").addEventListener("click", () => ownerAction(async () => accCreateDialog()));
$("acc-btn-role").addEventListener("click", () => ownerAction(async () => accRoleDialog()));
$("acc-btn-pass").addEventListener("click", () => ownerAction(async () => accPasswordDialog()));
$("acc-btn-revoke").addEventListener("click", () => ownerAction(accRevoke));
$("acc-btn-delete").addEventListener("click", () => ownerAction(accDelete));
$("acc-btn-reload").addEventListener("click", loadAccounts);
