"""Customers always import packages exported by an OLDER version, so a released migration must never change
(a package of that schema is upgraded by these exact files). New schema = a new 0NN file, then add it here."""

import hashlib
from pathlib import Path

import dibekho.db as dbpkg

FROZEN = {
    "001_init.sql": "44b053803e43785d",
    "002_product_variant.sql": "fd3be0573ee37dd1",
    "003_ignored_lines.sql": "da48dc185a9bad45",
    "004_reread.sql": "871307befcb32293",
    "005_hidden_inputs.sql": "23377646781d1115",
    "006_receipt_source.sql": "397ff25396b179a1",
    "007_prices.sql": "63b810bdba6e3940",
    "008_locations.sql": "35075389d1804f68",
    "009_trial_use.sql": "5b76d3b8d7c916ed",
}


def test_released_migrations_are_unchanged():
    folder = Path(dbpkg.__file__).parent / "migrations"
    got = {f.name: hashlib.sha256(f.read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:16]
           for f in folder.glob("*.sql")}
    assert got == FROZEN
