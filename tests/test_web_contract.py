"""The contract between the web page and the shared data, end to end.

A real Chrome (headless) opens the page on a shop's shared rows, fills in and presses the owner's windows (and a staff
member's), and the calls the page makes are captured. Those exact calls then run on a real Postgres with the project's
SQL (PGlite), the app pulls the result with its normal two-way sync, and the shop's data must show every change. Staff
requests are read by the app's own approval code. A renamed field or argument on either side turns this red, which no
test of one side alone could notice. Skipped without Chrome or PGlite."""

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
from dibekho.core.cloud import inbox, replica, twoway
from tests.pgdb import WEB_FILES, FakeCloud, Session, needs_pg

ROOT = Path(__file__).resolve().parent.parent
OWNER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


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
pytestmark = [pytest.mark.skipif(CHROME is None, reason="Chrome is not installed"), needs_pg]
TABLES = ("products", "customers", "suppliers", "documents", "document_lines", "stock_movements", "meta")
ARG_TYPES = {"p": "jsonb", "p_replaces": "uuid", "p_doc": "uuid", "p_id": "uuid", "p_a": "uuid", "p_b": "uuid",
             "p_location": "integer", "p_ids": "uuid[]", "p_name": "text"}


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def _shop(conn):
    with db.transaction(conn):
        a = catalog.create_product(conn, "Keo A", spec="15kg", unit="thung", category="Keo")
        b = catalog.create_product(conn, "Mang B", spec="3mm", unit="cuon", category="Mang")
        catalog.create_product(conn, "Keo C", spec="15kg", unit="thung", category="Keo")
        cust = catalog.upsert_customer(conn, "Cong ty A", phone="0900 000 001")
        catalog.upsert_customer(conn, "Khach X", phone="0900 000 002")
        catalog.upsert_customer(conn, "Khach Y", phone="0900 000 003")
        stock.insert_document(conn, "delivery", date(2026, 11, 2), [stock.Line(a, 5)], code="7", code_norm="7",
                              customer_id=cust)
        stock.insert_document(conn, "delivery", date(2026, 11, 3), [stock.Line(a, 3)], code="8", code_norm="8",
                              customer_id=cust, location_set=False)
    receipts.save(conn, receipts.ReceiptInput(date(2026, 11, 1), receipts.SUPPLIER, supplier_name="Cua khau",
                                              lines=[receipts.ReceiptLineInput(50, a),
                                                     receipts.ReceiptLineInput(20, b)]))
    return {"a": a, "b": b, "cust": cust}


@pytest.fixture
def cloud_shop(tmp_path):
    pg = Session(WEB_FILES)
    pg.add_account(OWNER)
    conn = db.connect(tmp_path / "shop.sqlite")
    replica.set_enabled(conn, True)
    ids = _shop(conn)
    replica.queue_all(conn)
    cloud = FakeCloud(pg)
    assert twoway.sync_round(conn, cloud, OWNER, "Shop").pushed > 0
    yield pg, conn, cloud, ids
    pg.close()


def _run_page(pg, tmp_path, probe="web_contract_probe.js", extra=""):
    fixture = {t: [r["r"] for r in pg.query(f"select to_jsonb(x) as r from public.{t} x where not deleted")]
               for t in TABLES}
    fixture = {"products": fixture["products"], "customers": fixture["customers"], "suppliers": fixture["suppliers"],
               "documents": fixture["documents"], "lines": fixture["document_lines"],
               "movements": fixture["stock_movements"], "meta": fixture["meta"]}
    site = tmp_path / "site"
    shutil.copytree(ROOT / "webapp", site, ignore=shutil.ignore_patterns("config.js"))
    (site / "config.js").write_text('const DIBEKHO_CLOUD = {url: "https://example.supabase.co", key: "k"};'
                                    "window.__DIBEKHO_TEST__ = true;", encoding="utf-8")
    (site / "fixture.js").write_text("window.__FIXTURE__ = " + json.dumps(fixture) + ";" + extra, encoding="utf-8")
    shutil.copy(ROOT / "tests" / probe, site / "probe.js")
    page = (site / "index.html").read_text(encoding="utf-8")
    page = page.replace("</body>", '<script src="fixture.js"></script><script src="probe.js"></script></body>')
    # the supabase library from the CDN is not needed (sb is stubbed): a tiny local stand-in keeps the test offline
    page = re.sub(r'<script src="https://cdn\.jsdelivr\.net[^>]*></script>', '<script src="sb_stub.js"></script>', page)
    (site / "sb_stub.js").write_text("window.supabase = { createClient: () => ({ auth: {}, from: () => ({}), rpc: () => ({}) }) };",
                                     encoding="utf-8")
    (site / "index.html").write_text(page, encoding="utf-8")

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(site)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        done = subprocess.run(
            [CHROME, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={tmp_path / 'chrome'}",
             "--virtual-time-budget=20000", "--dump-dom", f"http://127.0.0.1:{server.server_port}/"],
            capture_output=True, text=True, encoding="utf-8", timeout=120)
    finally:
        server.shutdown()
    found = re.search(r'data-probe="([^"]*)"', done.stdout)
    assert found, "the page never finished its scenario:\n" + done.stdout[-800:] + done.stderr[-400:]
    out = json.loads(html.unescape(found.group(1)))
    assert out["error"] is None, out["error"]
    return out


def _call(pg, fn, args):
    params, parts = [], []
    for i, (key, value) in enumerate(args.items(), start=1):
        cast = ARG_TYPES[key]
        if cast == "jsonb":
            value = json.dumps(value)
        elif cast == "uuid[]":
            value = "{" + ",".join(value) + "}"
        params.append(value)
        parts.append(f"{key} => ${i}::{cast}")
    return pg.query(f"select public.{fn}({', '.join(parts)}) as r", params, sub=OWNER)[0]["r"]


def _count(conn, sql, *args):
    return conn.execute(sql, args).fetchone()[0]


def test_every_owner_window_writes_what_the_app_then_shows(cloud_shop, tmp_path):
    pg, conn, cloud, ids = cloud_shop
    out = _run_page(pg, tmp_path)

    assert out["checks"]["staff"] == {"transfer": False, "receipt": True, "save": True, "editReceipt": False}
    assert out["checks"]["owner"] == {"transfer": True, "merge": True}
    assert "HV001" in out["checks"]["editTitle"]
    assert out["checks"]["returnFields"] is True
    assert out["checks"]["countMsg"] == "Đã lưu kiểm kê."
    assert out["checks"]["staffStar"] is False
    assert out["checks"]["starSpec"] == "18L/Thung"

    calls = out["calls"]
    assert [c["fn"] for c in calls] == [
        "web_transfer", "web_trial", "web_product_add", "web_product_edit", "web_product_merge", "web_customer_merge",
        "web_cancel", "web_set_location", "web_receipt", "web_receipt", "web_stock_count", "web_receipt"]
    for c in calls:
        _call(pg, c["fn"], c["args"])
    r = twoway.sync_round(conn, cloud, OWNER, "Shop")
    assert all(not m.conflicts for m in r.merged)

    levels = stock.stock_levels(conn, by_location=True)
    # transfer CH001: 12 to the office; trial DT001: 2 out at the office; delivery 8 taken from the office (-3)
    assert _count(conn, "SELECT COUNT(*) FROM documents WHERE kind = 'transfer' AND code = 'CH001'") == 1
    assert _count(conn, "SELECT COUNT(*) FROM documents WHERE kind = 'trial' AND code = 'DT001'") == 1
    assert levels[(ids["a"], stock.OFFICE)] == 12 - 2 - 3

    assert _count(conn, "SELECT COUNT(*) FROM products WHERE name_vi = 'Keo D' AND spec = '25kg' AND unit = 'thung'") == 1
    a = conn.execute("SELECT * FROM products WHERE id = ?", (ids["a"],)).fetchone()
    assert (a["name_vi"], a["stock_note"], a["active"]) == ("Keo A moi", "2 thung mop", 0)
    assert _count(conn, "SELECT COUNT(*) FROM products WHERE name_vi = 'Keo C'") == 0  # merged into SP002
    # its freed code went to the first new product made after the merge (step 12), as in the app
    assert _count(conn, "SELECT COUNT(*) FROM products WHERE code = 'SP003' AND name_vi = 'Son lot'") == 1
    assert _count(conn, "SELECT COUNT(*) FROM products WHERE id = ?", ids["b"]) == 1

    assert _count(conn, "SELECT COUNT(*) FROM customers WHERE name IN ('Khach X', 'Khach Y')") == 0
    assert _count(conn, "SELECT COUNT(*) FROM customers WHERE name = 'Khach XY'") == 1

    assert _count(conn, "SELECT COUNT(*) FROM documents WHERE kind = 'delivery' AND code = '7' AND status = 'cancelled'") == 1
    d8 = conn.execute("SELECT location_id, location_set FROM documents WHERE kind = 'delivery' AND code = '8'").fetchone()
    assert (d8["location_id"], d8["location_set"]) == (2, 1)

    assert [r[0] for r in conn.execute("SELECT status FROM documents WHERE code = 'HV001' ORDER BY id")] == ["replaced", "active"]
    edited = conn.execute("SELECT SUM(l.qty) FROM document_lines l JOIN documents d ON d.id = l.document_id "
                          "WHERE d.code = 'HV001' AND d.status = 'active' AND l.product_id = ?", (ids["a"],)).fetchone()[0]
    assert edited == 60
    back = conn.execute("SELECT customer_id, ref_code, code FROM documents WHERE kind = 'receipt' "
                        "AND receipt_source = 'return'").fetchone()
    assert (back["customer_id"], back["ref_code"], back["code"]) == (ids["cust"], "7", "HV002")

    counted = conn.execute("SELECT l.qty, l.location_id FROM document_lines l JOIN documents d ON d.id = l.document_id "
                           "WHERE d.kind = 'stock_count'").fetchall()
    assert [tuple(r) for r in counted] == [(18, stock.MAIN)]
    assert stock.stock_levels(conn, by_location=True)[(ids["b"], stock.MAIN)] == 18 + 2  # counted, then step 12

    # 12: the new product came with its receipt; the look-alike became the existing Mang B, not a second one
    star = conn.execute("SELECT id FROM documents WHERE kind = 'receipt' AND code = 'HV003'").fetchone()["id"]
    got = conn.execute("SELECT p.name_vi, p.name_zh, p.spec, p.category, l.qty FROM document_lines l "
                       "JOIN products p ON p.id = l.product_id WHERE l.document_id = ? ORDER BY l.line_no",
                       (star,)).fetchall()
    assert [tuple(r) for r in got] == [("Son lot", "底漆", "18L/Thung", "Son", 10), ("Mang B", "", "3mm", "Mang", 2)]
    assert _count(conn, "SELECT COUNT(*) FROM products WHERE name_vi = 'Mang B'") == 1

    # 13: Cài đặt → Tài khoản: the owner has the tab, staff do not; bad input never leaves the page; the buttons send
    # what the Edge Function (create, reset) and SQL 011 (role, revoke) take, and not one call touches oneself
    checks = out["checks"]
    assert checks["accountsTabStaff"] is False and checks["accountsTabOtherOwner"] is False and checks["accountsTabOwner"] is True and checks["accountRows"] == 3
    assert "chưa giống nhau" in checks["pwMismatch"] and "ít nhất 8" in checks["pwShort"] and "@dibekho.local" in checks["userAt"]
    assert checks["pwAfterCreate"] == "" and checks["ownerCreateAsked"] == 1
    lan = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    acc = out["accountCalls"]
    assert [c["body"] for c in acc if "fn" in c] == [
        {"action": "create", "username": "quan.ly2", "password": "MatKhau-12345", "role": "viewer", "display_name": "Chi Hoa"},
        {"action": "create", "username": "chu2", "password": "MatKhau-12345", "role": "desktop", "display_name": ""},
        {"action": "reset_password", "user_id": lan, "password": "Moi-MatKhau-9"}]
    assert all(c["fn"] == "accounts" for c in acc if "fn" in c)
    assert [(c["rpc"], c["args"]) for c in acc if c.get("rpc") not in (None, "web_accounts_list")] == [
        ("web_account_set_role", {"p_user": lan, "p_role": "viewer", "p_name": "Lan"}),
        ("web_account_revoke", {"p_user": lan})]
    assert sum(1 for c in acc if c.get("rpc") == "web_accounts_list") >= 4  # the list reloads after every change


def test_staff_requests_from_the_web_are_read_by_the_apps_approval(cloud_shop, tmp_path):
    pg, conn, cloud, ids = cloud_shop
    out = _run_page(pg, tmp_path)
    receipt, count = out["requests"]
    assert (receipt["kind"], count["kind"]) == ("receipt", "stock_count")
    data, errors = inbox.receipt_input(conn, receipt["payload"])
    assert errors == []
    assert [(ln.product_id, ln.qty) for ln in data.lines] == [(ids["b"], 4.5)]
    # sent now: the page dates the count today (a fixed date here turned red the next day)
    item = {"payload": count["payload"], "created_at": datetime.now(timezone.utc).isoformat()}
    day, place, lines, errors = inbox.check_count(conn, item)
    assert errors == [] and place == stock.OFFICE and lines == [(ids["a"], 3)]
