/* DiBeKho web: the Phiếu xuất kho window (customer's request 14/11/2026), like the app's (ui/issue_form.py): the
   customer, then per product how many come from Kho tổng and how many from Văn phòng; the price is suggested from the
   latest order and stays editable. The web writes nothing: the window makes the Excel file (xlsx.js) and the browser
   downloads it. The stock is taken when the file goes into the app's notes folder and the app reads it, like a
   delivery note; the same file read twice is never counted twice. A product may stand on several lines (another
   quantity, another price). While the ₫ / ¥ switch shows yuan the prices are typed in yuan at the rate the window
   opened with (user, 15/11/2026); the file keeps VND: a typed price becomes whole dong, a suggested price left
   untouched keeps its exact dong. */

"use strict";

/** The price of this product on the customer's latest priced order, else on anyone's (core/issues.last_price; the
    app breaks a tie of dates by its row number, the web by the time the order came in). */
function lastPrice(customerName, productId) {
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
  return (best || bestAny) ? (best || bestAny).l.unit_price : null;
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

function issueRowHtml() {
  return `<tr class="ix-row"><td><input class="ix-product" list="products-dl" placeholder="${esc(tr("issue.pick_ph"))}"></td>` +
    `<td class="ix-spec"></td><td class="ix-unit"></td>` +
    `<td class="num ix-have" data-place="1"></td><td class="yellow"><input class="qty ix-qty" data-place="1" inputmode="decimal"></td>` +
    `<td class="num ix-have" data-place="2"></td><td class="yellow"><input class="qty ix-qty" data-place="2" inputmode="decimal"></td>` +
    `<td><input class="qty ix-price" inputmode="decimal"></td><td class="num ix-amount"></td>` +
    `<td><input class="ix-note"></td><td><button class="flat ix-remove" title="${esc(tr("issue.remove"))}">✕</button></td></tr>`;
}

let issueRate = null;  // dong for one yuan while the open window takes its prices in yuan, else null

/** The row's price in dong, as the file carries it: null (empty), NaN (not a number). */
function issuePriceVnd(input) {
  const shown = parseQty(input.value);
  if (shown === null || Number.isNaN(shown) || !issueRate) return shown;
  if (!input.dataset.typed && input.dataset.vnd) return Number(input.dataset.vnd);
  return Math.round(shown * issueRate);
}

/** An amount as the window shows it: dong, or yuan at the window's rate. */
function issueMoney(vnd) {
  return issueRate ? "¥" + (vnd / issueRate).toLocaleString(numLocale(), { maximumFractionDigits: 2 }) : fmtVnd(vnd);
}

function openIssueForm() {
  issueRate = moneyInCny() ? FX.rate.vnd_per_cny : null;
  const heads = [tr("col.product"), tr("col.spec"), tr("col.unit"), tr("issue.have", { place: tr("place.1") }),
                 tr("issue.take", { place: tr("place.1") }), tr("issue.have", { place: tr("place.2") }),
                 tr("issue.take", { place: tr("place.2") }), tr(issueRate ? "issue.price_cny" : "issue.price"),
                 tr(issueRate ? "issue.amount_cny" : "issue.amount"), tr("col.note"), ""];
  const body = openDialog(tr("issue.title"),
    `<p class="hint">${esc(tr("issue.hint"))}${issueRate ? " " + esc(tr("issue.cny_hint", { rate: Math.round(issueRate).toLocaleString("vi-VN") })) : ""}</p>
     <div class="form2">
       <label>${esc(tr("issue.date"))}</label><input id="ix-date" type="date" value="${esc(todayLocal())}">
       <label>${esc(tr("col.customer"))}</label><input id="ix-customer" list="customers-dl" autocomplete="off" placeholder="${esc(tr("issue.customer_ph"))}">
       <label>${esc(tr("col.phone"))}</label><input id="ix-phone" autocomplete="off">
       <label>${esc(tr("col.contact"))}</label><input id="ix-contact" autocomplete="off">
       <label>${esc(tr("col.address"))}</label><input id="ix-address" autocomplete="off">
     </div>
     <div class="scroll tall"><table class="edit"><thead><tr>${heads.map((h, i) =>
       `<th class="${i === 4 || i === 6 ? "yellow" : i === 3 || i === 5 || i === 8 ? "num" : ""}">${esc(h)}</th>`).join("")}</tr></thead>
       <tbody id="ix-lines">${issueRowHtml()}${issueRowHtml()}${issueRowHtml()}</tbody></table></div>
     <div class="row"><button id="ix-add" class="flat">${esc(tr("issue.add_row"))}</button><span class="spacer"></span>
       <span id="ix-total" class="hint"></span></div>`,
    [{ label: tr("issue.save"), primary: true, run: saveIssue }], null,
    { dirty: () => [...$("ix-lines").querySelectorAll(".ix-product, .ix-qty")].some((i) => i.value.trim()) || !!$("ix-customer").value.trim(),
      question: tr("issue.discard") });

  const rowProduct = (tr_) => productFromLabel(tr_.querySelector(".ix-product").value);
  const fillPrice = (tr_) => {
    const price = tr_.querySelector(".ix-price");
    if (price.dataset.typed) return;  // the user's own price is kept
    const p = rowProduct(tr_);
    const v = p ? lastPrice($("ix-customer").value, p.id) : null;
    price.dataset.vnd = v === null ? "" : String(v);
    price.value = v === null ? "" : fmtQty(issueRate ? Math.round(v / issueRate * 100) / 100 : v);
  };
  const refresh = () => {
    let total = 0, priced = false;
    const taken = {};  // the rows of one product take from its stock together
    for (const tr_ of $("ix-lines").querySelectorAll("tr")) {
      const p = rowProduct(tr_);
      for (const place of [1, 2]) {
        const asked = parseQty(tr_.querySelector(`.ix-qty[data-place="${place}"]`).value);
        if (p && asked > 0) taken[`${p.id}|${place}`] = (taken[`${p.id}|${place}`] || 0) + asked;
      }
    }
    for (const tr_ of $("ix-lines").querySelectorAll("tr")) {
      const p = rowProduct(tr_);
      tr_.querySelector(".ix-spec").textContent = p ? [p.spec, p.variant].filter(Boolean).join(" · ") : "";
      tr_.querySelector(".ix-unit").textContent = p ? p.unit || "" : "";
      let qty = 0;
      for (const place of [1, 2]) {
        const have = tr_.querySelector(`.ix-have[data-place="${place}"]`);
        const box = tr_.querySelector(`.ix-qty[data-place="${place}"]`);
        const asked = parseQty(box.value);
        have.textContent = p ? fmtQty(stockOf(p.id)[place] || 0) : "";
        const over = p && asked > 0 && taken[`${p.id}|${place}`] > (stockOf(p.id)[place] || 0);
        have.classList.toggle("over", !!over);
        box.closest("td").classList.toggle("bad", Number.isNaN(asked));
        if (asked > 0) qty += asked;
      }
      const price = issuePriceVnd(tr_.querySelector(".ix-price"));
      const amount = p && qty > 0 && price !== null && !Number.isNaN(price) ? Math.round(qty * price * 100) / 100 : null;
      tr_.querySelector(".ix-amount").textContent = amount === null ? "" : issueMoney(amount);
      if (amount !== null) { total += amount; priced = true; }
    }
    $("ix-total").textContent = priced ? tr("issue.total", { money: issueMoney(total) }) : "";
  };

  body.addEventListener("input", (e) => {
    const tr_ = e.target.closest("tr.ix-row");
    if (e.target.id === "ix-customer") {
      const c = data.customers.find((x) => x.name === e.target.value.replace(/\s+/g, " ").trim());
      if (c) for (const [id, v] of [["ix-phone", c.phone], ["ix-contact", c.contact], ["ix-address", c.address]]) if (!$(id).value.trim()) $(id).value = v || "";
      for (const row of $("ix-lines").querySelectorAll("tr")) fillPrice(row);
    }
    if (tr_ && e.target.classList.contains("ix-price")) e.target.dataset.typed = e.target.value.trim() ? "1" : "";
    if (tr_ && e.target.classList.contains("ix-product")) {
      fillPrice(tr_);
      const rows = $("ix-lines").querySelectorAll("tr");
      if (rowProduct(tr_) && tr_ === rows[rows.length - 1]) $("ix-lines").insertAdjacentHTML("beforeend", issueRowHtml());
    }
    refresh();
  });
  body.addEventListener("click", (e) => {
    if (!e.target.classList.contains("ix-remove")) return;
    const rows = $("ix-lines").querySelectorAll("tr");
    if (rows.length > 1) e.target.closest("tr").remove();
    else for (const i of e.target.closest("tr").querySelectorAll("input")) { i.value = ""; delete i.dataset.typed; delete i.dataset.vnd; }
    refresh();
  });
  body.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.tagName === "INPUT") e.preventDefault(); });  // Enter never saves
  $("ix-add").addEventListener("click", () => { $("ix-lines").insertAdjacentHTML("beforeend", issueRowHtml()); });
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
    const [main, office] = [".ix-qty[data-place='1']", ".ix-qty[data-place='2']"].map((s) => parseQty(tr_.querySelector(s).value));
    const price = issuePriceVnd(tr_.querySelector(".ix-price"));
    if (!label && main === null && office === null) continue;
    const p = productFromLabel(label);
    if (!p) fail(tr("issue.unknown_product", { text: label || "?" }));
    if ([main, office, price].some((v) => Number.isNaN(v))) fail(tr("issue.not_number", { product: productName(p) }));
    if ([main, office, price].some((v) => v !== null && v < 0)) fail(tr("issue.negative", { product: productName(p) }));
    if (!((main || 0) + (office || 0) > 0)) continue;
    lines.push({ product: p, product_id: p.id, qty_main: main || 0, qty_office: office || 0, unit_price: price,
                 note: tr_.querySelector(".ix-note").value });
  }
  if (!lines.length) fail(tr("issue.need_lines"));
  return { date, customer, phone: $("ix-phone").value.replace(/\s+/g, " ").trim(),
           contact: $("ix-contact").value.replace(/\s+/g, " ").trim(), address: $("ix-address").value.replace(/\s+/g, " ").trim(), lines };
}

async function saveIssue() {
  const f = readIssueForm();
  const short = [], asked = new Map();  // the lines of one product count together
  for (const ln of f.lines) {
    for (const [place, qty] of [[1, ln.qty_main], [2, ln.qty_office]]) {
      if (!(qty > 0)) continue;
      const key = `${ln.product.id}|${place}`;
      asked.set(key, { product: ln.product, place, qty: ((asked.get(key) || {}).qty || 0) + qty });
    }
  }
  for (const a of asked.values()) {
    const have = stockOf(a.product.id)[a.place] || 0;
    if (a.qty > have) short.push(tr("issue.short_line", { product: productName(a.product), place: tr(`place.${a.place}`), qty: fmtQty(a.qty), have: fmtQty(have) }));
  }
  if (short.length && !confirm(`${tr("issue.short_ask")}\n\n${short.join("\n")}`)) return false;
  if (f.date > todayLocal() && !confirm(tr("issue.future_ask"))) return false;
  const rows = DBK_XLSX.noteRows(productById, f.lines);
  const total = rows.reduce((a, r) => a + (r.amount || 0), 0);
  // before saving the user sees what is written: yuan as typed and the dong the note carries
  const both = (vnd) => (issueRate ? `${issueMoney(vnd)} = ${fmtVnd(vnd)} ₫` : fmtVnd(vnd));
  const summary = rows.map((r) => `• ${r.code} ${r.name_vi}: ${fmtQty(r.qty)} ${r.unit} · ` +
    r.places.map(([place, qty]) => `${tr(`place.${place}`)} ${fmtQty(qty)}`).join(" + ") +
    (r.amount !== null ? ` · ${both(r.amount)}` : "")).join("\n");
  if (!confirm(`${tr("issue.confirm", { customer: f.customer })}\n\n${summary}\n\n${tr("issue.total", { money: both(total) })}`)) return false;
  let code;
  if (isOwner()) {
    // the owner's note is recorded on the cloud at once and takes the stock (user, 14/11/2026: the web is the
    // reference data); the server hands out the code (W + next order number) under the write lock
    const lines = f.lines.map((ln) => ({ product_id: ln.product_id, qty_main: ln.qty_main, qty_office: ln.qty_office,
                                         unit_price: ln.unit_price, note: ln.note }));
    const { data: made, error } = await sb.rpc("web_issue", { p: { doc_date: f.date, customer: f.customer, phone: f.phone,
                                                                  contact: f.contact, address: f.address, lines } });
    if (error) fail(error.message || String(error));
    code = made.code;
  } else {
    code = DBK_XLSX.nextCode(data.documents.filter((d) => d.kind === "delivery").map((d) => d.code));
  }
  const head = { code, doc_date: f.date, customer: f.customer, phone: f.phone, contact: f.contact, address: f.address,
                 letterhead: letterhead() };
  const bytes = DBK_XLSX.issueNote(fflate, head, rows);
  const name = `PhieuXuat_${code}.xlsx`;
  saveFile(name, bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
  if (isOwner()) {
    alert(tr("issue.done_owner", { code, name }));
    await loadAll();
  } else {
    alert(tr("issue.done", { name }));
  }
  return true;
}

$("issue-new").addEventListener("click", () => { if (canMakeIssue()) openIssueForm(); });
