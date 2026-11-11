/* DiBeKho statistics for the web: the same numbers as the app's core/stats.py, computed from the mirror tables.
   Pure functions, no DOM: tests/test_web_stats.py runs this file under node against the Python module, because
   the owner stops trusting both screens the day they disagree.

   data = { products, customers, documents, lines, movements }   (the mirror_* rows; dates are 'YYYY-MM-DD')
   filters = { productIds: [..] | null, categories: [..] | null, customerIds: [..] | null }
   Transfers are neither in nor out; trial use is an adjustment, not a sale; revenue is the goods of ACTIVE
   delivery notes only (fees apart); a line without a price counts nothing. */

(function (root) {
  "use strict";

  const IN_KINDS = ["receipt_in", "receipt_reverse"];
  const OUT_KINDS = ["delivery_out", "delivery_reverse"];
  const ADJ_KINDS = ["count_adjust", "count_reverse", "trial_out", "trial_reverse"];

  const has = (list) => list && list.length > 0;

  function productMatches(p, f) {
    if (has(f.productIds) && !f.productIds.includes(p.id)) return false;
    if (has(f.categories) && !f.categories.includes(p.category)) return false;
    return true;
  }

  function customerMatches(doc, f) {
    return !has(f.customerIds) || f.customerIds.includes(doc.customer_id);
  }

  // ---- periods (the app's day/month/quarter/year ranges and buckets) -------------------------------------------

  const pad = (n) => String(n).padStart(2, "0");
  const iso = (y, m, d) => `${y}-${pad(m)}-${pad(d)}`;
  const lastDay = (y, m) => new Date(Date.UTC(y, m, 0)).getUTCDate();

  function monthRange(y, m) { return [iso(y, m, 1), iso(y, m, lastDay(y, m))]; }
  function quarterRange(y, q) {
    const first = 3 * (q - 1) + 1;
    return [iso(y, first, 1), monthRange(y, first + 2)[1]];
  }
  function yearRange(y) { return [iso(y, 1, 1), iso(y, 12, 31)]; }

  function addDays(day, n) {
    const d = new Date(day + "T00:00:00Z");
    d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
  }

  /** by: 'day' | 'month' | 'none'. Labels like the app: dd/mm and mm/yyyy. */
  function buckets(start, end, by) {
    const out = [];
    if (by === "day") {
      for (let d = start; d <= end; d = addDays(d, 1)) out.push({ label: `${d.slice(8, 10)}/${d.slice(5, 7)}`, start: d, end: d });
    } else if (by === "month") {
      let y = Number(start.slice(0, 4)), m = Number(start.slice(5, 7));
      while (iso(y, m, 1) <= end) {
        const [s, e] = monthRange(y, m);
        out.push({ label: `${pad(m)}/${y}`, start: s > start ? s : start, end: e < end ? e : end });
        if (m === 12) { y += 1; m = 1; } else { m += 1; }
      }
    }
    return out;
  }

  // ---- summary -------------------------------------------------------------------------------------------------

  function summary(data, start, end, filters, by) {
    const f = filters || {};
    const docById = new Map(data.documents.map((d) => [d.id, d]));
    const byProduct = new Map();
    for (const m of data.movements) {
      if (!byProduct.has(m.product_id)) byProduct.set(m.product_id, []);
      byProduct.get(m.product_id).push(m);
    }
    const customerFiltered = has(f.customerIds);
    const rows = [];
    for (const p of data.products) {
      if (!productMatches(p, f)) continue;
      const moves = byProduct.get(p.id) || [];
      if (!p.active && moves.length === 0) continue;  // a stopped product shows only if it ever moved
      let opening = 0, qtyIn = 0, qtyOut = 0, adjust = 0;
      for (const m of moves) {
        const inRange = m.occurred_on >= start && m.occurred_on <= end;
        if (m.occurred_on < start) opening += m.qty;
        if (!inRange) continue;
        if (IN_KINDS.includes(m.kind)) qtyIn += m.qty;
        else if (OUT_KINDS.includes(m.kind) && customerMatches(docById.get(m.document_id) || {}, f)) qtyOut -= m.qty;
        else if (ADJ_KINDS.includes(m.kind)) adjust += m.qty;
      }
      rows.push({
        product_id: p.id, code: p.code, name_vi: p.name_vi, name_zh: p.name_zh, spec: p.spec, variant: p.variant,
        unit: p.unit, category: p.category, stock_note: p.stock_note,
        opening: customerFiltered ? null : opening, qty_in: qtyIn, qty_out: qtyOut, adjust,
        closing: customerFiltered ? null : opening + qtyIn - qtyOut + adjust,
        per_bucket: {}, revenue: null,
      });
    }
    const revenue = revenueByProduct(data, start, end, f);
    for (const r of rows) r.revenue = revenue.has(r.product_id) ? revenue.get(r.product_id) : null;
    let result = customerFiltered ? rows.filter((r) => r.qty_out) : rows;
    if (by && by !== "none" && result.length) fillBuckets(data, result, buckets(start, end, by), f, docById);
    return result;
  }

  function revenueByProduct(data, start, end, f) {
    const docById = new Map(data.documents.map((d) => [d.id, d]));
    const productById = new Map(data.products.map((p) => [p.id, p]));
    const out = new Map();
    for (const l of data.lines) {
      const d = docById.get(l.document_id), p = productById.get(l.product_id);
      if (!d || !p || d.kind !== "delivery" || d.status !== "active") continue;
      if (d.doc_date < start || d.doc_date > end || l.amount === null || l.amount === undefined) continue;
      if (!productMatches(p, f) || !customerMatches(d, f)) continue;
      out.set(l.product_id, (out.get(l.product_id) || 0) + l.amount);
    }
    return out;
  }

  function fillBuckets(data, rows, bks, f, docById) {
    const ids = new Set(rows.map((r) => r.product_id));
    const byId = new Map(rows.map((r) => [r.product_id, r]));
    for (const r of rows) for (const b of bks) r.per_bucket[b.label] = [0, 0];
    for (const m of data.movements) {
      if (!ids.has(m.product_id)) continue;
      for (const b of bks) {
        if (m.occurred_on < b.start || m.occurred_on > b.end) continue;
        const cell = byId.get(m.product_id).per_bucket[b.label];
        if (IN_KINDS.includes(m.kind)) cell[0] += m.qty;
        else if (OUT_KINDS.includes(m.kind) && customerMatches(docById.get(m.document_id) || {}, f)) cell[1] -= m.qty;
      }
    }
  }

  // ---- money ---------------------------------------------------------------------------------------------------

  /** Revenue of the period = goods only; fees apart (null when products or groups are filtered). */
  function money(data, start, end, filters) {
    const f = filters || {};
    const docById = new Map(data.documents.map((d) => [d.id, d]));
    const productById = new Map(data.products.map((p) => [p.id, p]));
    const orders = new Set(), unpriced = new Set();
    let goods = 0;
    for (const l of data.lines) {
      const d = docById.get(l.document_id), p = productById.get(l.product_id);
      if (!d || !p || d.kind !== "delivery" || d.status !== "active") continue;
      if (d.doc_date < start || d.doc_date > end || !productMatches(p, f) || !customerMatches(d, f)) continue;
      orders.add(d.id);
      if (l.amount === null || l.amount === undefined) unpriced.add(d.id); else goods += l.amount;
    }
    let fees = null;
    if (!has(f.productIds) && !has(f.categories)) {
      fees = 0;
      for (const d of data.documents) {
        if (d.kind === "delivery" && d.status === "active" && d.doc_date >= start && d.doc_date <= end &&
            customerMatches(d, f)) fees += d.fee_amount || 0;
      }
    }
    return { orders: orders.size, goods, fees, unpriced: unpriced.size };
  }

  function topOut(data, start, end, filters, limit) {
    return summary(data, start, end, filters, "none").filter((r) => r.qty_out > 0)
      .sort((a, b) => b.qty_out - a.qty_out).slice(0, limit || 10);
  }

  /** Total outgoing quantity per day, for the chart. */
  function dailyOut(data, start, end, filters) {
    const f = filters || {};
    const docById = new Map(data.documents.map((d) => [d.id, d]));
    const productById = new Map(data.products.map((p) => [p.id, p]));
    const perDay = new Map();
    for (const m of data.movements) {
      if (!OUT_KINDS.includes(m.kind) || m.occurred_on < start || m.occurred_on > end) continue;
      const p = productById.get(m.product_id), d = docById.get(m.document_id);
      if (!p || !d || !productMatches(p, f) || !customerMatches(d, f)) continue;
      perDay.set(m.occurred_on, (perDay.get(m.occurred_on) || 0) - m.qty);
    }
    const out = [];
    for (let d = start; d <= end; d = addDays(d, 1)) out.push([d, perDay.get(d) || 0]);
    return out;
  }

  const api = { IN_KINDS, OUT_KINDS, ADJ_KINDS, monthRange, quarterRange, yearRange, addDays, buckets, summary,
                money, topOut, dailyOut };
  root.DibeStats = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
