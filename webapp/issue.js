/* DiBeKho web: the Phiếu xuất kho window (customer's request 14/11/2026), like the app's (ui/issue_form.py): the
   customer, then per product how many come from Kho tổng and how many from Văn phòng; the price is suggested from the
   latest order and stays editable. The web writes nothing: the window makes the Excel file (xlsx.js) and the browser
   downloads it. The stock is taken when the file goes into the app's notes folder and the app reads it, like a
   delivery note; the same file read twice is never counted twice. A product may stand on several lines (another
   quantity, another price). While the ₫ / ¥ switch shows yuan the note is a yuan note (user, 21/11/2026; before, the
   yuan typed became dong): prices typed in yuan, the file and the cloud keep them in yuan (currency CNY, cloud 022)
   with the window's rate only to show '≈ … ₫'. A note being corrected keeps its own currency.
   A name typed that is not in the list is a new product (★, customer's request 15/11/2026): its packing and unit are
   typed on the row; the owner's note makes it on the cloud with the note (019) and its stock goes below zero until
   the goods come in; a staff file carries the name only and the app asks for it in Cần xử lý → Tạo mới.
   A draft order (customer's request 21/11/2026, «Lưu nháp»): the same file with NHÁP in the title, downloaded, nothing
   recorded; «Xuất từ phiếu nháp…» reads such a file back (from the app or the web) and the window saves it as a real
   note. */

"use strict";

/** The price of this product on the customer's latest priced order, else on anyone's, in `currency` (core/issues.last_price;
    the app breaks a tie of dates by its row number, the web by the time the order came in). A price of a note in the
    other currency is turned at `rate` (dong for one yuan), else the note's own rate; null when it cannot be. */
function lastPrice(customerName, productId, currency = "VND", rate = null) {
  if (!productId) return null;
  const name = String(customerName || "").replace(/\s+/g, " ").trim();
  let best = null, bestAny = null;
  const later = (a, b) => !b || a.d.doc_date > b.d.doc_date ||
    (a.d.doc_date === b.d.doc_date && (String(a.d.created_at) > String(b.d.created_at) ||
      (String(a.d.created_at) === String(b.d.created_at) && a.l.line_no < b.l.line_no)));
  for (const d of data.documents) {
    if (d.kind !== "delivery" || d.status !== "active") continue;
    for (const l of linesByDoc[d.id] || []) {
      if (l.product_id !== productId || l.unit_price === null || l.unit_price === undefined) continue;
      const hit = { d, l };
      if (later(hit, bestAny)) bestAny = hit;
      if (name && (customerById[d.customer_id] || {}).name === name && later(hit, best)) best = hit;
    }
  }
  const hit = best || bestAny;
  if (!hit) return null;
  const own = hit.d.currency === "CNY" ? "CNY" : "VND", price = hit.l.unit_price;
  if (own === currency) return price;
  const r = rate || hit.d.fx_rate;
  if (!r) return null;
  return currency === "CNY" ? Math.round(price / r * 100) / 100 : Math.round(price * r);
}

/** The company lines the app read above the title of the shop's delivery notes (meta note_letterhead, synced). */
function letterhead() {
  try {
    const lines = JSON.parse(data.meta.note_letterhead || "[]");
    return Array.isArray(lines) ? lines.filter((x) => typeof x === "string").slice(0, 3) : [];
  } catch (e) {
    return [];
  }
}

/** The places a Phiếu xuất kho takes from, in the order of the window: Kho tổng, Văn phòng Hà Nội, Văn phòng Bắc Ninh. */
const ISSUE_PLACES = [1, 2, 3];

function issueRowHtml() {
  return `<tr class="ix-row"><td><input class="ix-product" list="products-dl" placeholder="${esc(tr("issue.pick_ph"))}">` +
    `<div class="ix-newtag hint hidden">${esc(tr("issue.new_tag"))}</div>` +
    `<input class="ix-new-vi hidden" placeholder="${esc(tr("issue.vi_name_ph"))}"></td>` +
    `<td><span class="ix-spec"></span><input class="ix-new-spec hidden" placeholder="${esc(tr("col.spec"))}"></td>` +
    `<td><span class="ix-unit"></span><input class="ix-new-unit hidden" placeholder="${esc(tr("col.unit"))}"></td>` +
    `<td class="num ix-have" data-place="1"></td><td class="yellow"><input class="qty ix-qty" data-place="1" inputmode="decimal"></td>` +
    `<td class="num ix-have" data-place="2"></td><td class="yellow"><input class="qty ix-qty" data-place="2" inputmode="decimal"></td>` +
    `<td class="num ix-have" data-place="3"></td><td class="yellow"><input class="qty ix-qty" data-place="3" inputmode="decimal"></td>` +
    `<td><input class="qty ix-price" inputmode="decimal"></td><td class="num ix-amount"></td>` +
    `<td><input class="ix-note"></td><td><button class="flat ix-remove" title="${esc(tr("issue.remove"))}">✕</button></td></tr>`;
}

/** An order made by the app or the web (A160, W160): the owner may correct it (customer's request 19/11/2026; cloud 021). */
const isIssueCode = (code) => /^\s*[AaWw]\d+\s*$/.test(String(code || ""));
const canEditIssue = (d) => isOwner() && d.kind === "delivery" && d.status === "active" && isIssueCode(d.code);

/** The lines of a recorded note as the window shows them, like the app's issues.load: where each line was taken from
    comes from the stock movements (a line taken from several places has no place of its own). */
function issueLinesOf(d) {
  const pool = {};
  for (const m of data.movements) if (m.document_id === d.id) pool[`${m.product_id}|${m.location_id}`] = (pool[`${m.product_id}|${m.location_id}`] || 0) - m.qty;
  const lines = (linesByDoc[d.id] || []).filter((l) => l.product_id).slice().sort((a, b) => a.line_no - b.line_no);
  for (const l of lines) if (l.location_id) pool[`${l.product_id}|${l.location_id}`] = (pool[`${l.product_id}|${l.location_id}`] || 0) - l.qty;
  return lines.map((l) => {
    const take = { 1: 0, 2: 0, 3: 0 };
    if (l.location_id) take[l.location_id] = l.qty;
    else {
      let left = l.qty;
      for (const place of ISSUE_PLACES) {
        const part = Math.min(left, Math.max(pool[`${l.product_id}|${place}`] || 0, 0));
        take[place] = part; pool[`${l.product_id}|${place}`] = (pool[`${l.product_id}|${place}`] || 0) - part; left -= part;
      }
      if (left > 0) take[d.location_id || 1] += left;
    }
    return { product_id: l.product_id, main: take[1], office: take[2], bn: take[3], price: l.unit_price, note: l.note || "" };
  });
}

let issueEdit = null;  // {doc, lines} while the window corrects a recorded note, else null
/** The goods the note being corrected holds are free again for its new version. */
const issueGiven = (productId, place) => (issueEdit ? issueEdit.lines.reduce(
  (a, l) => a + (l.product_id === productId ? ({ 1: l.main, 2: l.office, 3: l.bn }[place] || 0) : 0), 0) : 0);
const issueHave = (productId, place) => (stockOf(productId)[place] || 0) + issueGiven(productId, place);

let issueCny = false;  // the open window makes a yuan note
let issueRate = null;  // dong for one yuan: only to show '≈ … ₫' and to turn a last price of the other currency

/** The row's price as typed and saved (dong, or yuan on a yuan note): null (empty), NaN (not a number). */
function issuePrice(input) {
  return parseQty(input.value);
}

/** An amount of the open note: dong, or yuan on a yuan note. */
function issueMoney(amount) {
  return issueCny ? fmtCny(amount) : fmtVnd(amount);
}

let issueDraft = null;  // the draft read back (DBK_XLSX.readDraft) the window was opened from, else null

function openIssueForm(editDoc = null, draft = null) {
  issueEdit = editDoc ? { doc: editDoc, lines: issueLinesOf(editDoc) } : null;
  issueDraft = editDoc ? null : draft;
  issueCny = issueEdit ? isCny(editDoc) : issueDraft ? issueDraft.currency === "CNY" : moneyInCny();
  issueRate = (issueEdit && isCny(editDoc) && editDoc.fx_rate) || rateNow() || null;
  const heads = [tr("col.product"), tr("col.spec"), tr("col.unit"),
                 ...ISSUE_PLACES.flatMap((n) => [tr("issue.have", { place: tr(`place.${n}`) }), tr("issue.take", { place: tr(`place.${n}`) })]),
                 tr(issueCny ? "issue.price_cny" : "issue.price"),
                 tr(issueCny ? "issue.amount_cny" : "issue.amount"), tr("col.note"), ""];
  const title = issueEdit ? tr("issue.edit_title", { code: editDoc.code })
    : issueDraft ? tr("issue.draft_title", { code: issueDraft.code }) : tr("issue.title");
  const hint = issueEdit ? tr("issue.edit_hint", { code: editDoc.code })
    : issueDraft ? tr("issue.draft_hint", { code: issueDraft.code }) : tr("issue.hint");
  const draftButtons = issueEdit ? [] : [{ label: tr("issue.from_draft"), run: pickDraft }, { label: tr("issue.save_draft"), run: saveDraft }];
  const body = openDialog(title,
    `<p class="hint">${esc(hint)}${issueCny ? " " + esc(tr("issue.cny_hint", { rate: issueRate ? Math.round(issueRate).toLocaleString("vi-VN") : "—" })) : ""}</p>
     <div class="form2">
       <label>${esc(tr("issue.date"))}</label><input id="ix-date" type="date" value="${esc(todayLocal())}">
       <label>${esc(tr("col.customer"))}</label><div class="row"><span class="suggest grow"><input id="ix-customer" autocomplete="off" placeholder="${esc(tr("issue.customer_ph"))}"><div id="ix-customer-sg" class="suggest-list" hidden></div></span><button id="ix-new-customer" class="flat" title="${esc(tr("issue.new_customer_tip"))}">${esc(tr("issue.new_customer"))}</button></div>
       <label>${esc(tr("col.phone"))}</label><input id="ix-phone" autocomplete="off">
       <label>${esc(tr("col.contact"))}</label><input id="ix-contact" autocomplete="off">
       <label>${esc(tr("col.address"))}</label><input id="ix-address" autocomplete="off">
       <label>${esc(tr("col.tax_code"))}</label><input id="ix-tax" autocomplete="off">
       <label>${esc(tr("col.email"))}</label><input id="ix-email" type="email" autocomplete="off">
     </div>
     <div class="scroll tall"><table class="edit"><thead><tr>${heads.map((h, i) =>
       `<th class="${i === 4 || i === 6 ? "yellow" : i === 3 || i === 5 || i === 8 ? "num" : ""}">${esc(h)}</th>`).join("")}</tr></thead>
       <tbody id="ix-lines">${issueRowHtml()}${issueRowHtml()}${issueRowHtml()}</tbody></table></div>
     <div class="row"><button id="ix-add" class="flat">${esc(tr("issue.add_row"))}</button><span class="spacer"></span>
       <span id="ix-total" class="hint"></span></div>`,
    [...draftButtons, { label: tr(issueEdit ? "issue.save_edit" : "issue.save"), primary: true, run: saveIssue }], null,
    { dirty: () => [...$("ix-lines").querySelectorAll(".ix-product, .ix-qty")].some((i) => i.value.trim()) || !!$("ix-customer").value.trim(),
      question: tr("issue.discard") });

  const rowProduct = (tr_) => productFromLabel(tr_.querySelector(".ix-product").value);
  const rowIsNew = (tr_) => !rowProduct(tr_) && !!tr_.querySelector(".ix-product").value.trim();
  const fillPrice = (tr_) => {
    const price = tr_.querySelector(".ix-price");
    if (price.dataset.typed || price.dataset.keep) return;  // the user's own price, or the one on the note being corrected, is kept
    const p = rowProduct(tr_);
    const v = p ? lastPrice($("ix-customer").value, p.id, issueCny ? "CNY" : "VND", issueRate) : null;
    price.value = v === null ? "" : fmtQty(v);
  };
  const refresh = () => {
    let total = 0, priced = false;
    const taken = {};  // the rows of one product take from its stock together
    for (const tr_ of $("ix-lines").querySelectorAll("tr")) {
      const p = rowProduct(tr_);
      for (const place of ISSUE_PLACES) {
        const asked = parseQty(tr_.querySelector(`.ix-qty[data-place="${place}"]`).value);
        if (p && asked > 0) taken[`${p.id}|${place}`] = (taken[`${p.id}|${place}`] || 0) + asked;
      }
    }
    for (const tr_ of $("ix-lines").querySelectorAll("tr")) {
      const p = rowProduct(tr_), isNew = rowIsNew(tr_);
      tr_.querySelector(".ix-spec").textContent = p ? [p.spec, p.variant].filter(Boolean).join(" · ") : "";
      tr_.querySelector(".ix-unit").textContent = p ? p.unit || "" : "";
      for (const sel of [".ix-newtag", ".ix-new-spec", ".ix-new-unit"]) tr_.querySelector(sel).classList.toggle("hidden", !isNew);
      tr_.querySelector(".ix-new-vi").classList.toggle("hidden", !(isNew && LANG === "zh"));
      let qty = 0;
      for (const place of ISSUE_PLACES) {
        const have = tr_.querySelector(`.ix-have[data-place="${place}"]`);
        const box = tr_.querySelector(`.ix-qty[data-place="${place}"]`);
        const asked = parseQty(box.value);
        have.textContent = p ? fmtQty(issueHave(p.id, place)) : isNew ? "0" : "";
        const over = (isNew && asked > 0) || (p && asked > 0 && taken[`${p.id}|${place}`] > issueHave(p.id, place));
        have.classList.toggle("over", !!over);
        box.closest("td").classList.toggle("bad", Number.isNaN(asked));
        if (asked > 0) qty += asked;
      }
      const price = issuePrice(tr_.querySelector(".ix-price"));
      const amount = (p || isNew) && qty > 0 && price !== null && !Number.isNaN(price) ? Math.round(qty * price * 100) / 100 : null;
      tr_.querySelector(".ix-amount").textContent = amount === null ? "" : issueMoney(amount);
      if (amount !== null) { total += amount; priced = true; }
    }
    $("ix-total").textContent = priced ? tr("issue.total", { money: issueMoney(total) }) : "";
  };

  /* The customers that fit what is being typed (user's request 24/11/2026). A <datalist> cannot do this: the
     browser filters the options by the letters typed as they stand, so "khach" would hide "Khách Mẫu". The rule
     is the app's (core/issues.suggest_customers): words in any order, no accents needed, the phone counts. */
  const customerLabel = (c) => [c.name, c.phone].filter(Boolean).join(" · ");
  const hideSuggestions = () => { $("ix-customer-sg").hidden = true; };
  const showSuggestions = (typed) => {
    const box = $("ix-customer-sg");
    const hits = data.customers.filter((c) => matches(typed, customerLabel(c))).slice(0, 20);
    if (!typed.trim() || !hits.length) return hideSuggestions();
    box.innerHTML = hits.map((c) => `<div data-name="${esc(c.name)}">${esc(customerLabel(c))}</div>`).join("");
    box.hidden = false;
  };
  body.addEventListener("mousedown", (e) => {  // mousedown: before the box loses focus
    const hit = e.target.closest("#ix-customer-sg div");
    if (!hit) return;
    e.preventDefault();
    const c = data.customers.find((x) => x.name === hit.dataset.name);
    hideSuggestions();
    if (!c) return;
    for (const [id, v] of [["ix-customer", c.name], ["ix-phone", c.phone], ["ix-contact", c.contact],
                           ["ix-address", c.address], ["ix-tax", c.tax_code], ["ix-email", c.email]]) $(id).value = v || "";
    for (const row of $("ix-lines").querySelectorAll("tr")) fillPrice(row);
    refresh();
  });
  body.addEventListener("focusout", (e) => { if (e.target.id === "ix-customer") setTimeout(hideSuggestions, 150); });
  body.addEventListener("keydown", (e) => { if (e.key === "Escape" && e.target.id === "ix-customer") hideSuggestions(); });
  body.addEventListener("input", (e) => {
    const tr_ = e.target.closest("tr.ix-row");
    if (e.target.id === "ix-customer") {
      showSuggestions(e.target.value);
      const c = data.customers.find((x) => x.name === e.target.value.replace(/\s+/g, " ").trim());
      if (c) for (const [id, v] of [["ix-phone", c.phone], ["ix-contact", c.contact], ["ix-address", c.address], ["ix-tax", c.tax_code], ["ix-email", c.email]]) if (!$(id).value.trim()) $(id).value = v || "";
      for (const row of $("ix-lines").querySelectorAll("tr")) fillPrice(row);
    }
    if (tr_ && e.target.classList.contains("ix-price")) e.target.dataset.typed = e.target.value.trim() ? "1" : "";
    if (tr_ && e.target.classList.contains("ix-product")) {
      delete tr_.querySelector(".ix-price").dataset.keep;  // another product: its own price is suggested
      fillPrice(tr_);
      const rows = $("ix-lines").querySelectorAll("tr");
      if ((rowProduct(tr_) || rowIsNew(tr_)) && tr_ === rows[rows.length - 1]) $("ix-lines").insertAdjacentHTML("beforeend", issueRowHtml());
    }
    refresh();
  });
  body.addEventListener("click", (e) => {
    if (e.target.id === "ix-new-customer") {
      // a customer not in the list yet (customer's request 18/11/2026): empty boxes for every detail, saved with the note
      for (const id of ["ix-customer", "ix-phone", "ix-contact", "ix-address", "ix-tax", "ix-email"]) $(id).value = "";
      $("ix-customer").placeholder = tr("issue.new_customer_ph");
      $("ix-customer").focus();
      for (const row of $("ix-lines").querySelectorAll("tr")) fillPrice(row);
      refresh();
      return;
    }
    if (!e.target.classList.contains("ix-remove")) return;
    const rows = $("ix-lines").querySelectorAll("tr");
    if (rows.length > 1) e.target.closest("tr").remove();
    else for (const i of e.target.closest("tr").querySelectorAll("input")) { i.value = ""; delete i.dataset.typed; }
    refresh();
  });
  body.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.tagName === "INPUT") e.preventDefault(); });  // Enter never saves
  $("ix-add").addEventListener("click", () => { $("ix-lines").insertAdjacentHTML("beforeend", issueRowHtml()); });
  if (issueEdit) {  // the note's own date, customer and lines, prices as recorded
    const c = customerById[editDoc.customer_id] || {};
    $("ix-date").value = editDoc.doc_date;
    for (const [id, v] of [["ix-customer", c.name], ["ix-phone", c.phone], ["ix-contact", c.contact], ["ix-address", c.address], ["ix-tax", c.tax_code], ["ix-email", c.email]]) $(id).value = v || "";
    $("ix-lines").innerHTML = "";
    for (const l of issueEdit.lines) {
      $("ix-lines").insertAdjacentHTML("beforeend", issueRowHtml());
      const row = $("ix-lines").lastElementChild, p = productById[l.product_id];
      row.querySelector(".ix-product").value = p ? productLabel(p) : "";
      row.querySelector(".ix-qty[data-place='1']").value = l.main ? fmtQty(l.main) : "";
      row.querySelector(".ix-qty[data-place='2']").value = l.office ? fmtQty(l.office) : "";
      row.querySelector(".ix-qty[data-place='3']").value = l.bn ? fmtQty(l.bn) : "";
      const price = row.querySelector(".ix-price");
      if (l.price !== null && l.price !== undefined) {
        price.value = fmtQty(l.price);
        price.dataset.keep = "1";
      }
      row.querySelector(".ix-note").value = l.note;
    }
    $("ix-lines").insertAdjacentHTML("beforeend", issueRowHtml());
    refresh();
  }
  if (issueDraft) {  // the draft's date, customer and lines: a product by its code, else a ★ new product
    $("ix-date").value = issueDraft.doc_date || todayLocal();
    for (const [id, v] of [["ix-customer", issueDraft.customer], ["ix-phone", issueDraft.phone], ["ix-contact", issueDraft.contact],
                           ["ix-address", issueDraft.address], ["ix-tax", issueDraft.tax_code], ["ix-email", issueDraft.email]]) $(id).value = v || "";
    $("ix-lines").innerHTML = "";
    for (const l of issueDraft.lines) {
      $("ix-lines").insertAdjacentHTML("beforeend", issueRowHtml());
      const row = $("ix-lines").lastElementChild;
      const p = l.code ? data.products.find((x) => x.code === l.code) : null;
      if (p) row.querySelector(".ix-product").value = productLabel(p);
      else {
        row.querySelector(".ix-product").value = LANG === "zh" ? (l.name_zh || l.name_vi) : l.name_vi;
        row.querySelector(".ix-new-vi").value = l.name_vi;
        row.querySelector(".ix-new-spec").value = l.spec;
      }
      row.querySelector(".ix-qty[data-place='1']").value = l.qty_main ? fmtQty(l.qty_main) : "";
      row.querySelector(".ix-qty[data-place='2']").value = l.qty_office ? fmtQty(l.qty_office) : "";
      row.querySelector(".ix-qty[data-place='3']").value = l.qty_bn ? fmtQty(l.qty_bn) : "";
      const price = row.querySelector(".ix-price");
      if (l.unit_price !== null && l.unit_price !== undefined) {
        price.value = fmtQty(l.unit_price);
        price.dataset.keep = "1";
      }
      row.querySelector(".ix-note").value = l.note;
    }
    $("ix-lines").insertAdjacentHTML("beforeend", issueRowHtml());
    refresh();
  }
}

/** Lưu nháp: the note's file with NHÁP in the title, downloaded; nothing is recorded (no stock, no revenue). */
async function saveDraft() {
  const f = readIssueForm();
  const rows = DBK_XLSX.noteRows(productById, f.lines);
  const now = new Date(), two = (n) => String(n).padStart(2, "0");
  // WN…: never one of the app's draft numbers (N1, N2…), which it counts in its own folder
  const code = issueDraft ? issueDraft.code : `WN${String(now.getFullYear()).slice(2)}${two(now.getMonth() + 1)}${two(now.getDate())}${two(now.getHours())}${two(now.getMinutes())}`;
  const head = { code, doc_date: f.date, customer: f.customer, phone: f.phone, contact: f.contact, address: f.address,
                 tax_code: f.tax_code, email: f.email, letterhead: letterhead(), currency: issueCny ? "CNY" : "VND", draft: true };
  const name = `PhieuXuat_NHAP_${code}.xlsx`;
  saveFile(name, DBK_XLSX.issueNote(fflate, head, rows), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
  alert(tr("issue.draft_saved", { name }));
  return true;
}

/** Xuất từ phiếu nháp…: pick a draft file (made by the app or the web); it opens in the window. */
async function pickDraft() {
  const file = await new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".xlsx";
    input.addEventListener("change", () => resolve(input.files[0] || null));
    input.addEventListener("cancel", () => resolve(null));
    input.click();
  });
  if (!file) return false;
  let draft;
  try {
    draft = DBK_XLSX.readDraft(fflate, new Uint8Array(await file.arrayBuffer()));
  } catch (e) {
    fail(tr("issue.draft_bad"));
  }
  const typed = [...$("ix-lines").querySelectorAll(".ix-product, .ix-qty")].some((i) => i.value.trim());
  if (typed && !confirm(tr("issue.draft_replace"))) return false;
  openIssueForm(null, draft);
  return false;  // the window stays open, now on the draft
}

/** The window's content checked like core/issues.problems; throws the first problem. */
function readIssueForm() {
  const customer = $("ix-customer").value.replace(/\s+/g, " ").trim();
  if (!customer) fail(tr("issue.need_customer"));
  const date = $("ix-date").value;
  if (!date) fail(tr("issue.need_date"));
  const lines = [];
  for (const tr_ of $("ix-lines").querySelectorAll("tr")) {
    const label = tr_.querySelector(".ix-product").value.trim();
    const [main, office, bn] = ISSUE_PLACES.map((n) => parseQty(tr_.querySelector(`.ix-qty[data-place='${n}']`).value));
    const price = issuePrice(tr_.querySelector(".ix-price"));
    if (!label && main === null && office === null && bn === null) continue;
    if (!label) fail(tr("issue.unknown_product", { text: "?" }));
    const p = productFromLabel(label);
    const clean = (s) => String(s || "").replace(/\s+/g, " ").trim();
    // on the Chinese page the typed name is the Chinese one, and the Vietnamese name must be typed too (user,
    // 15/11/2026: every product keeps a Vietnamese name, as in the app and on the cloud)
    const zh = LANG === "zh";
    const fresh = p ? null : { name_vi: zh ? clean(tr_.querySelector(".ix-new-vi").value) : clean(label),
                               name_zh: zh ? clean(label) : "", spec: clean(tr_.querySelector(".ix-new-spec").value),
                               unit: clean(tr_.querySelector(".ix-new-unit").value) };
    const name = p ? productName(p) : "★ " + clean(label);
    if (fresh && !fresh.name_vi && ((main || 0) + (office || 0) + (bn || 0) > 0)) {
      tr_.querySelector(".ix-new-vi").focus();
      fail(tr("issue.need_vi_name", { product: clean(label) }));
    }
    if ([main, office, bn, price].some((v) => Number.isNaN(v))) fail(tr("issue.not_number", { product: name }));
    if ([main, office, bn, price].some((v) => v !== null && v < 0)) fail(tr("issue.negative", { product: name }));
    if (!((main || 0) + (office || 0) + (bn || 0) > 0)) continue;
    lines.push({ product: p, product_id: p ? p.id : null, new: fresh, label: name, row: tr_, qty_main: main || 0,
                 qty_office: office || 0, qty_bn: bn || 0, unit_price: price, note: tr_.querySelector(".ix-note").value });
  }
  if (!lines.length) fail(tr("issue.need_lines"));
  return { date, customer, phone: $("ix-phone").value.replace(/\s+/g, " ").trim(),
           contact: $("ix-contact").value.replace(/\s+/g, " ").trim(), address: $("ix-address").value.replace(/\s+/g, " ").trim(),
           tax_code: $("ix-tax").value.replace(/\s+/g, " ").trim(), email: $("ix-email").value.replace(/\s+/g, " ").trim(), lines };
}

async function saveIssue() {
  const f = readIssueForm();
  // a new product that is in the catalog already: use that one (the app's issues.same_as_existing)
  for (const ln of f.lines) {
    if (!ln.new) continue;
    const key = (x) => unaccent(x).replace(/\s/g, "");
    const same = activeProducts().find((p) => (key(p.name_vi) === key(ln.new.name_vi) ||
        (ln.new.name_zh && key(p.name_zh) === key(ln.new.name_zh))) &&
      (!ln.new.spec || key(p.spec) === key(ln.new.spec)));
    if (same && confirm(tr("issue.looks_existing", { name: ln.label.replace(/^★ /, ""), product: productName(same), code: same.code }))) {
      Object.assign(ln, { product: same, product_id: same.id, new: null, label: productName(same) });
      ln.row.querySelector(".ix-product").value = productLabel(same);
    }
  }
  const short = [], asked = new Map();  // the lines of one product count together
  for (const ln of f.lines) {
    if (!ln.product) continue;  // a new product has nothing yet: it goes below zero, the user was told
    for (const [place, qty] of [[1, ln.qty_main], [2, ln.qty_office], [3, ln.qty_bn]]) {
      if (!(qty > 0)) continue;
      const key = `${ln.product.id}|${place}`;
      asked.set(key, { product: ln.product, place, qty: ((asked.get(key) || {}).qty || 0) + qty });
    }
  }
  for (const a of asked.values()) {
    const have = issueHave(a.product.id, a.place);
    if (a.qty > have) short.push(tr("issue.short_line", { product: productName(a.product), place: tr(`place.${a.place}`), qty: fmtQty(a.qty), have: fmtQty(have) }));
  }
  if (short.length && !confirm(`${tr("issue.short_ask")}\n\n${short.join("\n")}`)) return false;
  if (f.date > todayLocal() && !confirm(tr("issue.future_ask"))) return false;
  let rows = DBK_XLSX.noteRows(productById, f.lines);
  const total = rows.reduce((a, r) => a + (r.amount || 0), 0);
  // before saving the user sees what is written: dong, or the yuan of the note and about how many dong
  const both = (a) => (issueCny && issueRate ? `${issueMoney(a)} ≈ ${fmtVnd(Math.round(a * issueRate))} ₫` : issueMoney(a));
  const money = { currency: issueCny ? "CNY" : "VND", fx_rate: issueCny ? issueRate : null };
  if (issueCny && isOwner()) {
    // a yuan note needs cloud step 022: the older web_issue would record the yuan as dong, without a word
    const { data: version, error: vErr } = await sb.rpc("web_api_version");
    if (vErr || !(Number(version) >= 22)) fail(tr("issue.cny_sql"));
  }
  if (isOwner() && f.lines.some((ln) => ln.qty_bn > 0)) {
    // Văn phòng Bắc Ninh needs cloud step 023: the older web_issue would drop those goods without a word
    const { data: version, error: vErr } = await sb.rpc("web_api_version");
    if (vErr || !(Number(version) >= 23)) fail(tr("issue.bn_sql"));
  }
  const summary = rows.map((r, i) => `• ${r.code ? r.code + " " : ""}${f.lines[i].label}: ${fmtQty(r.qty)} ${r.unit} · ` +
    r.places.map(([place, qty]) => `${tr(`place.${place}`)} ${fmtQty(qty)}`).join(" + ") +
    (r.amount !== null ? ` · ${both(r.amount)}` : "")).join("\n");
  const fresh = f.lines.some((ln) => ln.new) ? `\n\n${tr(isOwner() ? "issue.confirm_new" : "issue.confirm_new_staff")}` : "";
  if (!confirm(`${issueEdit ? tr("issue.confirm_edit", { code: issueEdit.doc.code, customer: f.customer }) : tr("issue.confirm", { customer: f.customer })}\n\n${summary}\n\n${tr("issue.total", { money: both(total) })}${fresh}`)) return false;
  let code;
  if (issueEdit) {
    // a note corrected (cloud 021): the old one is deleted and this one recorded with the same code, in one go
    const lines = f.lines.map((ln) => ({ product_id: ln.product_id, new: ln.new || undefined, qty_main: ln.qty_main,
                                         qty_office: ln.qty_office, qty_bn: ln.qty_bn, unit_price: ln.unit_price, note: ln.note }));
    const { data: made, error } = await sb.rpc("web_issue_edit", { p: { replaces: issueEdit.doc.id, doc_date: f.date,
      customer: f.customer, phone: f.phone, contact: f.contact, address: f.address, tax_code: f.tax_code, email: f.email, lines,
      ...money } });
    if (error) fail(error.message || String(error));
    code = made.code;
    if (f.lines.some((ln) => ln.new)) {
      await loadAll();
      const ids = made.product_ids || [];
      const known = f.lines.map((ln, i) => (ids[i] && productById[ids[i]] ? { ...ln, product_id: ids[i], new: null } : ln));
      rows = DBK_XLSX.noteRows(productById, known);
    }
  } else if (isOwner()) {
    // the owner's note is recorded on the cloud at once and takes the stock (user, 14/11/2026: the web is the
    // reference data); the server hands out the code (W + next order number) under the write lock, and makes the
    // new products (019)
    const lines = f.lines.map((ln) => ({ product_id: ln.product_id, new: ln.new || undefined, qty_main: ln.qty_main,
                                         qty_office: ln.qty_office, qty_bn: ln.qty_bn, unit_price: ln.unit_price, note: ln.note }));
    // a yuan note goes through web_issue_money (022), which also keeps its currency
    const args = { p: { doc_date: f.date, customer: f.customer, phone: f.phone, contact: f.contact, address: f.address,
                        tax_code: f.tax_code, email: f.email, lines, ...money } };
    const { data: made, error } = await (issueCny ? sb.rpc("web_issue_money", args) : sb.rpc("web_issue", args));
    if (error) fail(error.message || String(error));
    code = made.code;
    if (f.lines.some((ln) => ln.new)) {
      // the file carries the codes of the products just made: the app then reads every row by its code
      await loadAll();
      const ids = made.product_ids || [];
      const known = f.lines.map((ln, i) => (ids[i] && productById[ids[i]] ? { ...ln, product_id: ids[i], new: null } : ln));
      rows = DBK_XLSX.noteRows(productById, known);
    }
  } else {
    code = DBK_XLSX.nextCode(data.documents.filter((d) => d.kind === "delivery").map((d) => d.code));
  }
  const head = { code, doc_date: f.date, customer: f.customer, phone: f.phone, contact: f.contact, address: f.address,
                 tax_code: f.tax_code, email: f.email, letterhead: letterhead(), currency: money.currency };
  const bytes = DBK_XLSX.issueNote(fflate, head, rows);
  const name = `PhieuXuat_${code}.xlsx`;
  saveFile(name, bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
  if (isOwner()) {
    alert(tr(issueEdit ? "issue.done_edit" : "issue.done_owner", { code, name }));
    await loadAll();
  } else {
    alert(tr("issue.done", { name }));
  }
  return true;
}

$("issue-new").addEventListener("click", () => { if (canMakeIssue()) openIssueForm(); });
