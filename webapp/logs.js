/* DiBeKho web: Cài đặt → Nhật ký (the maychinh login only, like Tài khoản). Every account's activity log, one row per
   account + machine + day, names already hidden by the app before sending (core/cloud/logs.py). Read only through
   cloud/supabase/017_app_logs.sql (log_list / log_get refuse every other login, the other owners included). */

"use strict";

let logRows = [];
let logText = "";
const logKey = (r) => `${r.user_id}|${r.device}|${r.day}`;

async function loadLogs() {
  $("log-msg").textContent = tr("logs.loading");
  try {
    const { data, error } = await sb.rpc("log_list", {});
    if (error) throw error;
    logRows = (data || []).map((r) => ({ ...r, id: logKey(r) }));
    $("log-msg").textContent = tr("logs.loaded", { n: logRows.length });
  } catch (e) {
    logRows = [];
    const text = String(e && e.message || e);
    $("log-msg").textContent = /log_list|could not find|does not exist/i.test(text) ? tr("logs.no_sql") : text;
  }
  buildTable("log-table", [
    { label: tr("logs.col_day"), get: (r) => r.day },
    { label: tr("logs.col_user"), get: (r) => r.sender },
    { label: tr("logs.col_device"), get: (r) => r.device },
    { label: tr("logs.col_version"), get: (r) => r.version },
    { label: tr("logs.col_errors"), get: (r) => Number(r.errors || 0), num: true },
    { label: tr("logs.col_size"), get: (r) => Math.max(1, Math.round(Number(r.bytes || 0) / 1024)), num: true },
  ], logRows, { select: "one", rowClass: (r) => (Number(r.errors) > 0 ? "low" : "") });
}

function renderLogText() {
  const want = $("log-filter").value.trim().toLowerCase();
  const errorsOnly = $("log-errors").checked;
  // an event is its first line plus the indented lines under it (a traceback)
  const events = [];
  for (const line of logText.split("\n")) {
    if (line.startsWith("    ") && events.length) events[events.length - 1] += "\n" + line;
    else if (line) events.push(line);
  }
  const shown = events.filter((e) => (!errorsOnly || /\[(error|crash)\]/.test(e)) && (!want || e.toLowerCase().includes(want)));
  $("log-text").textContent = shown.join("\n");
}

async function openLog() {
  const [id] = selected("log-table");
  const row = logRows.find((r) => r.id === id);
  if (!row) { alert(tr("logs.pick")); return; }
  const { data, error } = await sb.rpc("log_get", { p_user: row.user_id, p_device: row.device, p_day: row.day });
  if (error) { alert(String(error.message || error)); return; }
  logText = String(data || "");
  $("log-view").classList.remove("hidden");
  $("log-title").textContent = `${row.day} · ${row.sender} · ${row.device}`;
  $("log-view").dataset.name = `nhat-ky_${row.day}_${row.sender}_${row.device}.log`.replace(/[^\w.-]+/g, "_");
  renderLogText();
}

function saveLog() {
  if (!logText) return;
  const url = URL.createObjectURL(new Blob([logText], { type: "text/plain;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = $("log-view").dataset.name || "nhat-ky.log";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

document.querySelector('[data-stab="logs"]').addEventListener("click", loadLogs);
$("log-btn-open").addEventListener("click", openLog);
$("log-btn-reload").addEventListener("click", loadLogs);
$("log-btn-save").addEventListener("click", saveLog);
$("log-filter").addEventListener("input", renderLogText);
$("log-errors").addEventListener("change", renderLogText);
