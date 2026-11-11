"""The web statistics (webapp/stats.js, run under node) must give the same numbers as core/stats.py.

If the two screens ever disagree the owner stops trusting both, so the JavaScript is checked against the Python
module on a shop-like data set: several months, receipts, priced deliveries with fees, a cancelled delivery, count
adjustments, a transfer, trial use, and a stopped product that still has movements."""

import json
import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest

from dibekho import db
from dibekho.core import catalog, stats, stock
from dibekho.core.cloud import mirror

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

RUNNER = """
const fs = require("fs");
const S = require(process.argv[2]);
const input = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const out = input.cases.map((c) => ({
  summary: S.summary(input.data, c.start, c.end, c.filters, c.by),
  money: S.money(input.data, c.start, c.end, c.filters),
  top: S.topOut(input.data, c.start, c.end, c.filters, 10),
  daily: S.dailyOut(input.data, c.start, c.end, c.filters),
}));
process.stdout.write(JSON.stringify(out));
"""


def _build(conn):
    """-> (ids, customers). Returns the product ids by name and the customer ids."""
    with db.transaction(conn):
        a = catalog.create_product(conn, "Keo A", spec="15kg", unit="thùng", category="Keo")
        b = catalog.create_product(conn, "Keo B", spec="20kg", unit="thùng", category="Keo")
        c = catalog.create_product(conn, "Màng SBS", spec="3mm", unit="cuộn", category="Màng")
        old = catalog.create_product(conn, "Hàng cũ", spec="x", unit="cái", category="Cũ")
        c1 = catalog.upsert_customer(conn, "Công ty A", phone="0900 000 001")
        c2 = catalog.upsert_customer(conn, "Khách Mẫu", phone="0900 000 002")
        stock.insert_document(conn, "receipt", date(2026, 9, 20), [stock.Line(a, 100), stock.Line(b, 50),
                                                                   stock.Line(c, 80), stock.Line(old, 7)],
                              code="HV001", code_norm="HV001")
        sold_old = stock.insert_document(conn, "delivery", date(2026, 9, 25), [stock.Line(old, 7)], code="1",
                                         code_norm="1", customer_id=c1)
        stock.stock_count(conn, date(2026, 9, 30), {(a, stock.MAIN): 95})
        # October: priced deliveries, one with a shipping fee, two customers
        stock.insert_document(conn, "delivery", date(2026, 10, 3),
                              [stock.Line(a, 10, unit_price=100.0, amount=1000.0),
                               stock.Line(c, 5, unit_price=200.0, amount=1000.0)],
                              code="2", code_norm="2", customer_id=c1)
        fee_doc = stock.insert_document(conn, "delivery", date(2026, 10, 3),
                                        [stock.Line(b, 4, unit_price=50.0, amount=200.0),
                                         stock.Line(a, 2)],  # a line without a price
                                        code="3", code_norm="3", customer_id=c2)
        conn.execute("UPDATE documents SET fee_amount = 30 WHERE id = ?", (fee_doc,))
        cancelled = stock.insert_document(conn, "delivery", date(2026, 10, 9), [stock.Line(a, 20, unit_price=100.0,
                                                                                            amount=2000.0)],
                                          code="4", code_norm="4", customer_id=c1)
        stock.close_document(conn, cancelled, "cancelled")
        stock.insert_document(conn, "receipt", date(2026, 10, 15), [stock.Line(b, 30)], code="HV002",
                              code_norm="HV002")
        stock.transfer(conn, date(2026, 10, 16), stock.MAIN, stock.OFFICE, [stock.Line(a, 12)])
        stock.record_trial_use(conn, date(2026, 10, 18), stock.MAIN, [stock.Line(c, 2)])
        stock.insert_document(conn, "delivery", date(2026, 10, 20), [stock.Line(a, 6, unit_price=110.0, amount=660.0)],
                              code="5", code_norm="5", customer_id=c1)
        # November
        stock.stock_count(conn, date(2026, 11, 2), {(b, stock.MAIN): 70, (c, stock.OFFICE): 1})
        stock.insert_document(conn, "delivery", date(2026, 11, 5), [stock.Line(c, 8, unit_price=210.0, amount=1680.0)],
                              code="6", code_norm="6", customer_id=c2)
        del sold_old
        catalog.update_product(conn, old, active=0)  # stopped, but it moved in September
    return {"a": a, "b": b, "c": c, "old": old}, {"c1": c1, "c2": c2}


def _cases(ids, customers):
    return [
        ("all of October", date(2026, 10, 1), date(2026, 10, 31), None, "none"),
        ("whole period by month", date(2026, 9, 1), date(2026, 11, 30), None, "month"),
        ("one week by day", date(2026, 10, 1), date(2026, 10, 7), None, "day"),
        ("one day", date(2026, 10, 3), date(2026, 10, 3), None, "none"),
        ("a day with nothing", date(2026, 12, 25), date(2026, 12, 25), None, "none"),
        ("category Keo", date(2026, 9, 1), date(2026, 11, 30), stats.Filters(categories=["Keo"]), "none"),
        ("one product", date(2026, 10, 1), date(2026, 11, 30), stats.Filters(product_ids=[ids["a"]]), "month"),
        ("one customer", date(2026, 10, 1), date(2026, 10, 31), stats.Filters(customer_ids=[customers["c1"]]), "none"),
        ("customer + category", date(2026, 9, 1), date(2026, 11, 30),
         stats.Filters(customer_ids=[customers["c2"]], categories=["Màng", "Keo"]), "day"),
    ]


def _js_filters(f):
    if f is None:
        return {}
    return {"productIds": f.product_ids, "categories": f.categories, "customerIds": f.customer_ids}


def _close(x, y, what):
    if x is None or y is None:
        assert x is None and y is None, what
    else:
        assert x == pytest.approx(y, abs=1e-9), what


def test_web_statistics_match_the_app(conn, tmp_path):
    ids, customers = _build(conn)
    payload = mirror.build_payload(conn, "dev", "May")
    data = {k: payload[k] for k in ("products", "customers", "documents", "movements")}
    data["lines"] = payload["document_lines"]

    cases = _cases(ids, customers)
    (tmp_path / "in.json").write_text(json.dumps({
        "data": data,
        "cases": [{"start": s.isoformat(), "end": e.isoformat(), "filters": _js_filters(f), "by": by}
                  for _, s, e, f, by in cases]}), encoding="utf-8")
    (tmp_path / "run.js").write_text(RUNNER, encoding="utf-8")
    done = subprocess.run([NODE, str(tmp_path / "run.js"), str(ROOT / "webapp" / "stats.js"), str(tmp_path / "in.json")],
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stderr
    results = json.loads(done.stdout)

    for (label, start, end, filters, by), js in zip(cases, results):
        py_rows = {r.product_id: r for r in stats.summary(conn, start, end, filters, by)}
        js_rows = {r["product_id"]: r for r in js["summary"]}
        assert set(js_rows) == set(py_rows), f"{label}: which products are listed"
        for pid, py in py_rows.items():
            row = js_rows[pid]
            for field, js_field in (("opening", "opening"), ("qty_in", "qty_in"), ("qty_out", "qty_out"),
                                    ("adjust", "adjust"), ("closing", "closing"), ("revenue", "revenue")):
                _close(row[js_field], getattr(py, field), f"{label}: product {pid} {field}")
            assert set(row["per_bucket"]) == set(py.per_bucket), f"{label}: buckets of product {pid}"
            for bucket, (qin, qout) in py.per_bucket.items():
                _close(row["per_bucket"][bucket][0], qin, f"{label}: {pid} {bucket} in")
                _close(row["per_bucket"][bucket][1], qout, f"{label}: {pid} {bucket} out")

        money = stats.money(conn, start, end, filters)
        for field in ("orders", "goods", "fees", "unpriced"):
            _close(js["money"][field], getattr(money, field), f"{label}: money {field}")

        py_top = [(r.product_id, r.qty_out) for r in stats.top_out(conn, start, end, filters)]
        js_top = [(r["product_id"], r["qty_out"]) for r in js["top"]]
        assert sorted(js_top) == sorted(py_top), f"{label}: top out"
        assert [q for _, q in js_top] == sorted((q for _, q in js_top), reverse=True), f"{label}: top order"

        py_daily = stats.daily_out(conn, start, end, filters)
        assert [d for d, _ in js["daily"]] == [d.isoformat() for d, _ in py_daily], f"{label}: days"
        for (_, jq), (_, pq) in zip(js["daily"], py_daily):
            _close(jq, pq, f"{label}: daily out")


def test_the_fixture_really_exercises_the_tricky_parts(conn):
    """Guard against the comparison above passing vacuously on an empty-looking data set."""
    ids, customers = _build(conn)
    october = {r.product_id: r for r in stats.summary(conn, date(2026, 10, 1), date(2026, 10, 31))}
    assert october[ids["a"]].qty_out == 18 and october[ids["a"]].revenue == 1660  # the cancelled one cancels out
    assert october[ids["c"]].adjust == -2  # trial use is an adjustment, not an out
    assert stats.money(conn, date(2026, 10, 1), date(2026, 10, 31)).fees == 30
    assert stats.money(conn, date(2026, 10, 1), date(2026, 10, 31)).unpriced == 1  # the line without a price
    assert ids["old"] in {r.product_id for r in stats.summary(conn, date(2026, 12, 1), date(2026, 12, 31))}
