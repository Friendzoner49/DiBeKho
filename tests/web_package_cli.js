/* Runs webapp/package.js -- the very code the web page uses -- in Node, for tests/test_web_package.py.
   node web_package_cli.js export <pulled.json> <out.dibekho>
   node web_package_cli.js batch <package.dibekho> <pulled.json> <out.json> */
const fs = require("fs");
const path = require("path");

const W = path.join(__dirname, "..", "webapp");
global.DBK_SCHEMA = require(path.join(W, "schema.js"));
const PKG = require(path.join(W, "package.js"));
const initSqlJs = require(path.join(W, "vendor", "sql-wasm.js"));
const fflate = require(path.join(W, "vendor", "fflate.js"));

(async () => {
  const SQL = await initSqlJs({ locateFile: (f) => path.join(W, "vendor", f) });
  const [cmd, a, b, c] = process.argv.slice(2);
  if (cmd === "export") {
    const pulled = JSON.parse(fs.readFileSync(a, "utf8"));
    const pkg = PKG.buildPackage(SQL, fflate, pulled, new Date(2026, 10, 13, 9, 30, 0));
    fs.writeFileSync(b, pkg.bytes);
    process.stdout.write(pkg.name);
  } else if (cmd === "batch") {
    const { db } = PKG.readPackage(SQL, fflate, fs.readFileSync(a));
    try {
      fs.writeFileSync(c, JSON.stringify(PKG.buildBatch(db, JSON.parse(fs.readFileSync(b, "utf8")))));
    } finally {
      db.close();
    }
  } else {
    throw new Error(`unknown command ${cmd}`);
  }
})().catch((e) => {
  process.stderr.write(String(e && e.message ? e.message : e));
  process.exit(1);
});
