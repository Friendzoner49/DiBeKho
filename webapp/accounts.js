/* DiBeKho web: Cài đặt → Tài khoản (owner only). The owner creates accounts for staff and managers, changes a role,
   resets a password, takes a role away. Creating an account and setting a password go through the Edge Function
   `accounts` (cloud/supabase/functions/accounts), the only place that holds Supabase's admin key; the rest is SQL
   (cloud/supabase/011_accounts.sql). The page never stores or shows a password again after it is sent. */

const ACC_DOMAIN = "dibekho.local";
const ACC_ROLES = { desktop: "Chủ / quản lý", editor: "Nhân viên (gửi yêu cầu)", viewer: "Chỉ xem", "": "Chưa có quyền" };
const ACC_USERNAME = /^[a-z0-9._-]{3,30}$/;
const ACC_MIN_PASSWORD = 8;
let accounts = [];

const accShort = (email) => String(email || "").endsWith(`@${ACC_DOMAIN}`) ? String(email).slice(0, -(ACC_DOMAIN.length + 1)) : String(email || "");

function accRpcMessage(error) {
  const text = String(error.message || "");
  if (error.code === "PGRST202" || /could not find the function|does not exist/i.test(text)) {
    return "Máy chủ chưa có phần quản lý tài khoản: người cài đặt cần chạy SQL 011 (cloud/supabase/011_accounts.sql) trên Supabase.";
  }
  return text || "Lỗi không rõ. Hãy tải lại trang rồi thử lại.";
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
    if (status === 404) {
      fail("Chưa cài Edge Function «accounts» trên Supabase. Người cài đặt cần dán code trong cloud/supabase/functions/accounts/index.ts (xem docs/cloud/05-cai-dat.md).");
    }
    if (status === 401) {
      fail("Máy chủ từ chối phiên đăng nhập trước khi hàm chạy. Hãy đăng nhập lại; nếu vẫn vậy, người cài đặt tắt «Verify JWT» của hàm accounts (docs/cloud/05-cai-dat.md).");
    }
    fail("Không gọi được Edge Function (mạng chập chờn hoặc hàm chưa chạy). Thử lại sau ít phút.");
  }
  if (!data || data.ok !== true) fail((data && data.error) || "Edge Function trả lời không như mong đợi.");
  return data;
}

async function loadAccounts() {
  $("acc-msg").textContent = "Đang tải danh sách…";
  try {
    accounts = (await accRpc("web_accounts_list", {})) || [];
    $("acc-msg").textContent = `${accounts.length} tài khoản. Chọn một dòng rồi bấm nút bên trên. Dòng gạch ngang là tài khoản chưa có quyền.`;
  } catch (e) {
    accounts = [];
    $("acc-msg").textContent = e.message;
  }
  renderAccounts();
}

function renderAccounts() {
  buildTable("acc-table", [
    { label: "Tên đăng nhập", get: (a) => accShort(a.email) + (a.id === currentUserId ? " (bạn)" : "") },
    { label: "Tên hiển thị", get: (a) => a.display_name },
    { label: "Vai trò", get: (a) => ACC_ROLES[a.role] ?? a.role },
  ], accounts, { select: "one", rowClass: (a) => (a.role ? "" : "closed") });
}

function accPicked() {
  const [id] = selected("acc-table");
  const found = accounts.find((a) => a.id === id);
  if (!found) fail("Hãy bấm chọn một tài khoản trong danh sách trước.");
  return found;
}

const accRoleOptions = (current) => ["editor", "viewer", "desktop"]
  .map((r) => `<option value="${r}" ${r === current ? "selected" : ""}>${esc(ACC_ROLES[r])}</option>`).join("");

const accPasswordFields = () =>
  `<label>Mật khẩu:</label><input id="acc-pw" type="password" autocomplete="new-password" placeholder="ít nhất ${ACC_MIN_PASSWORD} ký tự, nên từ 10, có chữ và số">
   <label>Nhập lại mật khẩu:</label><input id="acc-pw2" type="password" autocomplete="new-password">
   <span></span><label class="check"><input id="acc-show" type="checkbox"> Hiện mật khẩu</label>`;

function accWireShow(body) {
  $("acc-show").addEventListener("change", (e) => {
    for (const id of ["acc-pw", "acc-pw2"]) body.querySelector(`#${id}`).type = e.target.checked ? "text" : "password";
  });
}

/** The same rules as the function (which checks again): a mistake is caught before anything is sent. */
function accCheckPassword() {
  const pw = $("acc-pw").value;
  if (pw.length < ACC_MIN_PASSWORD) fail(`Mật khẩu phải có ít nhất ${ACC_MIN_PASSWORD} ký tự (nên từ 10, có cả chữ và số).`);
  if (pw !== $("acc-pw2").value) fail("Hai ô mật khẩu chưa giống nhau.");
  return pw;
}

function accClearPasswords() {
  for (const id of ["acc-pw", "acc-pw2"]) { const el = $(id); if (el) el.value = ""; }
}

const OWNER_WARNING = "Vai trò CHỦ có toàn quyền: ghi thẳng mọi thứ, duyệt yêu cầu, thay toàn bộ dữ liệu, quản lý tài khoản. Chỉ nên cấp cho người quản lý.";

function accCreateDialog() {
  const body = openDialog("Tạo tài khoản",
    `<p class="hint">Mật khẩu do bạn gõ. Sau khi tạo, hãy gửi tên đăng nhập và mật khẩu cho người đó bằng hai tin nhắn riêng. Trang web không lưu và không hiện lại mật khẩu.</p>
     <div class="form2">
       <label>Tên đăng nhập:</label><span class="row"><input id="acc-user" class="grow" autocomplete="off" placeholder="vd. nhanvien1"><span class="hint">@${ACC_DOMAIN}</span></span>
       <label>Tên hiển thị:</label><input id="acc-name" autocomplete="off" placeholder="vd. Lan - kho (hiện cạnh yêu cầu họ gửi)">
       <label>Vai trò:</label><select id="acc-role">${accRoleOptions("editor")}</select>
       ${accPasswordFields()}
     </div>
     <p class="hint">Tên đăng nhập: 3–30 ký tự, chữ thường không dấu, số, dấu chấm, gạch dưới hoặc gạch ngang. Không cần địa chỉ email thật.</p>`,
    [{ label: "Tạo tài khoản", primary: true, run: async () => {
      const username = $("acc-user").value.trim().toLowerCase();
      if (username.includes("@")) fail(`Chỉ gõ tên ngắn (ví dụ nhanvien1), không gõ @${ACC_DOMAIN}.`);
      if (!ACC_USERNAME.test(username)) fail("Tên đăng nhập gồm 3–30 ký tự: chữ thường không dấu, số, dấu chấm, gạch dưới hoặc gạch ngang.");
      const role = $("acc-role").value;
      const password = accCheckPassword();
      if (role === "desktop" && !confirm(`${OWNER_WARNING}\n\nTạo tài khoản CHỦ «${username}»?`)) return false;
      try {
        await accFunction({ action: "create", username, password, role, display_name: $("acc-name").value.trim() });
      } finally { accClearPasswords(); }
      alert(`Đã tạo tài khoản «${username}» (${ACC_ROLES[role]}). Hãy gửi tên đăng nhập và mật khẩu cho người đó, mỗi thứ một tin nhắn riêng.`);
      await loadAccounts();
      return true;
    } }]);
  accWireShow(body);
}

function accRoleDialog() {
  const a = accPicked();
  const mine = a.id === currentUserId;
  const body = openDialog(`Đổi vai trò: ${accShort(a.email)}`,
    `<p class="hint">${mine ? "Đây là tài khoản của bạn: chỉ đổi được tên hiển thị (không tự hạ quyền được, sẽ không còn ai quản lý)." : "Người đó đăng xuất rồi đăng nhập lại là thấy quyền mới."}</p>
     <div class="form2">
       <label>Tên hiển thị:</label><input id="acc-name" value="${esc(a.display_name)}" autocomplete="off">
       <label>Vai trò:</label><select id="acc-role" ${mine ? "disabled" : ""}>${accRoleOptions(a.role || "viewer")}</select>
     </div>`,
    [{ label: "Lưu", primary: true, run: async () => {
      const role = mine ? "desktop" : $("acc-role").value;
      if (role === "desktop" && a.role !== "desktop" && !confirm(`${OWNER_WARNING}\n\nĐổi «${accShort(a.email)}» thành CHỦ?`)) return false;
      if (a.role === "desktop" && role !== "desktop" &&
          !confirm(`«${accShort(a.email)}» đang là chủ. Nếu app trên máy chính đang đăng nhập bằng tài khoản này thì đồng bộ sẽ dừng.\n\nVẫn hạ quyền?`)) return false;
      await accRpc("web_account_set_role", { p_user: a.id, p_role: role, p_name: $("acc-name").value.trim() || null });
      await loadAccounts();
      return true;
    } }]);
  void body;
}

function accPasswordDialog() {
  const a = accPicked();
  const body = openDialog(`Đặt lại mật khẩu: ${accShort(a.email)}`,
    `<p class="hint">${a.role === "desktop" ? "Tài khoản chủ: nếu app trên máy chính dùng tài khoản này, app sẽ báo cần gõ lại mật khẩu mới (Cài đặt → Cloud). " : ""}Hãy báo mật khẩu mới cho người đó bằng tin nhắn riêng.</p>
     <div class="form2">${accPasswordFields()}</div>`,
    [{ label: "Đổi mật khẩu", primary: true, run: async () => {
      const password = accCheckPassword();
      try {
        await accFunction({ action: "reset_password", user_id: a.id, password });
      } finally { accClearPasswords(); }
      alert(`Đã đổi mật khẩu của «${accShort(a.email)}». Hãy báo mật khẩu mới cho người đó, riêng từng tin nhắn.`);
      return true;
    } }]);
  accWireShow(body);
}

async function accRevoke() {
  const a = accPicked();
  if (a.id === currentUserId) fail("Không tự thu hồi quyền của chính mình được (sẽ không còn ai quản lý). Nhờ chủ khác làm.");
  if (!a.role) fail("Tài khoản này chưa có quyền gì để thu hồi.");
  const extra = a.role === "desktop" ? "\n\nĐây là tài khoản CHỦ: nếu app trên máy chính đang đăng nhập bằng tài khoản này thì đồng bộ sẽ dừng." : "";
  if (!confirm(`Thu hồi quyền của «${accShort(a.email)}»?\n\nTài khoản vẫn còn nhưng không xem và không ghi được gì nữa. Cấp lại bằng «Đổi vai trò…».${extra}`)) return;
  await accRpc("web_account_revoke", { p_user: a.id });
  await loadAccounts();
}

document.querySelector('[data-stab="accounts"]').addEventListener("click", loadAccounts);
$("acc-btn-add").addEventListener("click", () => ownerAction(async () => accCreateDialog()));
$("acc-btn-role").addEventListener("click", () => ownerAction(async () => accRoleDialog()));
$("acc-btn-pass").addEventListener("click", () => ownerAction(async () => accPasswordDialog()));
$("acc-btn-revoke").addEventListener("click", () => ownerAction(accRevoke));
$("acc-btn-reload").addEventListener("click", loadAccounts);
