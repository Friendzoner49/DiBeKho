/* DiBeKho web: the small "¥ ⇄ ₫" converter at the bottom left (customer's request 14/11/2026), like the app's
   (core/fx.py, ui/fx_dialog.py): type yuan or dong, the other box follows. The market rate comes from the free
   ExchangeRate-API endpoint (no key, updated once a day; its terms ask to name it next to the rate). The last rate
   is kept in this browser, so the converter still works offline and then says when the rate was fetched. One plain
   GET: nothing about the user or the shop is sent. */

"use strict";

const FX_URL = "https://open.er-api.com/v6/latest/CNY";
const FX_SOURCE = "ExchangeRate-API", FX_SOURCE_URL = "https://www.exchangerate-api.com";
const FX_KEY = "dibekho_fx";
const FX_FRESH_MS = 6 * 3600 * 1000;  // asked again when the window opens after 6 hours

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

function fxKeep(rate) { try { store("localStorage").setItem(FX_KEY, JSON.stringify(rate)); } catch (e) { /* only a cache */ } }

async function fxFetch() {
  const resp = await fetch(FX_URL, { headers: { Accept: "application/json" }, cache: "no-store" });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const rate = fxParse(await resp.json());
  fxKeep(rate);
  return rate;
}

const fxDay = (ms) => { const d = new Date(ms), p = (n) => String(n).padStart(2, "0"); return `${p(d.getDate())}/${p(d.getMonth() + 1)}/${d.getFullYear()}`; };
const fxTime = (ms) => { const d = new Date(ms), p = (n) => String(n).padStart(2, "0"); return `${fxDay(ms)} ${p(d.getHours())}:${p(d.getMinutes())}`; };
/** A number for the boxes: dong whole, yuan with up to 2 decimals, written with a comma on the Vietnamese page. */
const fxBox = (n, decimals) => { const s = String(Math.round(n * 10 ** decimals) / 10 ** decimals); return LANG === "vi" ? s.replace(".", ",") : s; };

function openConverter() {
  let rate = fxCached(), fromCny = true;
  openDialog(tr("fx.title"),
    `<div class="form2 fx">
       <label for="fx-cny">${esc(tr("fx.cny"))}</label><span class="fx-box"><input id="fx-cny" class="qty" inputmode="decimal" value="1"><b>¥</b></span>
       <label for="fx-vnd">${esc(tr("fx.vnd"))}</label><span class="fx-box"><input id="fx-vnd" class="qty" inputmode="decimal"><b>₫</b></span>
     </div>
     <p id="fx-info"></p>
     <p class="hint">${esc(tr("fx.source_before"))} <a href="${FX_SOURCE_URL}" target="_blank" rel="noopener noreferrer">${FX_SOURCE}</a>${esc(tr("fx.source_after"))}</p>
     <div class="row"><button id="fx-refresh">${esc(tr("fx.refresh"))}</button></div>`, []);
  dlg.classList.add("narrow");
  const show = (problem) => {
    if (!rate) { $("fx-info").textContent = tr(problem ? "fx.no_rate_error" : "fx.no_rate"); return; }
    $("fx-info").textContent = tr("fx.rate", { rate: fmtMoney(Math.round(rate.vnd_per_cny)), when: fxDay(rate.updated) }) +
      (problem ? "\n" + tr("fx.offline", { when: fxTime(rate.fetched) }) : "");
  };
  const convert = () => {
    if (!rate) return;
    if (fromCny) { const v = parseQty($("fx-cny").value); $("fx-vnd").value = v === null || Number.isNaN(v) ? "" : fxBox(v * rate.vnd_per_cny, 0); }
    else { const v = parseQty($("fx-vnd").value); $("fx-cny").value = v === null || Number.isNaN(v) ? "" : fxBox(v / rate.vnd_per_cny, 2); }
  };
  $("fx-cny").addEventListener("input", () => { fromCny = true; convert(); });
  $("fx-vnd").addEventListener("input", () => { fromCny = false; convert(); });
  const refresh = async () => {
    const btn = $("fx-refresh");
    btn.disabled = true; btn.textContent = tr("fx.refreshing");
    let problem = "";
    try { rate = await fxFetch(); } catch (e) { problem = String(e && e.message || e) || "?"; }
    if (!document.body.contains(btn)) return;  // the window was closed meanwhile
    btn.disabled = false; btn.textContent = tr("fx.refresh");
    show(problem); convert();
  };
  $("fx-refresh").addEventListener("click", refresh);
  show(""); convert();
  if (!rate || Date.now() - rate.fetched > FX_FRESH_MS) refresh();
}

$("fx-btn").addEventListener("click", openConverter);
