/* DiBeKho web: Tổng quan (dashboard), the page the main machine's role opens on (customer's request 14/11/2026: the
   manager wants the state of the business at a glance). Only the "desktop" role sees it; it shows nothing the other
   roles cannot already read in the other pages, so hiding it is enough (no row level security needed).

   Built with the evon ui-ux rules (direct build): one row of figures (revenue and orders compared with the same span
   of the previous period, products running low, products below zero), then the revenue of the last 12 months as
   columns with their value on top, then four lists (best sellers, best customers, running low, latest orders), each
   short enough that the two columns end level. Money follows the app (stats.js = core/stats.py): goods sold minus
   goods customers sent back, fees apart. */

"use strict";

const DASH_PERIODS = ["month", "last_month", "quarter", "year"];

function isoDay(d) {
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** The same day `months` months earlier, kept inside the shorter month (31/03 -> 28/02). */
function monthsBack(iso, months) {
  const [y, m, d] = iso.split("-").map(Number);
  const first = new Date(y, m - 1 - months, 1);
  const last = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate();
  return isoDay(new Date(first.getFullYear(), first.getMonth(), Math.min(d, last)));
}

/** [start, end, previous start, previous end, months] of a period; a running period ends today and is compared with
    the same span of the period before it (1-14 Nov against 1-14 Oct), not with a whole month. */
function dashRange(kind, today = todayLocal()) {
  const [y, m] = today.split("-").map(Number);
  if (kind === "last_month") {
    const [s, e] = DibeStats.monthRange(m === 1 ? y - 1 : y, m === 1 ? 12 : m - 1);
    const [ps, pe] = DibeStats.monthRange(m <= 2 ? y - 1 : y, ((m + 9) % 12) + 1);
    return [s, e, ps, pe];
  }
  const months = { month: 1, quarter: 3, year: 12 }[kind];
  const start = kind === "month" ? DibeStats.monthRange(y, m)[0]
    : kind === "quarter" ? DibeStats.quarterRange(y, Math.floor((m - 1) / 3) + 1)[0] : DibeStats.yearRange(y)[0];
  return [start, today, monthsBack(start, months), monthsBack(today, months)];
}

/** Money in a small space: 184,5 tr / 1,28 tỷ (Vietnamese), 1845万 / 1.28亿 (Chinese); the full number in the tooltip. */
function shortMoney(n) {
  if (moneyInCny()) return "¥" + shortNumber((Number(n) || 0) / FX.rate.vnd_per_cny);  // the ₫ / ¥ switch (fx.js)
  return shortNumber(n);
}

function shortNumber(n) {
  const v = Number(n) || 0, a = Math.abs(v);
  const one = (x) => (Math.round(x * 10) / 10).toLocaleString(LANG === "zh" ? "zh-CN" : "vi-VN");
  const two = (x) => (Math.round(x * 100) / 100).toLocaleString(LANG === "zh" ? "zh-CN" : "vi-VN");
  if (LANG === "zh") {
    if (a >= 1e8) return `${two(v / 1e8)}亿`;
    if (a >= 1e6) return `${Math.round(v / 1e4).toLocaleString("zh-CN")}万`;
    if (a >= 1e4) return `${one(v / 1e4)}万`;
    return v.toLocaleString("zh-CN", { maximumFractionDigits: a < 100 ? 2 : 0 });
  }
  if (a >= 1e9) return `${two(v / 1e9)} ${tr("money.billion")}`;
  if (a >= 1e6) return `${one(v / 1e6)} ${tr("money.million")}`;
  if (a >= 1e5) return `${Math.round(v / 1e3)} ${tr("money.thousand")}`;  // yuan stay readable: ¥4.250, not ¥4 nghìn
  return v.toLocaleString(numLocale(), { maximumFractionDigits: a < 100 ? 2 : 0 });
}

const fmtDay = (iso) => (iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}` : "");

/** Revenue and orders of each customer in a period (sold minus sent back, like the Khách hàng page). */
function customerRevenue(start, end) {
  const per = new Map();
  for (const d of data.documents) {
    if (d.status !== "active" || !d.customer_id || d.doc_date < start || d.doc_date > end) continue;
    if (d.kind !== "delivery" && !isReturn(d)) continue;
    const row = per.get(d.customer_id) || { id: d.customer_id, revenue: 0, orders: 0 };
    const sign = isReturn(d) ? -1 : 1;
    for (const l of linesByDoc[d.id] || []) if (l.amount !== null && l.amount !== undefined) row.revenue += sign * l.amount;
    if (!isReturn(d)) row.orders += 1;
    per.set(d.customer_id, row);
  }
  return [...per.values()].filter((r) => r.orders || r.revenue).sort((a, b) => b.revenue - a.revenue);
}

function monthsRevenue(today = todayLocal()) {
  const [y, m] = today.split("-").map(Number);
  const out = [];
  for (let i = 11; i >= 0; i--) {
    const d = new Date(y, m - 1 - i, 1);
    const [s, e] = DibeStats.monthRange(d.getFullYear(), d.getMonth() + 1);
    out.push({ y: d.getFullYear(), m: d.getMonth() + 1, total: DibeStats.money(statsModel(), s, e, {}).total || 0, running: i === 0 });
  }
  return out;
}

/* ---------------------------------------------------------------- the parts */

function deltaLine(now, before, money) {
  if (before === null || before === undefined) return `<p class="kpi-sub">${esc(tr("dash.no_before"))}</p>`;
  const diff = now - before;
  if (!diff) return `<p class="kpi-sub">${esc(tr("dash.same"))}</p>`;
  const cls = diff > 0 ? "up" : "down", arrow = diff > 0 ? "↗" : "↘";
  // small counts compare by the difference, money and bigger counts by the percentage
  const text = !money && Math.abs(before) < 20 ? fmtQty(Math.abs(diff))
    : before ? `${(Math.round(Math.abs(diff) / Math.abs(before) * 1000) / 10).toLocaleString(LANG === "zh" ? "zh-CN" : "vi-VN")}%` : "";
  return `<p class="kpi-sub"><span class="${cls}">${arrow} ${esc(text)}</span></p>`;
}

function kpi(label, value, sub, title = "", action = "") {
  return `<div class="kpi${action ? " click" : ""}"${action ? ` data-go="${esc(action)}" role="button" tabindex="0"` : ""}>` +
    `<p class="kpi-label">${esc(label)}</p><p class="kpi-value"${title ? ` title="${esc(title)}"` : ""}>${value}</p>${sub}</div>`;
}

function monthsChart(months) {
  const max = Math.max(1, ...months.map((x) => x.total));
  const w = 760, h = 210, top = 26, bottom = 26, gap = 10, bw = (w - gap * 11) / 12;
  const bars = months.map((x, i) => {
    const bh = Math.max(x.total > 0 ? 2 : 0, (x.total / max) * (h - top - bottom));
    const cx = i * (bw + gap), y = h - bottom - bh;
    const label = LANG === "zh" ? `${x.m}月` : `T${x.m}`;
    const full = `${label}/${x.y}: ${fmtMoney(x.total)}${x.running ? ` (${tr("dash.running")})` : ""}`;
    return `<g><title>${esc(full)}</title><rect class="bar${x.running ? " running" : ""}" x="${cx.toFixed(1)}" y="${y.toFixed(1)}" ` +
      `width="${bw.toFixed(1)}" height="${bh.toFixed(1)}" rx="3"></rect>` +
      `<text class="val" x="${(cx + bw / 2).toFixed(1)}" y="${(y - 7).toFixed(1)}">${x.total ? esc(shortMoney(x.total)) : "0"}</text>` +
      `<text class="axis" x="${(cx + bw / 2).toFixed(1)}" y="${h - 6}">${esc(label)}</text></g>`;
  }).join("");
  return `<div class="mchart-wrap"><svg viewBox="0 0 ${w} ${h}" class="mchart" role="img" aria-label="${esc(tr("dash.revenue_12"))}">${bars}</svg></div>` +
    `<p class="hint">${esc(tr("dash.running_note"))}</p>`;
}

/** A ranked list: name, a bar of its share of the first, the figure on the right. */
function rankList(rows, empty) {
  if (!rows.length) return `<p class="hint dash-empty">${esc(empty)}</p>`;
  const max = Math.max(1, ...rows.map((r) => r.value));
  return `<ol class="rank">` + rows.map((r) => `<li${r.open ? ` class="click" data-open="${esc(r.open)}"` : ""}>` +
    `<div class="rank-top"><span class="rank-name">${esc(r.name)}</span><b class="rank-fig" title="${esc(r.title || "")}">${esc(r.figure)}</b></div>` +
    `<svg class="hbar" viewBox="0 0 100 6" preserveAspectRatio="none" aria-hidden="true"><rect class="track" width="100" height="6"></rect>` +
    `<rect class="bar" width="${Math.max(r.value > 0 ? 1 : 0, (r.value / max) * 100).toFixed(1)}" height="6"></rect></svg>` +
    `<div class="rank-sub">${esc(r.sub || "")}</div></li>`).join("") + `</ol>`;
}

function panelHead(title, action) {
  return `<div class="panel-head"><h2>${esc(title)}</h2>${action ? `<button class="flat see-all" data-go="${esc(action)}">${esc(tr("dash.see_all"))}</button>` : ""}</div>`;
}

/* ---------------------------------------------------------------- the page */

function renderDashboard() {
  if (!isOwner()) return;
  const sel = $("dash-period");
  if (!sel.options.length) {
    sel.innerHTML = DASH_PERIODS.map((k) => `<option value="${k}">${esc(tr(`dash.p_${k}`))}</option>`).join("");
    sel.addEventListener("change", renderDashboard);
  }
  const [start, end, ps, pe] = dashRange(sel.value);
  const model = statsModel();
  const money = DibeStats.money(model, start, end, {}), before = DibeStats.money(model, ps, pe, {});
  const hasBefore = data.documents.some((d) => d.kind === "delivery" && d.status === "active" && d.doc_date <= pe);
  $("dash-range").textContent = tr("dash.range", { start: fmtDay(start), end: fmtDay(end), ps: fmtDay(ps), pe: fmtDay(pe) });

  const all = activeProducts();
  const low = all.filter((p) => isLow(p) && stockOf(p.id).total >= 0), negative = all.filter((p) => stockOf(p.id).total < 0);
  const unplaced = unplacedOrders().length;
  $("dash-kpis").innerHTML =
    kpi(tr("money.revenue"), `${esc(shortMoney(money.total))}${moneyInCny() ? "" : `<span class="unit"> ${esc(tr("money.unit"))}</span>`}`,
        deltaLine(money.total || 0, hasBefore ? before.total || 0 : null, true), `${fmtMoney(money.total)}${moneyInCny() ? "" : " " + tr("money.unit")}`) +
    kpi(tr("col.orders"), esc(fmtQty(money.orders)), deltaLine(money.orders, hasBefore ? before.orders : null, false)) +
    kpi(tr("dash.k_low"), esc(fmtQty(low.length)), `<p class="kpi-sub">${esc(lowDefault ? tr("dash.k_low_sub", { level: fmtQty(lowDefault) }) : tr("settings.low_off"))}</p>`, "", "low") +
    kpi(tr("dash.k_negative"), esc(fmtQty(negative.length)), `<p class="kpi-sub">${esc(tr("dash.k_negative_sub"))}</p>`, "", "low");
  // orders still waiting for "where was it taken from": something to do in the app, said once above the lists
  $("dash-banner").innerHTML = unplaced
    ? `<p class="banner click" data-go="pending" role="button" tabindex="0">${esc(tr("dash.unplaced", { n: unplaced }))}</p>` : "";

  $("dash-months").innerHTML = monthsChart(monthsRevenue());

  const tops = DibeStats.topOut(model, start, end, {}, 200)
    .sort((a, b) => (b.revenue || 0) - (a.revenue || 0) || b.qty_out - a.qty_out).slice(0, 5);
  $("dash-products").innerHTML = panelHead(tr("dash.top_products"), "stats") + rankList(tops.map((r) => ({
    name: productName(r), value: r.revenue || 0, figure: r.revenue ? shortMoney(r.revenue) : "—", title: fmtMoney(r.revenue),
    sub: tr("dash.sold", { qty: fmtQty(r.qty_out), unit: (productById[r.product_id] || {}).unit || "" }).trim(), open: `p:${r.product_id}`,
  })), tr("dash.none_sold"));

  const custs = customerRevenue(start, end).slice(0, 5);
  $("dash-customers").innerHTML = panelHead(tr("dash.top_customers"), "customers") + rankList(custs.map((r) => ({
    name: (customerById[r.id] || {}).name || "?", value: Math.max(0, r.revenue), figure: shortMoney(r.revenue), title: fmtMoney(r.revenue),
    sub: tr("dash.orders_n", { n: r.orders }), open: `c:${r.id}`,
  })), tr("dash.none_customers"));

  const short = all.filter(isLow).sort((a, b) => stockOf(a.id).total - stockOf(b.id).total).slice(0, 6);
  $("dash-low").innerHTML = panelHead(tr("dash.low"), short.length ? "low" : "") + (short.length
    ? `<ul class="lines">` + short.map((p) => {
      const s = stockOf(p.id);
      return `<li class="click ${s.total < 0 ? "neg" : "low"}" data-open="p:${esc(p.id)}"><div class="line-main"><span class="line-name">${esc(productName(p))}</span>` +
        `<span class="line-sub">${esc(tr("place.1"))} ${fmtQty(s[1])} · ${esc(tr("place.2"))} ${fmtQty(s[2])}</span></div>` +
        `<b class="line-fig">${fmtQty(s.total)}<small> ${esc(p.unit || "")}</small></b></li>`;
    }).join("") + `</ul>`
    : `<p class="hint dash-empty">${esc(lowDefault ? tr("dash.none_low") : tr("settings.low_off"))}</p>`);

  const recent = data.documents.filter((d) => d.kind === "delivery" && d.status === "active")
    .sort((a, b) => b.doc_date.localeCompare(a.doc_date) || String(b.created_at).localeCompare(String(a.created_at))).slice(0, 6);
  $("dash-recent").innerHTML = panelHead(tr("dash.recent"), recent.length ? "orders" : "") + (recent.length
    ? `<ul class="lines">` + recent.map((d) => {
      const amount = (linesByDoc[d.id] || []).reduce((a, l) => a + (l.amount || 0), 0);
      const priced = (linesByDoc[d.id] || []).some((l) => l.amount !== null && l.amount !== undefined);
      return `<li class="click" data-open="d:${esc(d.id)}"><div class="line-main"><span class="line-name">${esc((customerById[d.customer_id] || {}).name || "—")}</span>` +
        `<span class="line-sub">${esc(fmtDay(d.doc_date))} · ${esc(d.code || "")} · ${esc(placeOf(d))}</span></div>` +
        `<b class="line-fig" title="${esc(fmtMoney(amount))}">${priced ? esc(shortMoney(amount)) : "—"}</b></li>`;
    }).join("") + `</ul>`
    : `<p class="hint dash-empty">${esc(tr("dash.none_orders"))}</p>`);
}

/* clicks: a row opens its detail, "Xem tất cả" and the figures open the page behind them */
$("page-dashboard").addEventListener("click", (e) => {
  const open = e.target.closest("[data-open]");
  if (open) {
    const [kind, id] = open.dataset.open.split(/:(.*)/s);
    if (kind === "p") showProduct(id); else if (kind === "c") showCustomer(id); else showOrder(id);
    return;
  }
  const go = e.target.closest("[data-go]");
  if (!go) return;
  if (go.dataset.go === "low") { $("stock-low").checked = true; renderStock(); showPage("stock"); return; }
  showPage(go.dataset.go);
});
$("page-dashboard").addEventListener("keydown", (e) => {
  if ((e.key === "Enter" || e.key === " ") && e.target.matches("[data-go][role=button]")) { e.preventDefault(); e.target.click(); }
});
