/* The Phiếu xuất kho Excel file, written in the browser: the very cells of the app's own
   (src/dibekho/excel/issue_note.py), that is the grid of the shop's delivery notes (销售单 PHIẾU GIAO HÀNG) cell for
   cell, with the title PHIẾU XUẤT KHO, the company lines the app read from the shop's notes (meta note_letterhead) and
   two hidden columns (H Mã hàng, I Lấy từ kho) so the app reads it back exactly. The app reads it like any delivery
   note (excel/delivery_note.py) and takes the stock of each place when it is dropped into the notes folder. Only plain
   values, never formulas (the app reads files with data_only=True). The labels are the file's own bilingual text, the
   same whatever the page's language.

   A tiny xlsx writer (one sheet, shared strings, cell styles, merged cells, widths, hidden columns, print setup) on top
   of fflate's zip. Pure functions: tests/web_issue_cli.js runs this very code in Node and tests/test_web_issue.py
   compares the file with the app's cell by cell and reads it back with the app's reader. */

"use strict";

const DBK_XLSX = (() => {
  const TITLE = "出库单 PHIẾU XUẤT KHO";
  const LABELS = {
    customer: "客户名称 ( Tên khách hàng ): ",
    phone: "联系电话 ( Điện thoại liên hệ ): ",
    code: "订货单号 ( Mã đơn hàng )：",
    contact: "联系人( Người liên hệ )：",
    date: "送货日期 ( Ngày giao hàng )：",
    address: "地址( Địa chỉ): ",
  };
  const HEADERS = ["编 号\nSTT", "商 品 全 名\nTên hàng", "规格\nQUY CÁCH", "数 量\nSố lượng", "单 价\nVND", "金 额\nVND",
                   "备 注\nGhi chú", "货号\nMã hàng", "取货地点\nLấy từ kho"];
  const PLACES = { 1: "Kho tổng 总仓", 2: "Văn phòng 办公室" };
  const WORDS_LABEL = "总计大写\n (Tổng cộng viết bằng chữ)";
  const QTY_LABEL = "页小计 \n( Tổng số lượng ):\n";
  const SIGN_FROM = "送货单位及经手人（盖章）：Người giao hàng";
  const SIGN_TO = "收货单位及经手人（盖章）：Người nhận hàng";
  const SHEET = "出库单";
  const HEADER_ROW = 8;
  const WIDTHS = [17.1, 62.8, 20.2, 13.0, 34.8, 25.1, 25.8, 12.0, 24.0];  // A..I; H and I hidden
  const HIDDEN = [8, 9];
  const HEIGHTS = { 1: 61.15, 2: 40.9, 3: 9.0, 4: 40.15, 5: 54.0, 6: 44.25, 7: 31.9, [HEADER_ROW]: 40.15 };
  const LINE_HEIGHT = 38.0, TOTAL_HEIGHT = 76.5, SIGN_HEIGHT = 82.9;
  const MONEY = "[$VND]\\ #,##0";
  const TNR = "Times New Roman";
  const DIGITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"];
  const UNITS = ["", "nghìn", "triệu", "tỷ", "nghìn tỷ", "triệu tỷ"];

  /** '中文名\nTên Việt', like the customer's notes (core/text.split_bilingual_name reads it back). */
  function productName(nameVi, nameZh) {
    return nameZh && nameVi ? `${nameZh}\n${nameVi}` : (nameVi || nameZh || "");
  }

  /** 3 -> '3', 2.5 -> '2.5' (issue_note.number_text). */
  const numberText = (v) => String(Number(v));
  const placesText = (places) => places.filter(([, q]) => q).map(([loc, q]) => `${PLACES[loc]}: ${numberText(q)}`).join("; ");

  function three(n, full) {
    const h = Math.floor(n / 100), t = Math.floor(n / 10) % 10, u = n % 10, w = [];
    if (full || h) w.push(DIGITS[h], "trăm");
    if (t === 0) { if (u && (full || h)) w.push("linh"); }
    else if (t === 1) w.push("mười");
    else w.push(DIGITS[t], "mươi");
    if (u) w.push(u === 1 && t >= 2 ? "mốt" : u === 5 && t >= 1 ? "lăm" : DIGITS[u]);
    return w;
  }

  /** 2376000 -> 'HAI TRIỆU BA TRĂM BẢY MƯƠI SÁU NGHÌN VIỆT NAM ĐỒNG' (issue_note.vnd_words). */
  function vndWords(amount) {
    let n = Math.floor(amount + 0.5);
    if (n < 0) return "";
    if (n === 0) return "KHÔNG VIỆT NAM ĐỒNG";
    const groups = [];
    do { groups.push(n % 1000); n = Math.floor(n / 1000); } while (n);
    const words = [];
    for (let i = groups.length - 1; i >= 0; i--) {
      if (groups[i] === 0 && (words.length || i)) continue;
      words.push(...three(groups[i], words.length > 0));
      if (UNITS[i]) words.push(UNITS[i]);
    }
    return words.join(" ").toUpperCase() + " VIỆT NAM ĐỒNG";
  }

  /** About how many lines a wrapped cell takes (Excel does not grow a row a program wrote). */
  function wrappedLines(text, width, size) {
    const perLine = Math.max(1, width * 11 / size);
    let total = 0;
    for (const part of String(text || "").split("\n")) {
      let units = 0;
      for (const ch of part) units += ch.codePointAt(0) > 0x2E7F ? 2 : 1;
      total += Math.max(1, Math.ceil(units / perLine));
    }
    return total;
  }

  const pad = (n) => String(n).padStart(2, "0");

  /** The cells of the note (issue_note.issue_sheet): {cells: Map("r,c" -> cell), merges, heights, lastRow}. */
  function issueSheet(head, rows) {
    const cells = new Map(), merges = [], heights = { ...HEIGHTS };
    const put = (r, c, value, style = {}) => cells.set(`${r},${c}`, {
      r, c, value: value === "" || value === undefined ? null : value, font: TNR, size: 15, border: false,
      align: "center", wrap: true, money: false, ...style });
    const letter = [...(head.letterhead || []), "", ""].slice(0, 2);
    put(1, 1, letter[0] || null, { size: 20 });
    put(2, 1, letter[1] || null, { size: 20 });
    put(4, 1, TITLE, { size: 24 });
    const [y, m, d] = String(head.doc_date).split("-");
    put(5, 1, `${LABELS.customer}\n${head.customer}`, { size: 20, align: "left" });
    put(5, 3, LABELS.phone + (head.phone || ""), { size: 14, align: "left" });
    put(5, 6, LABELS.code + head.code, { size: 14, align: "left" });
    put(6, 3, LABELS.contact + (head.contact || ""), { size: 14, align: "left" });
    put(6, 6, `${LABELS.date}${pad(d)}-${pad(m)}-${y}`, { size: 14, align: "left" });
    put(7, 1, LABELS.address + (head.address || ""), { size: 14, align: "left" });
    merges.push("A1:G1", "A2:G2", "A3:G3", "A4:G4", "A5:B6", "C5:E5", "F5:G5", "C6:E6", "F6:G6", "A7:E7");
    HEADERS.forEach((text, i) => put(HEADER_ROW, i + 1, text, { border: i < 7 }));
    let r = HEADER_ROW, qtyTotal = 0, moneyTotal = 0, priced = false;
    rows.forEach((ln, i) => {
      r = HEADER_ROW + i + 1;
      const name = productName(ln.name_vi, ln.name_zh);
      put(r, 1, i + 1, { border: true });
      put(r, 2, name, { border: true });
      put(r, 3, ln.spec || null, { size: 18, border: true });
      put(r, 4, ln.qty, { size: 18, border: true });
      put(r, 5, ln.unit_price ?? null, { size: 18, border: true, money: true });
      put(r, 6, ln.amount ?? null, { size: 18, border: true, money: true });
      put(r, 7, ln.note || null, { border: true });
      put(r, 8, `${ln.code}|${ln.spec || ""}|${name}`, { size: 11, wrap: false });  // trusted while the row is unchanged
      put(r, 9, placesText(ln.places || []) || null, { size: 11, wrap: false });
      const lines = Math.max(wrappedLines(name, WIDTHS[1], 15), wrappedLines(ln.note, WIDTHS[6], 15),
                             wrappedLines(ln.spec, WIDTHS[2], 18));
      heights[r] = Math.max(LINE_HEIGHT, 20 * lines);
      qtyTotal += ln.qty;
      if (ln.amount !== null && ln.amount !== undefined) { moneyTotal += ln.amount; priced = true; }
    });
    r += 1;
    put(r, 1, WORDS_LABEL, { border: true });
    put(r, 2, priced ? vndWords(moneyTotal) : null, { border: true });
    put(r, 3, null, { border: true });
    put(r, 4, QTY_LABEL + numberText(qtyTotal), { border: true });
    put(r, 5, null, { border: true });
    put(r, 6, priced ? moneyTotal : null, { size: 18, border: true, money: true });
    put(r, 7, null, { border: true });
    merges.push(`B${r}:C${r}`);
    heights[r] = TOTAL_HEIGHT;
    r += 1;
    put(r, 1, SIGN_FROM, { size: 14, align: "left", wrap: false });
    put(r, 4, SIGN_TO, { size: 14, align: "left", wrap: false });
    merges.push(`A${r}:C${r}`);
    heights[r] = SIGN_HEIGHT;
    return { cells, merges, heights, lastRow: r };
  }

  const xml = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]))
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, "");
  const col = (c) => String.fromCharCode(64 + c);
  const ref = (r, c) => `${col(c)}${r}`;
  const NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"';
  const REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
  const HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n';

  /** The style sheet of the cells used; gives every cell its format number (cell.s). */
  function stylesXml(sheet) {
    const fonts = [], fontIndex = new Map(), xfs = [], xfIndex = new Map();
    const fontOf = (name, size) => {
      const key = `${name}|${size}`;
      if (!fontIndex.has(key)) {
        fontIndex.set(key, fonts.length + 1);
        fonts.push(`<font><b/><sz val="${size}"/><name val="${xml(name)}"/></font>`);
      }
      return fontIndex.get(key);
    };
    for (const cell of sheet.cells.values()) {
      const key = `${cell.font}|${cell.size}|${cell.border}|${cell.align}|${cell.wrap}|${cell.money}`;
      if (!xfIndex.has(key)) {
        const f = fontOf(cell.font, cell.size);
        xfIndex.set(key, xfs.length + 1);
        xfs.push(`<xf numFmtId="${cell.money ? 164 : 0}" fontId="${f}" fillId="0" borderId="${cell.border ? 1 : 0}" xfId="0"` +
          `${cell.money ? ' applyNumberFormat="1"' : ""} applyFont="1"${cell.border ? ' applyBorder="1"' : ""} applyAlignment="1">` +
          `<alignment horizontal="${cell.align}" vertical="center"${cell.wrap ? ' wrapText="1"' : ""}/></xf>`);
      }
      cell.s = xfIndex.get(key);
    }
    const side = (n) => `<${n} style="thin"><color auto="1"/></${n}>`;
    return `${HEAD}<styleSheet ${NS}>` +
      `<numFmts count="1"><numFmt numFmtId="164" formatCode="${xml(MONEY)}"/></numFmts>` +
      `<fonts count="${fonts.length + 1}"><font><sz val="11"/><name val="Calibri"/><family val="2"/></font>${fonts.join("")}</fonts>` +
      '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>' +
      `<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border><border>${side("left")}${side("right")}` +
      `${side("top")}${side("bottom")}<diagonal/></border></borders>` +
      '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>' +
      `<cellXfs count="${xfs.length + 1}"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>${xfs.join("")}</cellXfs>` +
      '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>';
  }

  function sheetXml(sheet, strings) {
    const index = new Map();
    const sid = (s) => { if (!index.has(s)) { index.set(s, strings.length); strings.push(s); } return index.get(s); };
    const byRow = new Map();
    for (const cell of sheet.cells.values()) {
      if (!byRow.has(cell.r)) byRow.set(cell.r, []);
      byRow.get(cell.r).push(cell);
    }
    const rowNumbers = [...new Set([...byRow.keys(), ...Object.keys(sheet.heights).map(Number)])].sort((a, b) => a - b);
    const rowsXml = rowNumbers.map((r) => {
      const ht = sheet.heights[r] ? ` ht="${sheet.heights[r]}" customHeight="1"` : "";
      const cs = (byRow.get(r) || []).sort((a, b) => a.c - b.c).map((cell) => {
        const at = `r="${ref(r, cell.c)}" s="${cell.s}"`;
        if (cell.value === null) return `<c ${at}/>`;
        if (typeof cell.value === "number") return `<c ${at}><v>${cell.value}</v></c>`;
        return `<c ${at} t="s"><v>${sid(String(cell.value))}</v></c>`;
      }).join("");
      return `<row r="${r}"${ht}>${cs}</row>`;
    }).join("");
    const cols = WIDTHS.map((w, i) => `<col min="${i + 1}" max="${i + 1}" width="${w}" customWidth="1"` +
      `${HIDDEN.includes(i + 1) ? ' hidden="1"' : ""}/>`).join("");
    const merges = `<mergeCells count="${sheet.merges.length}">${sheet.merges.map((m) => `<mergeCell ref="${m}"/>`).join("")}</mergeCells>`;
    return `${HEAD}<worksheet ${NS} xmlns:r="${REL}"><sheetPr><pageSetUpPr fitToPage="0"/></sheetPr><cols>${cols}</cols>` +
      `<sheetData>${rowsXml}</sheetData>${merges}` +
      '<pageMargins left="0" right="0" top="0.393700787401575" bottom="0.393700787401575" header="0.3" footer="0.3"/>' +
      '<pageSetup paperSize="9" scale="67" orientation="landscape"/></worksheet>';
  }

  /** The .xlsx bytes of one sheet. */
  function workbook(fflate, sheet, name, now) {
    const strings = [];
    const styles = stylesXml(sheet);
    const sheet1 = sheetXml(sheet, strings);
    const sst = `${HEAD}<sst ${NS} count="${strings.length}" uniqueCount="${strings.length}">` +
      strings.map((s) => `<si><t xml:space="preserve">${xml(s)}</t></si>`).join("") + "</sst>";
    const when = (now || new Date()).toISOString().replace(/\.\d+Z$/, "Z");
    const T = "http://schemas.openxmlformats.org/";
    const printArea = `<definedNames><definedName name="_xlnm.Print_Area" localSheetId="0">'${xml(name)}'!$A$1:$G$${sheet.lastRow}</definedName></definedNames>`;
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
      "xl/workbook.xml": `${HEAD}<workbook ${NS} xmlns:r="${REL}"><sheets><sheet name="${xml(name)}" sheetId="1" r:id="rId1"/></sheets>${printArea}</workbook>`,
      "xl/_rels/workbook.xml.rels": `${HEAD}<Relationships xmlns="${T}package/2006/relationships">` +
        `<Relationship Id="rId1" Type="${REL}/worksheet" Target="worksheets/sheet1.xml"/>` +
        `<Relationship Id="rId2" Type="${REL}/styles" Target="styles.xml"/>` +
        `<Relationship Id="rId3" Type="${REL}/sharedStrings" Target="sharedStrings.xml"/></Relationships>`,
      "xl/worksheets/sheet1.xml": sheet1,
      "xl/styles.xml": styles,
      "xl/sharedStrings.xml": sst,
    };
    const zip = {};
    for (const [path, text] of Object.entries(files)) zip[path] = fflate.strToU8(text);
    return fflate.zipSync(zip, { level: 6 });
  }

  /** The table of the file, as core/issues.note_rows: one row per product, like a delivery note; where it is taken
      from goes in the hidden 'Lấy từ kho' column. lines [{product_id, qty_main, qty_office, unit_price (null = no
      price), note}]. The unit is only for the window's summary, it is not in the file. */
  function noteRows(productById, lines) {
    return lines.map((ln) => {
      const p = productById[ln.product_id];
      const nameVi = [p.name_vi, p.variant].filter(Boolean).join(" ");
      const places = [[1, ln.qty_main], [2, ln.qty_office]].filter(([, q]) => q > 0);
      const qty = (ln.qty_main || 0) + (ln.qty_office || 0);
      const amount = ln.unit_price === null || ln.unit_price === undefined ? null : Math.round(qty * ln.unit_price * 100) / 100;
      return { code: p.code, name_vi: nameVi, name_zh: p.name_zh || "", spec: p.spec || "", unit: p.unit || "", qty, places,
               unit_price: ln.unit_price ?? null, amount, note: String(ln.note || "").replace(/\s+/g, " ").trim() };
    });
  }

  /** prefix + 1 + the highest order number among codes ('159', '076', 'A160', 'W161'; other codes not counted), as
      core/issues.next_code. The web writes W160, the app A160 (user's choice 14/11/2026). */
  function nextCode(codes, prefix = "W") {
    let max = 0;
    for (const c of codes) {
      const m = /^\s*[AaWw]?\s*0*(\d{1,9})\s*$/.exec(String(c ?? ""));
      if (m) max = Math.max(max, Number(m[1]));
    }
    return `${prefix}${max + 1}`;
  }

  /** The bytes of a Phiếu xuất kho: head {code, doc_date 'yyyy-mm-dd', customer, phone, contact, address, letterhead},
      rows [{code, name_vi, name_zh, spec, qty, places [[location id, qty]], unit_price, amount, note}]. */
  function issueNote(fflate, head, rows, now) {
    return workbook(fflate, issueSheet(head, rows), SHEET, now);
  }

  return { TITLE, LABELS, HEADERS, PLACES, HEADER_ROW, productName, placesText, vndWords, issueSheet, noteRows, nextCode, issueNote };
})();
if (typeof module !== "undefined") module.exports = DBK_XLSX;
