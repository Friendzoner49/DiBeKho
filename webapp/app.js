/* DiBeKho web: the shop's shared data (the cloud's real tables, docs/cloud/06-cloud-la-goc.md), laid out like the
   desktop app so the same people find the same buttons in the same places (user's request 12/11/2026).
   Plain JS on purpose: no build step, easy to edit. Reads with supabase-js.

   The web only looks (customer's request 14/11/2026): nothing here writes the shop's data. What it can do besides
   looking: make a Phiếu xuất kho Excel file (issue.js; the app takes the stock when the file is dropped in its notes
   folder), convert yuan and dong (fx.js), download a data package (package.js), and for the maychinh login manage
   accounts and the interface size (accounts.js). Every text comes from i18n.js (Tiếng Việt / 中文). */

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
const KIND_ORDER = ["delivery", "receipt", "stock_count", "transfer", "trial"];
const kindName = (k) => tr(`kind.${k}`);
const statusName = (s) => (s === "active" ? "" : tr(`status.${s}`));
const placeName = (id) => (id === 1 || id === 2 ? tr(`place.${id}`) : "");

const $ = (id) => document.getElementById(id);
const data = { products: [], customers: [], suppliers: [], documents: [], lines: [], movements: [], meta: {} };
let productById = {}, customerById = {}, supplierById = {}, docById = {}, linesByDoc = {}, stockByProduct = {};
let userRole = "", userName = "", currentUserId = "";
let lowDefault = 30;  // the app's alarm level (meta low_stock_default; 0 = off)
const ACCOUNT_ADMIN = "maychinh@dibekho.local";  // the one login that manages accounts (the server checks it too)
const isReturn = (d) => d.kind === "receipt" && d.receipt_source === "return";  // goods a customer sent back
const isOwner = () => userRole === "desktop";
/* Who may make a Phiếu xuất kho file: the main machine's role and staff; "chỉ xem" only looks. The file changes
   nothing by itself: the app takes the stock when it reads it. */
const canMakeIssue = () => userRole === "desktop" || userRole === "editor";

/* ---------------------------------------------------------------- helpers */

function unaccent(s) {
  // marks off, then the letter d with a stroke (U+0111) as a plain d; written by its code: no Vietnamese in scripts
  return (s || "").toLowerCase().normalize("NFD").replace(/\p{M}/gu, "").replaceAll(String.fromCharCode(0x111), "d");
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

/** A typed number: '1,5' and '1.5' both mean one and a half, full-width digits too (like the app). "" -> null. */
function parseQty(text) {
  const s = String(text ?? "").normalize("NFKC").trim().replace(",", ".");
  if (!s) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : NaN;
}

/** The product's name in the page's language: 中文 shows the Chinese name when the product has one. */
const pn = (p) => (LANG === "zh" ? (p.name_zh || p.name_vi) : p.name_vi) || "";
/** The other name, shown in the column next to it (Tên Trung on the Vietnamese page, 越南语名称 on the Chinese one). */
const pnOther = (p) => (LANG === "zh" ? (p.name_zh ? p.name_vi : "") : p.name_zh) || "";

function productName(p) {
  return [pn(p), p.spec, p.variant].filter(Boolean).join(" · ");
}

function productLabel(p) {
  return [p.code, p.name_vi, p.spec, p.variant, p.name_zh].filter(Boolean).join(" · ");
}

const stockOf = (id) => stockByProduct[id] || { total: 0, 1: 0, 2: 0 };
const activeProducts = () => data.products.filter((p) => p.active)
  .sort((a, b) => (a.category || "").localeCompare(b.category || "", "vi") || a.name_vi.localeCompare(b.name_vi, "vi") ||
                  (a.spec || "").localeCompare(b.spec || "", "vi"));

/* Sortable table, like the app's: click a header to sort; click a row to select it (select: "one"),
   double-click to open it. cols = [{label, get, num?, cls?, html?}]. */
const tableState = { "stock-table": { i: 0, dir: 1, sel: new Set() } };  // Tồn kho opens sorted by code (SP001…)

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
      return String(va ?? "").localeCompare(String(vb ?? ""), "vi", { numeric: true }) * st.dir;
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
        if (opts.open && st.sel.has(k)) { opts.open(item); return; }
        st.sel.clear(); st.sel.add(k);
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

/* ---------------------------------------------------------------- language */

function fillLanguageChoices() {
  for (const id of ["lang-login", "lang-app", "lang-settings"]) {
    const sel = $(id);
    sel.innerHTML = LANGS.map((l) => `<option value="${l}">${esc(LANG_NAMES[l])}</option>`).join("");
    sel.value = LANG;
    sel.addEventListener("change", () => setLang(sel.value));
  }
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
      ? tr("login.wrong") : tr("login.failed", { reason: error.message });
    return;
  }
  showApp();
}

async function showApp() {
  $("login").classList.add("hidden");
  $("app").classList.remove("hidden");
  // filter by our own id: the owner's account may read every profile row
  const { data: { user } } = await sb.auth.getUser();
  currentUserId = user.id;
  const { data: prof } = await sb.from("profiles").select("role,display_name").eq("user_id", user.id).maybeSingle();
  setRole(prof ? prof.role : "", (prof && prof.display_name) || (user.email || "").split("@")[0],
          (user.email || "").toLowerCase() === ACCOUNT_ADMIN);
  loadSharedScale();
  showPage(isOwner() && !PHONE ? "dashboard" : "stock");  // the manager opens on the overview (customer, 14/11/2026)
  await loadAll();
}

/* Phones only look at the stock table (user's decision 12/11/2026): no menu, no windows, nothing to edit. Decided once
   when the page opens: a touch screen (no mouse) whose short side is small. A phone turned sideways is still a phone;
   a computer with a small screen or a narrow window is not; a tablet or a computer gets the whole page. */
const PHONE = window.matchMedia("(pointer: coarse)").matches && Math.min(window.screen.width, window.screen.height) <= 760;
if (PHONE) document.body.classList.add("phone");

function setRole(role, name, accountAdmin = false) {
  userRole = role || "";
  userName = name || "";
  document.body.classList.remove("role-desktop", "role-editor", "role-viewer");
  document.body.classList.toggle("account-admin", role === "desktop" && !!accountAdmin);
  document.body.classList.toggle("maker", canMakeIssue());
  if (userRole) document.body.classList.add(`role-${userRole}`);
  $("who").textContent = `${userName} (${tr(`role.short_${userRole || "none"}`)})`;
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
    $("load-error").textContent = tr("load.failed", { reason: e.message || e });
    return;
  }
  renderAll();
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
  $("freshness").textContent = newest ? tr("top.freshness", { when: fmtTime(newest) }) : "";
  // suggestion lists of the Phiếu xuất kho window
  $("products-dl").innerHTML = activeProducts().map((p) => `<option value="${esc(productLabel(p))}">`).join("");
  $("customers-dl").innerHTML = data.customers.slice().sort((a, b) => a.name.localeCompare(b.name, "vi"))
    .map((c) => `<option value="${esc(c.name)}">`).join("");
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
  if (name === "dashboard" && !isOwner()) name = "stock";  // only the main machine's role has the overview
  if (name !== "detail") backTo = name;
  page = name;
  document.querySelectorAll(".page").forEach((p) => p.classList.toggle("hidden", p.id !== `page-${name}`));
  const top = ["orders", "customers", "stats"].includes(name) ? "search" : name === "detail" ? null : name;
  if (top) document.querySelectorAll(".nav").forEach((b) => b.classList.toggle("active", b.dataset.page === top));
  window.scrollTo(0, 0);
}

/* Each part draws on its own: one that fails (odd data) says so at the top instead of leaving every page after it blank
   (user, 13/11/2026: Thống kê stayed empty). */
function renderAll() {
  const failed = [];
  const parts = [renderDashboard, renderStock, renderPendingUnplaced, renderSearch, renderOrders, renderCustomers,
                 renderReceipts, renderCount, renderCatalog, renderSettingsInfo,
                 function renderStatsPage() { if (!$("page-stats").dataset.ready) { initStats(); $("page-stats").dataset.ready = "1"; } else { syncStatsControls(); renderStats(); } }];
  for (const part of parts) {
    try { part(); } catch (e) { console.error(e); failed.push(`${part.name}: ${e.message || e}`); }
  }
  if (failed.length) $("load-error").textContent = tr("load.part_failed", { parts: failed.join(" · ") });
}

/* ---------------------------------------------------------------- Tồn kho */

const isLow = (p) => lowDefault && stockOf(p.id).total < lowDefault;

function renderStock() {
  const f = $("stock-filter").value, onlyLow = $("stock-low").checked;
  const all = activeProducts();
  const items = all.filter((p) => (!onlyLow || isLow(p)) &&
    (!f || matches(f, `${p.code} ${p.name_vi} ${p.name_zh} ${p.spec} ${p.variant} ${p.category} ${p.stock_note}`)));
  if (PHONE) {
    // a phone: one card per product, nothing to scroll sideways; long names wrap in full (variants differ at the end)
    $("stock-table").innerHTML = '<div class="pcards">' + items.map((p) => {
      const s = stockOf(p.id), cls = s.total < 0 ? " neg" : isLow(p) ? " low" : "";
      const sub = [p.code, p.spec, p.variant].filter(Boolean).map(esc).join(" · ");
      return `<div class="pcard${cls}"><div class="pc-main"><div class="pc-name">${esc(pn(p))}</div>` +
        `<div class="pc-sub">${sub}</div><div class="pc-sub">${esc(tr("place.1"))} ${fmtQty(s[1])} · ${esc(tr("place.2"))} ${fmtQty(s[2])}</div></div>` +
        `<div class="pc-total"><span>${fmtQty(s.total)}</span><small>${esc(p.unit || "")}</small></div></div>`;
    }).join("") + "</div>";
  } else buildTable("stock-table", [
    { label: tr("col.code"), get: (p) => p.code },
    { label: tr("col.product"), get: pn, cls: "wrap" },
    { label: tr("col.other_name"), get: pnOther, cls: "wrap" },
    { label: tr("col.spec"), get: (p) => p.spec },
    { label: tr("col.variant"), get: (p) => p.variant },
    { label: tr("col.category"), get: (p) => p.category },
    { label: tr("col.unit"), get: (p) => p.unit },
    { label: tr("col.stock"), get: (p) => stockOf(p.id).total, num: true, cls: "num strong", html: (p) => fmtQty(stockOf(p.id).total) },
    { label: tr("col.stock_note"), get: (p) => p.stock_note },
    { label: tr("place.1"), get: (p) => stockOf(p.id)[1], num: true, cls: "num", html: (p) => fmtQty(stockOf(p.id)[1]) },
    { label: tr("place.2"), get: (p) => stockOf(p.id)[2], num: true, cls: "num", html: (p) => fmtQty(stockOf(p.id)[2]) },
    { label: tr("col.last_out"), get: (p) => stockOf(p.id).lastOut || "" },
  ], items, {
    rowClass: (p) => (stockOf(p.id).total < 0 ? "neg" : isLow(p) ? "low" : ""),
    select: "one", open: (p) => showProduct(p.id),
  });
  const low = all.filter(isLow).length, negative = all.filter((p) => stockOf(p.id).total < 0).length;
  $("stock-banner").classList.toggle("hidden", !low);
  $("stock-banner").textContent = tr("stock.banner", { n: low, level: fmtQty(lowDefault) }) +
    (PHONE ? "" : " " + tr("stock.banner_tick"));
  $("stock-summary").textContent = tr("stock.summary", { n: all.length, low, negative });
}

/* ---------------------------------------------------------------- Cần xử lý */

const unplacedOrders = () => data.documents.filter((d) => d.kind === "delivery" && d.status === "active" && d.location_set === false);

function renderPendingUnplaced() {
  const items = unplacedOrders().sort((a, b) => a.doc_date.localeCompare(b.doc_date));
  buildTable("pending-unplaced", [
    { label: tr("col.date"), get: (d) => d.doc_date },
    { label: tr("col.order_code"), get: (d) => d.code },
    { label: tr("col.customer"), get: (d) => (customerById[d.customer_id] || {}).name || "" },
    { label: tr("col.product"), get: (d) => (linesByDoc[d.id] || []).map((l) => `${(productById[l.product_id] || {}).code || "?"}×${fmtQty(l.qty)}`).join(", ") },
  ], items, { open: (d) => showOrder(d.id), empty: tr("pending.none") });
  const n = items.length;
  $("nav-pending").textContent = n ? `${tr("nav.pending")}  (${n})` : tr("nav.pending");
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
  out.innerHTML = `<h2>${esc(tr("search.found_products", { n: products.length }))}</h2><div id="sr-products"></div>` +
    `<h2>${esc(tr("search.found_customers", { n: customers.length }))}</h2><div id="sr-customers"></div>` +
    `<h2>${esc(tr("search.found_docs", { n: docs.length }))}</h2><div id="sr-docs"></div>`;
  buildTable("sr-products", [
    { label: tr("col.code"), get: (p) => p.code }, { label: tr("col.product"), get: productName }, { label: tr("col.other_name"), get: pnOther },
    { label: tr("col.stock"), get: (p) => stockOf(p.id).total, num: true, cls: "num strong", html: (p) => fmtQty(stockOf(p.id).total) },
  ], products, { open: (p) => showProduct(p.id) });
  buildTable("sr-customers", [
    { label: tr("col.customer"), get: (c) => c.name }, { label: tr("col.phone"), get: (c) => c.phone }, { label: tr("col.address"), get: (c) => c.address },
  ], customers, { open: (c) => showCustomer(c.id) });
  buildTable("sr-docs", [
    { label: tr("col.date"), get: (d) => d.doc_date }, { label: tr("col.kind"), get: (d) => kindName(d.kind) }, { label: tr("col.code"), get: (d) => d.code },
    { label: tr("col.who"), get: (d) => (customerById[d.customer_id] || {}).name || d.supplier_name },
    { label: tr("col.status"), get: (d) => statusName(d.status) },
  ], docs, { open: (d) => showOrder(d.id), rowClass: (d) => (d.status !== "active" ? "closed" : "") });
}

/* ---------------------------------------------------------------- Đơn hàng */

function renderOrders() {
  const kindSel = $("orders-kind");
  if (!kindSel.options.length) {
    kindSel.innerHTML = `<option value="all">${esc(tr("orders.all"))}</option>` +
      KIND_ORDER.map((k) => `<option value="${k}">${esc(kindName(k))}</option>`).join("");
    kindSel.value = "delivery";
  }
  const kind = kindSel.value, f = $("orders-filter").value, withClosed = $("orders-closed").checked;
  const items = data.documents.filter((d) => (kind === "all" || d.kind === kind) && (withClosed || d.status === "active") &&
      (!f || matches(f, `${d.code} ${(customerById[d.customer_id] || {}).name || ""} ${d.supplier_name} ${d.note}`)))
    .sort((a, b) => b.doc_date.localeCompare(a.doc_date) || String(b.code).localeCompare(String(a.code), "vi", { numeric: true }));
  buildTable("orders-table", [
    { label: tr("col.date"), get: (d) => d.doc_date },
    ...(kind === "all" ? [{ label: tr("col.kind"), get: (d) => kindName(d.kind) }] : []),
    { label: tr("col.code"), get: (d) => d.code },
    { label: tr("col.who"), get: (d) => (customerById[d.customer_id] || {}).name || d.supplier_name },
    { label: tr("col.place"), get: placeOf },
    { label: tr("col.status"), get: (d) => statusName(d.status) },
    { label: tr("col.note_total"), get: (d) => d.note_total, num: true, cls: "num", html: (d) => fmtMoney(d.note_total) },
  ], items, { select: "one", open: (d) => showOrder(d.id), rowClass: (d) => (d.status !== "active" ? "closed" : "") });
  $("orders-count").textContent = tr("orders.count", { n: items.length });
}

/* ---------------------------------------------------------------- Khách hàng */

function renderCustomers() {
  const f = $("customers-filter").value;
  const items = data.customers.filter((c) => !f || matches(f, `${c.name} ${c.contact} ${c.phone} ${c.address}`))
    .sort((a, b) => a.name.localeCompare(b.name, "vi"));
  const revenue = {};
  for (const d of data.documents) {
    if ((d.kind !== "delivery" && !isReturn(d)) || d.status !== "active" || !d.customer_id) continue;
    const sign = isReturn(d) ? -1 : 1;  // goods the customer sent back come off the revenue
    for (const l of linesByDoc[d.id] || []) if (l.amount !== null && l.amount !== undefined) revenue[d.customer_id] = (revenue[d.customer_id] || 0) + sign * l.amount;
  }
  buildTable("customers-table", [
    { label: tr("col.customer"), get: (c) => c.name }, { label: tr("col.contact"), get: (c) => c.contact },
    { label: tr("col.phone"), get: (c) => c.phone }, { label: tr("col.address"), get: (c) => c.address },
    { label: tr("col.revenue"), get: (c) => revenue[c.id] ?? null, num: true, cls: "num", html: (c) => fmtMoney(revenue[c.id]) },
  ], items, { open: (c) => showCustomer(c.id) });
}

/* ---------------------------------------------------------------- Hàng về */

function receiptSource(d) {
  return tr({ return: "source.return", other: "source.other" }[d.receipt_source] || "source.supplier");
}

function renderReceipts() {
  // only active receipts are listed, like the app: replaced (edited) and cancelled ones are left out (user, 13/11/2026)
  const items = data.documents.filter((d) => d.kind === "receipt" && d.status === "active")
    .sort((a, b) => b.doc_date.localeCompare(a.doc_date) || String(b.code).localeCompare(String(a.code), "vi", { numeric: true }));
  buildTable("receipts-table", [
    { label: tr("col.receipt_date"), get: (d) => d.doc_date },
    { label: tr("col.code"), get: (d) => d.code },
    { label: tr("col.source"), get: receiptSource },
    { label: tr("col.supplier_or_customer"), get: (d) => d.supplier_name || (customerById[d.customer_id] || {}).name || "" },
    { label: tr("col.into"), get: (d) => placeName(d.location_id) },
    { label: tr("col.items"), get: (d) => (linesByDoc[d.id] || []).length, num: true, cls: "num" },
    { label: tr("col.total_qty"), get: (d) => (linesByDoc[d.id] || []).reduce((a, l) => a + l.qty, 0), num: true, cls: "num",
      html: (d) => fmtQty((linesByDoc[d.id] || []).reduce((a, l) => a + l.qty, 0)) },
    { label: tr("col.note"), get: (d) => d.note },
  ], items, { select: "one", open: (d) => showOrder(d.id), empty: tr("receipts.none") });
}

/* ---------------------------------------------------------------- Kiểm kê (look only: counting is done in the app) */

function renderCount() {
  buildTable("count-table", [
    { label: tr("col.code"), get: (p) => p.code }, { label: tr("col.product"), get: pn }, { label: tr("col.other_name"), get: pnOther },
    { label: tr("col.spec"), get: (p) => p.spec }, { label: tr("col.variant"), get: (p) => p.variant }, { label: tr("col.unit"), get: (p) => p.unit },
    { label: tr("count.app_main"), get: (p) => stockOf(p.id)[1], num: true, cls: "num", html: (p) => fmtQty(stockOf(p.id)[1]) },
    { label: tr("count.app_office"), get: (p) => stockOf(p.id)[2], num: true, cls: "num", html: (p) => fmtQty(stockOf(p.id)[2]) },
    { label: tr("count.app_total"), get: (p) => stockOf(p.id).total, num: true, cls: "num strong", html: (p) => fmtQty(stockOf(p.id).total) },
    { label: tr("col.stock_note"), get: (p) => p.stock_note },
  ], activeProducts(), { select: "one", open: (p) => showProduct(p.id) });
}

/* ---------------------------------------------------------------- Cài đặt */

function renderCatalog() {
  const f = $("catalog-filter").value;
  const items = data.products.filter((p) => !f || matches(f, `${p.code} ${p.name_vi} ${p.name_zh} ${p.spec} ${p.variant} ${p.category}`))
    .sort((a, b) => a.code.localeCompare(b.code, "vi", { numeric: true }));
  buildTable("catalog-table", [
    { label: tr("col.code"), get: (p) => p.code }, { label: tr("col.product"), get: pn }, { label: tr("col.other_name"), get: pnOther },
    { label: tr("col.spec"), get: (p) => p.spec }, { label: tr("col.variant"), get: (p) => p.variant }, { label: tr("col.unit"), get: (p) => p.unit },
    { label: tr("col.category"), get: (p) => p.category }, { label: tr("col.in_use"), get: (p) => (p.active ? "✔" : "") },
  ], items, { select: "one", open: (p) => showProduct(p.id), rowClass: (p) => (p.active ? "" : "closed") });
}

function renderSettingsInfo() {
  $("settings-info").innerHTML = `<dt>${esc(tr("settings.account"))}</dt><dd>${esc(userName)}</dd>` +
    `<dt>${esc(tr("settings.role"))}</dt><dd>${esc(tr(`role.long_${userRole || "none"}`))}</dd>` +
    `<dt>${esc(tr("settings.low"))}</dt><dd>${esc(lowDefault ? fmtQty(lowDefault) : tr("settings.low_off"))} ${esc(tr("settings.low_where"))}</dd>` +
    `<dt>${esc(tr("settings.data"))}</dt><dd>${esc($("freshness").textContent)}</dd>`;
}

/* ---------------------------------------------------------------- wiring */

applyStatic();
fillLanguageChoices();
if (PHONE) $("stock-filter").placeholder = tr("stock.filter_phone");
for (const btn of document.querySelectorAll(".nav")) btn.addEventListener("click", () => showPage(btn.dataset.page));
for (const btn of document.querySelectorAll("[data-sub]")) btn.addEventListener("click", () => showPage(btn.dataset.sub));
for (const btn of document.querySelectorAll("[data-back]")) btn.addEventListener("click", () => showPage(btn.dataset.back));
for (const btn of document.querySelectorAll(".stab")) {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".stab").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".spane").forEach((p) => p.classList.toggle("hidden", p.id !== `stab-${btn.dataset.stab}`));
  });
}
/* Interface size: 100% by default (older customers: nothing changes unless maychinh chooses); only maychinh gets the choice, kept in
   this browser. A phone keeps its own card layout. */
const SCALE_KEY = "dibekho_ui_scale";
function uiScale() {
  try { const v = Number(store("localStorage").getItem(SCALE_KEY)); return [100, 110, 120].includes(v) ? v : 100; } catch (e) { return 100; }
}
function applyScale() {
  const z = PHONE ? 1 : uiScale() / 100;
  document.documentElement.style.zoom = PHONE ? "" : String(z);
  document.documentElement.style.setProperty("--z", String(z));  // vh units ignore zoom: the stylesheet divides by it
}
function keepScale(v) { try { store("localStorage").setItem(SCALE_KEY, String(v)); } catch (e) { /* not kept */ } }
applyScale();
$("ui-scale").value = String(uiScale());
// the size is shared by every machine: maychinh sets it in the cloud, every browser reads it after signing in
async function loadSharedScale() {
  try {
    const { data } = await sb.from("web_settings").select("value").eq("key", "ui_scale").maybeSingle();
    const v = Number(data && data.value);
    if ([100, 110, 120].includes(v)) { keepScale(v); applyScale(); $("ui-scale").value = String(v); }
  } catch (e) { /* not set yet, or SQL 012 not run: keep the default */ }
}
$("ui-scale").addEventListener("change", async () => {
  const v = $("ui-scale").value;
  try {
    const { error } = await sb.rpc("web_setting_set", { p_key: "ui_scale", p_value: v });
    if (error) throw error;
    keepScale(v); applyScale();
  } catch (e) {
    alert(String(e && e.message || e).includes("web_setting_set") ? tr("settings.scale_sql") : tr("settings.scale_failed"));
    $("ui-scale").value = String(uiScale());
  }
});

// the name at the top right opens Cài đặt → Chung, where the Đăng xuất button is
$("who").addEventListener("click", () => {
  if (PHONE) return;  // a phone has its own Đăng xuất button
  showPage("settings");
  document.querySelector('.stab[data-stab="general"]').click();
});
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
for (const id of ["logout", "logout-phone"]) {
  $(id).addEventListener("click", async () => { await sb.auth.signOut({ scope: "local" }); location.reload(); });
}

$("remember").checked = remembering();
try { $("user").value = store("localStorage").getItem(USER_KEY) || ""; } catch (e) { /* nothing saved */ }

if (!window.__DIBEKHO_TEST__) {
  sb.auth.getSession().then(({ data: { session } }) => {
    (session ? showApp() : Promise.resolve()).finally(() => {
      if (!session) $("login").classList.remove("hidden");
    });
  });
}
