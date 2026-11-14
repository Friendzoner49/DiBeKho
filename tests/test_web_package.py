""".dibekho packages made by the web page (webapp/package.js), run here in Node with the very same code and libraries
(tests/web_package_cli.js). A web package must open in the app exactly like the app's own, and the schema the web
builds from must be the app's. Importing a package is done in the app only (the web only looks, 14/11/2026).
Skipped without Node or PGlite."""

import json
import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest

from dibekho import db
from dibekho.core import catalog, deliveries, receipts, stock, transfer
from dibekho.core.cloud import twoway
from dibekho.core.workspace import Workspace
from tests.conftest import make_note
from tests.pgdb import WEB_FILES, FakeCloud, Session, needs_pg

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
OWNER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
LINE = ("背水涂\nvữa chống thấm", "10KG/thùng", 3, "")


def test_the_schema_the_web_builds_from_is_the_apps():
    import importlib.util

    spec = importlib.util.spec_from_file_location("make_web_schema", ROOT / "scripts" / "make_web_schema.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    current = (ROOT / "webapp" / "schema.js").read_text(encoding="utf-8")
    assert current == module.build(), "webapp/schema.js is out of date: run scripts/make_web_schema.py"




def _node(*args):
    done = subprocess.run([NODE, str(ROOT / "tests" / "web_package_cli.js"), *map(str, args)],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert done.returncode == 0, done.stderr
    return done.stdout


def _shop(conn, ws):
    """A shop with a bit of everything: a delivery read from a note (customer, alias, prices), goods-in from a supplier
    then edited (replaced + active, same code), a transfer, a count at one place, the shared settings."""
    with db.transaction(conn):
        a = catalog.create_product(conn, "Keo A", spec="15kg", unit="thùng", category="Keo")
        b = catalog.create_product(conn, "Màng B", spec="3mm", unit="cuộn", category="Màng")
        db.set_meta(conn, "low_stock_default", "12")
    make_note(ws.deliveries / "d1.xlsx", code="76", lines=[LINE])
    deliveries.scan(conn, ws)
    for line in deliveries.unknown_lines(conn, ws):
        deliveries.create_product_for_line(conn, line)
    deliveries.scan(conn, ws)
    first = receipts.save(conn, receipts.ReceiptInput(date(2026, 11, 1), receipts.SUPPLIER, supplier_name="Cửa khẩu",
                                                      lines=[receipts.ReceiptLineInput(50, a)]))
    receipts.save(conn, receipts.ReceiptInput(date(2026, 11, 1), receipts.SUPPLIER, supplier_name="Cửa khẩu",
                                              lines=[receipts.ReceiptLineInput(60, a), receipts.ReceiptLineInput(5, b)]),
                  replaces=first)
    with db.transaction(conn):
        stock.transfer(conn, date(2026, 11, 2), stock.MAIN, stock.OFFICE, [stock.Line(a, 7)])
        stock.stock_count(conn, date(2026, 11, 3), {(b, stock.MAIN): 4})
    return a, b


def _picture(conn):
    q = lambda sql: [tuple(r) for r in conn.execute(sql)]  # noqa: E731
    return {
        "products": q("SELECT code, name_vi, spec, unit, category, active FROM products ORDER BY code"),
        # the cloud keeps no local ids: documents made in the same second may come in another order (by content here;
        # what must keep its order -- a replaced receipt before its replacement -- is checked on its own)
        "documents": sorted(q("SELECT kind, code, status, doc_date, location_id FROM documents")),
        "lines": sorted(q("SELECT d.code, d.status, p.code, l.qty, l.unit_price FROM document_lines l "
                          "JOIN documents d ON d.id = l.document_id JOIN products p ON p.id = l.product_id")),
        "replaced_first": q("SELECT status FROM documents WHERE code = 'HV001' ORDER BY id"),
        "stock": sorted(stock.stock_levels(conn, by_location=True).items()),
        "customers": q("SELECT name, phone FROM customers ORDER BY name"),
        "suppliers": q("SELECT name FROM suppliers ORDER BY name"),
        "aliases": q("SELECT a.key, p.code FROM product_aliases a JOIN products p ON p.id = a.product_id ORDER BY a.key"),
        "meta": q("SELECT key, value FROM meta WHERE key IN ('low_stock_default', 'freed_codes', 'product_code_max') "
                  "ORDER BY key"),
    }


@pytest.fixture
def cloud_shop(tmp_path):
    if NODE is None:
        pytest.skip("Node is not installed")
    pg = Session(WEB_FILES)
    pg.add_account(OWNER)
    cloud = FakeCloud(pg)
    ws = Workspace(tmp_path / "a")
    ws.ensure()
    conn = db.connect(ws.db_path)
    _shop(conn, ws)
    twoway.start_from_this_machine(conn)
    twoway.sync_round(conn, cloud, OWNER, "A")
    yield pg, cloud, conn, ws, tmp_path
    conn.close()
    pg.close()


def _pulled(cloud, tmp_path, name="pulled.json"):
    pulled = cloud.rpc("sync_pull", {"p_after": 0}, OWNER)
    path = tmp_path / name
    path.write_text(json.dumps(pulled, ensure_ascii=False), encoding="utf-8")
    return pulled, path


@needs_pg
def test_a_web_package_opens_in_the_app_with_the_same_data(cloud_shop):
    pg, cloud, conn, ws, tmp = cloud_shop
    _, pulled_path = _pulled(cloud, tmp)
    package = tmp / "web.dibekho"
    name = _node("export", pulled_path, package)
    assert name == "DiBeKho_Web_2026-11-13_0930.dibekho"

    manifest = transfer.read_manifest(package)
    assert (manifest.device_name, manifest.schema_version) == ("Web", db.schema_version())
    other = Workspace(tmp / "b")
    other.ensure()
    transfer.import_package(other, package)
    copy = db.connect(other.db_path)
    assert _picture(copy) == _picture(conn)
    # the uuids travel: importing it into a shared-mode app keeps every row's identity
    for table in ("products", "documents", "stock_movements"):
        mine = {r[0] for r in conn.execute("SELECT uid FROM sync_map WHERE tbl = ?", (table,))}
        theirs = {r[0] for r in copy.execute("SELECT uid FROM sync_map WHERE tbl = ?", (table,))}
        assert mine == theirs, table
    copy.close()


@needs_pg
def test_reading_the_same_notes_after_a_web_package_adds_nothing(cloud_shop):
    """A web package has no scan records: the notes in the folder must be recognised by their content."""
    pg, cloud, conn, ws, tmp = cloud_shop
    _, pulled_path = _pulled(cloud, tmp)
    package = tmp / "web.dibekho"
    _node("export", pulled_path, package)
    other = Workspace(tmp / "d")
    other.ensure()
    shutil.copytree(ws.deliveries, other.deliveries, dirs_exist_ok=True)
    transfer.import_package(other, package)
    copy = db.connect(other.db_path)
    before = copy.execute("SELECT COUNT(*) FROM documents WHERE kind = 'delivery'").fetchone()[0]
    deliveries.scan(copy, other)
    assert copy.execute("SELECT COUNT(*) FROM documents WHERE kind = 'delivery'").fetchone()[0] == before == 1
    copy.close()


@needs_pg
def test_the_button_on_the_real_page_exports_under_its_security_policy(cloud_shop):
    """Headless Chrome, the page's own CSP (WebAssembly needs 'wasm-unsafe-eval', the .wasm file 'self'): Xuất dữ liệu
    gives a package the app opens with the same data. Importing a package is done in the app only (14/11/2026)."""
    import base64

    from tests import test_web_contract as contract

    if contract.CHROME is None:
        pytest.skip("Chrome is not installed")
    pg, cloud, conn, ws, tmp = cloud_shop
    pulled, _ = _pulled(cloud, tmp)
    out = contract._run_page(pg, tmp, probe="web_package_probe.js",
                             extra="window.__PULLED__ = " + json.dumps(pulled, ensure_ascii=False) + ";")
    assert out["alerts"] == [], out["alerts"]
    (exported,) = out["saved"]
    assert exported["name"].startswith("DiBeKho_Web_")
    package = tmp / exported["name"]
    package.write_bytes(base64.b64decode(exported["b64"]))
    other = Workspace(tmp / "e")
    other.ensure()
    transfer.import_package(other, package)
    copy = db.connect(other.db_path)
    assert _picture(copy) == _picture(conn)
    copy.close()
    assert out["pushes"] == [] and "DiBeKho_Web_" in out["msg"]
