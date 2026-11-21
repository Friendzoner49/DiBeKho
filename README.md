# DiBeKho for macOS (Swift) - work in progress, private

The Windows app stays the Python one. Both use the same data folder, `.dibekho` packages and cloud, so the schema
comes from the Python app: `tools/gen_from_python.py` writes `Sources/DiBeKhoCore/Generated/Migrations.swift` and the
golden data of the tests. Never edit the generated files; never commit customer data.

## State (phases 0-2 tried on the Mac M2; phases 3, 5 and 6 written and green on CI, waiting for the owner's try-out on the Mac; Cloud written, not tried)
- `DiBeKhoCore`: schema runner (as Python's `db.migrate`, no table of its own) and the Python app's sync triggers
  (generated, created on every open), accent-free search rules, stock, order, customer, product, search and
  period-stats queries, numbers, money and dates shown as in the Python app.
- Phase 2: `Xlsx` (an .xlsx reader that sees cells as openpyxl `data_only` does) and `DeliveryNoteReader` (port of
  `excel/delivery_note.py`, warnings and errors word for word).
- Phase 3 core: `Ledger` (core/stock: documents, movements, cancel, counts, transfers, trial use, place),
  `Receipts` (core/receipts: save, edit, return prices, suggestions, checks), `Catalog` (new products, freed codes,
  customers), screen texts vi/en/zh generated from `i18n/*.json`. A fixed list of operations on a made-up shop
  leaves every table exactly as the Python core leaves it (`tools/gen_phase3.py`, `WritesTests`).
- Phase 3b: `Deliveries` (core/deliveries: the scan of `phieu-giao-hang`, notes into documents, edited / lost /
  other-order notes, notes read after a stock count, names learned, read a note again) and `Matching`
  (core/catalog's name matching with a port of difflib's ratio, near-duplicate products). One scenario on the
  made-up shop (every kind of file, decisions, a partly approved note, a moved and an edited note, lost files,
  a count, a forgotten name) leaves the folder and every table as the Python app does, step by step
  (`tools/gen_scan.py`, `ScanTests`). Every path is checked to lie inside the work folder (no `..`, no link
  leading out of it).
- Phase 3c: `XlsxWriter` (a one-sheet .xlsx written the way Excel writes it), `IssueNote` + `Issues` (core/issues, excel/issue_note: the stock issue note, its Excel file, recording it through the scan path, deleting it), `ReceiptFile` (the Excel file of a goods receipt, and the reader of a goods-in file), `Inbox` (the files of `input/`). The same scenario as the Python core (four issue notes with deletes, four receipts with their files, the files of `input/`) gives the same tables step by step (`tools/gen_issue.py`, `IssueTests`); the .xlsx files the tests write are loaded by openpyxl on CI and compared cell by cell (fonts, borders, merges, widths, heights, print setup) with the Python app's files (`tools/check_xlsx.py`).
- The app opens the shop's own work folder (the Python app's config.json) and writes to it, holding the shared
  lock `data/dibekho.lock` exactly as Qt's QLockFile writes it, and taking the day's backup in `sao-luu/`. Cloud (written, compiled on CI with 92 tests green, app and screenshots built (run 44627464920), never run against a real Cloud; only the two-way merge has a golden): off until the user signs in under Settings → Cloud; then background two-way sync, staff approvals and a Storage backup. Until then changes wait in `sync_outbox` and the Python app sends them on its next sync. A practice copy (`Practice`,
  BẢN THỬ) is kept as an option.
- `DiBeKhoSwift` app (SwiftUI + `NSTableView`) laid out as the Python app: Tồn kho · Cần xử lý · Tra cứu · Hàng về ·
  Kiểm kê · Cài đặt; Hàng về with the receipt form, Kiểm kê with counts, transfers, trial use and their lists,
  Quét lại phiếu and Cần xử lý, Huỷ phiếu / Sửa phiếu / Đọc lại cả phiếu in a document's window; Đơn hàng, Khách hàng, Thống kê in their own windows. Packed as
  `DiBeKho Swift.app` (own name and bundle id, signed ad hoc) by `scripts/make_app.sh`.
- 92 tests (1 skipped: the customer's own notes, only on the developer's Mac). CI makes the app, starts it and
  keeps 14 screenshots (about 4 minutes a run).
- Trying it on the Mac: `docs/thu-tren-mac.md`.

- Master data and the inbox: `MasterData` (the 'dữ liệu gốc' workbook, export and import, stock matched by code, name, position), `Inbox` knows receipts, master workbooks, catalog sheets and `.dibekho` packages, `Report.exportCustomer`, and a `.dmg` built on CI. Their tests are Swift-only (not golden); compiled on CI (green), not yet tried on a Mac.

Not yet: restoring from a Cloud backup (it replaces the shared data; deliberately left), account admin (create / change role / revoke) and sending the usage log to the Cloud. Written 20/11 (CI green, 98 tests, not yet tried on a Mac): ⌘F, the Currency filter of the order list, the first-run language and folder chooser, staff and web requests in "Cần xử lý", typed-in yuan prices in the issue form, the automatic update check (it needs the repository's releases to be public) and more en/zh text (a few small boxes are still Vietnamese only). The pinned Stock column is not built: the table always fits the window, so the Stock column is always visible. Phase 4 (Cloud) is compiled on CI but untested against a real Cloud. See `docs/viec-con-lai.md`. Written 20/11 and not yet compiled: a first pass to make the screens look like the Python app (framed line tables with row numbers and ▲▼ in the issue and receipt forms, grid lines and content-sized columns in lists, the status line beside the top buttons, the General settings tab in the Python order with Change folder… and Reset data, the learned-names list that showed blank when opened).

## Build
- On a Mac (Xcode 15 or newer): `swift test` in this folder, or open `Package.swift` in Xcode.
- On GitHub: Actions -> build -> Run workflow (by hand only; the macOS minutes of a private repo are limited).
- After a new migration in the Python app: `uv --project <Python repo> run python -X utf8 tools/gen_from_python.py <Python repo>`, then run the tests.
