"""Every file hash written in the scan golden must belong to a file in ScanNotes/.

gen_scan.py rewrites the made-up notes (their bytes change on every run) and the golden holds their SHA-256: a
golden committed without its notes (or notes reverted after a regeneration) fails on CI. Run before a push:
    python -X utf8 tools/check_golden_notes.py
"""
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
golden = (ROOT / "Tests/DiBeKhoCoreTests/Generated/GoldenScan.swift").read_text(encoding="utf-8")
have = {hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT / "Tests/DiBeKhoCoreTests/ScanNotes").iterdir() if p.is_file()}
missing = sorted({m.group(2) for m in re.finditer(r"hash=([0-9a-f]{64})\|rel_path=([^|]*)", golden) if m.group(1) not in have})
if missing:
    print("The golden has hashes of notes that are not in ScanNotes/ (regenerate with tools/gen_scan.py and commit the notes too):")
    print("\n".join("  " + m for m in missing))
    sys.exit(1)
print("check_golden_notes: the scan golden matches the notes")
