/* Runs webapp/xlsx.js -- the very code the web page uses for a Phiếu xuất kho -- in Node, for tests/test_web_issue.py.
   node web_issue_cli.js file <in.json> <out.xlsx>     in.json = {head, rows}: the file of those rows
   node web_issue_cli.js rows <in.json> <out.json>     in.json = {products: {id: product}, lines}: noteRows()
   node web_issue_cli.js code                          the code of 14/11/2026 09:30:15 */
const fs = require("fs");
const path = require("path");

const W = path.join(__dirname, "..", "webapp");
const X = require(path.join(W, "xlsx.js"));
const fflate = require(path.join(W, "vendor", "fflate.js"));

const [cmd, a, b] = process.argv.slice(2);
try {
  if (cmd === "file") {
    const { head, rows } = JSON.parse(fs.readFileSync(a, "utf8"));
    fs.writeFileSync(b, X.issueNote(fflate, head, rows, new Date(Date.UTC(2026, 10, 14, 2, 30, 0))));
  } else if (cmd === "rows") {
    const { products, lines } = JSON.parse(fs.readFileSync(a, "utf8"));
    fs.writeFileSync(b, JSON.stringify(X.noteRows(products, lines)));
  } else if (cmd === "code") {
    process.stdout.write(X.newCode(new Date(2026, 10, 14, 9, 30, 15)));
  } else {
    throw new Error(`unknown command ${cmd}`);
  }
} catch (e) {
  process.stderr.write(String(e && e.stack ? e.stack : e));
  process.exit(1);
}
