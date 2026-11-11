"""The contract between the web and the main machine, end to end.

A real Chrome (headless) fills in and presses every form of the owner on the data of a real database; the rows the page
would insert into web_inbox are captured, and the desktop carries out exactly those rows on that database. If a field
name, a fingerprint or a payload shape differs between webapp/*.js and core/cloud/commands.py, this test goes red --
which no unit test of either side alone could notice. Skipped when Chrome is not installed."""

import functools
import html
import http.server
import json
import re
import shutil
import subprocess
import threading
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from dibekho import db
from dibekho.core import catalog, receipts, stock
from dibekho.core.cloud import commands, mirror

ROOT = Path(__file__).resolve().parent.parent


def find_chrome():
    for name in ("chrome", "google-chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    for path in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                 r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                 "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"):
        if Path(path).exists():
            return path
    return None


CHROME = find_chrome()
pytestmark = pytest.mark.skipif(CHROME is None, reason="Chrome is not installed")


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class Cloud:
    def __init__(self):
        self.patches = []

    def patch(self, path, body, token):
        self.patches.append((path, body))


def _shop(conn):
    with db.transaction(conn):
        a = catalog.create_product(conn, "Keo A", spec="15kg", unit="thung", category="Keo")
        b = catalog.create_product(conn, "Mang B", spec="3mm", unit="cuon", category="Mang")
        c = catalog.create_product(conn, "Keo C", spec="15kg", unit="thung", category="Keo")
        cust = catalog.upsert_customer(conn, "Cong ty A", phone="0900 000 001")
        catalog.upsert_customer(conn, "Khach X", phone="0900 000 002")
        catalog.upsert_customer(conn, "Khach Y", phone="0900 000 003")
        stock.insert_document(conn, "delivery", date(2026, 11, 2), [stock.Line(a, 5)], code="7", code_norm="7",
                              customer_id=cust)
        stock.insert_document(conn, "delivery", date(2026, 11, 3), [stock.Line(a, 3)], code="8", code_norm="8",
                              customer_id=cust)
    receipts.save(conn, receipts.ReceiptInput(date(2026, 11, 1), receipts.SUPPLIER, supplier_name="Cua khau",
                                              lines=[receipts.ReceiptLineInput(50, a),
                                                     receipts.ReceiptLineInput(20, b)]))
    return {"a": a, "b": b, "c": c, "cust": cust}


def _run_page(conn, tmp_path):
    payload = mirror.build_payload(conn, "dev", "May")
    fixture = {k: payload[k] for k in ("products", "customers", "documents", "movements")}
    fixture["lines"] = payload["document_lines"]
    site = tmp_path / "site"
    shutil.copytree(ROOT / "webapp", site, ignore=shutil.ignore_patterns("config.js"))
    (site / "config.js").write_text('const DIBEKHO_CLOUD = {url: "https://example.supabase.co", key: "k"};', encoding="utf-8")
    (site / "fixture.js").write_text("window.__FIXTURE__ = " + json.dumps(fixture) + ";", encoding="utf-8")
    shutil.copy(ROOT / "tests" / "web_contract_probe.js", site / "probe.js")
    page = (site / "index.html").read_text(encoding="utf-8")
    page = page.replace('<script src="owner.js"></script>',
                        '<script src="owner.js"></script><script src="fixture.js"></script><script src="probe.js"></script>')
    (site / "index.html").write_text(page, encoding="utf-8")

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(site)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        done = subprocess.run(
            [CHROME, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={tmp_path / 'chrome'}",
             "--virtual-time-budget=15000", "--dump-dom", f"http://127.0.0.1:{server.server_port}/"],
            capture_output=True, text=True, encoding="utf-8", timeout=120)
    finally:
        server.shutdown()
    found = re.search(r'data-probe="([^"]*)"', done.stdout)
    assert found, "the page never finished its scenario:\n" + done.stdout[-800:] + done.stderr[-400:]
    out = json.loads(html.unescape(found.group(1)))
    assert out["error"] is None, out["error"]
    return out


def _count(conn, sql, *args):
    return conn.execute(sql, args).fetchone()[0]


def test_every_owner_form_produces_commands_the_main_machine_carries_out(conn, ws, tmp_path):
    ids = _shop(conn)
    out = _run_page(conn, tmp_path)

    # what the page itself showed
    assert out["checks"]["staffChipsHidden"] is True and out["checks"]["staffActions"] == ""
    assert out["checks"]["ownerChipsShown"] is True and out["checks"]["ownerTabLabel"] == "Thao tác"
    assert "HV001" in out["checks"]["editTitle"] and out["checks"]["editLeftAfterSend"] is True
    assert out["checks"]["returnFieldsShown"] is True

    rows = out["captured"]
    assert [r["kind"] for r in rows] == [
        "cmd_transfer", "cmd_trial", "cmd_product_add", "cmd_product_edit", "cmd_product_merge", "cmd_customer_merge",
        "cmd_cancel_doc", "cmd_set_location", "cmd_receipt_edit", "receipt", "receipt", "stock_count"]
    assert all(r["payload"].get("summary") for r in rows if r["kind"].startswith("cmd_"))  # shown on the web later

    # the desktop carries out exactly those rows, as the owner's
    sent = datetime.now(timezone.utc).isoformat()
    items = [{"id": f"w{i}", "kind": r["kind"], "payload": r["payload"], "sender": "Chủ", "sender_role": "desktop",
              "created_at": sent} for i, r in enumerate(rows)]
    outcomes = commands.apply_owner_items(conn, ws, Cloud(), "tok", items)
    assert [(o.item["kind"], o.ok, o.summary) for o in outcomes if not o.ok] == []  # nothing refused
    assert len(outcomes) == len(rows)

    levels = stock.stock_levels(conn, by_location=True)
    assert _count(conn, "SELECT COUNT(*) FROM documents WHERE kind = 'transfer' AND code = 'CH001'") == 1
    # at the office: +12 transferred in, -2 trial use, -3 for delivery 8 once its place was set to the office
    assert levels[(ids["a"], stock.OFFICE)] == 12 - 2 - 3
    assert _count(conn, "SELECT COUNT(*) FROM documents WHERE kind = 'trial' AND code = 'DT001'") == 1

    assert _count(conn, "SELECT COUNT(*) FROM products WHERE name_vi = 'Keo D' AND spec = '25kg'") == 1
    a = conn.execute("SELECT * FROM products WHERE id = ?", (ids["a"],)).fetchone()
    assert (a["name_vi"], a["stock_note"], a["active"]) == ("Keo A moi", "2 thung mop", 0)
    assert _count(conn, "SELECT COUNT(*) FROM products WHERE id = ?", ids["c"]) == 0  # SP003 merged into SP002
    assert _count(conn, "SELECT COUNT(*) FROM products WHERE id = ?", ids["b"]) == 1

    assert _count(conn, "SELECT COUNT(*) FROM customers WHERE name IN ('Khach X', 'Khach Y')") == 0
    assert _count(conn, "SELECT COUNT(*) FROM customers WHERE name = 'Khach XY'") == 1

    assert _count(conn, "SELECT COUNT(*) FROM documents WHERE kind = 'delivery' AND code = '7' AND status = 'cancelled'") == 1
    d8 = conn.execute("SELECT location_id, location_set FROM documents WHERE kind = 'delivery' AND code = '8'").fetchone()
    assert (d8["location_id"], d8["location_set"]) == (2, 1)

    hv1 = conn.execute("SELECT status FROM documents WHERE code = 'HV001' ORDER BY id").fetchall()
    assert [r[0] for r in hv1] == ["replaced", "active"]
    edited = conn.execute("SELECT SUM(l.qty) FROM document_lines l JOIN documents d ON d.id = l.document_id "
                          "WHERE d.code = 'HV001' AND d.status = 'active' AND l.product_id = ?", (ids["a"],)).fetchone()[0]
    assert edited == 60

    assert _count(conn, "SELECT COUNT(*) FROM documents WHERE kind = 'receipt' AND status = 'active' AND code = 'HV002' "
                        "AND receipt_source = 'supplier'") == 1
    returned = conn.execute("SELECT customer_id, ref_code FROM documents WHERE kind = 'receipt' AND receipt_source = 'return'").fetchone()
    assert (returned["customer_id"], returned["ref_code"]) == (ids["cust"], "7")
    count_line = conn.execute("SELECT l.qty FROM document_lines l JOIN documents d ON d.id = l.document_id "
                              "WHERE d.kind = 'stock_count'").fetchone()
    assert count_line[0] == 18
