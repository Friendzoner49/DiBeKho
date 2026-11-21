"""Compare the Swift reader with the Python one on the customer's OWN notes, on the developer's machines only.

On the Windows PC:
    uv --project K:/HeThongSonDiBe run python -X utf8 tools/gen_real_notes.py K:/HeThongSonDiBe <folder of .xlsx notes> <out folder>
copies the notes to <out folder> with expected.json (what the Python reader reads in each). Never put that folder in
git (it holds customer data): carry it to the Mac (USB), then in this repo there:
    DIBEKHO_REAL_NOTES=<out folder> swift test --filter NotesTests
The test prints only file names and line numbers of a difference, never the notes' content.
"""

import json
import shutil
import sys
from pathlib import Path

SRC = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(SRC / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from note_lines import note_lines  # noqa: E402

source, out = Path(sys.argv[2]), Path(sys.argv[3])
out.mkdir(parents=True, exist_ok=True)
expected = {}
for i, path in enumerate(sorted(p for p in source.rglob("*.xlsx") if not p.name.startswith("~$"))):
    name = f"note-{i + 1:04d}.xlsx"  # neutral names: the customers' file names stay out of any log
    shutil.copy2(path, out / name)
    expected[name] = note_lines(out / name)
(out / "expected.json").write_text(json.dumps(expected, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"{len(expected)} notes copied to {out} with expected.json")
