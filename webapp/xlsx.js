/* The Phiếu xuất kho Excel file, written in the browser: the same layout, labels and values as the app's own
   (src/dibekho/excel/issue_note.py), so the app reads it like any delivery note (excel/delivery_note.py) and takes
   the stock of each place when it is dropped into the notes folder. Only plain values, never formulas (the app reads
   files with data_only=True). The labels are the file's own bilingual text, the same whatever the page's language.

   A tiny xlsx writer (one sheet, shared strings, a few cell styles, merged cells, column widths) on top of fflate's
   zip. Pure functions: tests/web_issue_cli.js runs this very code in Node and tests/test_web_issue.py reads the file
   back with the app's reader. */

"use strict";

const DBK_XLSX = (() => {
  const TITLE = "出库单  PHIẾU XUẤT KHO";
  const LABELS = {
    customer: "客户名称 ( Tên khách hàng )",
    phone: "联系电话 ( Điện thoại liên hệ )",
    code: "订货单号 ( Mã đơn hàng )",
    contact: "联系人 ( Người liên hệ )",
    date: "送货日期 ( Ngày giao hàng )",
    address: "地址 ( Địa chỉ )",
  };
  const HEADERS = ["编号\nSTT", "货号\nMã hàng", "商品全名\nTên hàng", "规格\nQuy cách", "单位\nĐơn vị", "数量\nSố lượng",
                   "取货地点\nLấy từ kho", "单价\nĐơn giá", "金额\nThành tiền", "备注\nGhi chú"];
  const PLACES = { 1: "Kho tổng 总仓", 2: "Văn phòng 办公室" };
  const TOTAL = "合计  Tổng cộng";
  const SIGNATURES = ["Người lập phiếu  制单人", "Người giao hàng  送货人", "Người nhận hàng  收货人"];
  const HEADER_ROW = 7;
  const WIDTHS = [6, 10, 42, 14, 8, 10, 16, 13, 15, 20];
  const SHEET = "出库单";
  const ST = { plain: 0, title: 1, label: 2, header: 3, cell: 4, money: 5, bold: 6, boldMoney: 7 };

  /** '中文名\nTên Việt', like the customer's notes (core/text.split_bilingual_name reads it back). */
  function productName(nameVi, nameZh) {
    return nameZh && nameVi ? `${nameZh}\n${nameVi}` : (nameVi || nameZh || "");
  }

  const xml = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]))
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, "");
  const col = (c) => String.fromCharCode(64 + c);  // the note has 10 columns: A..J
  const ref = (r, c) => `${col(c)}${r}`;

  /** The cells of the note: {cells: Map(row -> Map(col -> {v, s})), merges: [...], heights: {row: pt}}. */
  function issueSheet(head, rows) {
    const cells = new Map(), merges = [], heights = { [HEADER_ROW]: 34 };
    const put = (r, c, v, s) => { if (!cells.has(r)) cells.set(r, new Map()); cells.get(r).set(c, { v, s }); };
    const last = HEADERS.length;
    put(1, 1, TITLE, ST.title);
    merges.push(`A1:${col(last)}1`);
    const label = (r, c, key, value, span) => {
      if (!value) return;  // an empty optional field is not written: the reader would take the next cell as its value
      put(r, c, `${LABELS[key]}：${value}`, ST.label);
      merges.push(`${ref(r, c)}:${ref(r, c + span - 1)}`);
    };
    const [y, m, d] = String(head.doc_date).split("-");
    label(3, 1, "customer", head.customer, 4);
    label(3, 5, "phone", head.phone, 3);
    label(3, 8, "code", head.code, 3);
    label(4, 1, "contact", head.contact, 4);
    label(4, 8, "date", `${d}-${m}-${y}`, 3);
    label(5, 1, "address", head.address, last);
    HEADERS.forEach((text, i) => put(HEADER_ROW, i + 1, text, ST.header));
    let r = HEADER_ROW, qtyTotal = 0, moneyTotal = 0, priced = false;
    rows.forEach((ln, i) => {
      r = HEADER_ROW + i + 1;
      const values = [i + 1, ln.code, productName(ln.name_vi, ln.name_zh), ln.spec, ln.unit, ln.qty, PLACES[ln.location_id],
                      ln.unit_price, ln.amount, ln.note];
      values.forEach((v, j) => put(r, j + 1, v === "" ? null : v, j === 7 || j === 8 ? ST.money : ST.cell));
      qtyTotal += ln.qty;
      if (ln.amount !== null && ln.amount !== undefined) { moneyTotal += ln.amount; priced = true; }
    });
    r += 1;
    put(r, 3, TOTAL, ST.bold);
    put(r, 6, qtyTotal, ST.bold);
    if (priced) put(r, 9, moneyTotal, ST.boldMoney);
    [2, 5, 8].forEach((c, i) => put(r + 2, c, SIGNATURES[i], ST.bold));
    return { cells, merges, heights };
  }

  const NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"';
  const REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
  const HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n';

  function sheetXml(sheet, strings) {
    const index = new Map();
    const sid = (s) => { if (!index.has(s)) { index.set(s, strings.length); strings.push(s); } return index.get(s); };
    const rowsXml = [...sheet.cells.keys()].sort((a, b) => a - b).map((r) => {
      const ht = sheet.heights[r] ? ` ht="${sheet.heights[r]}" customHeight="1"` : "";
      const cs = [...sheet.cells.get(r).entries()].sort((a, b) => a[0] - b[0]).map(([c, { v, s }]) => {
        const at = `r="${ref(r, c)}"${s ? ` s="${s}"` : ""}`;
        if (v === null || v === undefined) return `<c ${at}/>`;
        if (typeof v === "number") return `<c ${at}><v>${v}</v></c>`;
        return `<c ${at} t="s"><v>${sid(String(v))}</v></c>`;
      }).join("");
      return `<row r="${r}"${ht}>${cs}</row>`;
    }).join("");
    const cols = WIDTHS.map((w, i) => `<col min="${i + 1}" max="${i + 1}" width="${w}" customWidth="1"/>`).join("");
    const merges = sheet.merges.length
      ? `<mergeCells count="${sheet.merges.length}">${sheet.merges.map((m) => `<mergeCell ref="${m}"/>`).join("")}</mergeCells>` : "";
    return `${HEAD}<worksheet ${NS} xmlns:r="${REL}"><cols>${cols}</cols><sheetData>${rowsXml}</sheetData>${merges}` +
      `<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/></worksheet>`;
  }

  const font = (bold, size) => `<font>${bold ? "<b/>" : ""}<sz val="${size}"/><name val="Calibri"/><family val="2"/></font>`;
  const side = (n) => `<${n} style="thin"><color rgb="FF999999"/></${n}>`;
  const xf = (num, fontId, border, align) => `<xf numFmtId="${num}" fontId="${fontId}" fillId="0" borderId="${border}" xfId="0"` +
    `${num ? ' applyNumberFormat="1"' : ""}${fontId ? ' applyFont="1"' : ""}${border ? ' applyBorder="1"' : ""}` +
    (align ? ` applyAlignment="1"><alignment ${align}/></xf>` : "/>");
  const WRAP = 'vertical="center" wrapText="1"';
  const STYLES = `${HEAD}<styleSheet ${NS}>` +
    `<fonts count="3">${font(false, 11)}${font(true, 11)}${font(true, 16)}</fonts>` +
    '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>' +
    `<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border><border>${side("left")}${side("right")}` +
    `${side("top")}${side("bottom")}<diagonal/></border></borders>` +
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>' +
    `<cellXfs count="8">${xf(0, 0, 0, "")}${xf(0, 2, 0, 'horizontal="center"')}${xf(0, 0, 0, WRAP)}` +
    `${xf(0, 1, 1, `horizontal="center" ${WRAP}`)}${xf(0, 0, 1, WRAP)}${xf(3, 0, 1, WRAP)}${xf(0, 1, 0, "")}${xf(3, 1, 0, "")}</cellXfs>` +
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>';

  /** The .xlsx bytes of one sheet. */
  function workbook(fflate, sheet, name, now) {
    const strings = [];
    const sheet1 = sheetXml(sheet, strings);
    const sst = `${HEAD}<sst ${NS} count="${strings.length}" uniqueCount="${strings.length}">` +
      strings.map((s) => `<si><t xml:space="preserve">${xml(s)}</t></si>`).join("") + "</sst>";
    const when = (now || new Date()).toISOString().replace(/\.\d+Z$/, "Z");
    const T = "http://schemas.openxmlformats.org/";
    const files = {
      "[Content_Types].xml": `${HEAD}<Types xmlns="${T}package/2006/content-types">` +
        `<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>` +
        `<Default Extension="xml" ContentType="application/xml"/>` +
        `<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>` +
        `<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>` +
        `<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>` +
        `<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>` +
        `<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>` +
        `<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/></Types>`,
      "_rels/.rels": `${HEAD}<Relationships xmlns="${T}package/2006/relationships">` +
        `<Relationship Id="rId1" Type="${REL}/officeDocument" Target="xl/workbook.xml"/>` +
        `<Relationship Id="rId2" Type="${T}package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>` +
        `<Relationship Id="rId3" Type="${REL}/extended-properties" Target="docProps/app.xml"/></Relationships>`,
      "docProps/app.xml": `${HEAD}<Properties xmlns="${T}officeDocument/2006/extended-properties" ` +
        `xmlns:vt="${T}officeDocument/2006/docPropsVTypes"><Application>Microsoft Excel</Application></Properties>`,
      "docProps/core.xml": `${HEAD}<cp:coreProperties xmlns:cp="${T}package/2006/metadata/core-properties" ` +
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" ' +
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">' +
        `<dcterms:created xsi:type="dcterms:W3CDTF">${when}</dcterms:created>` +
        `<dcterms:modified xsi:type="dcterms:W3CDTF">${when}</dcterms:modified></cp:coreProperties>`,
      "xl/workbook.xml": `${HEAD}<workbook ${NS} xmlns:r="${REL}"><sheets><sheet name="${xml(name)}" sheetId="1" r:id="rId1"/></sheets></workbook>`,
      "xl/_rels/workbook.xml.rels": `${HEAD}<Relationships xmlns="${T}package/2006/relationships">` +
        `<Relationship Id="rId1" Type="${REL}/worksheet" Target="worksheets/sheet1.xml"/>` +
        `<Relationship Id="rId2" Type="${REL}/styles" Target="styles.xml"/>` +
        `<Relationship Id="rId3" Type="${REL}/sharedStrings" Target="sharedStrings.xml"/></Relationships>`,
      "xl/worksheets/sheet1.xml": sheet1,
      "xl/styles.xml": STYLES,
      "xl/sharedStrings.xml": sst,
    };
    const zip = {};
    for (const [path, text] of Object.entries(files)) zip[path] = fflate.strToU8(text);
    return fflate.zipSync(zip, { level: 6 });
  }

  /** The table of the file, as core/issues.note_rows: one row per product and place (a product taken from both places
      is two rows). lines [{product_id, qty_main, qty_office, unit_price (null = no price), note}]. */
  function noteRows(productById, lines) {
    const rows = [];
    for (const ln of lines) {
      const p = productById[ln.product_id];
      const nameVi = [p.name_vi, p.variant].filter(Boolean).join(" ");
      for (const [place, qty] of [[1, ln.qty_main], [2, ln.qty_office]]) {
        if (!(qty > 0)) continue;
        const amount = ln.unit_price === null || ln.unit_price === undefined ? null : Math.round(qty * ln.unit_price * 100) / 100;
        rows.push({ code: p.code, name_vi: nameVi, name_zh: p.name_zh || "", spec: p.spec || "", unit: p.unit || "", qty,
                    location_id: place, unit_price: ln.unit_price ?? null, amount, note: String(ln.note || "").replace(/\s+/g, " ").trim() });
      }
    }
    return rows;
  }

  /** PX + date and time (PX261114-093215), like core/issues.new_code: machines and the web never share a counter. */
  function newCode(now) {
    const d = now || new Date(), p = (n) => String(n).padStart(2, "0");
    return `PX${p(d.getFullYear() % 100)}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
  }

  /** The bytes of a Phiếu xuất kho: head {code, doc_date 'yyyy-mm-dd', customer, phone, contact, address},
      rows [{code, name_vi, name_zh, spec, unit, qty, location_id, unit_price, amount, note}]. */
  function issueNote(fflate, head, rows, now) {
    return workbook(fflate, issueSheet(head, rows), SHEET, now);
  }

  return { TITLE, LABELS, HEADERS, PLACES, TOTAL, SIGNATURES, HEADER_ROW, productName, issueSheet, noteRows, newCode, issueNote };
})();
if (typeof module !== "undefined") module.exports = DBK_XLSX;
