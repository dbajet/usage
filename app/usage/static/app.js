"use strict";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

let state = {
  me: null,
  admin: null,
  dashboard: null,
  meters: null,
  houseId: 0,
  entriesPage: 1,
  readingSource: "manual",
};

const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const VIZ_COLORS = ["var(--viz-1)", "var(--viz-2)", "var(--viz-3)"];

function esc(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function beginButtonBusy() {
  const button = document.activeElement;
  if (!(button instanceof HTMLButtonElement) || button.disabled) return null;
  button.classList.add("busy");
  button.disabled = true;
  return button;
}

function endButtonBusy(button) {
  if (!button) return;
  button.classList.remove("busy");
  button.disabled = false;
}

async function api(path, options = {}) {
  const busyButton = beginButtonBusy();
  try {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    if (!response.ok) {
      let message = "The request failed.";
      try { message = (await response.json()).detail || message; } catch (_) {}
      throw new Error(message);
    }
    if (response.status === 204) return {};
    return await response.json();
  } finally { endButtonBusy(busyButton); }
}

function showLoginError(error) {
  const target = $("#login-error");
  target.textContent = error.message || String(error);
  target.hidden = false;
  $("#login-notice").hidden = true;
}

function showLoginNotice(message) {
  const target = $("#login-notice");
  target.textContent = message;
  target.hidden = false;
  $("#login-error").hidden = true;
}

function showAppError(error) {
  const target = $("#app-error");
  target.textContent = error.message || String(error);
  target.hidden = false;
  setTimeout(() => { target.hidden = true; }, 6000);
}

function openModal({ title, message = "", fields = [], options = [], submitLabel = "Save", danger = false, remove = false }) {
  return new Promise((resolve) => {
    const backdrop = $("#modal-backdrop");
    $("#modal-title").textContent = title;
    const messageTarget = $("#modal-message");
    messageTarget.textContent = message;
    messageTarget.hidden = !message;
    $("#modal-fields").innerHTML = options.length
      ? options.map((option) => `
          <button class="ghost option${option.active ? " active" : ""}" type="button" data-modal-option="${esc(String(option.value))}">
            ${esc(option.label)}
          </button>`).join("")
      : fields.map((field) => {
          if (field.type === "checkbox") {
            return `<label class="check"><input type="checkbox" data-modal-field="${esc(field.name)}"${field.value ? " checked" : ""}> ${esc(field.label)}</label>`;
          }
          const step = field.type === "number" ? ' step="0.01"' : "";
          return `<label>${esc(field.label)}<input type="${esc(field.type || "text")}"${step} data-modal-field="${esc(field.name)}" value="${esc(field.value ?? "")}"></label>`;
        }).join("");
    $("#modal-submit").hidden = Boolean(options.length);
    $("#modal-submit").textContent = submitLabel;
    $("#modal-submit").classList.toggle("danger", danger);
    $("#modal-submit").classList.toggle("primary", !danger);
    $("#modal-remove").hidden = !remove;
    backdrop.hidden = false;
    const first = $("#modal-fields input:not([type=checkbox])");
    if (first) first.focus();

    const close = (result) => {
      backdrop.hidden = true;
      $("#modal-form").onsubmit = null;
      $("#modal-cancel").onclick = null;
      $("#modal-remove").onclick = null;
      backdrop.onclick = null;
      document.onkeydown = null;
      resolve(result);
    };
    $("#modal-remove").onclick = () => close({ __remove: true });
    $("#modal-form").onsubmit = (event) => {
      event.preventDefault();
      const values = {};
      $$("#modal-fields [data-modal-field]").forEach((input) => {
        values[input.dataset.modalField] = input.type === "checkbox" ? input.checked : input.value;
      });
      close(values);
    };
    $$("#modal-fields [data-modal-option]").forEach((button) =>
      button.addEventListener("click", () => close({ value: button.dataset.modalOption })));
    $("#modal-cancel").onclick = () => close(null);
    backdrop.onclick = (event) => { if (event.target === backdrop) close(null); };
    document.onkeydown = (event) => { if (event.key === "Escape") close(null); };
  });
}

async function confirmModal(title, message, submitLabel = "Delete") {
  return (await openModal({ title, message, submitLabel, danger: true })) !== null;
}

function storedItem(key, fallback) {
  try { return localStorage.getItem(key) || fallback; } catch (_) { return fallback; }
}

function storeItem(key, value) {
  try { localStorage.setItem(key, String(value)); } catch (_) {}
}

function showView(name) {
  storeItem("usage-view", name);
  // Entries fits the viewport: the table body scrolls, never the page.
  document.body.classList.toggle("view-fixed", name === "entries");
  $$(".app-nav button").forEach((item) => item.classList.toggle("active", item.dataset.nav === name));
  $$(".app-main > section").forEach((section) => { section.hidden = section.id !== `view-${name}`; });
  if (name === "settings") {
    let tab = storedItem("usage-settings-tab", "meters");
    if (!state.me.is_admin && (tab === "houses" || tab === "users")) tab = "meters";
    showSettingsTab(tab);
    loadPasskeys();
    loadMeters();
    if (state.me && state.me.is_admin) loadAdmin();
  }
  if (name === "entries") loadEntries();
  if (name === "stats") loadStats();
}

async function load() {
  const params = new URLSearchParams(location.search);
  const loginToken = params.get("login");
  if (loginToken) {
    history.replaceState(null, "", location.pathname);
    try {
      await api("/api/auth/verify-link", { method: "POST", body: JSON.stringify({ token: loginToken }) });
    } catch (error) {
      showPublic();
      showLoginError(error);
      return;
    }
  }
  try {
    const session = await api("/api/session");
    if (!session.authenticated) { showPublic(); return; }
    state.me = await api("/api/me");
    showApp();
  } catch (error) {
    showPublic();
  }
}

function showPublic() {
  $("#login").hidden = false;
  $("#app").hidden = true;
}

function showApp() {
  $("#login").hidden = true;
  $("#app").hidden = false;
  $("#me-line").textContent = `${state.me.name || state.me.email} · ${state.me.email}` + (state.me.is_admin ? " · admin" : "");
  api("/api/version")
    .then((data) => {
      $("#version .version-text").textContent = `v${data.version}` + (data.build ? ` · ${data.build}` : "");
      $("#version").hidden = false;
    })
    .catch(() => {});
  const view = storedItem("usage-view", "stats");
  showView(["stats", "entries", "settings"].includes(view) ? view : "stats");
}

async function requestLink(event) {
  event.preventDefault();
  try {
    const email = $("#login-email").value.trim();
    const data = await api("/api/auth/request-link", { method: "POST", body: JSON.stringify({ email }) });
    if (data.dev_link) {
      const target = $("#login-notice");
      target.innerHTML = `Development mode — <a href="${esc(data.dev_link)}">click here to sign in</a>`;
      target.hidden = false;
      $("#login-error").hidden = true;
    } else {
      showLoginNotice(data.message);
    }
  } catch (error) { showLoginError(error); }
}

function bufferToBase64url(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  bytes.forEach((value) => { binary += String.fromCharCode(value); });
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function base64urlToBuffer(value) {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - value.length % 4) % 4);
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes.buffer;
}

async function signInWithPasskey() {
  try {
    const email = $("#login-email").value.trim();
    if (!email) {
      showLoginError(new Error("Enter your email first."));
      return;
    }
    const options = await api("/api/auth/passkey/options", { method: "POST", body: JSON.stringify({ email }) });
    const assertion = await navigator.credentials.get({ publicKey: {
      challenge: base64urlToBuffer(options.challenge),
      rpId: options.rp_id,
      allowCredentials: (options.allow_credentials || []).map((id) => ({ type: "public-key", id: base64urlToBuffer(id) })),
      userVerification: "preferred",
      timeout: 60000,
    } });
    await api("/api/auth/passkey/verify", { method: "POST", body: JSON.stringify({
      credential_id: bufferToBase64url(assertion.rawId),
      client_data: bufferToBase64url(assertion.response.clientDataJSON),
      authenticator_data: bufferToBase64url(assertion.response.authenticatorData),
      signature: bufferToBase64url(assertion.response.signature),
    }) });
    await load();
  } catch (error) { showLoginError(error); }
}

async function registerPasskey() {
  try {
    const options = await api("/api/passkeys/options", { method: "POST", body: "{}" });
    const credential = await navigator.credentials.create({ publicKey: {
      challenge: base64urlToBuffer(options.challenge),
      rp: { id: options.rp_id, name: options.rp_name },
      user: {
        id: base64urlToBuffer(options.user_id),
        name: options.user_name,
        displayName: options.user_display_name,
      },
      pubKeyCredParams: [{ type: "public-key", alg: -7 }, { type: "public-key", alg: -257 }],
      excludeCredentials: (options.exclude_credentials || []).map((id) => ({ type: "public-key", id: base64urlToBuffer(id) })),
      authenticatorSelection: { residentKey: "preferred", userVerification: "preferred" },
      timeout: 60000,
    } });
    await api("/api/passkeys", { method: "POST", body: JSON.stringify({
      credential_id: bufferToBase64url(credential.rawId),
      client_data: bufferToBase64url(credential.response.clientDataJSON),
      attestation_object: bufferToBase64url(credential.response.attestationObject),
    }) });
    await loadPasskeys();
  } catch (error) { showAppError(error); }
}

async function loadPasskeys() {
  try {
    const data = await api("/api/passkeys");
    $("#passkey-list").innerHTML = (data.passkeys || []).map((item) => `
      <div class="mini-row">
        <span><strong>Passkey</strong> · added ${esc(String(item.created_at || "").slice(0, 10))}</span>
        <button class="ghost compact" data-delete-passkey="${item.id}" type="button">Remove</button>
      </div>`).join("") || '<p class="meta">No passkey registered yet.</p>';
    $$("[data-delete-passkey]").forEach((button) => button.addEventListener("click", async () => {
      try {
        await api(`/api/passkeys/${button.dataset.deletePasskey}`, { method: "DELETE" });
        await loadPasskeys();
      } catch (error) { showAppError(error); }
    }));
  } catch (error) { showAppError(error); }
}

async function ensureDashboard() {
  state.dashboard = await api("/api/dashboard");
  const houses = state.dashboard.houses || [];
  if (!state.houseId) state.houseId = Number(storedItem("usage-house", "0"));
  if (!houses.some((house) => house.id === state.houseId)) {
    state.houseId = houses.length ? houses[0].id : 0;
  }
  storeItem("usage-house", state.houseId);
  const current = houses.find((house) => house.id === state.houseId);
  $("#house-name").textContent = current ? current.name : "";
  $("#house-btn").hidden = houses.length < 2;
}

function currentView() {
  const active = $(".app-nav button.active");
  return active ? active.dataset.nav : "stats";
}

async function chooseHouse() {
  const houses = (state.dashboard && state.dashboard.houses) || [];
  const choice = await openModal({
    title: "Choose the house",
    options: houses.map((house) => ({ value: house.id, label: house.name, active: house.id === state.houseId })),
  });
  if (choice === null || Number(choice.value) === state.houseId) return;
  state.houseId = Number(choice.value);
  storeItem("usage-house", state.houseId);
  state.entriesPage = 1;
  const current = houses.find((house) => house.id === state.houseId);
  $("#house-name").textContent = current ? current.name : "";
  showView(currentView());
}

async function loadEntries() {
  try {
    await ensureDashboard();
    renderReadingForm();
    await loadReadings(state.entriesPage);
  } catch (error) { showAppError(error); }
}

function houseMeters() {
  return (state.dashboard.meters || []).filter((meter) => meter.house_id === state.houseId);
}

function renderReadingForm() {
  const meters = houseMeters();
  const select = $("#reading-meter");
  select.innerHTML = meters.map((meter) => `<option value="${meter.id}">${esc(meter.label || meter.kind)} (${esc(meter.kind)})</option>`).join("");
  renderValueInputs();
}

function selectedMeter() {
  return houseMeters().find((meter) => meter.id === Number($("#reading-meter").value));
}

function renderValueInputs() {
  const meter = selectedMeter();
  state.readingSource = "manual";
  $("#reading-hint").hidden = true;
  $("#reading-values").innerHTML = (meter ? meter.registers : []).map((register) => `
    <input type="number" step="0.01" data-register-value="${register.id}"
      placeholder="${esc(register.label || "Counter")}${meter.unit ? ` (${esc(meter.unit)})` : ""}" required>`).join("");
}

async function readPhoto() {
  const meter = selectedMeter();
  const file = $("#reading-photo").files[0];
  if (!meter) { showAppError(new Error("Add a meter first.")); return; }
  if (!file) { showAppError(new Error("Choose a photo first.")); return; }
  try {
    const dataUrl = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(new Error("The photo could not be loaded."));
      reader.readAsDataURL(file);
    });
    const data = await api("/api/readings/extract", { method: "POST", body: JSON.stringify({
      meter_id: meter.id,
      media_type: file.type,
      image_base64: String(dataUrl).split(",")[1] || "",
    }) });
    let missing = false;
    (data.values || []).forEach((item) => {
      const input = $(`[data-register-value="${item.register_id}"]`);
      if (input && item.value !== null) input.value = item.value;
      if (item.value === null) missing = true;
    });
    state.readingSource = "photo";
    const hint = $("#reading-hint");
    hint.textContent = missing
      ? "Some registers could not be read - fill them in and verify the rest."
      : "Values read from the photo - please verify before saving.";
    hint.hidden = false;
  } catch (error) { showAppError(error); }
}

function currentMonthValue() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function previousMonthValue(value) {
  const year = Number(value.slice(0, 4));
  const month = Number(value.slice(5, 7));
  const shifted = month === 1 ? `${year - 1}-12` : `${year}-${String(month - 1).padStart(2, "0")}`;
  return shifted;
}

function openReadingModal() {
  const meters = houseMeters();
  if (!meters.length) { showAppError(new Error("Add a meter first (Settings, Meters).")); return; }
  renderReadingForm();
  $("#reading-month").value = currentMonthValue();
  $("#reading-photo").value = "";
  $("#reading-modal").hidden = false;
}

function closeReadingModal() {
  $("#reading-modal").hidden = true;
}

function pastePhoto(event) {
  if ($("#reading-modal").hidden) return;
  const item = Array.from(event.clipboardData ? event.clipboardData.items : [])
    .find((entry) => entry.type.startsWith("image/"));
  if (!item) return;
  event.preventDefault();
  const file = item.getAsFile();
  if (!file) return;
  const transfer = new DataTransfer();
  transfer.items.add(file);
  $("#reading-photo").files = transfer.files;
  readPhoto();
}

async function addReading(event) {
  event.preventDefault();
  const meter = selectedMeter();
  if (!meter) { showAppError(new Error("Add a meter first.")); return; }
  const values = $$("#reading-values [data-register-value]").map((input) => ({
    register_id: Number(input.dataset.registerValue),
    value: Number(input.value),
  }));
  try {
    // A monthly reading is stored mid-month, like the imported history.
    await api("/api/readings", { method: "POST", body: JSON.stringify({
      meter_id: meter.id,
      read_on: `${$("#reading-month").value}-15`,
      source: state.readingSource,
      values,
    }) });
    $("#reading-photo").value = "";
    renderValueInputs();
    closeReadingModal();
    await loadReadings(1);
  } catch (error) { showAppError(error); }
}

async function loadReadings(page) {
  if (!state.houseId) {
    $("#reading-list").innerHTML = '<p class="meta">No house is linked to your account yet.</p>';
    $("#reading-pager").innerHTML = "";
    return;
  }
  try {
    const data = await api(`/api/readings?house_id=${state.houseId}&page=${page}`);
    state.entriesPage = data.page;
    renderReadings(data);
  } catch (error) { showAppError(error); }
}

function fmtThousand(value) {
  return Number(value).toLocaleString("en-US");
}

function renderReadings(data) {
  const readings = data.readings || [];
  if (!readings.length) {
    $("#reading-list").innerHTML = '<p class="meta">No reading yet - add one with the button above.</p>';
    $("#reading-pager").innerHTML = "";
    return;
  }
  const meters = [];
  readings.forEach((reading) => {
    if (!meters.some((meter) => meter.id === reading.meter_id)) {
      meters.push({ id: reading.meter_id, label: reading.meter_label || reading.kind, unit: reading.unit });
    }
  });
  meters.sort((a, b) => a.id - b.id);
  const months = [...new Set(readings.map((reading) => reading.read_on))];
  const byKey = new Map(readings.map((reading) => [`${reading.read_on}|${reading.meter_id}`, reading]));
  const header = `<tr><th>Date</th>${meters.map((meter) =>
    `<th>${esc(meter.label)}${meter.unit ? ` <span class="meta">(${esc(meter.unit)})</span>` : ""}</th>`).join("")}</tr>`;
  let lastYear = "";
  const rows = months.map((month) => {
    const cells = meters.map((meter) => {
      const reading = byKey.get(`${month}|${meter.id}`);
      if (!reading) return "<td></td>";
      const text = reading.values.map((value) => fmtThousand(value.value)).join(" / ");
      const tip = reading.values.map((value) => `${value.label || "counter"}: ${fmtThousand(value.value)}`).join(" · ");
      return `<td class="cell-reading" data-edit-reading="${reading.id}" title="${esc(`${tip} · ${reading.source} · click to edit`)}">${text}</td>`;
    }).join("");
    const year = month.slice(0, 4);
    const monthName = MONTH_NAMES[Number(month.slice(5, 7)) - 1];
    const newYear = year !== lastYear;
    const label = newYear ? `<strong>${esc(year)}</strong>&nbsp;·&nbsp;${monthName}` : monthName;
    lastYear = year;
    return `<tr${newYear ? ' class="year-row"' : ""}><td title="${esc(month)}">${label}</td>${cells}</tr>`;
  }).join("");
  $("#reading-list").innerHTML = `<div class="table-wrap"><table><thead>${header}</thead><tbody>${rows}</tbody></table></div>`;
  const chevronLeft = '<svg class="msym" fill="currentColor" xmlns="http://www.w3.org/2000/svg" viewBox="0 -960 960 960"><path d="M560-240 320-480l240-240 56 56-184 184 184 184-56 56Z"/></svg>';
  const chevronRight = '<svg class="msym" fill="currentColor" xmlns="http://www.w3.org/2000/svg" viewBox="0 -960 960 960"><path d="M504-480 320-664l56-56 240 240-240 240-56-56 184-184Z"/></svg>';
  $("#reading-pager").innerHTML = `
    <button class="ghost compact icon-button" data-page="${data.page - 1}" type="button" aria-label="Previous page"${data.page <= 1 ? " disabled" : ""}>${chevronLeft}</button>
    <span class="meta">Page ${data.page} / ${data.pages} · ${data.total} months</span>
    <button class="ghost compact icon-button" data-page="${data.page + 1}" type="button" aria-label="Next page"${data.page >= data.pages ? " disabled" : ""}>${chevronRight}</button>`;
  $$("[data-page]").forEach((button) => button.addEventListener("click", () => loadReadings(Number(button.dataset.page))));
  $$("[data-edit-reading]").forEach((cell) => cell.addEventListener("click", () => editReading(Number(cell.dataset.editReading), data)));
  wireTableHover("#reading-list");
}

async function editReading(readingId, data) {
  const reading = (data.readings || []).find((item) => item.id === readingId);
  const answers = await openModal({
    title: `Edit reading · ${reading.meter_label || reading.kind}`,
    fields: [
      { name: "read_on", label: "Month", type: "month", value: reading.read_on.slice(0, 7) },
      ...reading.values.map((value) => ({
        name: `register-${value.register_id}`,
        label: value.label || "Counter",
        type: "number",
        value: value.value,
      })),
    ],
    remove: true,
  });
  if (answers === null) return;
  if (answers.__remove) {
    if (!await confirmModal("Delete reading", "Delete this reading?")) return;
    try {
      await api(`/api/readings/${readingId}`, { method: "DELETE" });
      await loadReadings(state.entriesPage);
    } catch (error) { showAppError(error); }
    return;
  }
  const values = reading.values.map((value) => ({
    register_id: value.register_id,
    value: Number(answers[`register-${value.register_id}`]),
  }));
  try {
    await api(`/api/readings/${readingId}`, { method: "PUT", body: JSON.stringify({ read_on: `${answers.read_on}-15`, values }) });
    await loadReadings(state.entriesPage);
  } catch (error) { showAppError(error); }
}

async function loadStats() {
  try {
    await ensureDashboard();
    if (!state.houseId) {
      $("#stats-content").innerHTML = '<p class="meta">No house is linked to your account yet.</p>';
      return;
    }
    const tables = await api(`/api/stats/tables?house_id=${state.houseId}`);
    const series = await api(`/api/stats/series?house_id=${state.houseId}`);
    renderStats(tables, series);
  } catch (error) { showAppError(error); }
}

function statsPrefs() {
  const defaults = { tables: true, graphs: true, merged: false, fromYear: 0, toYear: 9999 };
  try {
    return { ...defaults, ...JSON.parse(localStorage.getItem("usage-stats-prefs") || "{}") };
  } catch (_) {
    return defaults;
  }
}

function storeStatsPrefs(prefs) {
  try { localStorage.setItem("usage-stats-prefs", JSON.stringify(prefs)); } catch (_) {}
}

function saveStatsPrefs(event) {
  const tables = $("#stats-show-tables");
  const graphs = $("#stats-show-graphs");
  if (!tables.checked && !graphs.checked) {
    // At least one of the two stays on: hiding the last one re-enables the other.
    (event && event.target === tables ? graphs : tables).checked = true;
  }
  storeStatsPrefs({
    ...statsPrefs(),
    tables: tables.checked,
    graphs: graphs.checked,
    merged: $("#stats-merge-graphs").checked,
  });
  if (state.statsData) renderStats(state.statsData.tables, state.statsData.series);
}

function applyYearRange(from, to) {
  storeStatsPrefs({ ...statsPrefs(), fromYear: from, toYear: to });
  if (state.statsData) renderStats(state.statsData.tables, state.statsData.series);
}

function wireYearSlider() {
  const slider = $("#year-slider");
  let active = null;
  const yearAt = (event) => {
    const rect = slider.getBoundingClientRect();
    const bounds = state.yearBounds;
    const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    return Math.round(bounds.min + ratio * (bounds.max - bounds.min));
  };
  slider.addEventListener("pointerdown", (event) => {
    if (!state.yearBounds) return;
    event.preventDefault();
    const bounds = state.yearBounds;
    const year = yearAt(event);
    active = Math.abs(year - bounds.from) <= Math.abs(year - bounds.to) ? "from" : "to";
    slider.setPointerCapture(event.pointerId);
    if (active === "from") applyYearRange(Math.min(year, bounds.to), bounds.to);
    else applyYearRange(bounds.from, Math.max(year, bounds.from));
  });
  slider.addEventListener("pointermove", (event) => {
    if (!active || !state.yearBounds) return;
    const bounds = state.yearBounds;
    const year = yearAt(event);
    if (active === "from") {
      const from = Math.min(year, bounds.to);
      if (from !== bounds.from) applyYearRange(from, bounds.to);
    } else {
      const to = Math.max(year, bounds.from);
      if (to !== bounds.to) applyYearRange(bounds.from, to);
    }
  });
  const stop = () => { active = null; };
  slider.addEventListener("pointerup", stop);
  slider.addEventListener("pointercancel", stop);
  [["#year-thumb-from", "from"], ["#year-thumb-to", "to"]].forEach(([selector, which]) => {
    $(selector).addEventListener("keydown", (event) => {
      if (!state.yearBounds) return;
      const delta = event.key === "ArrowLeft" ? -1 : event.key === "ArrowRight" ? 1 : 0;
      if (!delta) return;
      event.preventDefault();
      const bounds = state.yearBounds;
      if (which === "from") {
        applyYearRange(Math.min(Math.max(bounds.min, bounds.from + delta), bounds.to), bounds.to);
      } else {
        applyYearRange(bounds.from, Math.max(Math.min(bounds.max, bounds.to + delta), bounds.from));
      }
    });
  });
}

function legendMarkup(seriesList) {
  if (seriesList.length < 2) return "";
  return `
    <div class="viz-legend">
      ${seriesList.map((item, index) => `<span><i style="background:${VIZ_COLORS[index % VIZ_COLORS.length]}"></i>${esc(item.label)}${item.unit ? ` (${esc(item.unit)})` : ""}</span>`).join("")}
    </div>`;
}

function yearFilter(tables, series) {
  const prefs = statsPrefs();
  const allYears = (tables.kinds || []).flatMap((kind) => kind.years.map((year) => year.year));
  const holder = $("#year-range");
  if (!allYears.length || Math.min(...allYears) === Math.max(...allYears)) {
    holder.hidden = true;
    return { tables, series };
  }
  const minYear = Math.min(...allYears);
  const maxYear = Math.max(...allYears);
  const fromYear = Math.min(Math.max(prefs.fromYear || minYear, minYear), maxYear);
  const toYear = Math.min(Math.max(prefs.toYear || maxYear, fromYear), maxYear);
  holder.hidden = false;
  state.yearBounds = { min: minYear, max: maxYear, from: fromYear, to: toYear };
  const span = Math.max(1, maxYear - minYear);
  const percent = (year) => ((year - minYear) * 100) / span;
  $("#year-range-label").textContent = fromYear === toYear ? String(fromYear) : `${fromYear} – ${toYear}`;
  $("#year-fill").style.left = `${percent(fromYear)}%`;
  $("#year-fill").style.width = `${percent(toYear) - percent(fromYear)}%`;
  $("#year-thumb-from").style.left = `calc(${percent(fromYear)}% - 8px)`;
  $("#year-thumb-to").style.left = `calc(${percent(toYear)}% - 8px)`;
  return {
    tables: {
      kinds: (tables.kinds || [])
        .map((kind) => ({ ...kind, years: kind.years.filter((year) => year.year >= fromYear && year.year <= toYear) }))
        .filter((kind) => kind.years.length),
    },
    series: {
      series: (series.series || [])
        .map((item) => ({
          ...item,
          points: item.points.filter((point) => {
            const year = Number(point.month.slice(0, 4));
            return year >= fromYear && year <= toYear;
          }),
        }))
        .filter((item) => item.points.length),
    },
  };
}

function renderStats(tables, series) {
  state.statsData = { tables, series };
  const prefs = statsPrefs();
  $("#stats-show-tables").checked = prefs.tables;
  $("#stats-show-graphs").checked = prefs.graphs;
  $("#stats-merge-graphs").checked = prefs.merged;
  if (!(tables.kinds || []).length) {
    $("#year-range").hidden = true;
    $("#stats-content").innerHTML = '<p class="meta">No reading yet - add measurements in Entries first.</p>';
    return;
  }
  const filtered = yearFilter(tables, series);
  const kinds = filtered.tables.kinds;
  let html = "";
  if (prefs.graphs && prefs.merged) {
    const allSeries = filtered.series.series;
    html += `
      <div class="card">
        <h3>Trends <span class="meta">(all meters, one scale)</span></h3>
        ${chartMarkup(allSeries, true)}
        ${legendMarkup(allSeries)}
      </div>`;
  }
  html += kinds.map((kind) => {
    const kindSeries = filtered.series.series.filter((item) => item.kind === kind.kind);
    const title = kind.kind.charAt(0).toUpperCase() + kind.kind.slice(1);
    const parts = [];
    if (prefs.tables) parts.push(`<div class="table-wrap">${statsTable(kind)}</div>`);
    if (prefs.graphs && !prefs.merged) parts.push(chartMarkup(kindSeries) + legendMarkup(kindSeries));
    if (!parts.length) return "";
    return `
      <div class="card">
        <h3>${esc(title)}${kind.unit ? ` <span class="meta">(${esc(kind.unit)} per month)</span>` : ""}</h3>
        ${parts.join("")}
      </div>`;
  }).join("");
  if (!html) html = '<p class="meta">Tables and graphs are both hidden - enable one above.</p>';
  $("#stats-content").innerHTML = html;
  wireTableHover("#stats-content");
  wireChartHover("#stats-content");
}

function clearTableHover(table) {
  table.querySelectorAll(".hl-col").forEach((cell) => cell.classList.remove("hl-col"));
  table.querySelectorAll(".hl-row").forEach((row) => row.classList.remove("hl-row"));
}

function wireTableHover(rootSelector) {
  $$(`${rootSelector} table`).forEach((table) => {
    table.addEventListener("mouseover", (event) => {
      const cell = event.target.closest("td, th");
      if (!cell || !table.contains(cell)) return;
      clearTableHover(table);
      Array.from(table.rows).forEach((row) => {
        const target = row.cells[cell.cellIndex];
        if (target) target.classList.add("hl-col");
      });
      cell.closest("tr").classList.add("hl-row");
    });
    table.addEventListener("mouseleave", () => clearTableHover(table));
  });
}

function fmtValue(value) {
  return String(Math.round(value * 100) / 100);
}

function statsTable(kind) {
  const header = `<tr><th>Year</th>${MONTH_NAMES.map((name) => `<th>${name}</th>`).join("")}<th>Total</th></tr>`;
  const rows = kind.years.map((year) => `
    <tr>
      <td>${year.year}</td>
      ${year.months.map((month) => `<td>${month === null ? "" : fmtValue(month)}</td>`).join("")}
      <td class="total">${fmtValue(year.total)}</td>
    </tr>`).join("");
  return `<table><thead>${header}</thead><tbody>${rows}</tbody></table>`;
}

function niceStep(rough) {
  const magnitude = Math.pow(10, Math.floor(Math.log10(rough)));
  const normalized = rough / magnitude;
  if (normalized <= 1) return magnitude;
  if (normalized <= 2) return 2 * magnitude;
  if (normalized <= 5) return 5 * magnitude;
  return 10 * magnitude;
}

function chartMarkup(seriesList, merged = false) {
  const months = [...new Set(seriesList.flatMap((item) => item.points.map((point) => point.month)))].sort();
  const pointCount = seriesList.reduce((count, item) => count + item.points.length, 0);
  if (months.length < 2 || pointCount < 2) return "";
  const width = 720;
  const height = 240;
  const left = 48;
  const right = 28;
  const top = 12;
  const bottom = 30;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const maxValue = Math.max(1, ...seriesList.flatMap((item) => item.points.map((point) => point.value)));
  const step = niceStep(maxValue / 4);
  const yMax = Math.ceil(maxValue / step) * step;
  const xAt = (month) => left + (months.indexOf(month) * plotWidth) / (months.length - 1);
  const yAt = (value) => top + plotHeight - (value / yMax) * plotHeight;

  const gridLines = [];
  const yLabels = [];
  for (let value = 0; value <= yMax; value += step) {
    const y = yAt(value);
    gridLines.push(`<line x1="${left}" y1="${y}" x2="${width - right}" y2="${y}"></line>`);
    yLabels.push(`<text x="${left - 6}" y="${y + 4}" text-anchor="end">${fmtValue(value)}</text>`);
  }
  const labelStep = Math.max(1, Math.ceil(months.length / 6));
  const xLabels = months
    .filter((month, index) => index % labelStep === 0)
    .map((month) => {
      const name = MONTH_NAMES[Number(month.slice(5, 7)) - 1];
      return `<text x="${xAt(month)}" y="${height - 8}" text-anchor="middle">${name} ${month.slice(2, 4)}</text>`;
    });

  const showDots = months.length <= 36;
  const paths = seriesList.map((item, index) => {
    const color = VIZ_COLORS[index % VIZ_COLORS.length];
    const path = item.points
      .map((point, pointIndex) => `${pointIndex === 0 ? "M" : "L"}${xAt(point.month).toFixed(1)},${yAt(point.value).toFixed(1)}`)
      .join(" ");
    const dots = showDots
      ? item.points.map((point) =>
          `<circle class="dot" cx="${xAt(point.month).toFixed(1)}" cy="${yAt(point.value).toFixed(1)}" r="3" fill="${color}"></circle>`).join("")
      : "";
    return `<g class="series"><path d="${path}" stroke="${color}"></path>${dots}</g>`;
  });

  const hoverY = `y1="${top}" y2="${top + plotHeight}"`;
  const config = {
    months,
    left,
    plotWidth,
    count: months.length,
    merged,
    series: seriesList.map((item) => ({
      label: item.label,
      unit: item.unit,
      values: Object.fromEntries(item.points.map((point) => [point.month, point.value])),
    })),
  };
  return `
    <div class="viz-holder" data-chart="${esc(JSON.stringify(config))}">
      <svg class="viz-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Monthly consumption trend">
        <g class="grid">${gridLines.join("")}</g>
        <g class="axis">${yLabels.join("")}${xLabels.join("")}</g>
        ${paths.join("")}
        <g class="viz-hover" hidden>
          <line class="hov-prev" ${hoverY} hidden></line>
          <line class="hov-next" ${hoverY} hidden></line>
          <line class="hov-main" ${hoverY}></line>
        </g>
      </svg>
      <div class="viz-tip" hidden></div>
    </div>`;
}

function wireChartHover(rootSelector) {
  $$(`${rootSelector} .viz-holder`).forEach((holder) => {
    const config = JSON.parse(holder.dataset.chart);
    const svg = holder.querySelector("svg");
    const hover = svg.querySelector(".viz-hover");
    const prevLine = hover.querySelector(".hov-prev");
    const nextLine = hover.querySelector(".hov-next");
    const mainLine = hover.querySelector(".hov-main");
    const tip = holder.querySelector(".viz-tip");
    const xAt = (index) => config.left + (index * config.plotWidth) / Math.max(1, config.count - 1);
    const shifted = (month, years) => `${Number(month.slice(0, 4)) + years}-${month.slice(5, 7)}`;
    const monthLabel = (month) => `${MONTH_NAMES[Number(month.slice(5, 7)) - 1]} ${month.slice(0, 4)}`;
    const setLine = (line, month) => {
      const index = config.months.indexOf(month);
      if (index < 0) { line.setAttribute("hidden", ""); return false; }
      line.removeAttribute("hidden");
      line.setAttribute("x1", xAt(index));
      line.setAttribute("x2", xAt(index));
      return true;
    };
    const rowFor = (month) => {
      const values = config.series
        .filter((series) => series.values[month] !== undefined)
        .map((series) => {
          const prefix = config.series.length > 1 ? `${series.label}: ` : "";
          return `${prefix}${fmtThousand(series.values[month])}${series.unit ? ` ${series.unit}` : ""}`;
        });
      if (!values.length) return "";
      return `<strong>${esc(monthLabel(month))}</strong> · ${esc(values.join(" · "))}`;
    };
    svg.addEventListener("mousemove", (event) => {
      const rect = svg.getBoundingClientRect();
      const x = ((event.clientX - rect.left) * 720) / rect.width;
      const index = Math.round(((x - config.left) * Math.max(1, config.count - 1)) / config.plotWidth);
      if (index < 0 || index >= config.count) {
        hover.setAttribute("hidden", "");
        tip.hidden = true;
        return;
      }
      const month = config.months[index];
      hover.removeAttribute("hidden");
      setLine(mainLine, month);
      const rows = [rowFor(month)];
      if (config.merged) {
        prevLine.setAttribute("hidden", "");
        nextLine.setAttribute("hidden", "");
      } else {
        // Year-over-year: one line twelve months back, one twelve months ahead.
        const before = shifted(month, -1);
        const after = shifted(month, 1);
        if (setLine(prevLine, before)) rows.push(rowFor(before));
        if (setLine(nextLine, after)) rows.push(rowFor(after));
      }
      tip.innerHTML = rows.filter(Boolean).join("<br>");
      tip.hidden = false;
      const holderRect = holder.getBoundingClientRect();
      let tipLeft = event.clientX - holderRect.left + 14;
      if (tipLeft + tip.offsetWidth > holderRect.width - 8) {
        tipLeft = Math.max(8, event.clientX - holderRect.left - tip.offsetWidth - 14);
      }
      tip.style.left = `${tipLeft}px`;
      tip.style.top = `${event.clientY - holderRect.top + 14}px`;
    });
    svg.addEventListener("mouseleave", () => {
      hover.setAttribute("hidden", "");
      tip.hidden = true;
    });
  });
}

async function loadAdmin() {
  try {
    state.admin = await api("/api/admin/overview");
    $$("#settings-tabs button").forEach((button) => { button.hidden = false; });
    renderHouses();
    renderUsers();
  } catch (error) { showAppError(error); }
}

async function loadMeters() {
  try {
    await ensureDashboard();
    const houses = state.dashboard.houses || [];
    const current = houses.find((house) => house.id === state.houseId);
    $("#meters-house-name").textContent = current ? current.name : "";
    if (!state.houseId) {
      state.meters = [];
      $("#meter-list").innerHTML = '<p class="meta">No house is linked to your account yet.</p>';
      $("#meter-form").hidden = true;
      return;
    }
    $("#meter-form").hidden = false;
    const data = await api(`/api/meters?house_id=${state.houseId}`);
    state.meters = data.meters || [];
    renderMeters();
  } catch (error) { showAppError(error); }
}

function showSettingsTab(name) {
  storeItem("usage-settings-tab", name);
  $$("#settings-tabs button").forEach((button) => button.classList.toggle("active", button.dataset.settingsTab === name));
  $$("[data-settings-panel]").forEach((panel) => { panel.hidden = panel.dataset.settingsPanel !== name; });
}

function houseName(houseId) {
  const house = (state.admin.houses || []).find((item) => item.id === houseId);
  return house ? house.name : `#${houseId}`;
}

function renderHouses() {
  $("#house-list").innerHTML = (state.admin.houses || []).map((house) => `
    <div class="mini-row">
      <span><strong>${esc(house.name)}</strong></span>
      <span>
        <button class="ghost compact" data-rename-house="${house.id}" type="button">Rename</button>
        <button class="ghost compact danger" data-delete-house="${house.id}" type="button">Delete</button>
      </span>
    </div>`).join("") || '<p class="meta">No house yet.</p>';
  $$("[data-rename-house]").forEach((button) => button.addEventListener("click", async () => {
    const answers = await openModal({
      title: "Rename house",
      fields: [{ name: "name", label: "House name", value: houseName(Number(button.dataset.renameHouse)) }],
    });
    if (answers === null || !answers.name.trim()) return;
    try {
      await api(`/api/houses/${button.dataset.renameHouse}`, { method: "PUT", body: JSON.stringify({ name: answers.name.trim() }) });
      await loadAdmin();
    } catch (error) { showAppError(error); }
  }));
  $$("[data-delete-house]").forEach((button) => button.addEventListener("click", async () => {
    if (!await confirmModal("Delete house", "Delete this house, its meters and all their readings?")) return;
    try {
      await api(`/api/houses/${button.dataset.deleteHouse}`, { method: "DELETE" });
      await loadAdmin();
    } catch (error) { showAppError(error); }
  }));
}

function renderUsers() {
  const houses = state.admin.houses || [];
  $("#user-list").innerHTML = (state.admin.users || []).map((user) => `
    <div class="mini-row wrap-row">
      <span>
        <strong>${esc(user.name || user.email)}</strong> · ${esc(user.email)}
        ${user.is_admin ? '<span class="badge">admin</span>' : ""}
      </span>
      <span class="house-checks">
        ${houses.map((house) => `
          <label class="check compact">
            <input type="checkbox" data-link-user="${user.id}" data-link-house="${house.id}"
              ${user.house_ids.includes(house.id) ? "checked" : ""}> ${esc(house.name)}
          </label>`).join("")}
        <button class="ghost compact" data-edit-user="${user.id}" type="button">Edit</button>
        <button class="ghost compact danger" data-delete-user="${user.id}" type="button">Delete</button>
      </span>
    </div>`).join("") || '<p class="meta">No user yet.</p>';
  $$("[data-link-user]").forEach((box) => box.addEventListener("change", async () => {
    try {
      await api("/api/user-houses", { method: "POST", body: JSON.stringify({
        user_id: Number(box.dataset.linkUser),
        house_id: Number(box.dataset.linkHouse),
        linked: box.checked,
      }) });
      await loadAdmin();
    } catch (error) { showAppError(error); }
  }));
  $$("[data-edit-user]").forEach((button) => button.addEventListener("click", async () => {
    const user = state.admin.users.find((item) => item.id === Number(button.dataset.editUser));
    const answers = await openModal({
      title: `Edit user · ${user.email}`,
      fields: [
        { name: "name", label: "Name", value: user.name },
        { name: "is_admin", label: "Admin", type: "checkbox", value: user.is_admin },
      ],
    });
    if (answers === null) return;
    try {
      await api(`/api/users/${user.id}`, { method: "PUT", body: JSON.stringify({ name: answers.name, is_admin: answers.is_admin }) });
      await loadAdmin();
    } catch (error) { showAppError(error); }
  }));
  $$("[data-delete-user]").forEach((button) => button.addEventListener("click", async () => {
    if (!await confirmModal("Delete user", "Delete this user?")) return;
    try {
      await api(`/api/users/${button.dataset.deleteUser}`, { method: "DELETE" });
      await loadAdmin();
    } catch (error) { showAppError(error); }
  }));
}

function renderMeters() {
  $("#meter-list").innerHTML = (state.meters || []).map((meter) => `
    <div class="mini-row wrap-row${meter.active ? "" : " inactive"}">
      <span>
        <strong>${esc(meter.label || meter.kind)}</strong> · ${esc(meter.kind)}
        ${meter.unit ? ` · ${esc(meter.unit)}` : ""}${meter.active ? "" : ' <span class="badge">inactive</span>'}
        <br>
        ${meter.registers.map((register) => `
          <span class="meta">
            ${esc(register.label || "register")} (start ${register.initial_value})${register.active ? "" : " — inactive"}
            <button class="ghost compact" data-edit-register="${register.id}" type="button">Edit</button>
            <button class="ghost compact danger" data-delete-register="${register.id}" type="button">×</button>
          </span>`).join(" ")}
      </span>
      <span>
        <button class="ghost compact" data-add-register="${meter.id}" type="button">Add register</button>
        <button class="ghost compact" data-edit-meter="${meter.id}" type="button">Edit</button>
        <button class="ghost compact danger" data-delete-meter="${meter.id}" type="button">Delete</button>
      </span>
    </div>`).join("") || '<p class="meta">No meter yet.</p>';
  $$("[data-edit-meter]").forEach((button) => button.addEventListener("click", async () => {
    const meter = state.meters.find((item) => item.id === Number(button.dataset.editMeter));
    const answers = await openModal({
      title: `Edit meter · ${meter.label || meter.kind}`,
      fields: [
        { name: "label", label: "Label", value: meter.label },
        { name: "unit", label: "Unit", value: meter.unit },
        { name: "active", label: "Active", type: "checkbox", value: meter.active },
      ],
    });
    if (answers === null) return;
    try {
      await api(`/api/meters/${meter.id}`, { method: "PUT", body: JSON.stringify({
        label: answers.label,
        unit: answers.unit,
        active: answers.active,
      }) });
      await loadMeters();
    } catch (error) { showAppError(error); }
  }));
  $$("[data-delete-meter]").forEach((button) => button.addEventListener("click", async () => {
    if (!await confirmModal("Delete meter", "Delete this meter and all its readings?")) return;
    try {
      await api(`/api/meters/${button.dataset.deleteMeter}`, { method: "DELETE" });
      await loadMeters();
    } catch (error) { showAppError(error); }
  }));
  $$("[data-add-register]").forEach((button) => button.addEventListener("click", async () => {
    const answers = await openModal({
      title: "Add register",
      fields: [
        { name: "label", label: "Register label (e.g. HP)", value: "" },
        { name: "initial_value", label: "Start value of the counter", type: "number", value: 0 },
      ],
      submitLabel: "Add",
    });
    if (answers === null) return;
    try {
      await api(`/api/meters/${button.dataset.addRegister}/registers`, { method: "POST", body: JSON.stringify({
        label: answers.label,
        initial_value: Number(answers.initial_value) || 0,
      }) });
      await loadMeters();
    } catch (error) { showAppError(error); }
  }));
  $$("[data-edit-register]").forEach((button) => button.addEventListener("click", async () => {
    const register = state.meters.flatMap((meter) => meter.registers)
      .find((item) => item.id === Number(button.dataset.editRegister));
    const answers = await openModal({
      title: `Edit register · ${register.label || "register"}`,
      fields: [
        { name: "label", label: "Register label", value: register.label },
        { name: "initial_value", label: "Start value of the counter", type: "number", value: register.initial_value },
        { name: "active", label: "Active", type: "checkbox", value: register.active },
      ],
    });
    if (answers === null) return;
    try {
      await api(`/api/registers/${register.id}`, { method: "PUT", body: JSON.stringify({
        label: answers.label,
        initial_value: Number(answers.initial_value) || 0,
        active: answers.active,
      }) });
      await loadMeters();
    } catch (error) { showAppError(error); }
  }));
  $$("[data-delete-register]").forEach((button) => button.addEventListener("click", async () => {
    if (!await confirmModal("Delete register", "Delete this register?")) return;
    try {
      await api(`/api/registers/${button.dataset.deleteRegister}`, { method: "DELETE" });
      await loadMeters();
    } catch (error) { showAppError(error); }
  }));
}

async function addHouse(event) {
  event.preventDefault();
  try {
    await api("/api/houses", { method: "POST", body: JSON.stringify({ name: $("#house-name").value.trim() }) });
    $("#house-name").value = "";
    await loadAdmin();
  } catch (error) { showAppError(error); }
}

async function addUser(event) {
  event.preventDefault();
  try {
    await api("/api/users", { method: "POST", body: JSON.stringify({
      email: $("#user-email").value.trim(),
      name: $("#user-name").value.trim(),
      is_admin: $("#user-admin").checked,
    }) });
    $("#user-email").value = "";
    $("#user-name").value = "";
    $("#user-admin").checked = false;
    await loadAdmin();
  } catch (error) { showAppError(error); }
}

function toggleDualRegisters() {
  const dual = $("#meter-dual").checked;
  $("#register-two-label").hidden = !dual;
  $("#register-two-initial").hidden = !dual;
}

async function addMeter(event) {
  event.preventDefault();
  const registers = [
    { label: $("#register-one-label").value.trim(), initial_value: Number($("#register-one-initial").value) || 0 },
  ];
  if ($("#meter-dual").checked) {
    registers.push({ label: $("#register-two-label").value.trim(), initial_value: Number($("#register-two-initial").value) || 0 });
  }
  try {
    await api("/api/meters", { method: "POST", body: JSON.stringify({
      house_id: state.houseId,
      kind: $("#meter-kind").value,
      label: $("#meter-label").value.trim(),
      unit: $("#meter-unit").value.trim(),
      registers,
    }) });
    $("#meter-label").value = "";
    $("#meter-unit").value = "";
    $("#meter-dual").checked = false;
    toggleDualRegisters();
    await loadMeters();
  } catch (error) { showAppError(error); }
}

async function logout() {
  try { await api("/api/auth/logout", { method: "POST", body: "{}" }); } catch (_) {}
  location.reload();
}

addEventListener("DOMContentLoaded", () => {
  $("#request-link-form").addEventListener("submit", requestLink);
  $("#btn-passkey").addEventListener("click", signInWithPasskey);
  $("#btn-logout").addEventListener("click", logout);
  $("#btn-add-passkey").addEventListener("click", registerPasskey);
  $("#house-form").addEventListener("submit", addHouse);
  $("#user-form").addEventListener("submit", addUser);
  $("#meter-form").addEventListener("submit", addMeter);
  $("#meter-dual").addEventListener("change", toggleDualRegisters);
  $("#house-btn").addEventListener("click", chooseHouse);
  // On narrow screens the version hides behind the info icon: a tap reveals it.
  $("#version").addEventListener("click", () => $("#version").classList.toggle("open"));
  $("#stats-show-tables").addEventListener("change", saveStatsPrefs);
  $("#stats-show-graphs").addEventListener("change", saveStatsPrefs);
  $("#stats-merge-graphs").addEventListener("change", saveStatsPrefs);
  wireYearSlider();
  $("#reading-meter").addEventListener("change", renderValueInputs);
  $("#btn-read-photo").addEventListener("click", readPhoto);
  $("#reading-form").addEventListener("submit", addReading);
  $("#btn-new-reading").addEventListener("click", openReadingModal);
  $("#btn-prev-month").addEventListener("click", () => {
    const input = $("#reading-month");
    input.value = previousMonthValue(input.value || currentMonthValue());
  });
  $("#reading-cancel").addEventListener("click", closeReadingModal);
  $("#reading-modal").addEventListener("click", (event) => {
    if (event.target === $("#reading-modal")) closeReadingModal();
  });
  document.addEventListener("paste", pastePhoto);
  const themeApp = $("#theme-btn-app");
  if (themeApp) themeApp.addEventListener("click", toggleTheme);
  $$(".app-nav button").forEach((button) => button.addEventListener("click", () => showView(button.dataset.nav)));
  $$("#settings-tabs button").forEach((button) => button.addEventListener("click", () => showSettingsTab(button.dataset.settingsTab)));
  load();
});
