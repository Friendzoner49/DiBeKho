/* Driven by tests/test_web_package.py inside headless Chrome, under the page's real Content-Security-Policy: the owner
   presses Xuất dữ liệu. sql.js (WebAssembly) and fflate load from vendor/ as on the real page; sync_pull answers with
   window.__PULLED__; the download and any sync_push (there must be none: the web only looks) are captured. */

(async () => {
  const out = { saved: [], pushes: [], alerts: [], error: null };
  try {
    sb.rpc = async (fn, args) => {
      if (fn === "sync_pull") return { data: window.__PULLED__, error: null };
      if (fn === "sync_push") { out.pushes.push(args); return { data: { ok: true, max_rev: 999 }, error: null }; }
      return { data: null, error: { message: `unexpected ${fn}` } };
    };
    loadAll = async () => {};
    window.confirm = () => true;
    window.alert = (text) => out.alerts.push(text);
    const toB64 = (bytes) => { let s = ""; for (const b of bytes) s += String.fromCharCode(b); return btoa(s); };
    saveFile = (name, bytes) => out.saved.push({ name, b64: toB64(bytes) });

    setRole("desktop", "Chủ", true);
    $("pkg-export").click();
    for (let i = 0; i < 200 && !out.saved.length && !out.alerts.length; i++) await new Promise((r) => setTimeout(r, 50));
    if (!out.saved.length) throw new Error("no package saved: " + out.alerts.join(" | "));
    out.msg = $("pkg-msg").textContent;
  } catch (e) {
    out.error = String(e && e.stack ? e.stack : e);
  }
  document.body.setAttribute("data-probe", JSON.stringify(out));
})();
