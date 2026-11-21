"""CI: the .xlsx files the Swift tests wrote must hold what the Python app's files hold (cells, fonts, borders, merges,
widths, heights, print setup), read by openpyxl.

    python3 tools/check_xlsx.py Tests/DiBeKhoCoreTests/XlsxRef <folder the tests wrote to>

Every <name>.json of the reference folder must have a <name>.xlsx in the other. Needs openpyxl (pip install openpyxl).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from xlsx_dump import compare, dump  # noqa: E402

refs, made = Path(sys.argv[1]), Path(sys.argv[2])
problems = 0
names = sorted(p.stem for p in refs.glob("*.json"))
if not names:
    sys.exit("no reference files in " + str(refs))
for name in names:
    target = made / f"{name}.xlsx"
    if not target.exists():
        print(f"MISSING {name}.xlsx")
        problems += 1
        continue
    expected = json.loads((refs / f"{name}.json").read_text(encoding="utf-8"))
    diffs = compare(expected, dump(target))
    if diffs:
        problems += len(diffs)
        print(f"DIFFERENT {name}.xlsx")
        for d in diffs[:25]:
            print("   ", d)
    else:
        print(f"ok {name}.xlsx ({len(expected['cells'])} cells)")
sys.exit(1 if problems else 0)
