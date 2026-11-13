/* DiBeKho "is this new product already in the catalog?" for the web: the app's catalog.find_possible_duplicates
   (an exact name + packing + type match, then the fuzzy matcher at score >= 0.5, minus candidates whose packing,
   type or category clearly differ), with Python's difflib ratio ported as it is. Pure functions, no DOM:
   tests/test_web_dupes.py runs this file under node against the Python module, so the web asks about the same
   look-alikes the app does.

   products = the products rows (code, name_vi, name_zh, spec, variant, category, active), deleted ones left out. */

(function (root) {
  "use strict";

  const s = (v) => (v === null || v === undefined ? "" : String(v));
  /** core.text.clean: NFC, whitespace collapsed, trimmed. */
  const clean = (v) => s(v).normalize("NFC").replace(/\s+/g, " ").trim();
  /** core.text.unaccent: casefold, NFKD, combining marks dropped, đ -> d. */
  const unaccent = (v) => s(v).toLowerCase().normalize("NFKD").replace(/\p{Mn}/gu, "").replaceAll("đ", "d");

  const CJK = /[㐀-䶿一-鿿]/gu;
  // Python's \b and \d are Unicode-aware (a Chinese character is a word character): the same, spelled out
  const MODEL = /(?<![\p{L}\p{N}_])([A-Z]{2,4})\s*-?\s*(\p{Nd}{2,4})(?![\p{L}\p{N}_])/gu;
  const KG = /(\p{Nd}+(?:[.,]\p{Nd}+)?)\s*kg/giu;
  const DIM = /(\p{Nd}+(?:[.,]\p{Nd}+)?c?m)\s*\*\s*(\p{Nd}+(?:[.,]\p{Nd}+)?m)/giu;

  const rstrip = (t, ch) => { let i = t.length; while (i > 0 && t[i - 1] === ch) i--; return t.slice(0, i); };

  function features(text) {
    const up = text.toUpperCase();
    return {
      cjk: new Set(text.match(CJK) || []),
      models: new Set([...up.matchAll(MODEL)].map((m) => m[1] + m[2])),
      kg: new Set([...text.matchAll(KG)].map((m) => rstrip(rstrip(m[1].replaceAll(",", "."), "0"), "."))),
      dims: new Set([...text.matchAll(DIM)].map((m) => `${m[1]}*${m[2]}`.toLowerCase())),
    };
  }

  const common = (a, b) => [...a].filter((x) => b.has(x)).length;

  /* ---- difflib.SequenceMatcher(None, a, b).ratio(), on code points like Python's str */

  function ratio(a, b) {
    a = Array.from(a); b = Array.from(b);
    const b2j = new Map();
    b.forEach((ch, i) => { if (!b2j.has(ch)) b2j.set(ch, []); b2j.get(ch).push(i); });
    if (b.length >= 200) {  // autojunk
      const ntest = Math.floor(b.length / 100) + 1;
      for (const [ch, idx] of [...b2j]) if (idx.length > ntest) b2j.delete(ch);
    }
    const longest = (alo, ahi, blo, bhi) => {
      let besti = alo, bestj = blo, bestsize = 0, j2len = new Map();
      for (let i = alo; i < ahi; i++) {
        const newj2len = new Map();
        for (const j of b2j.get(a[i]) || []) {
          if (j < blo) continue;
          if (j >= bhi) break;
          const k = (j2len.get(j - 1) || 0) + 1;
          newj2len.set(j, k);
          if (k > bestsize) { besti = i - k + 1; bestj = j - k + 1; bestsize = k; }
        }
        j2len = newj2len;
      }
      // isjunk is None, so nothing is junk (popular elements are only left out of b2j): extend over equal ones
      while (besti > alo && bestj > blo && a[besti - 1] === b[bestj - 1]) { besti--; bestj--; bestsize++; }
      while (besti + bestsize < ahi && bestj + bestsize < bhi && a[besti + bestsize] === b[bestj + bestsize]) bestsize++;
      return [besti, bestj, bestsize];
    };
    let matches = 0;
    const queue = [[0, a.length, 0, b.length]];
    while (queue.length) {
      const [alo, ahi, blo, bhi] = queue.pop();
      const [i, j, k] = longest(alo, ahi, blo, bhi);
      if (k) {
        matches += k;
        if (alo < i && blo < j) queue.push([alo, i, blo, j]);
        if (i + k < ahi && j + k < bhi) queue.push([i + k, ahi, j + k, bhi]);
      }
    }
    const total = a.length + b.length;
    return total ? (2 * matches) / total : 1;
  }

  /* ---- catalog.match_score / _ranked / _spec_conflicts / find_same / find_possible_duplicates */

  function matchScore(noteText, noteSpec, p) {
    const a = features(`${noteText} ${noteSpec}`);
    const b = features(`${s(p.name_zh)} ${s(p.name_vi)} ${s(p.spec)}`);
    let score = 0;
    if (a.cjk.size && b.cjk.size) {
      const overlap = common(a.cjk, b.cjk) / a.cjk.size;
      if (overlap < 0.5) return 0.3 * overlap;
      score += 0.6 * overlap;
    }
    score += 0.2 * ratio(unaccent(noteText), unaccent(`${s(p.name_vi)} ${s(p.name_zh)}`));
    if (a.models.size && b.models.size) score += common(a.models, b.models) ? 0.3 : -0.6;
    if (a.kg.size && b.kg.size) score = common(a.kg, b.kg) ? score + 0.2 : score * 0.4;
    if (a.dims.size && b.dims.size) score += common(a.dims, b.dims) ? 0.15 : -0.15;
    return score;
  }

  // catalog.products(): active ones, ORDER BY category, name_vi, spec, variant (SQLite compares code points)
  const cmp = (x, y) => (x < y ? -1 : x > y ? 1 : 0);
  const activeSorted = (products) => products.filter((p) => p.active)
    .sort((x, y) => cmp(s(x.category), s(y.category)) || cmp(s(x.name_vi), s(y.name_vi)) ||
                    cmp(s(x.spec), s(y.spec)) || cmp(s(x.variant), s(y.variant)));

  function ranked(products, name, spec) {
    const note = features(`${name} ${spec}`).cjk;
    let candidates = activeSorted(products);
    if (note.size) {
      const overlap = new Map(candidates.map((p) => [p, common(note, features(s(p.name_zh)).cjk) / note.size]));
      const top = Math.max(0, ...overlap.values());
      if (top === 0) return [];
      candidates = candidates.filter((p) => overlap.get(p) >= top - 1e-9);
    }
    return candidates.map((p) => [matchScore(name, spec, p), p]).filter((x) => x[0] > 0).sort((x, y) => y[0] - x[0]);
  }

  function specConflicts(a, b) {
    a = unaccent(clean(a)); b = unaccent(clean(b));
    if (!a || !b) return false;
    const fa = features(a), fb = features(b);
    if (fa.kg.size && fb.kg.size) return !common(fa.kg, fb.kg);
    if (fa.dims.size && fb.dims.size) return !common(fa.dims, fb.dims);
    return !a.includes(b) && !b.includes(a);
  }

  const key = (v) => unaccent(clean(v));

  /** -> products that may already be this one, best evidence first (catalog.find_possible_duplicates). */
  function findPossibleDuplicates(products, nameVi, nameZh = "", spec = "", variant = "", category = "") {
    const result = [], seen = new Set();
    // find_same: every product (stopped ones too), in the order they were made
    const same = products.slice().sort((x, y) => s(x.created_at).localeCompare(s(y.created_at)) || cmp(s(x.code), s(y.code)))
      .find((p) => key(p.name_vi) === key(nameVi) && key(p.spec) === key(spec) && key(p.variant) === key(variant) &&
                   (!category || key(p.category) === key(category)));
    if (same) { seen.add(same); result.push(same); }
    const variantNorm = key(variant), categoryNorm = key(category);
    for (const [score, p] of ranked(products, `${s(nameZh)} ${s(nameVi)}`, s(spec))) {
      if (score < 0.5 || seen.has(p)) continue;
      if (specConflicts(spec, p.spec)) continue;
      if (variantNorm && p.variant && key(p.variant) !== variantNorm) continue;
      if (categoryNorm && p.category && key(p.category) !== categoryNorm) continue;
      seen.add(p);
      result.push(p);
    }
    return result;
  }

  const api = { clean, unaccent, ratio, matchScore, findPossibleDuplicates };
  root.DibeDupes = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
