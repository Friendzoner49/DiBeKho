/* DiBeKho web: the "₫ | ¥" switch at the bottom left (user's request 14/11/2026), like the app's
   (core/fx.py, ui/currency_switch.py): ¥ shows every amount of the page (revenue, prices, totals, the overview,
   statistics) in yuan at today's market rate; ₫ goes back to dong. The data and every file (CSV, packages, the
   Phiếu xuất kho) stay in VND: fmtMoney (app.js) only changes the text on screen.

   The rate comes from FXRatesAPI (no key, the market rate of the minute; user 15/11/2026: the once-a-day rate "does
   not work in real time"), and from the free ExchangeRate-API endpoint (once a day) when the first does not answer;
   both ask to be named next to the rate. Kept in this browser for offline use and fetched again when older than ten
   minutes (every ten minutes while yuan is shown). One plain GET: nothing about the user or the shop is sent. */

"use strict";

const FX_URL = "https://api.fxratesapi.com/latest?base=CNY&currencies=VND";
const FX_SOURCE = "FXRatesAPI";
const FX_DAILY_URL = "https://open.er-api.com/v6/latest/CNY";  // the fallback: one rate a day
const FX_DAILY_SOURCE = "ExchangeRate-API";
const FX_KEY = "dibekho_fx", CUR_KEY = "dibekho_currency";
const FX_FRESH_MS = 10 * 60 * 1000;

/** A provider's JSON -> {vnd_per_cny, updated (ms), fetched (ms), source}; throws when it is not a usable answer
    (core/fx.parse: FXRatesAPI {success, base, timestamp} or ExchangeRate-API {result, base_code, time_last_update_unix}). */
function fxParse(answer, fetched = Date.now()) {
  let stamp, source;
  if (answer && answer.success === true && answer.base === "CNY") { stamp = answer.timestamp; source = FX_SOURCE; }
  else if (answer && answer.result === "success" && answer.base_code === "CNY") { stamp = answer.time_last_update_unix; source = FX_DAILY_SOURCE; }
  else throw new Error(tr("fx.bad_answer"));
  const vnd = (answer.rates || {}).VND;
  if (typeof vnd !== "number" || !(vnd > 0)) throw new Error(tr("fx.bad_answer"));
  return { vnd_per_cny: vnd, updated: Number(stamp || 0) * 1000, fetched, source };
}

function fxCached() {
  try {
    const r = JSON.parse(store("localStorage").getItem(FX_KEY) || "null");
    return r && r.vnd_per_cny > 0 ? r : null;
  } catch (e) { return null; }
}

function keep(key, value) { try { store("localStorage").setItem(key, value); } catch (e) { /* only a preference */ } }

async function fxGet(url) {
  const resp = await fetch(url, { headers: { Accept: "application/json" }, cache: "no-store" });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return fxParse(await resp.json());
}

async function fxFetch() {
  let rate;
  try { rate = await fxGet(FX_URL); } catch (e) { rate = await fxGet(FX_DAILY_URL); }
  keep(FX_KEY, JSON.stringify(rate));
  return rate;
}

const fxDay = (ms) => { const d = new Date(ms), p = (n) => String(n).padStart(2, "0"); return `${p(d.getDate())}/${p(d.getMonth() + 1)}`; };
const fxTime = (ms) => { const d = new Date(ms), p = (n) => String(n).padStart(2, "0"); return `${fxDay(ms)} ${p(d.getHours())}:${p(d.getMinutes())}`; };

let fxBusy = false;

function fxShow(problem = "") {
  for (const b of document.querySelectorAll("[data-cur]")) b.classList.toggle("on", b.dataset.cur === (moneyInCny() ? "cny" : "vnd"));
  const info = $("fx-info");
  if (!FX.rate) { info.textContent = fxBusy ? tr("fx.no_rate") : problem ? tr("fx.no_rate_error") : ""; return; }
  info.textContent = tr("fx.rate_short", { rate: Math.round(FX.rate.vnd_per_cny).toLocaleString("vi-VN"), when: fxTime(FX.rate.updated) }) +
    (problem ? "\n" + tr("fx.offline", { when: fxTime(FX.rate.fetched) }) : "");
  info.title = tr("fx.source", { source: FX.rate.source || FX_DAILY_SOURCE });
}

/** Show the amounts in dong or yuan; yuan needs a rate (fetched first when this browser has none). */
async function fxChoose(currency, explicit = true) {
  if (currency === "cny" && !FX.rate) await fxRefresh(explicit);
  if (currency === "cny" && !FX.rate) { FX.currency = "vnd"; fxShow(); return; }
  FX.currency = currency;
  keep(CUR_KEY, currency);
  fxShow();
  renderAll();
  if (currency === "cny" && Date.now() - FX.rate.fetched > FX_FRESH_MS) fxRefresh(false);
}

async function fxRefresh(explicit = true) {
  if (fxBusy) return;
  fxBusy = true;
  $("fx-refresh").disabled = true;
  fxShow();
  let problem = "";
  try { FX.rate = await fxFetch(); } catch (e) { problem = String(e && e.message || e) || "?"; }
  fxBusy = false;
  $("fx-refresh").disabled = false;
  fxShow(problem);
  if (!problem && moneyInCny()) renderAll();  // a new rate: the amounts change
  if (!FX.rate && explicit) alert(tr("fx.no_rate_error"));
}

FX.rate = fxCached();
FX.currency = (() => { try { return store("localStorage").getItem(CUR_KEY) === "cny" && FX.rate ? "cny" : "vnd"; } catch (e) { return "vnd"; } })();
for (const b of document.querySelectorAll("[data-cur]")) b.addEventListener("click", () => fxChoose(b.dataset.cur));
$("fx-refresh").addEventListener("click", () => fxRefresh(true));
fxShow();
if (moneyInCny() && Date.now() - FX.rate.fetched > FX_FRESH_MS) fxRefresh(false);
// the page stays open all day: while yuan is shown the rate follows the market (not under an open window)
setInterval(() => { if (moneyInCny() && !document.querySelector("dialog[open]")) fxRefresh(false); }, FX_FRESH_MS);
