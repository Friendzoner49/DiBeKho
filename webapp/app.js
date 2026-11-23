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
  // the app's rule (core/text.matches_words): every word typed must be in the text, in any order, accents,
  // spaces and punctuation ignored -- so "fs101" finds "FS-101" and "0900000001" finds "0900 000 001"
  const bare = (s) => unaccent(s).replace(/[^\p{L}\p{N}]+/gu, "");
  return unaccent(needle).split(/\s+/).filter(Boolean).every((w) => bare(hay).includes(bare(w)));
}

function fmtQty(n) {
  if (n === null || n === undefined || n === "") return "";
  return Number.isInteger(n) ? String(n) : String(Math.round(n * 1000) / 1000).replace(".", ",");
}

/* Money: the data is in VND; the ₫ / ¥ switch (fx.js) decides what the screen shows. Files always keep VND. */
const FX = { currency: "vnd", rate: null };  // rate {vnd_per_cny, updated, fetched}
const moneyInCny = () => FX.currency === "cny" && !!FX.rate;
const numLocale = () => (LANG === "zh" ? "zh-CN" : "vi-VN");

/** An amount in dong, as in the files and the Phiếu xuất kho window. */
function fmtVnd(n) {
  return n === null || n === undefined ? "" : Number(n).toLocaleString("vi-VN");
}

/** An amount as the screen shows it: dong, or ¥ with up to 2 decimals at today's rate. */
function fmtMoney(n) {
  if (n === null || n === undefined) return "";
  if (!moneyInCny()) return fmtVnd(n);
  return "¥" + (Number(n) / FX.rate.vnd_per_cny).toLocaleString(numLocale(), { maximumFractionDigits: 2 });
}

/* A note priced in yuan (documents.currency = "CNY", user 15/11/2026): its amounts show as printed, in yuan, and are
   never added to the dong. While the switch is on dong, "about ... dong" follows in brackets at the rate kept with the
   note (today's when it has none); on yuan everything is yuan already. The same rules as core/fx.py. */
const isCny = (d) => !!d && d.currency === "CNY";
const fmtCny = (n) => "¥" + Number(n).toLocaleString(numLocale(), { maximumFractionDigits: 2 });
const rateNow = () => (FX.rate ? FX.rate.vnd_per_cny : 0);

/** An amount of ONE note, in the note's own currency. */
function fmtNative(n, d, approx = true) {
  if (n === null || n === undefined || !isCny(d)) return fmtMoney(n);
  const rate = d.fx_rate || rateNow();
  return fmtCny(n) + (approx && rate && !moneyInCny() ? ` (≈ ${fmtVnd(Math.round(n * rate))} ₫)` : "");
}

/** A sum over notes of both currencies: "120.000.000 ₫ + ¥4.800 (≈ 137.280.000 ₫)". */
function fmtBoth(vnd, cny, approx, brackets = true) {
  if (!cny) return fmtMoney(vnd);
  if (moneyInCny()) return fmtCny((vnd || 0) / FX.rate.vnd_per_cny + cny);
  const about = approx || cny * rateNow();
  const tail = brackets && about ? ` (≈ ${fmtVnd(Math.round((vnd || 0) + about))} ₫)` : "";
  return (vnd ? `${fmtVnd(vnd)} ₫ + ${fmtCny(cny)}` : fmtCny(cny)) + tail;
}

/** One number for such a sum, in dong (to sort by, and for the Tổng quan charts). */
const moneyValue = (vnd, cny, approx) => (vnd === null || vnd === undefined) && !cny ? null : (vnd || 0) + (approx || (cny || 0) * rateNow());

/** Adds a line amount of document d to {vnd, cny, approx}. */
function addMoney(acc, d, amount) {
  if (isCny(d)) { acc.cny = (acc.cny || 0) + amount; acc.approx = (acc.approx || 0) + amount * (d.fx_rate || 0); }
  else acc.vnd = (acc.vnd || 0) + amount;
  return acc;
}
const noMoney = () => ({ vnd: null, cny: null, approx: null });

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

/** The picker's line (Phiếu xuất kho): the name in the page's language first, the other name last. */
function productLabel(p) {
  return [p.code, pn(p), p.spec, p.variant, pnOther(p)].filter(Boolean).join(" · ");
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
  showPage(isOwner() ? "dashboard" : "stock");  // the manager opens on the overview (customer, 14/11/2026), phone too (15/11)
  await loadAll();
}

/* Phones only look at the stock table (user's decision 12/11/2026): no menu, no windows, nothing to edit. Decided once
   when the page opens: a touch screen (no mouse) whose short side is small. A phone turned sideways is still a phone;
   a computer with a small screen or a narrow window is not; a tablet or a computer gets the whole page.
   The owner's phone (role desktop, customer's request 15/11/2026, evon wireframe B) also has Tổng quan, Đơn hàng,
   Khách hàng and Thống kê: one header (☰ on Tổng quan opens the menu, ‹ on the others goes back to it). A test may
   force the phone layout with ?phone=1 (a desktop browser has a mouse). */
const PHONE = new URLSearchParams(location.search).get("phone") === "1" ||
  (window.matchMedia("(pointer: coarse)").matches && Math.min(window.screen.width, window.screen.height) <= 760);
if (PHONE) document.body.classList.add("phone");
const ownerPhone = () => PHONE && isOwner();
const PHONE_PAGES = ["dashboard", "stock", "orders", "customers", "stats"];

function setRole(role, name, accountAdmin = false) {
  userRole = role || "";
  userName = name || "";
  document.body.classList.remove("role-desktop", "role-editor", "role-viewer");
  document.body.classList.toggle("account-admin", role === "desktop" && !!accountAdmin);
  document.body.classList.toggle("maker", canMakeIssue());
  if (userRole) document.body.classList.add(`role-${userRole}`);
  document.body.classList.toggle("owner-phone", ownerPhone());
  $("who").textContent = `${userName} (${tr(`role.short_${userRole || "none"}`)})`;
  $("ph-who").textContent = $("who").textContent;
}

function phoneMenu(open) {
  $("ph-drawer").classList.toggle("hidden", !open);
  if (open) $("ph-drawer").querySelector(`[data-ph="${page}"]`)?.focus();
}
$("ph-menu").addEventListener("click", () => phoneMenu(true));
$("ph-scrim").addEventListener("click", () => phoneMenu(false));
$("ph-back").addEventListener("click", () => showPage("dashboard"));
$("ph-reload").addEventListener("click", loadAll);
$("ph-drawer").addEventListener("click", (e) => {
  const b = e.target.closest("[data-ph]");
  if (b) { phoneMenu(false); showPage(b.dataset.ph); }
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("ph-drawer").classList.contains("hidden")) phoneMenu(false); });

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
  if (ownerPhone() && name !== "detail" && !PHONE_PAGES.includes(name)) name = "dashboard";
  if (ownerPhone()) {
    $("ph-title").textContent = name === "detail" ? "" : tr(`nav.${name}`);
    $("ph-menu").hidden = name !== "dashboard";
    $("ph-back").hidden = name === "dashboard";
    for (const b of document.querySelectorAll("[data-ph]")) b.classList.toggle("active", b.dataset.ph === name);
  }
  if (name !== "detail") backTo = name;
  page = name;
  document.body.dataset.page = name;
  document.querySelectorAll(".page").forEach((p) => p.classList.toggle("hidden", p.id !== `page-${name}`));
  const top = ["orders", "customers", "stats"].includes(name) ? "search" : name === "detail" ? null : name;
  if (top) document.querySelectorAll(".nav").forEach((b) => b.classList.toggle("active", b.dataset.page === top));
  window.scrollTo(0, 0);
}

/* Going to the next or previous page (user, 15/11/2026): a swipe left / right on a touch screen, PgDn / PgUp on a
   computer, in the order of the menu (the owner's phone: its menu; a staff phone has the stock only). Never while a
   window or the phone menu is open, while typing, or when the swipe scrolls a wide table sideways. */
function pageOrder() {
  if (PHONE) return ownerPhone() ? PHONE_PAGES : [];
  return [...document.querySelectorAll(".nav")].filter((b) => b.offsetParent !== null).map((b) => b.dataset.page);
}

function stepPage(step) {
  const order = pageOrder();
  const at = page === "detail" ? backTo : ["orders", "customers", "stats"].includes(page) && !order.includes(page) ? "search" : page;
  const next = order[order.indexOf(at) + step];
  if (order.includes(at) && next) showPage(next);
}

const pageMovesBlocked = () => $("app").classList.contains("hidden") || dlg.open || !$("ph-drawer").classList.contains("hidden");
const typingIn = (el) => !!el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName));
/** A box where PgUp / PgDn does something of its own: a list, a text area, a number or a date. A one-line text box
    (the filter) does nothing with them, and a box no longer on screen (the password box after signing in with Enter
    keeps the focus, found on a real computer) does not count. */
const keysOwnedBy = (el) => !!el && el.getClientRects().length > 0 && (el.isContentEditable ||
  ["TEXTAREA", "SELECT"].includes(el.tagName) || (el.tagName === "INPUT" && ["number", "date", "range"].includes(el.type)));

document.addEventListener("keydown", (e) => {
  if (!["PageDown", "PageUp"].includes(e.key) || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
  if (pageMovesBlocked() || keysOwnedBy(document.activeElement)) return;
  e.preventDefault();
  stepPage(e.key === "PageDown" ? 1 : -1);
});

/** The boxes around the touch that scroll sideways (a wide table), with where each one stands. A swipe that scrolled
    one of them was for the table; a swipe that moved none (the table is at its edge, or there is none) turns the page.
    Found on a real iPad: the stock table is wider than the screen, and refusing every swipe that started on it left
    the swipe doing nothing on most pages. */
function sidewaysScrollers(el) {
  const found = [];
  for (; el && el !== document.body; el = el.parentElement) {
    const x = getComputedStyle(el).overflowX;
    if ((x === "auto" || x === "scroll") && el.scrollWidth > el.clientWidth + 1) found.push([el, el.scrollLeft]);
  }
  return found;
}

let swipe = null;
document.addEventListener("touchstart", (e) => {
  const t = e.touches[0];
  swipe = e.touches.length === 1 && !pageMovesBlocked() && !typingIn(e.target)
    ? { x: t.clientX, y: t.clientY, at: Date.now(), scrollers: sidewaysScrollers(e.target), pageX: window.scrollX } : null;
}, { passive: true });
document.addEventListener("touchend", (e) => {
  if (!swipe) return;
  const t = e.changedTouches[0], dx = t.clientX - swipe.x, dy = t.clientY - swipe.y, quick = Date.now() - swipe.at < 800;
  const scrolled = swipe.scrollers.some(([el, left]) => Math.abs(el.scrollLeft - left) > 2) || Math.abs(window.scrollX - swipe.pageX) > 2;
  swipe = null;
  if (scrolled) return;
  if (quick && Math.abs(dx) > 70 && Math.abs(dx) > 2 * Math.abs(dy)) stepPage(dx < 0 ? 1 : -1);
}, { passive: true });
document.addEventListener("touchcancel", () => { swipe = null; }, { passive: true });

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
  const customers = data.customers.filter((c) => matches(f, `${c.name} ${c.contact} ${c.phone} ${c.address} ${c.tax_code || ""} ${c.email || ""}`));
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
  const cur = kind === "delivery" ? $("orders-currency").value : "";  // orders in dong / in yuan (user, 15/11/2026)
  $("orders-currency").closest("label").hidden = kind !== "delivery";
  const items = data.documents.filter((d) => (kind === "all" || d.kind === kind) && (withClosed || d.status === "active") &&
      (!cur || isCny(d) === (cur === "CNY")) &&
      (!f || matches(f, `${d.code} ${(customerById[d.customer_id] || {}).name || ""} ${d.supplier_name} ${d.note}`)))
    .sort((a, b) => b.doc_date.localeCompare(a.doc_date) || String(b.code).localeCompare(String(a.code), "vi", { numeric: true }));
  if (ownerPhone()) {
    renderOrdersPhone(items);
    $("orders-count").textContent = tr("orders.count", { n: items.length });
    return;
  }
  buildTable("orders-table", [
    { label: tr("col.date"), get: (d) => d.doc_date },
    ...(kind === "all" ? [{ label: tr("col.kind"), get: (d) => kindName(d.kind) }] : []),
    { label: tr("col.code"), get: (d) => d.code },
    { label: tr("col.who"), get: (d) => (customerById[d.customer_id] || {}).name || d.supplier_name },
    { label: tr("col.place"), get: placeOf },
    { label: tr("col.status"), get: (d) => statusName(d.status) },
    // a note priced in dong and one priced in yuan in two columns (user, 15/11/2026: one column read as one sum)
    { label: tr("col.total_vnd"), get: (d) => (isCny(d) ? null : d.note_total), num: true, cls: "num",
      html: (d) => (isCny(d) ? "" : esc(fmtNative(d.note_total, d))) },
    { label: tr("col.total_cny"), get: (d) => (isCny(d) ? d.note_total : null), num: true, cls: "num",
      html: (d) => (isCny(d) ? esc(fmtNative(d.note_total, d)) : "") },
  ], items, { select: "one", open: (d) => showOrder(d.id), rowClass: (d) => (d.status !== "active" ? "closed" : "") });
  $("orders-count").textContent = tr("orders.count", { n: items.length });
}

/** The owner's phone (evon wireframe B): one white block of rows per day, newest first; who on top, code and place
    under it, the amount on the right (a yuan note in yuan, about how many dong under it). */
const PHONE_ROWS = 150;
function renderOrdersPhone(items) {
  const today = todayLocal(), yesterday = isoDay(new Date(Date.now() - 864e5));
  const dayName = (d) => (d === today ? tr("phone.today") : d === yesterday ? tr("phone.yesterday") : fmtDay(d));
  const groups = [];
  for (const d of items.slice(0, PHONE_ROWS)) {
    if (!groups.length || groups[groups.length - 1].day !== d.doc_date) groups.push({ day: d.doc_date, docs: [] });
    groups[groups.length - 1].docs.push(d);
  }
  const row = (d) => {
    const who = (customerById[d.customer_id] || {}).name || d.supplier_name || "—";
    const sub = [d.kind === "delivery" ? "" : kindName(d.kind), d.code, placeOf(d),
                 tr("phone.lines_n", { n: (linesByDoc[d.id] || []).length })].filter(Boolean).map(esc).join(" · ");
    const priced = d.note_total !== null && d.note_total !== undefined;
    const money = !priced ? "" : isCny(d)
      ? `${esc(fmtCny(d.note_total))}${moneyInCny() || !(d.fx_rate || rateNow()) ? "" : `<small>≈ ${esc(shortNumber(d.note_total * (d.fx_rate || rateNow())))} ₫</small>`}`
      : esc(fmtMoney(d.note_total) + (moneyInCny() ? "" : " ₫"));
    return `<li class="click${d.status !== "active" ? " closed" : ""}" data-open="${esc(d.id)}"><div class="line-main"><span class="line-name">${esc(who)}</span>` +
      `<span class="line-sub">${sub}${d.status !== "active" ? ` · <span class="tag-off">${esc(statusName(d.status))}</span>` : ""}</span></div>` +
      `<b class="line-fig">${money}</b></li>`;
  };
  $("orders-table").innerHTML = items.length
    ? groups.map((g) => `<p class="day-head">${esc(dayName(g.day))}</p><section class="panel"><ul class="lines">${g.docs.map(row).join("")}</ul></section>`).join("") +
      (items.length > PHONE_ROWS ? `<p class="hint">${esc(tr("phone.more", { shown: PHONE_ROWS, n: items.length }))}</p>` : "")
    : `<p class="hint dash-empty">${esc(tr("dash.none_orders"))}</p>`;
}
$("orders-table").addEventListener("click", (e) => {
  const li = ownerPhone() && e.target.closest("li[data-open]");
  if (li) showOrder(li.dataset.open);
});
$("customers-table").addEventListener("click", (e) => {
  const li = ownerPhone() && e.target.closest("li[data-open]");
  if (li) showCustomer(li.dataset.open);
});

/* ---------------------------------------------------------------- Khách hàng */

function renderCustomers() {
  const f = $("customers-filter").value;
  const items = data.customers.filter((c) => !f || matches(f, `${c.name} ${c.contact} ${c.phone} ${c.address} ${c.tax_code || ""} ${c.email || ""}`))
    .sort((a, b) => a.name.localeCompare(b.name, "vi"));
  const revenue = {};
  for (const d of data.documents) {
    if ((d.kind !== "delivery" && !isReturn(d)) || d.status !== "active" || !d.customer_id) continue;
    const sign = isReturn(d) ? -1 : 1;  // goods the customer sent back come off the revenue
    for (const l of linesByDoc[d.id] || []) if (l.amount !== null && l.amount !== undefined) revenue[d.customer_id] = addMoney(revenue[d.customer_id] || noMoney(), d, sign * l.amount);
  }
  const rev = (c) => revenue[c.id] || noMoney();
  if (ownerPhone()) {
    // the owner's phone: who bought the most first, the name in full, the revenue on the right
    const value = (c) => moneyValue(rev(c).vnd, rev(c).cny, rev(c).approx) || 0;
    const orders = {};
    for (const d of data.documents) if (d.kind === "delivery" && d.status === "active" && d.customer_id) orders[d.customer_id] = (orders[d.customer_id] || 0) + 1;
    const sorted = items.slice().sort((a, b) => value(b) - value(a) || a.name.localeCompare(b.name, "vi"));
    $("customers-table").innerHTML = sorted.length ? `<section class="panel"><ul class="lines">` + sorted.map((c) =>
      `<li class="click" data-open="${esc(c.id)}"><div class="line-main"><span class="line-name">${esc(c.name)}</span>` +
      `<span class="line-sub">${esc([tr("phone.orders_n", { n: orders[c.id] || 0 }), c.phone].filter(Boolean).join(" · "))}</span></div>` +
      `<b class="line-fig">${esc(value(c) ? shortMoney(value(c)) : "—")}</b></li>`).join("") + `</ul></section>`
      : `<p class="hint dash-empty">${esc(tr("dash.none_customers"))}</p>`;
    return;
  }
  buildTable("customers-table", [
    { label: tr("col.customer"), get: (c) => c.name }, { label: tr("col.contact"), get: (c) => c.contact },
    { label: tr("col.phone"), get: (c) => c.phone }, { label: tr("col.address"), get: (c) => c.address },
    { label: tr("col.tax_code"), get: (c) => c.tax_code || "" }, { label: tr("col.email"), get: (c) => c.email || "" },
    { label: tr("col.revenue"), get: (c) => moneyValue(rev(c).vnd, rev(c).cny, rev(c).approx), num: true, cls: "num",
      html: (c) => esc(fmtBoth(rev(c).vnd, rev(c).cny, rev(c).approx)) },
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

/* ---------------------------------------------------------------- Tra cứu → Danh mục mặt hàng, Cài đặt */

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
    const scope = btn.closest(".page");  // Tra cứu and Cài đặt each have their own tabs
    scope.querySelectorAll(".stab").forEach((b) => b.classList.toggle("active", b === btn));
    scope.querySelectorAll(".spane").forEach((p) => p.classList.toggle("hidden", p.id !== `stab-${btn.dataset.stab}`));
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
$("orders-currency").addEventListener("change", renderOrders);
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
