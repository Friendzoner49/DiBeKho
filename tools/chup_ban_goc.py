"""Chụp mọi màn và hộp thoại của bản Python vào anh-ban-goc/ (ảnh mẫu để so bản Swift).

Dùng đúng code giao diện của bản Python (kiểu Fusion như app thật) trên một cửa hàng bịa ra
(scripts/readme_screenshots.py), không bao giờ mở dữ liệu thật hay config.json thật.

    uv --project K:/HeThongSonDiBe run python -X utf8 tools/chup_ban_goc.py K:/HeThongSonDiBe

Sau mỗi lần bản Python đổi giao diện thì chạy lại và commit ảnh mới.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

here = Path(__file__).resolve().parent
out = here.parent / "anh-ban-goc"
python_repo = Path(sys.argv[1] if len(sys.argv) > 1 else "K:/HeThongSonDiBe").resolve()

src = (python_repo / "scripts" / "readme_screenshots.py").read_text(encoding="utf-8")
lang = 'LANG = sys.argv[1] if len(sys.argv) > 1 else None'
folder = 'out, tmp = Path({"en": "docs/images/en", "zh": "docs/images/zh"}.get(LANG, "docs/images")), Path(tempfile.mkdtemp())'
if lang not in src or folder not in src or src.count('print("ok")') != 1:
    sys.exit("scripts/readme_screenshots.py của bản Python đã đổi: sửa lại tools/chup_ban_goc.py cho khớp.")
src = src.replace(lang, 'LANG = "vi"')
src = src.replace(folder, f'out, tmp = Path({out.as_posix()!r}), Path(tempfile.mkdtemp())')
src = src.replace('print("ok")', f"DIBEKHOMAC = {here.parent.as_posix()!r}\n"
                  + (here / "chup_ban_goc_them.py").read_text(encoding="utf-8"))

out.mkdir(exist_ok=True)
for old in out.glob("*.png"):
    old.unlink()
with tempfile.TemporaryDirectory() as tmp:
    script = Path(tmp) / "chup.py"
    script.write_text(src, encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=".")
    result = subprocess.run([sys.executable, "-X", "utf8", str(script)], cwd=python_repo, env=env,
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
print(result.stdout[-3000:])
if result.returncode != 0:
    print(result.stderr[-3000:])
    sys.exit(result.returncode)

# the README script's own shots: keep those with a different state, drop the ones taken again above
for name, new in (("tra-cuu", "03b-tra-cuu-tim-khach"), ("kiem-ke", "05b-kiem-ke-dang-go-so"),
                  ("hang-ve", "16d-nhap-hang-ve-co-hang"), ("chuyen-hang", "13b-chuyen-hang-dang-go"),
                  ("can-xu-ly", "02b-can-xu-ly-co-viec")):
    if (out / f"{name}.png").exists():
        (out / f"{name}.png").replace(out / f"{new}.png")
for name in ("ton-kho", "thong-ke", "chi-tiet-don", "chi-tiet-khach"):
    (out / f"{name}.png").unlink(missing_ok=True)
print(len(list(out.glob("*.png"))), "ảnh trong", out)
