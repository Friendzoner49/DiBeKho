/* .dibekho data packages made by the web page itself (user's choice 13/11/2026), the same files the app makes and
   reads (core/transfer.py). The shared data on the cloud is the most complete copy, so a package made here is the
   whole data of the shop -- without the kept Excel originals (phieu-goc) and the app's log, which the cloud never held.

   Export: every live row of the cloud (sync_pull from 0) written into a new SQLite database built with the app's own
   migrations (schema.js, generated from them), with integer ids, references translated and sync_map filled so the app
   keeps the uuids. Importing a package is done in the app only (the web only looks, customer's request 14/11/2026;
   core/cloud/admin.py).

   Pure functions take the libraries as arguments, so tests/web_package_cli.js runs the very same code in Node. */

"use strict";

const DBK_PKG = (() => {
  const S = typeof DBK_SCHEMA !== "undefined" ? DBK_SCHEMA : require("./schema.js");
  // the page's language (i18n.js); in Node (tests/web_package_cli.js) the plain English words
  const say = (key, plain) => (typeof tr === "function" ? tr(key) : plain);

  /* ---------------------------------------------------------------- the database */

  function run(db, sql, params) {
    db.run(sql, params || []);
  }

  function rows(db, sql, params) {
    const st = db.prepare(sql);
    st.bind(params || []);
    const out = [];
    while (st.step()) out.push(st.getAsObject());
    st.free();
    return out;
  }

  function one(db, sql) {
    const r = db.exec(sql);
    return r.length && r[0].values.length ? r[0].values[0][0] : null;
  }

  /** Run the migrations newer than the database's version, as db.migrate does (foreign keys off, checked after). */
  function migrate(db) {
    const current = one(db, "PRAGMA user_version") || 0;
    run(db, "PRAGMA foreign_keys = OFF");
    for (const [version, statements] of S.migrations) {
      if (version <= current) continue;
      run(db, "BEGIN");
      try {
        for (const sql of statements) run(db, sql);
        if (db.exec("PRAGMA foreign_key_check").length) throw new Error(`migration ${version}: foreign key check failed`);
        run(db, `PRAGMA user_version = ${version}`);
        run(db, "COMMIT");
      } catch (e) {
        run(db, "ROLLBACK");
        throw e;
      }
    }
    run(db, "PRAGMA foreign_keys = ON");
  }

  function columns(db, table) {
    return rows(db, `PRAGMA table_info(${table})`).map((c) => c.name);
  }

  /* ---------------------------------------------------------------- export */

  const ORDER_COLUMNS = ["created_at", "rev"];

  /** Live cloud rows of one table in the order local ids are handed out: the oldest first (the app sorts by id in
      places: a replaced receipt comes before its replacement). */
  function ordered(t, list, ids) {
    const live = list.filter((r) => !r.deleted);
    const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
    if (t.natural) return live.sort((a, b) => cmp(String(a[t.key]), String(b[t.key])));
    const parent = t.name === "document_lines" || t.name === "document_skipped_lines" ? "document_id" : null;
    return live.sort((a, b) => {
      if (parent) {
        const pa = ids.documents.get(a.document_id) || 0, pb = ids.documents.get(b.document_id) || 0;
        if (pa !== pb) return pa - pb;
        if (a.line_no !== undefined && a.line_no !== b.line_no) return (a.line_no || 0) - (b.line_no || 0);
      }
      for (const c of ORDER_COLUMNS) {
        const x = cmp(a[c] == null ? "" : String(a[c]).padStart(c === "rev" ? 20 : 0, "0"),
                      b[c] == null ? "" : String(b[c]).padStart(c === "rev" ? 20 : 0, "0"));
        if (x) return x;
      }
      return cmp(String(a.id), String(b.id));
    });
  }

  function localValue(t, col, value, ids) {
    if (value === null || value === undefined) return null;
    if (t.refs[col]) {
      const local = ids[t.refs[col]].get(value);
      if (local === undefined) throw new Error(`${t.name}.${col}: ${t.refs[col]} ${value} ${say("pkg.missing_ref", "is missing")}`);
      return local;
    }
    if (t.booleans.includes(col)) return value ? 1 : 0;
    if (t.timestamps.includes(col)) return String(value).slice(0, 19).replace("T", " ");
    if (typeof value === "boolean") return value ? 1 : 0;
    if (typeof value === "object") return JSON.stringify(value);
    return value;
  }

  /** A new database holding every live row of `pulled` (the answer of sync_pull(0)). Returns the sql.js Database. */
  function buildDatabase(SQL, pulled) {
    const db = new SQL.Database();
    migrate(db);
    const tables = (pulled && pulled.tables) || {};
    const ids = {};
    run(db, "PRAGMA foreign_keys = OFF");
    run(db, "BEGIN");
    for (const t of S.synced) {
      ids[t.name] = new Map();
      const list = ordered(t, tables[t.name] || [], ids);
      const cols = columns(db, t.name).filter((c) => t.natural || c !== t.key);
      list.forEach((r, i) => {
        if (t.only_keys.length && !t.only_keys.includes(r.key)) return;
        if (!t.natural) ids[t.name].set(r.id, i + 1);
      });
      for (const r of list) {
        if (t.only_keys.length && !t.only_keys.includes(r.key)) continue;
        const use = cols.filter((c) => c in r);
        const values = use.map((c) => localValue(t, c, r[c], ids));
        if (t.natural) {
          run(db, `INSERT OR REPLACE INTO ${t.name}(${use.join(", ")}) VALUES (${use.map(() => "?").join(", ")})`, values);
        } else {
          const local = ids[t.name].get(r.id);
          const key = t.key === "rowid" ? "rowid" : t.key;
          run(db, `INSERT INTO ${t.name}(${key}, ${use.join(", ")}) VALUES (?, ${use.map(() => "?").join(", ")})`,
              [local, ...values]);
          run(db, "INSERT INTO sync_map(tbl, local_id, uid) VALUES (?, ?, ?)", [t.name, String(local), r.id]);
        }
      }
    }
    if (db.exec("PRAGMA foreign_key_check").length) {
      run(db, "ROLLBACK");
      throw new Error(say("pkg.broken_refs", "the cloud's rows do not match (foreign keys)"));
    }
    run(db, "COMMIT");
    run(db, "PRAGMA foreign_keys = ON");
    return db;
  }

  function stamp(d) {
    const p = (n) => String(n).padStart(2, "0");
    return { iso: `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`,
             file: `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}` };
  }

  /** {name, bytes} of a .dibekho package of `pulled`. */
  function buildPackage(SQL, fflate, pulled, now, device) {
    const db = buildDatabase(SQL, pulled);
    try {
      const when = stamp(now || new Date());
      const manifest = {
        device_name: device || "Web", device_id: "web", exported_at: when.iso, schema_version: S.version,
        app_version: "web",
        deliveries: one(db, "SELECT COUNT(*) FROM documents WHERE kind = 'delivery' AND status = 'active'"),
        products: one(db, "SELECT COUNT(*) FROM products WHERE active = 1"),
        format: S.format,
      };
      const bytes = fflate.zipSync({ "manifest.json": fflate.strToU8(JSON.stringify(manifest)), "kho.sqlite": db.export() },
                                   { level: 6 });
      return { name: `DiBeKho_${(device || "Web").replace(/[^A-Za-z0-9_-]/g, "") || "Web"}_${when.file}.dibekho`, bytes, manifest };
    } finally {
      db.close();
    }
  }

  /* ---------------------------------------------------------------- the browser */

  let libs = null;

  function addScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = () => reject(new Error(`${say("pkg.no_script", "cannot load")} ${src}`));
      document.head.appendChild(s);
    });
  }

  /** sql.js and fflate, loaded the first time they are needed (about 700 KB). */
  async function loadLibs() {
    if (libs) return libs;
    if (typeof initSqlJs === "undefined") await addScript("vendor/sql-wasm.js");
    if (typeof fflate === "undefined") await addScript("vendor/fflate.js");
    const SQL = await initSqlJs({ locateFile: (f) => `vendor/${f}` });
    libs = { SQL, fflate };
    return libs;
  }

  return { migrate, buildDatabase, buildPackage, loadLibs };
})();
if (typeof module !== "undefined") module.exports = DBK_PKG;
