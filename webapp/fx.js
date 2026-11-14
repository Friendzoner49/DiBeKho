/* DiBeKho web: the "₫ | ¥" switch at the bottom left (user's request 14/11/2026), like the app's
   (core/fx.py, ui/currency_switch.py): ¥ shows every amount of the page (revenue, prices, totals, the overview,
   statistics) in yuan at today's market rate; ₫ goes back to dong. The data and every file (CSV, packages, the
   Phiếu xuất kho) stay in VND: fmtMoney (app.js) only changes the text on screen.

   The rate comes from the free ExchangeRate-API endpoint (no key, updated once a day; its terms ask to name it next
   to the rate), kept in this browser for offline use and fetched again when older than 6 hours. One plain GET:
   nothing about the user or the shop is sent. */

"use strict";

const FX_URL = "https://open.er-api.com/v6/latest/CNY";
const FX_SOURCE = "ExchangeRate-API";
const FX_KEY = "dibekho_fx", CUR_KEY = "dibekho_currency";
const FX_FRESH_MS = 6 * 3600 * 1000;

/** The provider's JSON -> {vnd_per_cny, updated (ms), fetched (ms)}; throws when it is not a usable answer. */
function fxParse(answer, fetched = Date.now()) {
  if (!answer || answer.result !== "success" || answer.base_code !== "CNY") throw new Error(tr("fx.bad_answer"));
  const vnd = (answer.rates || {}).VND;
  if (typeof vnd !== "number" || !(vnd > 0)) throw new Error(tr("fx.bad_answer"));
  return { vnd_per_cny: vnd, updated: Number(answer.time_last_update_unix || 0) * 1000, fetched };
}

function fxCached() {
  try {
    const r = JSON.parse(store("localStorage").getItem(FX_KEY) || "null");
    return r && r.vnd_per_cny > 0 ? r : null;
  } catch (e) { return null; }
}

function keep(key, value) { try { store("localStorage").setItem(key, value); } catch (e) { /* only a preference */ } }

async function fxFetch() {
  const resp = await fetch(FX_URL, { headers: { Accept: "application/json" }, cache: "no-store" });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const rate = fxParse(await resp.json());
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
  info.textContent = tr("fx.rate_short", { rate: Math.round(FX.rate.vnd_per_cny).toLocaleString("vi-VN"), when: fxDay(FX.rate.updated) }) +
    (problem ? "\n" + tr("fx.offline", { when: fxTime(FX.rate.fetched) }) : "");
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
$("fx-info").title = tr("fx.source", { source: FX_SOURCE });
for (const b of document.querySelectorAll("[data-cur]")) b.addEventListener("click", () => fxChoose(b.dataset.cur));
$("fx-refresh").addEventListener("click", () => fxRefresh(true));
fxShow();
if (moneyInCny() && Date.now() - FX.rate.fetched > FX_FRESH_MS) fxRefresh(false);
