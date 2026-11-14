"""The web page in Tiếng Việt and 中文 (14/11/2026): both languages have the same keys, every key the page uses exists,
and no Vietnamese text is left hard-coded outside webapp/i18n.js (the file template xlsx.js is bilingual on purpose)."""

import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "webapp"
NODE = shutil.which("node")
# letters only Vietnamese uses (a Chinese or English text never has them)
VIET = re.compile("[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹáàãéèíìóòõúùýĂÂĐÊÔƠƯ]")
SCRIPTS = sorted(p for p in WEB.glob("*.js") if p.name not in ("config.js", "config.example.js"))
# keys built from data (kind of a document, its status...): every value the data can hold
DYNAMIC = {
    "kind": ["delivery", "receipt", "stock_count", "transfer", "trial"],
    "status": ["cancelled", "replaced", "active_long", "cancelled_long", "replaced_long"],
    "place": ["1", "2"],
    "move": ["delivery_out", "delivery_reverse", "receipt_in", "receipt_reverse", "count_adjust", "count_reverse",
             "transfer_out", "transfer_in", "transfer_reverse", "trial_out", "trial_reverse"],
    "role": [f"{w}_{r}" for w in ("short", "long", "acc") for r in ("desktop", "editor", "viewer", "none")],
    "dash": ["p_month", "p_last_month", "p_quarter", "p_year"],
    "doclist": ["transfer", "trial", "stock_count"],
}


@pytest.fixture(scope="module")
def text():
    if NODE is None:
        pytest.skip("Node is not installed")
    done = subprocess.run([NODE, "-e", f"process.stdout.write(JSON.stringify(require({json.dumps(str(WEB / 'i18n.js'))}).WEB_TEXT))"],
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _without_comments(js: str) -> str:
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in js.splitlines())


def test_both_languages_have_the_same_keys(text):
    assert set(text["vi"]) == set(text["zh"])
    for key, vi in text["vi"].items():
        assert set(re.findall(r"\{(\w+)\}", vi)) == set(re.findall(r"\{(\w+)\}", text["zh"][key])), key
        assert not VIET.search(text["zh"][key]) or key in ("place.1", "place.2"), (key, text["zh"][key])


def test_every_key_the_page_uses_exists(text):
    used = set()
    for path in SCRIPTS:
        used |= set(re.findall(r"""\btr\(\s*["']([\w.]+)["']""", path.read_text(encoding="utf-8")))
    page = (WEB / "index.html").read_text(encoding="utf-8")
    used |= set(re.findall(r'data-i18n(?:-ph|-title)?="([\w.]+)"', page))
    for prefix, values in DYNAMIC.items():
        used |= {f"{prefix}.{v}" for v in values}
    missing = sorted(used - set(text["vi"]))
    assert not missing, missing
    # a key also counts as used when the code names it in a string ("a.b" chosen by a condition, a table of keys)
    named = set()
    for path in SCRIPTS:
        if path.name != "i18n.js":
            named |= set(re.findall(r"""["'`]([a-z]+\.[\w]+)["'`]""", path.read_text(encoding="utf-8")))
    unused = sorted(k for k in set(text["vi"]) - used - named if not any(k.startswith(p + ".") for p in DYNAMIC))
    assert not unused, unused


def test_no_vietnamese_left_in_the_scripts():
    found = []
    for path in SCRIPTS:
        if path.name in ("i18n.js", "xlsx.js"):
            continue
        for n, line in enumerate(_without_comments(path.read_text(encoding="utf-8")).splitlines(), 1):
            if VIET.search(line):
                found.append(f"{path.name}:{n}: {line.strip()[:90]}")
    assert not found, "\n".join(found)


def test_no_vietnamese_left_in_the_page():
    class Texts(HTMLParser):
        def __init__(self):
            super().__init__()
            self.found = []
            self.skip = 0

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style"):
                self.skip += 1
            for name, value in attrs:
                if name in ("placeholder", "title", "aria-label", "alt") and value and VIET.search(value):
                    self.found.append(f"{tag} {name}={value}")

        def handle_endtag(self, tag):
            if tag in ("script", "style"):
                self.skip -= 1

        def handle_data(self, data):
            if not self.skip and VIET.search(data):
                self.found.append(data.strip())

    p = Texts()
    p.feed((WEB / "index.html").read_text(encoding="utf-8"))
    assert not p.found, p.found
