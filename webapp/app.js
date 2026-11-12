/* DiBeKho web: the shop's shared data (the cloud's real tables, docs/cloud/06-cloud-la-goc.md), laid out like the
   desktop app so the same people find the same buttons in the same places (user's request 12/11/2026).
   Plain JS on purpose: no build step, easy to edit. Reads with supabase-js; the owner writes through the functions of
   cloud/supabase/009_web_rpc.sql (forms.js), staff send requests to web_inbox that the owner approves in the app. */

"use strict";

/* "Nhớ tôi": ticked = the sign-in survives closing the browser (localStorage) and the name is filled in next time;
   not ticked = it ends with the browser (sessionStorage), for a shared computer. Storage may be blocked (private
   window): then nothing is kept and the page still works. */
const REMEMBER_KEY = "dibekho_remember", USER_KEY = "dibekho_user";
function store(kind) { try { return window[kind]; } catch (e) { return null; } }
function remembering() { try { return store("localStorage").getItem(REMEMBER_KEY) !== "0"; } catch (e) { return true; } }
const authStorage = {
  getItem(k) { try { return store(remembering() ? "localStorage" : "sessionStorage").getItem(k); } catch (e) { return null; } },
  setItem(k, v) { try { store(remembering() ? "localStorage" : "sessionStorage").setItem(k, v); } catch (e) { /* not kept */ } },
  removeItem(k) {
    for (const kind of ["localStorage", "sessionStorage"]) { try { store(kind).removeItem(k); } catch (e) { /* none */ } }
  },
};
const sb = supabase.createClient(DIBEKHO_CLOUD.url, DIBEKHO_CLOUD.key,
                                 { auth: { storage: authStorage, persistSession: true } });
const EMAIL_DOMAIN = "dibekho.local";
const KIND_VI = { delivery: "Phiếu giao hàng", receipt: "Hàng về", stock_count: "Kiểm kê",
                  transfer: "Chuyển hàng", trial: "Dùng thử" };
const KIND_ORDER = ["delivery", "receipt", "stock_count", "transfer", "trial"];
const STATUS_VI = { active: "", cancelled: "đã huỷ", replaced: "đã thay" };
const PLACE = { 1: "Kho tổng", 2: "Văn phòng" };

const $ = (id) => document.getElementById(id);
const data = { products: [], customers: [], suppliers: [], documents: [], lines: [], movements: [], meta: {} };
let productById = {}, customerById = {}, supplierById = {}, docById = {}, linesByDoc = {}, stockByProduct = {};
let userRole = "", userName = "";
let lowDefault = 30;  // the app's alarm level (meta low_stock_default; 0 = off)
const isOwner = () => userRole === "desktop";
const isStaff = () => userRole === "editor";

/* ---------------------------------------------------------------- helpers */

function unaccent(s) {
  return (s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replaceAll("đ", "d");
}

function matches(needle, hay) {
  return unaccent(needle).split(/\s+/).filter(Boolean).every((w) => unaccent(hay).includes(w));
}

function fmtQty(n) {
  if (n === null || n === undefined || n === "") return "";
  return Number.isInteger(n) ? String(n) : String(Math.round(n * 1000) / 1000).replace(".", ",");
}

function fmtMoney(n) {
  return n === null || n === undefined ? "" : Number(n).toLocaleString("vi-VN");
}

// the cloud keeps UTC in updated_at: show the viewer's own clock, like the app
function fmtTime(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return "";
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// the viewer's own calendar day (toISOString() gives the UTC day)
function todayLocal() {
  const d = new Date(), p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** A typed quantity: '1,5' and '1.5' both mean one and a half, full-width digits too (like the app). "" -> null. */
function parseQty(text) {
  const s = String(text ?? "").normalize("NFKC").trim().replace(",", ".");
  if (!s) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : NaN;
}

function productName(p) {
  return [p.name_vi, p.spec, p.variant].filter(Boolean).join(" · ");
}

function productLabel(p) {
  return [p.code, p.name_vi, p.spec, p.variant, p.name_zh].filter(Boolean).join(" · ");
}

const stockOf = (id) => stockByProduct[id] || { total: 0, 1: 0, 2: 0 };
const activeProducts = () => data.products.filter((p) => p.active)
  .sort((a, b) => (a.category || "").localeCompare(b.category || "", "vi") || a.name_vi.localeCompare(b.name_vi, "vi") ||
                  (a.spec || "").localeCompare(b.spec || "", "vi"));

/* Sortable table, like the app's: click a header to sort; click a row to select it (select: "one" | "many"),
   double-click to open it. cols = [{label, get, num?, cls?, html?}]. */
const tableState = {};

function buildTable(into, cols, items, opts = {}) {
  const st = tableState[into] ||= { i: null, dir: 1, sel: new Set() };
  const keyOf = opts.key || ((x) => x.id);
  if (opts.open && !opts.select) opts = { ...opts, select: "one" };  // every list that opens rows can select one
  let rows = items;
  if (st.i !== null && cols[st.i]) {
    const c = cols[st.i];
    rows = items.slice().sort((a, b) => {
      const va = c.get(a), vb = c.get(b);
      if (c.num) return ((va ?? -Infinity) - (vb ?? -Infinity)) * st.dir;
      return String(va ?? "").localeCompare(String(vb ?? ""), "vi") * st.dir;
    });
  }
  const alive = new Set(items.map(keyOf));
  for (const k of [...st.sel]) if (!alive.has(k)) st.sel.delete(k);
  const head = cols.map((c, i) =>
    `<th data-i="${i}" class="sortable ${c.num ? "num" : ""} ${st.i === i ? (st.dir > 0 ? "asc" : "desc") : ""}">${esc(c.label)}</th>`).join("");
  const body = rows.map((item) => {
    const k = keyOf(item);
    return `<tr data-k="${esc(k)}" class="${opts.rowClass ? opts.rowClass(item) : ""} ${st.sel.has(k) ? "sel" : ""}">` +
      cols.map((c) => `<td class="${c.cls || ""}">${c.html ? c.html(item) : esc(c.get(item))}</td>`).join("") + "</tr>";
  }).join("");
  const el = $(into);
  el.innerHTML = `<div class="scroll"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>` +
    (opts.empty && !rows.length ? `<p class="hint">${esc(opts.empty)}</p>` : "");
  const byKey = new Map(items.map((x) => [String(keyOf(x)), x]));
  for (const th of el.querySelectorAll("th.sortable")) {
    th.addEventListener("click", () => {
      const i = Number(th.dataset.i);
      if (st.i === i) st.dir *= -1; else { st.i = i; st.dir = 1; }
      buildTable(into, cols, items, opts);
    });
  }
  for (const tr of el.querySelectorAll("tbody tr")) {
    const item = byKey.get(tr.dataset.k);
    if (opts.select) {
      tr.addEventListener("click", (e) => {
        if (e.target.closest("input, select, button")) return;
        const k = keyOf(item);
        // phones cannot double-click reliably: tapping the row that is already selected opens it
        if (opts.open && opts.select === "one" && st.sel.has(k)) { opts.open(item); return; }
        if (opts.select === "many") { st.sel.has(k) ? st.sel.delete(k) : st.sel.add(k); }
        else { st.sel.clear(); st.sel.add(k); }
        for (const other of el.querySelectorAll("tbody tr")) {
          const it = byKey.get(other.dataset.k);
          other.classList.toggle("sel", !!it && st.sel.has(keyOf(it)));
        }
      });
    }
    if (opts.open) {
      tr.classList.add("click");
      tr.addEventListener("dblclick", (e) => { if (!e.target.closest("input, select, button")) opts.open(item); });
    }
  }
  return el;
}

function selected(into) {
  const st = tableState[into];
  return st ? [...st.sel] : [];
}

/* ---------------------------------------------------------------- login */

async function signIn() {
  const user = $("user").value.trim();
  const email = user.includes("@") ? user : `${user}@${EMAIL_DOMAIN}`;
  $("login-error").textContent = "";
  const remember = $("remember").checked;
  try {
    store("localStorage").setItem(REMEMBER_KEY, remember ? "1" : "0");
    if (remember) store("localStorage").setItem(USER_KEY, user); else store("localStorage").removeItem(USER_KEY);
    if (!remember) {  // a sign-in kept from before must not outlive this one
      const ls = store("localStorage");
      Object.keys(ls).filter((k) => k.startsWith("sb-")).forEach((k) => ls.removeItem(k));
    }
  } catch (e) { /* storage blocked: nothing is remembered */ }
  const { error } = await sb.auth.signInWithPassword({ email, password: $("password").value });
  if (error) {
    $("login-error").textContent = /credentials/i.test(error.message)
      ? "Sai tên đăng nhập hoặc mật khẩu." : `Không đăng nhập được: ${error.message}`;
    return;
  }
  showApp();
}

async function showApp() {
  $("login").classList.add("hidden");
  $("app").classList.remove("hidden");
  // filter by our own id: the owner's account may read every profile row
  const { data: { user } } = await sb.auth.getUser();
  const { data: prof } = await sb.from("profiles").select("role,display_name").eq("user_id", user.id).maybeSingle();
  setRole(prof ? prof.role : "", (prof && prof.display_name) || (user.email || "").split("@")[0]);
  await loadAll();
}

function setRole(role, name) {
  userRole = role || "";
  userName = name || "";
  document.body.classList.remove("role-desktop", "role-editor", "role-viewer");
  if (userRole) document.body.classList.add(`role-${userRole}`);
  const what = { desktop: "chủ", editor: "nhân viên", viewer: "chỉ xem" }[userRole] || "chưa có quyền";
  $("who").textContent = `${userName} (${what})`;
}

/* ---------------------------------------------------------------- data */

async function fetchAll(table, key = "id") {
  // PostgREST pages at 1000 rows: a stable order is required or rows repeat/vanish between pages
  const out = [];
  for (let from = 0; ; from += 1000) {
    const { data: rows, error } = await sb.from(table).select("*").eq("deleted", false).order(key).range(from, from + 999);
    if (error) throw error;
    out.push(...rows);
    if (rows.length < 1000) return out;
  }
}

/** The tables the web reads (tests/test_web_loads_all_tables.py keeps this list complete). */
const WEB_TABLES = ["products", "customers", "suppliers", "documents", "document_lines", "stock_movements", "meta"];

async function loadAll() {
  $("load-error").textContent = "";
  try {
    const [products, customers, suppliers, documents, lines, movements, meta] = await Promise.all([
      fetchAll("products"), fetchAll("customers"), fetchAll("suppliers"), fetchAll("documents"),
      fetchAll("document_lines"), fetchAll("stock_movements"), fetchAll("meta", "key"),
    ]);
    setData({ products, customers, suppliers, documents, lines, movements, meta });
  } catch (e) {
    $("load-error").textContent = `Không tải được dữ liệu: ${e.message || e}`;
    return;
  }
  renderAll();
  loadInbox();
}

function setData(d) {
  Object.assign(data, d, { meta: {} });
  for (const m of d.meta) data.meta[m.key] = m.value;
  productById = {}; customerById = {}; supplierById = {}; docById = {}; linesByDoc = {}; stockByProduct = {};
  for (const p of data.products) productById[p.id] = p;
  for (const c of data.customers) customerById[c.id] = c;
  for (const s of data.suppliers) supplierById[s.id] = s;
  for (const doc of data.documents) {
    doc.supplier_name = (supplierById[doc.supplier_id] || {}).name || "";
    docById[doc.id] = doc;
  }
  for (const l of data.lines) (linesByDoc[l.document_id] ||= []).push(l);
  for (const m of data.movements) {
    const t = stockByProduct[m.product_id] ||= { total: 0, 1: 0, 2: 0, lastOut: "" };
    t.total += m.qty; t[m.location_id] = (t[m.location_id] || 0) + m.qty;
    if (m.kind === "delivery_out" && m.occurred_on > t.lastOut) t.lastOut = m.occurred_on;
  }
  const level = Number(data.meta.low_stock_default);
  lowDefault = data.meta.low_stock_default !== undefined && Number.isFinite(level) ? level : 30;
  let newest = "";
  for (const list of [d.products, d.customers, d.documents, d.movements, d.lines]) {
    for (const r of list) if (r.updated_at && r.updated_at > newest) newest = r.updated_at;
  }
  $("freshness").textContent = newest ? `Dữ liệu chung · thay đổi gần nhất lúc ${fmtTime(newest)}` : "";
  // suggestion lists of the forms
  $("products-dl").innerHTML = activeProducts().map((p) => `<option value="${esc(productLabel(p))}">`).join("");
  $("suppliers-dl").innerHTML = data.suppliers.map((s) => `<option value="${esc(s.name)}">`).join("");
  $("categories-dl").innerHTML = [...new Set(data.products.map((p) => p.category).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b, "vi")).map((c) => `<option value="${esc(c)}">`).join("");
}

function productFromLabel(text) {
  const t = String(text || "").trim();
  if (!t) return null;
  return activeProducts().find((p) => productLabel(p) === t) || activeProducts().find((p) => p.code === t.split(" ")[0]) || null;
}

/* ---------------------------------------------------------------- navigation (the app's left bar) */

let page = "stock";
let backTo = "stock";

function showPage(name) {
  if (name !== "detail") backTo = name;
  page = name;
  document.querySelectorAll(".page").forEach((p) => p.classList.toggle("hidden", p.id !== `page-${name}`));
  const top = ["orders", "customers", "stats"].includes(name) ? "search" : name === "detail" ? null : name;
  if (top) document.querySelectorAll(".nav").forEach((b) => b.classList.toggle("active", b.dataset.page === top));
  window.scrollTo(0, 0);
}

function renderAll() {
  renderStock(); renderPendingUnplaced(); renderSearch(); renderOrders(); renderCustomers(); renderReceipts();
  renderCount(); renderCatalog(); renderSettingsInfo();
  if (!$("page-stats").dataset.ready) { initStats(); $("page-stats").dataset.ready = "1"; } else { syncStatsControls(); renderStats(); }
}

/* ---------------------------------------------------------------- Tồn kho */

function renderStock() {
  const f = $("stock-filter").value, onlyLow = $("stock-low").checked;
  const all = activeProducts();
  const isLow = (p) => lowDefault && stockOf(p.id).total < lowDefault;
  const items = all.filter((p) => (!onlyLow || isLow(p)) &&
    (!f || matches(f, `${p.code} ${p.name_vi} ${p.name_zh} ${p.spec} ${p.variant} ${p.category} ${p.stock_note}`)));
  buildTable("stock-table", [
    { label: "Mã", get: (p) => p.code },
    { label: "Mặt hàng", get: (p) => p.name_vi },
    { label: "Tên Trung", get: (p) => p.name_zh },
    { label: "Quy cách", get: (p) => p.spec },
    { label: "Loại / màu", get: (p) => p.variant },
    { label: "Nhóm hàng", get: (p) => p.category },
    { label: "Đơn vị", get: (p) => p.unit },
    { label: "Tồn", get: (p) => stockOf(p.id).total, num: true, cls: "num strong", html: (p) => fmtQty(stockOf(p.id).total) },
    { label: "Ghi chú tồn kho", get: (p) => p.stock_note },
    { label: "Kho tổng", get: (p) => stockOf(p.id)[1], num: true, cls: "num", html: (p) => fmtQty(stockOf(p.id)[1]) },
    { label: "Văn phòng", get: (p) => stockOf(p.id)[2], num: true, cls: "num", html: (p) => fmtQty(stockOf(p.id)[2]) },
    { label: "Xuất gần nhất", get: (p) => stockOf(p.id).lastOut || "" },
  ], items, {
    rowClass: (p) => (stockOf(p.id).total < 0 ? "neg" : isLow(p) ? "low" : ""),
    select: "one", open: (p) => showProduct(p.id),
  });
  const low = all.filter(isLow).length, negative = all.filter((p) => stockOf(p.id).total < 0).length;
  $("stock-banner").classList.toggle("hidden", !low);
  $("stock-banner").textContent = `⚠ ${low} mặt hàng sắp hết (dưới ${fmtQty(lowDefault)}) — nên đặt thêm hàng. Tick “Chỉ hiện hàng sắp hết” để xem riêng.`;
  $("stock-summary").textContent = `${all.length} mặt hàng · ${low} sắp hết (cam) · ${negative} tồn âm (đỏ — thiếu hàng về hoặc chưa kiểm kê)`;
}

/* ---------------------------------------------------------------- Cần xử lý */

function renderPendingUnplaced() {
  const items = data.documents.filter((d) => d.kind === "delivery" && d.status === "active" && d.location_set === false)
    .sort((a, b) => a.doc_date.localeCompare(b.doc_date));
  buildTable("pending-unplaced", [
    { label: "Ngày", get: (d) => d.doc_date },
    { label: "Mã đơn", get: (d) => d.code },
    { label: "Khách hàng", get: (d) => (customerById[d.customer_id] || {}).name || "" },
    { label: "Mặt hàng", get: (d) => (linesByDoc[d.id] || []).map((l) => `${(productById[l.product_id] || {}).code || "?"}×${fmtQty(l.qty)}`).join(", ") },
    { label: "Lấy hàng từ", get: () => "", html: (d) => isOwner()
        ? `<select data-place="${esc(d.id)}"><option value="1">Kho tổng</option><option value="2">Văn phòng</option></select> ` +
          `<button data-place-save="${esc(d.id)}">Lưu</button>` : "chưa chọn" },
  ], items, { open: (d) => showOrder(d.id), empty: "Không có đơn nào chờ chọn nơi lấy hàng." });
  for (const btn of $("pending-unplaced").querySelectorAll("[data-place-save]")) {
    btn.addEventListener("click", () => {
      const id = btn.dataset.placeSave;
      const sel = $("pending-unplaced").querySelector(`select[data-place="${CSS.escape(id)}"]`);
      ownerAction(() => rpcWrite("web_set_location", { p_doc: id, p_location: Number(sel.value) }));
    });
  }
  updatePendingBadge();
}

let inboxRows = [];

const INBOX_KIND = {
  receipt: "Hàng về", delivery_file: "Phiếu giao hàng (file)", stock_count: "Kiểm kê",
  cmd_transfer: "Chuyển hàng (lệnh cũ)", cmd_trial: "Xuất dùng thử (lệnh cũ)", cmd_product_add: "Thêm mặt hàng (lệnh cũ)",
  cmd_product_edit: "Sửa mặt hàng (lệnh cũ)", cmd_product_merge: "Gộp mặt hàng (lệnh cũ)", cmd_customer_merge: "Gộp khách (lệnh cũ)",
  cmd_cancel_doc: "Huỷ phiếu (lệnh cũ)", cmd_set_location: "Đặt nơi (lệnh cũ)", cmd_receipt_edit: "Sửa phiếu hàng về (lệnh cũ)",
};

function inboxDetail(r) {
  const p = r.payload || {};
  if (p.summary) return p.summary;
  if (r.kind === "delivery_file") return p.file_name || "";
  if (r.kind === "stock_count") return `${p.count_date || ""} · ${PLACE[p.location_id] || "Kho tổng"} · ${(p.lines || []).length} mặt hàng`;
  return `${p.doc_date || ""} · ${p.supplier_name || (customerById[p.customer_id] || {}).name || ""} · ${(p.lines || []).length} dòng`;
}

function inboxStatus(r) {
  const res = r.result || {};
  if (r.status === "rejected") return res.reason ? `✖ Không vào sổ: ${res.reason}` : "✖ Bị từ chối";
  if (r.status !== "applied") return "⏳ Chờ chủ duyệt trên app";
  if (r.kind === "delivery_file") return res.already ? "✔ App đã có phiếu này" : "✔ Đã nhận, app đang đọc";
  return `✔ Đã vào sổ${res.code ? ` (${res.code})` : ""}`;
}

async function loadInbox() {
  if (!userRole || userRole === "viewer") { $("pending-inbox").innerHTML = ""; inboxRows = []; updatePendingBadge(); return; }
  const { data: rows, error } = await sb.from("web_inbox").select("*").order("created_at", { ascending: false }).limit(50);
  inboxRows = error || !rows ? [] : rows;
  let names = new Map();
  if (isOwner()) {
    const { data: profs } = await sb.from("profiles").select("user_id,display_name");
    names = new Map((profs || []).map((p) => [p.user_id, p.display_name || ""]));
  }
  buildTable("pending-inbox", [
    { label: "Gửi lúc", get: (r) => fmtTime(r.created_at) },
    ...(isOwner() ? [{ label: "Người gửi", get: (r) => names.get(r.created_by) || "" }] : []),
    { label: "Loại", get: (r) => INBOX_KIND[r.kind] || r.kind },
    { label: "Nội dung", get: inboxDetail },
    { label: "Trạng thái", get: inboxStatus },
  ], inboxRows, { empty: "Chưa có yêu cầu nào." });
  updatePendingBadge();
}

function updatePendingBadge() {
  const unplaced = data.documents.filter((d) => d.kind === "delivery" && d.status === "active" && d.location_set === false).length;
  const waiting = inboxRows.filter((r) => r.status === "pending").length;
  const n = unplaced + waiting;
  $("nav-pending").textContent = n ? `Cần xử lý  (${n})` : "Cần xử lý";
  $("nav-pending").classList.toggle("alert", n > 0);
}

/* ---------------------------------------------------------------- Tra cứu */

function renderSearch() {
  const f = $("search-input").value.trim();
  const out = $("search-results");
  if (!f) { out.innerHTML = ""; return; }
  const products = data.products.filter((p) => matches(f, `${p.code} ${p.name_vi} ${p.name_zh} ${p.spec} ${p.variant} ${p.category} ${p.stock_note}`));
  const customers = data.customers.filter((c) => matches(f, `${c.name} ${c.contact} ${c.phone} ${c.address}`));
  const docs = data.documents.filter((d) => matches(f, `${d.code} ${d.note} ${(customerById[d.customer_id] || {}).name || ""} ${d.supplier_name}`))
    .sort((a, b) => b.doc_date.localeCompare(a.doc_date)).slice(0, 200);
  out.innerHTML = `<h2>Mặt hàng (${products.length})</h2><div id="sr-products"></div>` +
    `<h2>Khách hàng (${customers.length})</h2><div id="sr-customers"></div><h2>Phiếu (${docs.length})</h2><div id="sr-docs"></div>`;
  buildTable("sr-products", [
    { label: "Mã", get: (p) => p.code }, { label: "Mặt hàng", get: productName }, { label: "Tên Trung", get: (p) => p.name_zh },
    { label: "Tồn", get: (p) => stockOf(p.id).total, num: true, cls: "num strong", html: (p) => fmtQty(stockOf(p.id).total) },
  ], products, { open: (p) => showProduct(p.id) });
  buildTable("sr-customers", [
    { label: "Khách hàng", get: (c) => c.name }, { label: "Điện thoại", get: (c) => c.phone }, { label: "Địa chỉ", get: (c) => c.address },
  ], customers, { open: (c) => showCustomer(c.id) });
  buildTable("sr-docs", [
    { label: "Ngày", get: (d) => d.doc_date }, { label: "Loại", get: (d) => KIND_VI[d.kind] || d.kind }, { label: "Mã", get: (d) => d.code },
    { label: "Khách / nguồn", get: (d) => (customerById[d.customer_id] || {}).name || d.supplier_name },
    { label: "Trạng thái", get: (d) => STATUS_VI[d.status] ?? d.status },
  ], docs, { open: (d) => showOrder(d.id), rowClass: (d) => (d.status !== "active" ? "closed" : "") });
}

/* ---------------------------------------------------------------- Đơn hàng */

function renderOrders() {
  const kindSel = $("orders-kind");
  if (!kindSel.options.length) {
    kindSel.innerHTML = `<option value="all">Tất cả</option>` + KIND_ORDER.map((k) => `<option value="${k}">${KIND_VI[k]}</option>`).join("");
    kindSel.value = "delivery";
  }
  const kind = kindSel.value, f = $("orders-filter").value, withClosed = $("orders-closed").checked;
  const items = data.documents.filter((d) => (kind === "all" || d.kind === kind) && (withClosed || d.status === "active") &&
      (!f || matches(f, `${d.code} ${(customerById[d.customer_id] || {}).name || ""} ${d.supplier_name} ${d.note}`)))
    .sort((a, b) => b.doc_date.localeCompare(a.doc_date) || String(b.code).localeCompare(String(a.code), "vi", { numeric: true }));
  buildTable("orders-table", [
    { label: "Ngày", get: (d) => d.doc_date },
    ...(kind === "all" ? [{ label: "Loại", get: (d) => KIND_VI[d.kind] || d.kind }] : []),
    { label: "Mã", get: (d) => d.code },
    { label: "Khách / nguồn", get: (d) => (customerById[d.customer_id] || {}).name || d.supplier_name },
    { label: "Nơi", get: placeOf },
    { label: "Trạng thái", get: (d) => STATUS_VI[d.status] ?? d.status },
    { label: "Tổng tiền", get: (d) => d.note_total, num: true, cls: "num", html: (d) => fmtMoney(d.note_total) },
  ], items, { select: "one", open: (d) => showOrder(d.id), rowClass: (d) => (d.status !== "active" ? "closed" : "") });
  $("orders-count").textContent = `${items.length} phiếu`;
}

/* ---------------------------------------------------------------- Khách hàng */

function renderCustomers() {
  const f = $("customers-filter").value;
  const items = data.customers.filter((c) => !f || matches(f, `${c.name} ${c.contact} ${c.phone} ${c.address}`))
    .sort((a, b) => a.name.localeCompare(b.name, "vi"));
  const revenue = {};
  for (const d of data.documents) {
    if (d.kind !== "delivery" || d.status !== "active" || !d.customer_id) continue;
    for (const l of linesByDoc[d.id] || []) if (l.amount !== null && l.amount !== undefined) revenue[d.customer_id] = (revenue[d.customer_id] || 0) + l.amount;
  }
  buildTable("customers-table", [
    { label: "Khách hàng", get: (c) => c.name }, { label: "Người liên hệ", get: (c) => c.contact },
    { label: "Điện thoại", get: (c) => c.phone }, { label: "Địa chỉ", get: (c) => c.address },
    { label: "Doanh thu", get: (c) => revenue[c.id] ?? null, num: true, cls: "num", html: (c) => fmtMoney(revenue[c.id]) },
  ], items, { select: isOwner() ? "many" : null, open: (c) => showCustomer(c.id) });
}

/* ---------------------------------------------------------------- Hàng về */

function renderReceipts() {
  const items = data.documents.filter((d) => d.kind === "receipt")
    .sort((a, b) => b.doc_date.localeCompare(a.doc_date) || String(b.code).localeCompare(String(a.code), "vi", { numeric: true }));
  buildTable("receipts-table", [
    { label: "Ngày về", get: (d) => d.doc_date },
    { label: "Mã", get: (d) => d.code },
    { label: "Nguồn hàng", get: (d) => (d.receipt_source === "return" ? "Khách trả lại" : "Cửa khẩu / công ty mẹ") },
    { label: "Nhà cung cấp / khách", get: (d) => d.supplier_name || (customerById[d.customer_id] || {}).name || "" },
    { label: "Nhập vào", get: (d) => PLACE[d.location_id] || "" },
    { label: "Số mặt hàng", get: (d) => (linesByDoc[d.id] || []).length, num: true, cls: "num" },
    { label: "Tổng số lượng", get: (d) => (linesByDoc[d.id] || []).reduce((a, l) => a + l.qty, 0), num: true, cls: "num",
      html: (d) => fmtQty((linesByDoc[d.id] || []).reduce((a, l) => a + l.qty, 0)) },
    { label: "Trạng thái", get: (d) => STATUS_VI[d.status] ?? d.status },
    { label: "Ghi chú", get: (d) => d.note },
  ], items, { select: "one", open: (d) => showOrder(d.id), rowClass: (d) => (d.status !== "active" ? "closed" : ""),
              empty: "Chưa có lần hàng về nào." });
}

/* ---------------------------------------------------------------- Cài đặt */

function renderCatalog() {
  const f = $("catalog-filter").value;
  const items = data.products.filter((p) => !f || matches(f, `${p.code} ${p.name_vi} ${p.name_zh} ${p.spec} ${p.variant} ${p.category}`))
    .sort((a, b) => a.code.localeCompare(b.code, "vi", { numeric: true }));
  buildTable("catalog-table", [
    { label: "Mã", get: (p) => p.code }, { label: "Mặt hàng", get: (p) => p.name_vi }, { label: "Tên Trung", get: (p) => p.name_zh },
    { label: "Quy cách", get: (p) => p.spec }, { label: "Loại / màu", get: (p) => p.variant }, { label: "Đơn vị", get: (p) => p.unit },
    { label: "Nhóm hàng", get: (p) => p.category }, { label: "Đang dùng", get: (p) => (p.active ? "✔" : "") },
  ], items, { select: "one", open: (p) => (isOwner() ? productForm(p) : showProduct(p.id)), rowClass: (p) => (p.active ? "" : "closed") });
}

function renderSettingsInfo() {
  const what = { desktop: "Chủ (làm được mọi việc như trên app)", editor: "Nhân viên (gửi yêu cầu, chủ duyệt trên app)",
                 viewer: "Chỉ xem" }[userRole] || "Chưa được cấp quyền";
  $("settings-info").innerHTML = `<dt>Tài khoản</dt><dd>${esc(userName)}</dd><dt>Quyền</dt><dd>${esc(what)}</dd>` +
    `<dt>Báo động khi tồn dưới</dt><dd>${lowDefault ? esc(fmtQty(lowDefault)) : "đang tắt"} (đổi trong app: Cài đặt → Danh mục mặt hàng)</dd>` +
    `<dt>Dữ liệu</dt><dd>${esc($("freshness").textContent)}</dd>`;
}

/* ---------------------------------------------------------------- wiring */

for (const btn of document.querySelectorAll(".nav")) btn.addEventListener("click", () => showPage(btn.dataset.page));
for (const btn of document.querySelectorAll("[data-sub]")) btn.addEventListener("click", () => showPage(btn.dataset.sub));
for (const btn of document.querySelectorAll("[data-back]")) btn.addEventListener("click", () => showPage(btn.dataset.back));
for (const btn of document.querySelectorAll(".stab")) {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".stab").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".spane").forEach((p) => p.classList.toggle("hidden", p.id !== `stab-${btn.dataset.stab}`));
  });
}
$("stock-filter").addEventListener("input", renderStock);
$("stock-low").addEventListener("change", renderStock);
$("search-input").addEventListener("input", renderSearch);
$("orders-kind").addEventListener("change", renderOrders);
$("orders-filter").addEventListener("input", renderOrders);
$("orders-closed").addEventListener("change", renderOrders);
$("customers-filter").addEventListener("input", renderCustomers);
$("catalog-filter").addEventListener("input", renderCatalog);
$("login-btn").addEventListener("click", signIn);
$("password").addEventListener("keydown", (e) => e.key === "Enter" && signIn());
$("reload").addEventListener("click", loadAll);
$("logout").addEventListener("click", async () => { await sb.auth.signOut(); location.reload(); });

$("remember").checked = remembering();
try { $("user").value = store("localStorage").getItem(USER_KEY) || ""; } catch (e) { /* nothing saved */ }

if (!window.__DIBEKHO_TEST__) {
  sb.auth.getSession().then(({ data: { session } }) => {
    (session ? showApp() : Promise.resolve()).finally(() => {
      if (!session) $("login").classList.remove("hidden");
    });
  });
}
