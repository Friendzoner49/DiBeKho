<div align="center">

<img src="resources/dibekho.png" alt="DiBeKho logo" width="112">

# DiBeKho

**English** · [Tiếng Việt](README.vi.md) · [中文](README.zh.md)

**Automatic stock tracking from Excel delivery notes: runs on your own computer, no internet needed, zero running cost.**

[![Windows 10 | 11](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D6?logo=windows&logoColor=white)](https://github.com/Friendzoner49/DiBeKho/releases/latest/download/DiBeKho-windows-setup.exe)
[![macOS 13+](https://img.shields.io/badge/macOS-13%2B%20Apple%20Silicon-000000?logo=apple&logoColor=white)](https://github.com/Friendzoner49/DiBeKho/releases/latest/download/DiBeKho-mac-arm64.dmg)

<img src="docs/images/en/ton-kho.png" alt="Stock screen" width="860">

</div>

---

**Contents:** [What it does](#what-dibekho-does) · [Download and install](#download-and-install) · [Your first day](#your-first-day) · [User guide](#user-guide) · [Mistakes and errors](#mistakes-and-errors) · [FAQ](#faq) · [Developers](#for-developers)

## What DiBeKho does

You drop Excel delivery notes into a folder. The app reads them, takes the goods off the stock, and records the orders and customers. Nothing has to be typed in again.

- 📦 **See the stock** of every product, split between the **main warehouse** and the **office**; below 30 the row turns orange with "Running low — order more", negative stock is red; a **note** per product (damaged, misprinted, expired boxes…).
- 📥 **Enter goods in** in one window: from a border gate / parent company, or a customer return.
- 🔢 **Stock count** per place (main warehouse, office): type what you counted, the app records the difference. **Transfer** goods between the two.
- 🔎 **Search** products, customers, phone numbers and note numbers; accents are optional and Chinese works.
- 💰 **Revenue per customer:** total, the products they buy most, every order with unit prices and amounts, for any period.
- 📊 **Statistics** by day, month, quarter or year, and **export to Excel**.
- ↶ **Undo:** a mistake is put right with one button.
- 💾 **Automatic daily backups**; **move all data** to another computer with one file.
- 🌐 Interface in **Vietnamese, English and Chinese**.

> The app reads the **selling prices** on the delivery notes (unit price, amount, shipping fee) to work out revenue; it has no purchase prices, so it does not compute profit. Your data stays on your computer and is never sent anywhere.

## Download and install

Button names in this guide are those of the English interface. Vietnamese users: see [README.vi.md](README.vi.md).

### You need

| | Requirement |
|---|---|
| **Windows** | Windows 10 or 11, 64-bit |
| **Mac** | A Mac with an **Apple chip** (M1, M2, M3, M4…), macOS 13 or later. Intel Macs are **not** supported |

### Downloads

Every file is on the [**Downloads (Releases)**](https://github.com/Friendzoner49/DiBeKho/releases/latest) page. Pick one:

| Computer | File | When |
|---|---|---|
| Windows | [**Installer** `DiBeKho-windows-setup.exe`](https://github.com/Friendzoner49/DiBeKho/releases/latest/download/DiBeKho-windows-setup.exe) | Default (the **Windows** button at the top) |
| Windows | [Zipped installer `DiBeKho-windows-setup.zip`](https://github.com/Friendzoner49/DiBeKho/releases/latest/download/DiBeKho-windows-setup.zip) | The browser blocks the `.exe` (see below). It holds the same installer |
| Mac | [`DiBeKho-mac-arm64.dmg`](https://github.com/Friendzoner49/DiBeKho/releases/latest/download/DiBeKho-mac-arm64.dmg) | Mac with an Apple chip (the **macOS** button at the top) |

### Windows

1. Click the **Windows** button at the top of this page. The installer `DiBeKho-windows-setup.exe` is downloaded. If the browser says it "isn't commonly downloaded" and cancels it: download the **`.zip`** from the table above, open it and double-click `DiBeKho-windows-setup.exe` inside.
2. Open the installer. If a blue "Windows protected your PC" box appears, click **More info** → **Run anyway**. (The app has no paid code signature, so Windows warns; it is safe.)
3. Click **Next** until **Finish**. No administrator rights are needed.
4. Open **DiBeKho** from the Start menu or the desktop icon.

### Mac

1. Click the **macOS** button at the top of this page. The file `DiBeKho-mac-arm64.dmg` is downloaded.
2. Open the `.dmg` and **drag the DiBeKho icon into the Applications folder**.
3. Open **DiBeKho** from Applications. The first time, macOS blocks it because Apple has not checked the app:
   - Open **System Settings → Privacy & Security**, scroll down, click **Open Anyway** and enter your password.
   - When the app asks for access to the **Documents** folder, click **Allow**.
4. **The Mac keeps saying "Move to Trash / Done" and there is no Open Anyway button?** Open **Terminal** (find it with Spotlight), paste the command below and press Enter. It only removes the "downloaded from the internet" mark from DiBeKho. Do it once after each new install.

   ```
   xattr -dr com.apple.quarantine /Applications/DiBeKho.app
   ```

### Updating

Download the new version as above and **install it over the old one** (Mac: drag into Applications and choose **Replace**). Your data in `Documents/DiBeKho` is kept.

> When two computers pass data to each other, **both must have the latest version**. A newer app reads data from an older one (it converts it automatically), but an older app cannot read data from a newer one.

### Uninstalling

- **Windows:** *Settings → Apps → DiBeKho → Uninstall*. The uninstaller asks whether to delete the data folder too (default: no).
- **Mac:** in the app, **Settings → Uninstall…**. The app removes itself from Applications once it closes.

## Your first day

Do these 4 steps once, in this order.

**1. Open the app.** Choose the language and the **working folder** (the default `Documents/DiBeKho` is fine) and click **Start**. Do not choose a folder inside OneDrive, iCloud or Google Drive: cloud syncing can damage the data.

**2. Load the product catalog** from your monthly stock sheet (Excel):
1. On the **Stock** screen, click **Import catalog from Excel…** and choose the file.
2. Check the preview. Double-click a cell to fix it; untick rows you do not want.
3. Keep **Use the stock in the file (column F) as the app's stock, as of** ticked and pick the date. The stock in the file becomes the app's stock. If the app cannot find the stock column, it asks you which one it is.
4. Click **Import selected rows**.

**3. Check the opening stock.** If step 2 gave no stock: open **Stock count**, pick the date, type the counted quantity of each product and click **Save count**.

**4. Read your first delivery notes:** see [Delivery notes every day](#1-delivery-notes-every-day) just below.

## User guide

### 1. Delivery notes every day

1. Copy the day's delivery notes (`.xlsx`) into the `phieu-giao-hang/` folder (**Open delivery notes folder** opens it). Subfolders, for example one per month, are fine.
2. Click **⟳ Rescan notes** (or press **F5**). The app also scans every time it starts.
3. Notes whose product names the app knows are read straight away and the stock goes down. A finished note is moved to `phieu-giao-hang/da-xu-ly/`: the notes left outside are the ones still waiting.
4. If **To do** on the left shows a number, some lines are not recognised yet. They are grouped by order, with every line of the order (✓ = already recognised), so you can compare with the paper note. Under **Is product**, choose:

| The line is | Choose |
|---|---|
| A product you already have | One of the suggestions; if it is not there, **🔍 Choose another product…** and type a few letters |
| A new product | **＋ Create new product**, and type the quantity already in stock (before this note) under **Opening stock** |
| A shipping or service fee | **✕ Not goods** (usually already chosen) |
| Not sure | **⏸ Later (keep waiting)**: the other lines are recorded, this one waits |

5. Click **Apply and read notes again**, check the summary and agree. The app remembers your choice and recognises the same name next time.

> Scrolling with the mouse wheel **never** changes a choice or a number. When the same name is in several orders, choosing it in one sets the others too.

6. A note does not say where the goods came from, so each new order shows in **To do → Orders without a place yet**. Choose **Main warehouse** or **Office** for each order and click **Save places**. Meanwhile the goods are taken from the main warehouse (the total is already right). Chose wrong? Change **Taken from** in the order window.

### 2. Goods in

<img src="docs/images/en/hang-ve.png" alt="Goods in window" width="760">

1. Open **Goods in** and click **＋ Goods in…**.
2. Choose where the goods come from:
   - **Border gate / parent company**: type the supplier, or pick one used before.
   - **Customer return**: pick the customer, and the order if you know it.
3. Three products are suggested. Type a **quantity** on each row; rows left without a quantity are skipped.
   - To change a product, click its name → **🔍 Choose a product from the catalog…** or **★ New product (not in the catalog)…**.
   - For more rows, click **＋ Add row**.
4. Choose **Put in**: main warehouse or office.
5. Click **Save goods in**, read the summary and agree. The stock goes up, the receipt gets a code (HV001, HV002…) and an Excel file of it is saved in `output/hang-ve/`.

A mistake? Click **↶ Undo** straight away, or select the receipt in the list and click **Edit selected…**. The old receipt stays in the history as "replaced".

Goods-in files of the old kind (a filled template) can still be imported with **Choose a file to import…**.

### 3. Stock count

Open **Stock count**, pick the date, type what you counted in the 2 yellow columns **Counted: Main warehouse** and **Counted: Office**, and click **Save count**. A place left empty stays as it is. The app only records the difference between your count and its own number, so the history stays clear.

- **Transfer…**: goods carried between the main warehouse and the office. Choose from and to, type the quantities and click **Save transfer**. The total does not change, only each place (transfers CH001, CH002…).
- **Stock note** column (the same as on the Stock page): double-click to write, e.g. "3 boxes misprinted, 2 expire 12/2026". It is saved at once, goes with the data package to another computer and is in the Excel files.

### 4. Looking things up

- **Stock:** columns **Main warehouse**, **Office** and the total. **Red** rows = negative stock (a goods in or a stock count is missing); **orange** rows with "⚠ Running low — order more" = below the alert level (**30** by default, changed in **Settings → Products → Alert when stock is below**). Tick **Only low stock** for the list to order. Double-click the **Stock note** cell to write a note; double-click elsewhere for everything that came in and went out, and the stock at each place.
- **Search** (**Ctrl+F**): one box for products, customers, phone numbers, note numbers and notes. The buttons under it open the **Order list**, the **Customer list** and **Statistics and Excel export**.
- Open **an order**: customer, lines with **Unit price** and **Amount**, goods + other fees = total, **Open original file**, **Read note again**, **Cancel document**.
- Open **a customer**: **Revenue**, the products they buy most (revenue, selling price), and **every order with its prices underneath**. Untick **All time** and pick **From … to …** to see what they bought, and at what price, in that period. **Export to Excel…** saves exactly that (every order with its prices, the products bought) to a file in `output/`.
- Prices come from the unit price / amount columns of the note. A note without a price leaves the cell empty (—) and it is not counted in revenue.

### 5. Statistics and Excel export

**Search → Statistics and Excel export**: choose the period (day, month, quarter, year, or from – to) and the products, categories or customers to include. The table shows opening stock, in, out, closing stock, **revenue** and the stock note, with best sellers and a chart; the line above it gives the revenue of the period = goods + other fees. Click **Export to Excel…** to save a file in `output/` (with unit price, amount, revenue, place and note columns).

### 6. Product catalog

**Settings → Products**:
- **Add product**, **Edit product…** (or double-click a row): name, packing, type/colour, category, **Low-stock alert at**.
- **Delete product** only works for a product that no note uses. A product already in use can be made *inactive* instead (hidden from lists, old notes unchanged). The code of a deleted product is never given out again.
- Long names: drag a column border wider, or hover over a cell to read the whole name.

### 7. Moving to another computer

Only **one computer** works at a time, and both need the same app version (see [Updating](#updating)).

1. On the computer in use: **Settings → Data transfer and backups → Export data**. A `.dibekho` file appears in `output/`.
2. Send that file (USB, Zalo, e-mail…) and copy it into the `input/` folder of the other computer.
3. On the other computer: **To do → Import data**. Its current data is backed up first, then replaced.

**Master data in Excel** (products, customers and stock; **no** orders):
- **Settings → Data transfer and backups → Export master data…** makes one Excel file with 3 sheets: Products, Customers, Stock.
- Correct the numbers in the **Stock** sheet if needed, then **Import master data…** (here or on another computer): products keep their codes and the app's stock becomes exactly the numbers in the file.
- When the app is not sure which product a stock row belongs to, it shows **Check the stock before importing**: yellow rows need you to look and pick the right product.

### 8. Backups

The app backs up once a day when it starts and keeps the last 14 copies in `sao-luu/`. **Settings → Data transfer and backups** has **Back up now** and **Restore selected**.

### 9. Starting over

**Settings → General → Reset data** (the app always backs up first):
- **Reset stock (keep products)…**: keeps the catalog and learned names; removes notes, goods in, stock counts and customers; reads every note again right away.
- **Delete all data…**: the app is as freshly installed (only language, size and working folder are kept).

Your own files (delivery notes, `input/`, `output/`, backups) are never deleted.

## Mistakes and errors

| Situation | What to do |
|---|---|
| You just did something wrong (Apply, stock count, goods in, editing/deleting a product, an import…) | Click **↶ Undo** at the top right: the data goes back to exactly how it was before. Click again to go further back (up to 20 steps) |
| A line was matched to the wrong product some time ago | **Settings → Products → Learned names on notes**: click the order, then **Forget and read again…** on the wrong line. The note comes back to **To do** to choose again |
| A note was entered by mistake | Open the order, **Cancel document** (stock is given back, history kept). Deleting the file does **not** cancel it |
| A note file was deleted from the folder | The stock does not change. **To do** offers **Restore file**, **Cancel document** or **Ignore** |
| A note file was edited after it was read | **To do** offers **Use new version** or **Keep old version** |
| You want to go back to an earlier day | **Settings → Data transfer and backups**, pick a backup, **Restore selected** |

### Sending the log when something goes wrong

The app writes what you do and every error into a log (1 MB at most; when full, the oldest part is dropped). When something goes wrong, send the log to whoever looks after the app, so they can see where the problem is:

1. Open **Settings → General**.
2. Click the version number **3 times quickly**. A small **Log…** button appears next to it.
3. Click **Log…** → **Save to a file…**. The app saves `NhatKy_<date time>.log` in the `output/` folder.
4. Send that file by Zalo or e-mail.

> ⚠ The log contains customer names and file names. Send it only to whoever looks after the app; never post it publicly.

## FAQ

**If I drop the same note in twice, is it subtracted twice?** No. The app recognises a note by the file's content, even after it is renamed or moved to another folder.

**What if a note is edited after the app has read it?** The app asks whether to use the new version or keep the old one; it never changes the numbers by itself.

**Why is a stock negative?** The app does not block it, because a note records what really happened. It usually means a goods in or a stock count is missing.

**Change the language?** **Settings → General → Language**.

**Edge says "DiBeKho-windows-setup.exe isn't commonly downloaded" and cancels the download?** Edge warns because the installer has no code signature (the app is safe). Quickest: download the **`.zip`** from [Downloads](#downloads), open it and double-click the installer inside. Or keep the blocked file: in Edge's download list, hover over it → click **…** → **Keep** → **Show more** → **Keep anyway**.

**Text and buttons too small or too big?** **Settings → General → Text and button size** (100–150%), then close and reopen the app.

**Where is my data?** All in one folder, by default `Documents/DiBeKho`:

```
DiBeKho/
├── phieu-giao-hang/   ← put delivery notes here
│   └── da-xu-ly/      ← notes fully recorded
├── input/             ← old-style goods-in files, or a data package from another computer
│   └── da-xu-ly/      ← files already imported
├── output/            ← Excel reports, goods-in receipts (hang-ve/), data packages, saved logs
├── sao-luu/           ← automatic backups
└── data/              ← the app's own data (do not edit)
```

## Screenshots

<table>
  <tr>
    <td width="50%"><img src="docs/images/en/can-xu-ly.png" alt="To do"><br><b>To do:</b> match unknown names, drop shipping-fee lines</td>
    <td width="50%"><img src="docs/images/en/tra-cuu.png" alt="Search"><br><b>Search:</b> accent-insensitive search across everything</td>
  </tr>
  <tr>
    <td><img src="docs/images/en/thong-ke.png" alt="Statistics"><br><b>Statistics:</b> in, out and stock per period, Excel export</td>
    <td><img src="docs/images/en/chi-tiet-khach.png" alt="Customer details"><br><b>Customer details:</b> revenue, products they buy most, every order with its prices</td>
  </tr>
</table>

<sub>Screenshots use made-up data, not real customer data.</sub>

## For developers

[![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/PySide6-Qt%206.10-41CD52?logo=qt&logoColor=white)](https://doc.qt.io/qtforpython-6/)
[![SQLite](https://img.shields.io/badge/SQLite-local-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org/)

Needs [**uv**](https://docs.astral.sh/uv/) (it downloads Python 3.13 and the libraries into the project's `.venv/`).

```bash
uv sync                 # set up the environment
uv run dibekho          # run the app from source
uv run pytest -q        # run the tests
uv run ruff check src tests --select F,E9
```

- **Build and release:** push a `v*` tag → GitHub Actions builds the Mac and Windows versions and publishes them under **Releases**. Building on your own machine: [docs/chay-thu-va-build.md](docs/chay-thu-va-build.md) (Vietnamese).
- **Source:** `src/dibekho/` has `db/` (SQLite, migrations), `core/` (business logic), `excel/` (Excel reading and writing), `ui/` (PySide6) and `i18n/`. `core/`, `excel/` and `db/` never import Qt, so they are tested with pytest without opening a window.
- **Rule:** stock = the sum of stock movements and is never edited directly; cancelling a note adds the opposite movements.
- **Licenses:** after changing a dependency, run `uv run python scripts/make_licenses.py` (a test checks the versions).
- **Privacy:** real customer Excel files and `.dibekho` packages are never committed (`samples/`, root `*.xlsx` and `*.dibekho` are in `.gitignore`).

## License

DiBeKho is open-source software under the [MIT License](LICENSE): you may use, copy, change and share it freely, keeping the copyright notice.

The app ships with third-party software under its own licenses, notably **Qt for Python (PySide6), under the GNU LGPL v3**, plus openpyxl (MIT) and Python (PSF). The full list and texts are in the app (**Settings → General → Open-source licenses…**) and in [src/dibekho/licenses/LICENSES.txt](src/dibekho/licenses/LICENSES.txt).
