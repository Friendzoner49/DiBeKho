"""The web's look-alike check (webapp/dupes.js, run under node) must name the same products as the app's
catalog.find_possible_duplicates, so "★ Mặt hàng mới" and "Thêm mặt hàng" on the web ask exactly when the app
would. Also checks the port of Python's difflib ratio on its own, on many random strings."""

import difflib
import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from dibekho import db
from dibekho.core import catalog

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

RUNNER = """
const fs = require("fs");
const D = require(process.argv[2]);
const input = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
process.stdout.write(JSON.stringify({
  dupes: input.cases.map((c) => D.findPossibleDuplicates(input.products, ...c).map((p) => p.code)),
  ratios: input.pairs.map(([a, b]) => D.ratio(a, b)),
  scores: input.scores.map(([n, sp, code]) => D.matchScore(n, sp, input.products.find((p) => p.code === code))),
}));
"""

CATALOG = [  # name_vi, name_zh, spec, variant, category
    ("Sơn chống thấm FS-101", "防水涂料", "20KG/Thùng", "Xám nhạt", "Sơn"),
    ("Sơn chống thấm FS-101", "防水涂料", "10KG/Thùng", "Xám nhạt", "Sơn"),
    ("Sơn chống thấm FS-102", "防水涂料", "20KG/Thùng", "Trắng", "Sơn"),
    ("Màng SBS", "SBS防水卷材", "3mm 1m*10m", "", "Màng"),
    ("Màng SBS", "SBS防水卷材", "4mm 1m*10m", "", "Màng"),
    ("Màng PPE", "涤纶PPE", "1m*100m", "Nguyên sinh", "Màng"),
    ("Màng PPE", "涤纶PPE", "1m*100m", "Tái chế", "Màng"),
    ("Vải polyester", "聚酯布", "1m*50m", "", "Vải"),
    ("Keo dán", "胶水", "18,5kg", "", "Keo"),
    ("Keo dán", "胶水", "5kg", "", "Keo"),
    ("Bột trét", "", "40kg/bao", "", "Bột"),
    ("Ống bọc 32-50", "管根套", "32-50", "", "Phụ kiện"),
    ("Ống bọc 50-75", "管根套", "50-75", "", "Phụ kiện"),
    ("Đồ cũ", "旧货", "", "", "Cũ"),
]

CASES = [  # what someone types for a brand-new product: name_vi, name_zh, spec, variant[, category]
    ["Sơn chống thấm FS-101", "", "20KG/Thùng", "Xám nhạt"],
    ["son chong tham fs101", "", "20kg", ""],
    ["Sơn FS 101", "防水涂料", "20 kg", ""],
    ["Sơn", "防水涂料", "10KG", "Xám nhạt"],
    ["Sơn mới", "防水涂料", "5KG", ""],
    ["Màng SBS", "SBS防水卷材", "3mm", ""],
    ["Màng chống thấm", "防水卷材", "", ""],
    ["Màng PPE", "涤纶PPE", "1m*100m", "Tái chế"],
    ["Vải", "聚酯布", "1m*50m", ""],
    ["Keo", "胶水", "18.5KG", ""],
    ["Keo dán", "", "", ""],
    ["Bột trét tường", "", "40kg", ""],
    ["Ống bọc", "管根套", "32-50", ""],
    ["Ống bọc", "管根套", "", ""],
    ["Đồ cũ", "旧货", "", ""],
    ["Hàng hoàn toàn khác", "完全不同", "1L", ""],
    ["Sơn chống thấm FS-102", "防水涂料", "20KG/Thùng", "Trắng", "Keo"],
    ["Keo dán", "胶水", "5kg", "", "Keo"],
]


def _js(payload) -> dict:
    tmp = ROOT / "tests" / "_dupes_input.json"
    script = ROOT / "tests" / "_dupes_runner.js"
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    script.write_text(RUNNER, encoding="utf-8")
    try:
        done = subprocess.run([NODE, str(script), str(ROOT / "webapp" / "dupes.js"), str(tmp)], capture_output=True,
                              text=True, encoding="utf-8", timeout=120)
        assert done.returncode == 0, done.stderr[-2000:]
        return json.loads(done.stdout)
    finally:
        tmp.unlink(missing_ok=True)
        script.unlink(missing_ok=True)


def _random_pairs(n=400):
    rnd = random.Random(7)
    alphabet = "aaabcdeeghikmnnoostu  -0123456789xđ防水涂料胶"
    word = lambda: "".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 40)))  # noqa: E731
    pairs = [[word(), word()] for _ in range(n)]
    pairs.append(["a" * 120 + "b" * 30, "ab" * 130])  # long enough for difflib's autojunk
    pairs.append(["", ""])
    return pairs


def test_the_web_names_the_same_look_alikes_as_the_app(tmp_path):
    conn = db.connect(tmp_path / "k.sqlite")
    with db.transaction(conn):
        for name_vi, name_zh, spec, variant, category in CATALOG:
            catalog.create_product(conn, name_vi, name_zh, spec, variant=variant, category=category)
        conn.execute("UPDATE products SET active = 0 WHERE name_vi = 'Đồ cũ'")  # stopped: still an exact match
    products = [dict(r) for r in conn.execute("SELECT * FROM products")]
    want = [[p["code"] for p in catalog.find_possible_duplicates(conn, *c)] for c in CASES]
    pairs = _random_pairs()
    scores = [[f"{c[1]} {c[0]}", c[2], p["code"]] for c in CASES for p in products]
    got = _js({"products": products, "cases": CASES, "pairs": pairs, "scores": scores})
    assert any(want) and not all(want)  # the cases do tell look-alikes from new products
    for case, w, g in zip(CASES, want, got["dupes"]):
        assert g == w, case
    for (a, b), r in zip(pairs, got["ratios"]):
        assert r == pytest.approx(difflib.SequenceMatcher(None, a, b).ratio(), abs=1e-12), (a, b)
    by_code = {p["code"]: p for p in conn.execute("SELECT * FROM products")}
    for (n, sp, code), sc in zip(scores, got["scores"]):
        assert sc == pytest.approx(catalog.match_score(n, sp, by_code[code]), abs=1e-12), (n, sp, code)
