"""Quick check for the Swift mistakes that broke CI before (Windows has no Swift compiler).

Run before every push:  python -X utf8 tools/swift_lint.py
It is a heuristic, not a compiler: a clean run does not replace CI, it only catches the repeat offenders.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
problems = []


def flag(path, no, why):
    problems.append(f"{path.relative_to(ROOT)}:{no}: {why}")


for path in sorted((ROOT / "Sources").rglob("*.swift")) + sorted((ROOT / "Tests").glob("*/*.swift")):
    if "Generated" in path.parts:
        continue
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        code = line.split("//")[0]
        # 1. 'try' to the right of ?: or ?? ("try cannot appear to the right of a non-assignment operator")
        if re.search(r"(\?\?|&&|\|\||==|\s\+\s)\s*try\s", code):
            flag(path, i + 1, "`try` right of a binary operator: put `try` at the start of the expression")
        # 2. a View function with several statements and no @ViewBuilder / return
        m = re.match(r"\s*(private |fileprivate |static )*func \w+\(.*\) -> some View \{\s*$", code)
        if m:
            indent = len(line) - len(line.lstrip())
            prev = lines[i - 1].strip() if i else ""
            body = []
            for j in range(i + 1, len(lines)):
                cur = lines[j]
                if cur.strip() == "}" and len(cur) - len(cur.lstrip()) == indent:
                    break
                body.append(cur)
            top = [b for b in body if b.strip() and len(b) - len(b.lstrip()) == indent + 4]
            starts_decl = any(re.match(r"\s*(let|var|guard|if|switch|for)\b", b) for b in top)
            has_return = any(re.match(r"\s*return\b", b) for b in top)
            views = [b for b in top if re.match(r"\s*[A-Z]\w*[({]", b)]
            if (starts_decl or len(views) > 1) and not has_return and "@ViewBuilder" not in prev:
                flag(path, i + 1, "`some View` function with statements and no `return`: add @ViewBuilder (or return)")
    # 3. UI.* used in a type that is not @MainActor
    text = "\n".join(lines)
    for m in re.finditer(r"^(?:@MainActor\s*\n)?(?:public |private )?(enum|struct|final class|class) (\w+)[^{\n]*\{", text, re.M):
        header = m.group(0)
        if "@MainActor" in header or "View" in header or "App" in header:
            continue
        start = m.end()
        nxt = re.search(r"^(?:@MainActor\s*\n)?(?:public |private )?(enum|struct|final class|class) \w+", text[start:], re.M)
        block = text[start:start + (nxt.start() if nxt else len(text))]
        if re.search(r"\bUI\.(ask|info|error|open)\(", block) and "@MainActor" not in block:
            line_no = text[: m.start()].count("\n") + 1
            if not text[max(0, m.start() - 15): m.start()].strip().endswith("@MainActor"):
                flag(path, line_no, f"{m.group(2)} calls UI.* but is not @MainActor")

print("\n".join(problems) if problems else "swift_lint: nothing suspicious")
sys.exit(1 if problems else 0)
