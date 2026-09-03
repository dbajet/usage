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
  hiddenMeters: new Set(),
  sensors: null,
  sensorDays: 1,
  sensorOffset: 0,
  hiddenSensors: new Set(),
};

const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const VIZ_COLORS = ["var(--viz-1)", "var(--viz-2)", "var(--viz-3)", "var(--viz-4)", "var(--viz-5)", "var(--viz-6)"];
// The choices offered in the per-meter colour picker.
const METER_COLORS = [
  { label: "Blue", value: "#2a78d6" },
  { label: "Orange", value: "#eb6834" },
  { label: "Green", value: "#1baf7a" },
  { label: "Purple", value: "#8f62d9" },
  { label: "Magenta", value: "#c2478f" },
  { label: "Gold", value: "#a07b1f" },
  { label: "Red", value: "#d64550" },
  { label: "Teal", value: "#189aa8" },
  { label: "Brown", value: "#a06a3c" },
  { label: "Gray", value: "#6b7280" },
];

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

function openModal({ title, message = "", fields = [], options = [], submitLabel = "Save", danger = false, remove = false, top = false }) {
  return new Promise((resolve) => {
    // Two layers: the base modal, and one that can stack on top of it.
    const part = (name) => $(top ? `#modal2-${name}` : `#modal-${name}`);
    const backdrop = part("backdrop");
    part("title").textContent = title;
    const messageTarget = part("message");
    messageTarget.textContent = message;
    messageTarget.hidden = !message;
    part("fields").innerHTML = options.length
      ? options.map((option) => `
          <button class="ghost option${option.active ? " active" : ""}" type="button" data-modal-option="${esc(String(option.value))}">
            ${option.color ? `<span class="swatch" style="background:${esc(option.color)}"></span>` : ""}${esc(option.label)}
          </button>`).join("")
      : fields.map((field) => {
          if (field.type === "heading") {
            return `<p class="modal-heading">${esc(field.label)}</p>`;
          }
          if (field.type === "html") {
            return field.html;
          }
          if (field.type === "checkbox") {
            return `<label class="check"><input type="checkbox" data-modal-field="${esc(field.name)}"${field.value ? " checked" : ""}> ${esc(field.label)}</label>`;
          }
          if (field.type === "select") {
            return `<label>${esc(field.label)}<select data-modal-field="${esc(field.name)}">${(field.options || []).map((option) =>
              `<option value="${esc(option)}"${option === field.value ? " selected" : ""}>${esc(option)}</option>`).join("")}</select></label>`;
          }
          const step = field.type === "number" ? ' step="any"' : "";
          return `<label>${esc(field.label)}<input type="${esc(field.type || "text")}"${step} data-modal-field="${esc(field.name)}" value="${esc(field.value ?? "")}"></label>`;
        }).join("");
    part("submit").hidden = Boolean(options.length);
    part("submit").textContent = submitLabel;
    part("submit").classList.toggle("danger", danger);
    part("submit").classList.toggle("primary", !danger);
    part("remove").hidden = !remove;
    backdrop.hidden = false;
    const first = part("fields").querySelector("input:not([type=checkbox])");
    if (first) first.focus();

    const previousKeydown = document.onkeydown;
    const close = (result) => {
      backdrop.hidden = true;
      part("form").onsubmit = null;
      part("cancel").onclick = null;
      part("remove").onclick = null;
      backdrop.onclick = null;
      document.onkeydown = previousKeydown;
      resolve(result);
    };
    part("remove").onclick = () => close({ __remove: true });
    part("form").onsubmit = (event) => {
      event.preventDefault();
      const values = {};
      part("fields").querySelectorAll("[data-modal-field]").forEach((input) => {
        values[input.dataset.modalField] = input.type === "checkbox" ? input.checked : input.value;
      });
      close(values);
    };
    part("fields").querySelectorAll("[data-modal-option]").forEach((button) =>
      button.addEventListener("click", () => close({ value: button.dataset.modalOption })));
    part("cancel").onclick = () => close(null);
    backdrop.onclick = (event) => { if (event.target === backdrop) close(null); };
    document.onkeydown = (event) => { if (event.key === "Escape") close(null); };
  });
}

async function confirmModal(title, message, submitLabel = "Delete", top = false) {
  return (await openModal({ title, message, submitLabel, danger: true, top })) !== null;
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
    loadSensorSettings();
    loadReminder();
    if (state.me && state.me.is_admin) loadAdmin();
  }
  if (name === "entries") loadEntries();
  if (name === "stats") loadStats();
  if (name === "sensors") loadSensors();
}

async function chooseHouseView() {
  // After the house changes, a view or tab the new house cannot show falls back.
  await ensureDashboard();
  if (currentView() === "sensors" && !houseHasSensors()) { showView("stats"); return; }
  if (currentView() === "settings" && storedItem("usage-settings-tab", "meters") === "sensors" && !houseHasSensors()) {
    showSettingsTab("meters");
  }
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
  showView(["stats", "sensors", "entries", "settings"].includes(view) ? view : "stats");
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
  // Sensors only show up for a house that has received some: the nav item
  // and the settings tab stay out of the way elsewhere.
  const hasSensors = Boolean(current && current.has_sensors);
  $('[data-nav="sensors"]').hidden = !hasSensors;
  $('[data-settings-tab="sensors"]').hidden = !hasSensors;
}

function houseHasSensors() {
  const current = ((state.dashboard && state.dashboard.houses) || []).find((house) => house.id === state.houseId);
  return Boolean(current && current.has_sensors);
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
  state.hiddenSensors = new Set();
  await chooseHouseView();
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

const ICON_CAMERA = '<svg class="msym" fill="currentColor" xmlns="http://www.w3.org/2000/svg" viewBox="0 -960 960 960"><path d="M480-260q75 0 127.5-52.5T660-440q0-75-52.5-127.5T480-620q-75 0-127.5 52.5T300-440q0 75 52.5 127.5T480-260Zm0-80q-42 0-71-29t-29-71q0-42 29-71t71-29q42 0 71 29t29 71q0 42-29 71t-71 29ZM160-120q-33 0-56.5-23.5T80-200v-480q0-33 23.5-56.5T160-760h126l74-80h240l74 80h126q33 0 56.5 23.5T880-680v480q0 33-23.5 56.5T800-120H160Zm0-80h640v-480H638l-73-80H395l-73 80H160v480Zm320-240Z"/></svg>';
const ICON_PICTURE = '<svg class="msym" fill="currentColor" xmlns="http://www.w3.org/2000/svg" viewBox="0 -960 960 960"><path d="M200-120q-33 0-56.5-23.5T120-200v-560q0-33 23.5-56.5T200-840h560q33 0 56.5 23.5T840-760v560q0 33-23.5 56.5T760-120H200Zm0-80h560v-560H200v560Zm40-80h480L570-480 450-320l-90-120-120 160Zm-40 80v-560 560Z"/></svg>';

function renderValueInputs() {
  const meter = selectedMeter();
  state.readingSource = "manual";
  $("#reading-hint").hidden = true;
  // A photo per register: cycling displays show one register at a time.
  $("#reading-values").innerHTML = (meter ? meter.registers : []).map((register) => `
    <div class="value-row">
      <input type="number" step="any" data-register-value="${register.id}"
        placeholder="${esc(register.label || (meter.monthly ? "Consumption of the month" : "Counter"))}${meter.unit ? ` (${esc(meter.unit)})` : ""}" required>
      <button class="ghost icon-only mobile-only" data-photo-camera="${register.id}" type="button"
        title="Take a photo of ${esc(register.label || "the counter")}">${ICON_CAMERA}</button>
      <button class="ghost icon-only" data-photo-file="${register.id}" type="button"
        title="Read ${esc(register.label || "the counter")} from a photo">${ICON_PICTURE}</button>
    </div>`).join("");
  $$("[data-photo-camera]").forEach((button) => button.addEventListener("click", () => {
    state.photoTarget = Number(button.dataset.photoCamera);
    state.photoButton = button;
    $("#reading-camera").click();
  }));
  $$("[data-photo-file]").forEach((button) => button.addEventListener("click", () => {
    state.photoTarget = Number(button.dataset.photoFile);
    state.photoButton = button;
    $("#reading-photo").click();
  }));
}

async function downscalePhoto(file) {
  // Phone photos are several MB; ~1.5k px is plenty to read the digits and
  // uploads far faster on mobile. Falls back to the original on any failure.
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, 1568 / Math.max(bitmap.width, bitmap.height));
    if (scale >= 1) { bitmap.close(); return file; }
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.85));
    return blob || file;
  } catch (_) {
    return file;
  }
}

async function readPhoto() {
  const meter = selectedMeter();
  const file = $("#reading-photo").files[0];
  if (!meter) { showAppError(new Error("Add a meter first.")); return; }
  if (!file) { showAppError(new Error("Choose a photo first.")); return; }
  const button = state.photoButton;
  if (button) { button.classList.add("busy"); button.disabled = true; }
  try {
    const photo = await downscalePhoto(file);
    const dataUrl = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(new Error("The photo could not be loaded."));
      reader.readAsDataURL(photo);
    });
    const data = await api("/api/readings/extract", { method: "POST", body: JSON.stringify({
      meter_id: meter.id,
      media_type: photo.type || file.type,
      image_base64: String(dataUrl).split(",")[1] || "",
      register_id: state.photoTarget || 0,
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
      ? "The register could not be read - fill it in manually."
      : "Values read from the photo - please verify before saving.";
    hint.hidden = false;
  } catch (error) { showAppError(error); } finally {
    if (button) { button.classList.remove("busy"); button.disabled = false; }
    state.photoButton = null;
    $("#reading-photo").value = "";
  }
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

function defaultReadingMonth() {
  // Early in the month a reading is usually last month's; from the 25th it is this month's.
  const current = currentMonthValue();
  return new Date().getDate() >= 25 ? current : previousMonthValue(current);
}

function openReadingModal() {
  const meters = houseMeters();
  if (!meters.length) { showAppError(new Error("Add a meter first (Settings, Meters).")); return; }
  renderReadingForm();
  $("#reading-month").value = defaultReadingMonth();
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
  // The paste lands on the focused register, else the first empty one.
  const inputs = $$("#reading-values [data-register-value]");
  const target = inputs.find((input) => input === document.activeElement)
    || inputs.find((input) => !input.value) || inputs[0];
  if (!target) return;
  state.photoTarget = Number(target.dataset.registerValue);
  state.photoButton = $(`[data-photo-file="${state.photoTarget}"]`);
  const transfer = new DataTransfer();
  transfer.items.add(file);
  $("#reading-photo").files = transfer.files;
  readPhoto();
}

function cameraPhoto() {
  // The capture input opens the phone camera directly; the shot lands in the
  // regular photo input and is read right away.
  const file = $("#reading-camera").files[0];
  if (!file) return;
  const transfer = new DataTransfer();
  transfer.items.add(file);
  $("#reading-photo").files = transfer.files;
  $("#reading-camera").value = "";
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

function fmtRounded(value) {
  return Math.round(Number(value)).toLocaleString("en-US");
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
  // Columns follow the user's own meter order from the dashboard.
  const order = new Map(houseMeters().map((meter, index) => [meter.id, index]));
  meters.sort((a, b) => (order.has(a.id) ? order.get(a.id) : 1000 + a.id) - (order.has(b.id) ? order.get(b.id) : 1000 + b.id));
  const months = [...new Set(readings.map((reading) => reading.read_on))];
  const byKey = new Map(readings.map((reading) => [`${reading.read_on}|${reading.meter_id}`, reading]));
  const header = `<tr><th>Date</th>${meters.map((meter) =>
    `<th>${esc(meter.label)}${meter.unit ? ` <span class="meta">(${esc(meter.unit)})</span>` : ""}</th>`).join("")}</tr>`;
  let lastYear = "";
  const rows = months.map((month) => {
    const cells = meters.map((meter) => {
      const reading = byKey.get(`${month}|${meter.id}`);
      if (!reading) return "<td></td>";
      // The cells stay whole numbers; the exact value lives in the tooltip and the edit dialog.
      const text = reading.values.map((value) => fmtRounded(value.value)).join(" / ");
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

function legendMarkup(seriesList, interactive = false) {
  if (seriesList.length < 2) return "";
  return `
    <div class="viz-legend">
      ${seriesList.map((item, index) => {
        const color = item.color || VIZ_COLORS[index % VIZ_COLORS.length];
        const side = interactive && item.axis === "right" ? ' <span class="meta">· right</span>' : "";
        const content = `<i style="background:${color}"></i>${esc(item.label)}${item.unit ? ` (${esc(item.unit)})` : ""}${side}`;
        if (!interactive) return `<span>${content}</span>`;
        const off = state.hiddenMeters.has(item.meter_id) ? " off" : "";
        return `<button class="legend-toggle${off}" type="button" data-legend-toggle="${item.meter_id}" title="Show or hide this meter">${content}</button>`;
      }).join("")}
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
  $("#year-reset").disabled = fromYear === minYear && toYear === maxYear;
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
    const allSeries = filtered.series.series.map((item, index) => ({
      ...item,
      color: item.color || VIZ_COLORS[index % VIZ_COLORS.length],
    }));
    const visibleSeries = allSeries.filter((item) => !state.hiddenMeters.has(item.meter_id));
    const dual = visibleSeries.some((item) => item.axis === "right") && visibleSeries.some((item) => item.axis !== "right");
    html += `
      <div class="card">
        <h3>Trends <span class="meta">(all meters, ${dual ? "left and right scales" : "one scale"} - click the legend to hide a meter)</span></h3>
        ${chartMarkup(visibleSeries, true) || '<p class="meta">Every meter is hidden - click the legend to bring one back.</p>'}
        ${legendMarkup(allSeries, true)}
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
  $$("[data-legend-toggle]").forEach((button) => button.addEventListener("click", () => {
    const meterId = Number(button.dataset.legendToggle);
    if (state.hiddenMeters.has(meterId)) state.hiddenMeters.delete(meterId);
    else state.hiddenMeters.add(meterId);
    renderStats(state.statsData.tables, state.statsData.series);
  }));
}

function clearTableHover(table) {
  table.querySelectorAll(".hl-col").forEach((cell) => cell.classList.remove("hl-col"));
  table.querySelectorAll(".hl-row").forEach((row) => row.classList.remove("hl-row"));
  const holder = table.closest(".card")?.querySelector(".viz-holder");
  if (holder && holder.clearMark) holder.clearMark();
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
      const row = cell.closest("tr");
      row.classList.add("hl-row");
      // A month cell rings the matching point on the card's graph.
      const holder = table.closest(".card")?.querySelector(".viz-holder");
      if (holder && holder.markMonth && cell.tagName === "TD" && cell.cellIndex >= 1 && cell.cellIndex <= 12) {
        holder.markMonth(`${row.cells[0].textContent.trim()}-${String(cell.cellIndex).padStart(2, "0")}`);
      }
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
      ${year.months.map((month) => `<td>${month === null ? "" : fmtRounded(month)}</td>`).join("")}
      <td class="total">${fmtRounded(year.total)}</td>
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
  // Merged graphs can read some meters on a second, right-hand scale.
  const onRight = (item) => merged && item.axis === "right";
  const rightSeries = seriesList.filter(onRight);
  const leftSeries = seriesList.filter((item) => !onRight(item));
  const dual = rightSeries.length > 0 && leftSeries.length > 0;
  const width = 720;
  const height = 240;
  const left = 48;
  const right = dual ? 48 : 28;
  const top = 12;
  const bottom = 30;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const scaleOf = (list) => {
    const maxValue = Math.max(1, ...list.flatMap((item) => item.points.map((point) => point.value)));
    const step = niceStep(maxValue / 4);
    return { step, yMax: Math.ceil(maxValue / step) * step };
  };
  const leftScale = scaleOf(leftSeries.length ? leftSeries : rightSeries);
  const divisions = Math.round(leftScale.yMax / leftScale.step);
  const rightScale = { step: 0, yMax: 0 };
  if (dual) {
    // Both scales share the grid lines: same divisions, each with a nice step.
    const maxValue = Math.max(1, ...rightSeries.flatMap((item) => item.points.map((point) => point.value)));
    rightScale.step = niceStep(maxValue / divisions);
    rightScale.yMax = rightScale.step * divisions;
  }
  const xAt = (month) => left + (months.indexOf(month) * plotWidth) / (months.length - 1);
  const yOn = (value, yMax) => top + plotHeight - (value / yMax) * plotHeight;
  const yAt = (value, item) => yOn(value, dual && onRight(item) ? rightScale.yMax : leftScale.yMax);

  const gridLines = [];
  const yLabels = [];
  for (let division = 0; division <= divisions; division += 1) {
    const y = yOn(division * leftScale.step, leftScale.yMax);
    gridLines.push(`<line x1="${left}" y1="${y}" x2="${width - right}" y2="${y}"></line>`);
    yLabels.push(`<text x="${left - 6}" y="${y + 4}" text-anchor="end">${fmtValue(division * leftScale.step)}</text>`);
    if (dual) {
      yLabels.push(`<text x="${width - right + 6}" y="${y + 4}" text-anchor="start">${fmtValue(division * rightScale.step)}</text>`);
    }
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
    const color = item.color || VIZ_COLORS[index % VIZ_COLORS.length];
    const path = item.points
      .map((point, pointIndex) => `${pointIndex === 0 ? "M" : "L"}${xAt(point.month).toFixed(1)},${yAt(point.value, item).toFixed(1)}`)
      .join(" ");
    const dots = showDots
      ? item.points.map((point) =>
          `<circle class="dot" cx="${xAt(point.month).toFixed(1)}" cy="${yAt(point.value, item).toFixed(1)}" r="3" fill="${color}"></circle>`).join("")
      : "";
    return `<g class="series"><path d="${path}" stroke="${color}"></path>${dots}</g>`;
  });

  const config = {
    months,
    left,
    plotWidth,
    count: months.length,
    merged,
    top,
    plotHeight,
    yMax: leftScale.yMax,
    yMaxRight: dual ? rightScale.yMax : 0,
    series: seriesList.map((item, index) => ({
      label: item.label,
      unit: item.unit,
      color: item.color || VIZ_COLORS[index % VIZ_COLORS.length],
      right: onRight(item) && dual,
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
          <g class="hov-dots"></g>
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
    const dots = hover.querySelector(".hov-dots");
    const yAt = (value, series) => {
      const yMax = series && series.right ? config.yMaxRight : config.yMax;
      return config.top + config.plotHeight - (value / yMax) * config.plotHeight;
    };
    const tip = holder.querySelector(".viz-tip");
    const xAt = (index) => config.left + (index * config.plotWidth) / Math.max(1, config.count - 1);
    const shifted = (month, years) => `${Number(month.slice(0, 4)) + years}-${month.slice(5, 7)}`;
    const monthLabel = (month) => `${MONTH_NAMES[Number(month.slice(5, 7)) - 1]} ${month.slice(0, 4)}`;
    const addDots = (month) => {
      const index = config.months.indexOf(month);
      if (index < 0) return;
      config.series.forEach((series) => {
        const value = series.values[month];
        if (value === undefined) return;
        const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        dot.setAttribute("class", "hov-dot");
        dot.setAttribute("cx", xAt(index).toFixed(1));
        dot.setAttribute("cy", yAt(value, series).toFixed(1));
        dot.setAttribute("r", "4.5");
        dot.setAttribute("stroke", series.color);
        dots.appendChild(dot);
      });
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
    // The table of the same card can mark a month on this graph.
    holder.markMonth = (month) => {
      dots.innerHTML = "";
      if (config.months.indexOf(month) < 0) { hover.setAttribute("hidden", ""); return; }
      hover.removeAttribute("hidden");
      addDots(month);
    };
    holder.clearMark = () => {
      hover.setAttribute("hidden", "");
      dots.innerHTML = "";
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
      const rows = [rowFor(month)];
      dots.innerHTML = "";
      // A ring on the hovered value, like the year-over-year ones.
      addDots(month);
      if (!config.merged) {
        // Year-over-year: a dot on the value twelve months back and ahead.
        [shifted(month, -1), shifted(month, 1)].forEach((other) => {
          if (config.months.indexOf(other) < 0) return;
          rows.push(rowFor(other));
          addDots(other);
        });
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

// ---------- Sensors (Home Assistant thermometers) ----------

const SENSOR_STALE_MS = 3 * 60 * 60 * 1000;
const LONG_PRESS_MS = 500;

function fmtAgo(iso) {
  const elapsed = Date.now() - Date.parse(iso);
  if (!Number.isFinite(elapsed)) return "";
  const minutes = Math.round(elapsed / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}

function fmtTemp(value) {
  return Number(value).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

function fmtInstant(time, days) {
  const date = new Date(time);
  const day = `${MONTH_NAMES[date.getMonth()]} ${date.getDate()}`;
  if (days >= 365) return `${day}, ${date.getFullYear()}`;
  const clock = `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
  return `${day}, ${clock}`;
}

function wantsCelsius() {
  return storedItem("usage-temp-unit", "F") === "C";
}

function wantsPrevious() {
  return storedItem("usage-sensor-previous", "0") === "1";
}

function splitPrevious(seriesList, days, tMax) {
  // The server sends two periods in one flat list; the earlier one is
  // shifted forward by the range so it lines up under the shown one.
  const span = days * 86400000;
  const boundary = tMax - span;
  return seriesList.map((item) => {
    const timed = item.points.map((point) => ({ ...point, time: Date.parse(point.at) }));
    return {
      ...item,
      points: timed.filter((point) => point.time >= boundary),
      previousPoints: timed.filter((point) => point.time < boundary).map((point) => ({ ...point, time: point.time + span })),
    };
  });
}

function displayTemp(value, unit) {
  // A viewer's choice: every temperature shows in Celsius or in Fahrenheit,
  // whatever the thermometer reports. Other units pass through.
  if (value === null || value === undefined) return { value, unit };
  if (wantsCelsius() && unit === "°F") return { value: ((value - 32) * 5) / 9, unit: "°C" };
  if (!wantsCelsius() && unit === "°C") return { value: (value * 9) / 5 + 32, unit: "°F" };
  return { value, unit };
}

function displaySensors(sensors) {
  return sensors.map((sensor) => {
    const shown = displayTemp(sensor.last_value, sensor.unit);
    return { ...sensor, last_value: shown.value, unit: shown.unit };
  });
}

function displaySeries(seriesList) {
  return seriesList.map((item) => ({
    ...item,
    unit: displayTemp(0, item.unit).unit,
    points: item.points.map((point) => ({
      ...point,
      average: displayTemp(point.average, item.unit).value,
      low: displayTemp(point.low, item.unit).value,
      high: displayTemp(point.high, item.unit).value,
    })),
  }));
}

function fmtPeriodEdge(time, days) {
  // The graph title: a clock for a day, dates for a week or a month, months for a year.
  const date = new Date(time);
  if (days <= 1) return fmtInstant(time, days);
  if (days <= 30) return `${MONTH_NAMES[date.getMonth()]} ${date.getDate()}`;
  return `${MONTH_NAMES[date.getMonth()]} ${date.getFullYear()}`;
}

function sensorColors(sensors) {
  // One colour per active sensor, in the house's order: tiles, lines and legend agree.
  return new Map(sensors.filter((sensor) => sensor.active).map((sensor, index) => [sensor.id, VIZ_COLORS[index % VIZ_COLORS.length]]));
}

async function loadSensors() {
  try {
    await ensureDashboard();
    if (!state.houseId) {
      $("#sensor-content").innerHTML = '<p class="meta">No house is linked to your account yet.</p>';
      return;
    }
    state.sensorDays = Number(storedItem("usage-sensor-days", "1")) || 1;
    $("#sensor-celsius").checked = wantsCelsius();
    $("#sensor-previous").checked = wantsPrevious();
    $$("[data-sensor-days]").forEach((button) => button.classList.toggle("active", Number(button.dataset.sensorDays) === state.sensorDays));
    if (!houseHasSensors()) { showView("stats"); return; }
    const list = await api(`/api/sensors?house_id=${state.houseId}`);
    const series = await api(`/api/sensors/series?house_id=${state.houseId}&days=${state.sensorDays}&previous=${wantsPrevious()}&offset=${state.sensorOffset}`);
    state.sensors = list.sensors || [];
    state.sensorData = series;
    renderSensors();
  } catch (error) { showAppError(error); }
}

function renderSensors() {
  const sensors = displaySensors(state.sensors || []);
  const data = state.sensorData || { series: [], days: state.sensorDays, bucket_minutes: 10 };
  if (!sensors.length) {
    $("#sensor-content").innerHTML = `
      <div class="card">
        <p class="meta">No sensor yet. Once Home Assistant pushes readings with this house's sensor token
          (Settings, Houses), the thermometers appear here on their own.</p>
      </div>`;
    return;
  }
  const colors = sensorColors(sensors);
  const activeIds = sensors.filter((sensor) => sensor.active).map((sensor) => sensor.id);
  // Tiles are "selected" while some sensors are hidden: the visible ones.
  const visibleIds = activeIds.filter((id) => !state.hiddenSensors.has(id));
  const selecting = visibleIds.length < activeIds.length;
  const tiles = sensors
    .filter((sensor) => sensor.active && sensor.last_value !== null)
    .map((sensor) => {
      const stale = Date.now() - Date.parse(sensor.last_at) > SENSOR_STALE_MS;
      const visible = !state.hiddenSensors.has(sensor.id);
      const classes = ["sensor-tile", stale ? "stale" : "", selecting && visible ? "selected" : "", selecting && !visible ? "dimmed" : ""];
      return `
        <div class="${classes.filter(Boolean).join(" ")}" data-sensor-tile="${sensor.id}" role="button" tabindex="0"
          style="border-left-color:${colors.get(sensor.id)}"
          title="${esc(sensor.entity_id)} - click: only this sensor · Ctrl+click or long press: add or remove it">
          <div class="tile-name">${esc(sensor.name)}</div>
          <div class="tile-value">${fmtTemp(sensor.last_value)}${sensor.unit ? ` <span class="meta">${esc(sensor.unit)}</span>` : ""}</div>
          <div class="tile-when">${esc(fmtAgo(sensor.last_at))}</div>
        </div>`;
    }).join("");
  const tMax = data.until ? Date.parse(data.until) : Date.now();
  const tMin = tMax - data.days * 86400000;
  const allSeries = splitPrevious(displaySeries(data.series || []), data.days, tMax)
    .map((item) => ({ ...item, color: colors.get(item.sensor_id) || VIZ_COLORS[0] }));
  const visible = allSeries.filter((item) => !state.hiddenSensors.has(item.sensor_id));
  const previousLabel = { 1: "day", 7: "week", 30: "30 days", 365: "year" }[data.days] || "period";
  const bucketLabel = data.bucket_minutes >= 1440 ? "daily" : data.bucket_minutes >= 60 ? `${data.bucket_minutes / 60}-hour` : `${data.bucket_minutes}-minute`;
  const rangeLabel = `${fmtPeriodEdge(tMin, data.days)} – ${fmtPeriodEdge(tMax, data.days)}`;
  const hint = `${bucketLabel} averages${data.bucket_minutes > 10 ? " with the low-high band" : ""}${data.previous ? `; dotted: the previous ${previousLabel}` : ""}. Click the legend to hide a sensor.`;
  $("#sensor-later").disabled = !state.sensorOffset;
  $("#sensor-content").innerHTML = `
    <div class="card">
      <h3>Now</h3>
      <div class="sensor-tiles">${tiles || '<p class="meta">No reading received yet.</p>'}</div>
    </div>
    <div class="card">
      <h3 title="${esc(hint)}">${esc(rangeLabel)}${data.previous ? ' <span class="meta">· dotted: previous</span>' : ""}</h3>
      ${sensorChartMarkup(visible, data.days, data.bucket_minutes, tMax) || '<p class="meta">No reading in this period.</p>'}
      ${sensorLegendMarkup(allSeries)}
    </div>`;
  wireSensorChartHover("#sensor-content");
  $$("[data-sensor-tile]").forEach((tile) => {
    const sensorId = Number(tile.dataset.sensorTile);
    const solo = () => {
      // Plain click: only this sensor on the graph; again on the lone one: everyone back.
      state.hiddenSensors = visibleIds.length === 1 && visibleIds[0] === sensorId
        ? new Set()
        : new Set(activeIds.filter((id) => id !== sensorId));
      renderSensors();
    };
    const toggle = () => {
      // Ctrl/Cmd+click, or a long press on a phone: add or remove this sensor
      // from the selection. Removing the last one brings everyone back.
      const hidden = new Set(state.hiddenSensors);
      if (!selecting) {
        state.hiddenSensors = new Set(activeIds.filter((id) => id !== sensorId));
      } else if (hidden.has(sensorId)) {
        hidden.delete(sensorId);
        state.hiddenSensors = hidden;
      } else {
        hidden.add(sensorId);
        state.hiddenSensors = activeIds.every((id) => hidden.has(id)) ? new Set() : hidden;
      }
      renderSensors();
    };
    let pressTimer = null;
    // Touch events rather than pointer events: Chrome cancels the pointer on
    // a long hold, but keeps the touch sequence alive. The toggle re-renders
    // the tiles, so the click the browser fires after the touch lands on a
    // new element: a shared flag swallows it.
    tile.addEventListener("touchstart", () => {
      state.tileLongPressed = false;
      pressTimer = setTimeout(() => { pressTimer = null; state.tileLongPressed = true; toggle(); }, LONG_PRESS_MS);
    }, { passive: true });
    ["touchend", "touchmove", "touchcancel"].forEach((name) => tile.addEventListener(name, () => {
      if (pressTimer) { clearTimeout(pressTimer); pressTimer = null; }
    }, { passive: true }));
    tile.addEventListener("contextmenu", (event) => event.preventDefault());
    tile.addEventListener("click", (event) => {
      if (state.tileLongPressed) { state.tileLongPressed = false; return; }
      if (event.ctrlKey || event.metaKey) toggle();
      else solo();
    });
    tile.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      if (event.ctrlKey || event.metaKey) toggle();
      else solo();
    });
  });
  $$("[data-sensor-toggle]").forEach((button) => button.addEventListener("click", () => {
    const sensorId = Number(button.dataset.sensorToggle);
    if (state.hiddenSensors.has(sensorId)) state.hiddenSensors.delete(sensorId);
    else state.hiddenSensors.add(sensorId);
    renderSensors();
  }));
}

function sensorLegendMarkup(seriesList) {
  if (!seriesList.length) return "";
  return `
    <div class="viz-legend">
      ${seriesList.map((item) => {
        const off = state.hiddenSensors.has(item.sensor_id) ? " off" : "";
        return `<button class="legend-toggle${off}" type="button" data-sensor-toggle="${item.sensor_id}" title="Show or hide this sensor">
          <i style="background:${item.color}"></i>${esc(item.name)}</button>`;
      }).join("")}
    </div>`;
}

function sensorTicks(tMin, tMax, days) {
  // Ticks on local-time boundaries: hours for a day, midnights for a week or
  // a month, the first of each month for a year.
  const ticks = [];
  const cursor = new Date(tMin);
  cursor.setSeconds(0, 0);
  if (days <= 1) {
    cursor.setMinutes(0);
    cursor.setHours(Math.ceil(cursor.getHours() / 4) * 4);
  } else if (days <= 30) {
    cursor.setHours(0, 0);
    cursor.setDate(cursor.getDate() + 1);
  } else {
    cursor.setHours(0, 0);
    cursor.setMonth(cursor.getMonth() + 1, 1);
  }
  while (cursor.getTime() <= tMax) {
    const time = cursor.getTime();
    let label;
    if (days <= 1) label = `${String(cursor.getHours()).padStart(2, "0")}:00`;
    else if (days <= 30) label = `${MONTH_NAMES[cursor.getMonth()]} ${cursor.getDate()}`;
    else label = MONTH_NAMES[cursor.getMonth()];
    if (days <= 30 && days > 7 && cursor.getDate() % 5 !== 0) label = "";
    if (label) ticks.push({ time, label });
    if (days <= 1) cursor.setHours(cursor.getHours() + 4);
    else if (days <= 30) cursor.setDate(cursor.getDate() + 1);
    else cursor.setMonth(cursor.getMonth() + 1);
  }
  return ticks;
}

function sensorStep(rough) {
  // A finer ladder than the consumption charts: 20 -> 25 -> 50 rather than 20 -> 50.
  const magnitude = Math.pow(10, Math.floor(Math.log10(rough)));
  const normalized = rough / magnitude;
  const factor = [1, 2, 2.5, 5, 10].find((candidate) => normalized <= candidate) || 10;
  return factor * magnitude;
}

function sensorChartMarkup(seriesList, days, bucketMinutes, tMax) {
  const tMin = tMax - days * 86400000;
  const points = seriesList.flatMap((item) => [...item.points, ...(item.previousPoints || [])]);
  if (points.length < 2) return "";
  const width = 720;
  const height = 260;
  const left = 44;
  const right = 16;
  const top = 12;
  const bottom = 28;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  let low = Math.min(...points.map((point) => point.low));
  let high = Math.max(...points.map((point) => point.high));
  if (high - low < 2) { low -= 1; high += 1; }
  // Temperatures are not zero-based: the scale hugs the data, about six divisions.
  const step = sensorStep((high - low) / 6);
  const yMin = Math.floor(low / step) * step;
  const yMax = Math.ceil(high / step) * step;
  const xAt = (time) => left + ((time - tMin) / (tMax - tMin)) * plotWidth;
  const yAt = (value) => top + plotHeight - ((value - yMin) / (yMax - yMin)) * plotHeight;

  const gridLines = [];
  const yLabels = [];
  for (let value = yMin; value <= yMax + step / 2; value += step) {
    const y = yAt(value);
    gridLines.push(`<line x1="${left}" y1="${y.toFixed(1)}" x2="${width - right}" y2="${y.toFixed(1)}"></line>`);
    yLabels.push(`<text x="${left - 6}" y="${(y + 4).toFixed(1)}" text-anchor="end">${fmtValue(value)}</text>`);
  }
  const xLabels = sensorTicks(tMin, tMax, days).map((tick) =>
    `<text x="${xAt(tick.time).toFixed(1)}" y="${height - 8}" text-anchor="middle">${esc(tick.label)}</text>`);

  const withBand = bucketMinutes > 10;
  const lineOf = (timed) => timed.map((point, index) => `${index === 0 ? "M" : "L"}${xAt(point.time).toFixed(1)},${yAt(point.average).toFixed(1)}`).join(" ");
  const paths = seriesList.map((item) => {
    const timed = item.points;
    let band = "";
    if (withBand && timed.length > 1) {
      const upper = timed.map((point) => `${xAt(point.time).toFixed(1)},${yAt(point.high).toFixed(1)}`);
      const lower = timed.slice().reverse().map((point) => `${xAt(point.time).toFixed(1)},${yAt(point.low).toFixed(1)}`);
      band = `<polygon class="band" points="${upper.join(" ")} ${lower.join(" ")}" fill="${item.color}"></polygon>`;
    }
    const previous = (item.previousPoints || []).length > 1
      ? `<path class="previous" d="${lineOf(item.previousPoints)}" stroke="${item.color}"></path>`
      : "";
    return `<g class="series">${band}${previous}<path d="${lineOf(timed)}" stroke="${item.color}"></path></g>`;
  });

  const config = {
    tMin,
    tMax,
    days,
    left,
    plotWidth,
    top,
    plotHeight,
    yMin,
    yMax,
    bucketMs: bucketMinutes * 60000,
    series: seriesList.map((item) => ({
      name: item.name,
      unit: item.unit,
      color: item.color,
      points: item.points.map((point) => [point.time, point.average, point.low, point.high]),
      previous: (item.previousPoints || []).map((point) => [point.time, point.average, point.low, point.high]),
    })),
  };
  return `
    <div class="viz-holder" data-sensor-chart="${esc(JSON.stringify(config))}">
      <svg class="viz-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Sensor trend">
        <g class="grid">${gridLines.join("")}</g>
        <g class="axis">${yLabels.join("")}${xLabels.join("")}</g>
        ${paths.join("")}
        <g class="viz-hover" hidden>
          <g class="hov-dots"></g>
        </g>
      </svg>
      <div class="viz-tip" hidden></div>
    </div>`;
}

function wireSensorChartHover(rootSelector) {
  $$(`${rootSelector} [data-sensor-chart]`).forEach((holder) => {
    const config = JSON.parse(holder.dataset.sensorChart);
    const svg = holder.querySelector("svg");
    const hover = svg.querySelector(".viz-hover");
    const dots = hover.querySelector(".hov-dots");
    const tip = holder.querySelector(".viz-tip");
    const xAt = (time) => config.left + ((time - config.tMin) / (config.tMax - config.tMin)) * config.plotWidth;
    const yAt = (value) => config.top + config.plotHeight - ((value - config.yMin) / (config.yMax - config.yMin)) * config.plotHeight;
    const nearest = (points, time) => {
      let best = null;
      points.forEach((point) => {
        if (best === null || Math.abs(point[0] - time) < Math.abs(best[0] - time)) best = point;
      });
      return best && Math.abs(best[0] - time) <= config.bucketMs * 1.5 ? best : null;
    };
    svg.addEventListener("mousemove", (event) => {
      const rect = svg.getBoundingClientRect();
      const x = ((event.clientX - rect.left) * 720) / rect.width;
      const time = config.tMin + ((x - config.left) / config.plotWidth) * (config.tMax - config.tMin);
      dots.innerHTML = "";
      const rows = [];
      let shown = null;
      config.series.forEach((series) => {
        const point = nearest(series.points, time);
        const before = nearest(series.previous, time);
        if (!point && !before) return;
        if (shown === null) shown = (point || before)[0];
        const previous = before ? ` · prev ${fmtTemp(before[1])}` : "";
        if (!point) {
          rows.push(`${esc(series.name)}: –${previous}`);
          return;
        }
        const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        dot.setAttribute("class", "hov-dot");
        dot.setAttribute("cx", xAt(point[0]).toFixed(1));
        dot.setAttribute("cy", yAt(point[1]).toFixed(1));
        dot.setAttribute("r", "4.5");
        dot.setAttribute("stroke", series.color);
        dots.appendChild(dot);
        const range = point[2] !== point[3] ? ` (${fmtTemp(point[2])} – ${fmtTemp(point[3])})` : "";
        rows.push(`${esc(series.name)}: ${fmtTemp(point[1])}${series.unit ? ` ${esc(series.unit)}` : ""}${range}${previous}`);
      });
      if (shown === null) {
        hover.setAttribute("hidden", "");
        tip.hidden = true;
        return;
      }
      hover.removeAttribute("hidden");
      tip.innerHTML = [`<strong>${esc(fmtInstant(shown, config.days))}</strong>`, ...rows].join("<br>");
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

async function loadSensorSettings() {
  try {
    await ensureDashboard();
    const houses = state.dashboard.houses || [];
    const current = houses.find((house) => house.id === state.houseId);
    $("#sensors-house-name").textContent = current ? current.name : "";
    if (!state.houseId) {
      state.sensors = [];
      $("#sensor-list").innerHTML = '<p class="meta">No house is linked to your account yet.</p>';
      return;
    }
    if (!houseHasSensors()) {
      state.sensors = [];
      if (storedItem("usage-settings-tab", "meters") === "sensors") showSettingsTab("meters");
      return;
    }
    const data = await api(`/api/sensors?house_id=${state.houseId}`);
    state.sensors = data.sensors || [];
    renderSensorSettings();
  } catch (error) { showAppError(error); }
}

function renderSensorSettings() {
  const sensors = state.sensors || [];
  $("#sensor-list").innerHTML = sensors.map((sensor, index) => `
    <div class="mini-row wrap-row${sensor.active ? "" : " inactive"}">
      <span>
        <strong>${esc(sensor.name)}</strong>${sensor.unit ? ` · ${esc(sensor.unit)}` : ""}${sensor.active ? "" : ' <span class="badge">hidden</span>'}
        <br>
        <span class="meta">${esc(sensor.entity_id)}${sensor.last_value === null ? "" : ` · ${fmtTemp(sensor.last_value)} ${esc(sensor.unit)} ${esc(fmtAgo(sensor.last_at))}`}</span>
      </span>
      <span class="icon-actions">
        <button class="ghost compact icon-only" data-move-sensor="${sensor.id}" data-move-delta="-1" type="button"
          title="Move up"${index === 0 ? " disabled" : ""}>${ICON_UP}</button>
        <button class="ghost compact icon-only" data-move-sensor="${sensor.id}" data-move-delta="1" type="button"
          title="Move down"${index === sensors.length - 1 ? " disabled" : ""}>${ICON_DOWN}</button>
        <button class="ghost compact" data-edit-sensor="${sensor.id}" type="button">Edit</button>
        <button class="ghost compact" data-toggle-sensor="${sensor.id}" type="button"
          title="${sensor.active ? "Keep collecting, but leave it out of the graphs" : "Show it in the graphs again"}">${sensor.active ? "Hide" : "Show"}</button>
      </span>
    </div>`).join("") || '<p class="meta">No sensor yet - they appear once Home Assistant starts pushing readings.</p>';
  $$("[data-move-sensor]").forEach((button) => button.addEventListener("click", async () => {
    // The sensor order is shared by the whole house.
    const ids = state.sensors.map((sensor) => sensor.id);
    const index = ids.indexOf(Number(button.dataset.moveSensor));
    const target = index + Number(button.dataset.moveDelta);
    if (index < 0 || target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    try {
      await api("/api/sensors/order", { method: "POST", body: JSON.stringify({ house_id: state.houseId, sensor_ids: ids }) });
      await loadSensorSettings();
    } catch (error) { showAppError(error); }
  }));
  $$("[data-edit-sensor]").forEach((button) => button.addEventListener("click", async () => {
    const sensor = state.sensors.find((item) => item.id === Number(button.dataset.editSensor));
    const answers = await openModal({
      title: `Edit sensor · ${sensor.name}`,
      message: sensor.entity_id,
      fields: [
        { name: "name", label: "Name", value: sensor.name },
        { name: "unit", label: "Unit", value: sensor.unit },
        { name: "active", label: "Shown in the graphs", type: "checkbox", value: sensor.active },
      ],
    });
    if (answers === null) return;
    try {
      await api(`/api/sensors/${sensor.id}`, { method: "PUT", body: JSON.stringify({
        name: answers.name,
        unit: answers.unit,
        active: answers.active,
      }) });
      await loadSensorSettings();
    } catch (error) { showAppError(error); }
  }));
  $$("[data-toggle-sensor]").forEach((button) => button.addEventListener("click", async () => {
    // Hidden sensors keep collecting; deleting one would only bring it back on the next push.
    const sensor = state.sensors.find((item) => item.id === Number(button.dataset.toggleSensor));
    try {
      await api(`/api/sensors/${sensor.id}`, { method: "PUT", body: JSON.stringify({
        name: sensor.name,
        unit: sensor.unit,
        active: !sensor.active,
      }) });
      await loadSensorSettings();
    } catch (error) { showAppError(error); }
  }));
}

async function issueSensorToken(house) {
  const warning = house.has_sensor_token
    ? "This house already has a sensor token. Generating a new one stops the previous one at once: update Home Assistant with the new token."
    : "The token lets Home Assistant push the thermometers' readings into this house. It is shown once.";
  if (!await openModal({ title: `Sensor token · ${house.name}`, message: warning, submitLabel: "Generate" })) return;
  try {
    const data = await api(`/api/houses/${house.id}/sensor-token`, { method: "POST", body: "{}" });
    await openModal({
      title: `Sensor token · ${house.name}`,
      message: "Copy it now into Home Assistant's secrets.yaml (see deploy/home-assistant.yaml); it will not be shown again.",
      submitLabel: "Done",
      fields: [{ type: "html", html: `<div class="token-box">${esc(data.token)}</div>` }],
    });
    await loadAdmin();
  } catch (error) { showAppError(error); }
}

async function loadAdmin() {
  try {
    state.admin = await api("/api/admin/overview");
    $$("#settings-tabs button").forEach((button) => {
      if (button.dataset.settingsTab === "houses" || button.dataset.settingsTab === "users") button.hidden = false;
    });
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

async function loadReminder() {
  // The reminder applies to the selected house and is on unless opted out.
  try {
    await ensureDashboard();
    const houses = state.dashboard.houses || [];
    const current = houses.find((house) => house.id === state.houseId);
    $("#reminder-house").textContent = current ? current.name : "";
    $("#reminder-toggle").disabled = !state.houseId;
    if (!state.houseId) return;
    const data = await api("/api/me/reminders");
    $("#reminder-toggle").checked = !(data.disabled_house_ids || []).includes(state.houseId);
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

function timezoneOptions() {
  try { return Intl.supportedValuesOf("timeZone"); } catch (_) { return ["Europe/Paris", "America/Los_Angeles", "UTC"]; }
}

function renderHouses() {
  $("#house-list").innerHTML = (state.admin.houses || []).map((house) => `
    <div class="mini-row">
      <span><strong>${esc(house.name)}</strong> <span class="meta">· ${esc(house.timezone || "")}</span></span>
      <span>
        <button class="ghost compact" data-token-house="${house.id}" type="button"
          title="${house.has_sensor_token ? "Replace the Home Assistant sensor token" : "Create the Home Assistant sensor token"}">
          Sensor token${house.has_sensor_token ? ' <span class="badge">set</span>' : ""}</button>
        <button class="ghost compact" data-rename-house="${house.id}" type="button">Edit</button>
        <button class="ghost compact danger" data-delete-house="${house.id}" type="button">Delete</button>
      </span>
    </div>`).join("") || '<p class="meta">No house yet.</p>';
  $$("[data-token-house]").forEach((button) => button.addEventListener("click", () =>
    issueSensorToken((state.admin.houses || []).find((item) => item.id === Number(button.dataset.tokenHouse)))));
  $$("[data-rename-house]").forEach((button) => button.addEventListener("click", async () => {
    const house = (state.admin.houses || []).find((item) => item.id === Number(button.dataset.renameHouse));
    const answers = await openModal({
      title: `Edit house · ${house.name}`,
      fields: [
        { name: "name", label: "House name", value: house.name },
        // The reminder email goes out at 06:15 in the house's own time zone.
        { name: "timezone", label: "Time zone", type: "select", value: house.timezone, options: timezoneOptions() },
      ],
    });
    if (answers === null || !answers.name.trim()) return;
    try {
      await api(`/api/houses/${house.id}`, { method: "PUT", body: JSON.stringify({
        name: answers.name.trim(),
        timezone: answers.timezone,
      }) });
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

const ICON_AXIS_LEFT = '<svg class="msym" fill="currentColor" xmlns="http://www.w3.org/2000/svg" viewBox="0 -960 960 960"><path d="M80-80v-800h80v800H80Zm160-160v-160h640v160H240Zm0-320v-160h400v160H240Z"/></svg>';
const ICON_AXIS_RIGHT = '<svg class="msym" fill="currentColor" xmlns="http://www.w3.org/2000/svg" viewBox="0 -960 960 960"><path d="M800-80v-800h80v800h-80ZM80-240v-160h640v160H80Zm240-320v-160h400v160H320Z"/></svg>';
const ICON_UP = '<svg class="msym" fill="currentColor" xmlns="http://www.w3.org/2000/svg" viewBox="0 -960 960 960"><path d="M440-160v-487L216-423l-56-57 320-320 320 320-56 57-224-224v487h-80Z"/></svg>';
const ICON_DOWN = '<svg class="msym" fill="currentColor" xmlns="http://www.w3.org/2000/svg" viewBox="0 -960 960 960"><path d="M480-160 160-480l56-57 224 224v-487h80v487l224-224 56 57-320 320Z"/></svg>';

function renderMeters() {
  const meters = state.meters || [];
  $("#meter-list").innerHTML = meters.map((meter, index) => `
    <div class="mini-row wrap-row${meter.active ? "" : " inactive"}">
      <span>
        <strong>${esc(meter.label || meter.kind)}</strong> · ${esc(meter.kind)}
        ${meter.unit ? ` · ${esc(meter.unit)}` : ""}${meter.monthly ? ' <span class="badge">monthly value</span>' : ""}${meter.active ? "" : ' <span class="badge">inactive</span>'}
        <br>
        <span class="meta">${meter.registers.map((register) =>
          `${esc(register.label || "register")}${meter.monthly ? "" : ` (start ${register.initial_value})`}${register.active ? "" : " — inactive"}`).join(" · ")}</span>
      </span>
      <span class="icon-actions">
        <button class="ghost compact icon-only" data-color-meter="${meter.id}" type="button" title="Choose the colour">
          <span class="swatch" style="background:${esc(meter.color || "var(--muted)")}"></span>
        </button>
        <button class="ghost compact icon-only${meter.axis === "right" ? " active" : ""}" data-axis-meter="${meter.id}" type="button"
          title="Merged graph: ${meter.axis === "right" ? "right axis (click for left)" : "left axis (click for right)"}">
          ${meter.axis === "right" ? ICON_AXIS_RIGHT : ICON_AXIS_LEFT}
        </button>
        <button class="ghost compact icon-only" data-move-meter="${meter.id}" data-move-delta="-1" type="button"
          title="Move up"${index === 0 ? " disabled" : ""}>${ICON_UP}</button>
        <button class="ghost compact icon-only" data-move-meter="${meter.id}" data-move-delta="1" type="button"
          title="Move down"${index === meters.length - 1 ? " disabled" : ""}>${ICON_DOWN}</button>
        <button class="ghost compact" data-edit-meter="${meter.id}" type="button">Edit</button>
        <button class="ghost compact danger" data-delete-meter="${meter.id}" type="button">Delete</button>
      </span>
    </div>`).join("") || '<p class="meta">No meter yet.</p>';
  $$("[data-move-meter]").forEach((button) => button.addEventListener("click", async () => {
    // The order is personal: it only changes what THIS user sees everywhere.
    const ids = state.meters.map((meter) => meter.id);
    const index = ids.indexOf(Number(button.dataset.moveMeter));
    const target = index + Number(button.dataset.moveDelta);
    if (index < 0 || target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    try {
      await api("/api/me/meter-order", { method: "POST", body: JSON.stringify({ house_id: state.houseId, meter_ids: ids }) });
      await loadMeters();
    } catch (error) { showAppError(error); }
  }));
  $$("[data-axis-meter]").forEach((button) => button.addEventListener("click", async () => {
    // Which side of the merged graph this meter reads on - personal, like the colour.
    const meter = state.meters.find((item) => item.id === Number(button.dataset.axisMeter));
    try {
      await api("/api/me/meter-axis", { method: "POST", body: JSON.stringify({
        meter_id: meter.id,
        axis: meter.axis === "right" ? "left" : "right",
      }) });
      await loadMeters();
    } catch (error) { showAppError(error); }
  }));
  $$("[data-color-meter]").forEach((button) => button.addEventListener("click", async () => {
    // The colour is personal, like the order: it follows this user everywhere.
    const meter = state.meters.find((item) => item.id === Number(button.dataset.colorMeter));
    const choice = await openModal({
      title: `Colour of ${meter.label || meter.kind}`,
      options: [
        { value: "", label: "Default", active: !meter.color },
        ...METER_COLORS.map((color) => ({ ...color, color: color.value, active: meter.color === color.value })),
      ],
    });
    if (choice === null) return;
    try {
      await api("/api/me/meter-color", { method: "POST", body: JSON.stringify({ meter_id: meter.id, color: choice.value }) });
      await loadMeters();
    } catch (error) { showAppError(error); }
  }));
  $$("[data-edit-meter]").forEach((button) => button.addEventListener("click", () =>
    editMeter(Number(button.dataset.editMeter))));
  $$("[data-delete-meter]").forEach((button) => button.addEventListener("click", async () => {
    if (!await confirmModal("Delete meter", "Delete this meter and all its readings?")) return;
    try {
      await api(`/api/meters/${button.dataset.deleteMeter}`, { method: "DELETE" });
      await loadMeters();
    } catch (error) { showAppError(error); }
  }));
}

const ICON_EDIT = '<svg class="msym" fill="currentColor" xmlns="http://www.w3.org/2000/svg" viewBox="0 -960 960 960"><path d="M200-200h57l391-391-57-57-391 391v57Zm-80 80v-170l528-527q12-11 26.5-17t30.5-6q16 0 31 6t26 18l55 56q12 11 17.5 26t5.5 30q0 16-5.5 30.5T817-647L290-120H120Zm640-584-56-56 56 56Zm-141 85-28-29 57 57-29-28Z"/></svg>';
const ICON_DELETE = '<svg class="msym" fill="currentColor" xmlns="http://www.w3.org/2000/svg" viewBox="0 -960 960 960"><path d="M280-120q-33 0-56.5-23.5T200-200v-520h-40v-80h200v-40h240v40h200v80h-40v520q0 33-23.5 56.5T680-120H280Zm400-600H280v520h400v-520ZM360-280h80v-360h-80v360Zm160 0h80v-360h-80v360ZM280-720v520-520Z"/></svg>';
const ICON_ADD = '<svg class="msym" fill="currentColor" xmlns="http://www.w3.org/2000/svg" viewBox="0 -960 960 960"><path d="M440-440H200v-80h240v-240h80v240h240v80H520v240h-80v-240Z"/></svg>';

function registerRowsMarkup(meter) {
  // The meter modal lists the registers; each row edits or deletes in a
  // stacked modal, and the last row adds one.
  return meter.registers.map((register) => `
    <div class="mini-row${register.active ? "" : " inactive"}">
      <span>${esc(register.label || "register")}${meter.monthly ? "" : ` (start ${register.initial_value})`}${register.active ? "" : " — inactive"}</span>
      <span class="icon-actions">
        <button class="ghost compact icon-only" data-modal-edit-register="${register.id}" type="button" title="Edit the register">${ICON_EDIT}</button>
        <button class="ghost compact icon-only danger" data-modal-delete-register="${register.id}" type="button" title="Delete the register">${ICON_DELETE}</button>
      </span>
    </div>`).join("") + `
    <div class="mini-row">
      <span class="meta">Add a register</span>
      <span class="icon-actions">
        <button class="ghost compact icon-only" data-modal-add-register type="button" title="Add a register">${ICON_ADD}</button>
      </span>
    </div>`;
}

async function refreshModalRegisters(meterId) {
  await loadMeters();
  const meter = state.meters.find((item) => item.id === meterId);
  const holder = $("#modal-registers");
  if (!holder || !meter) return;
  holder.innerHTML = registerRowsMarkup(meter);
  wireModalRegisters(meterId);
}

function wireModalRegisters(meterId) {
  $$("[data-modal-edit-register]").forEach((button) => button.addEventListener("click", async () => {
    const meter = state.meters.find((item) => item.id === meterId);
    const register = meter.registers.find((item) => item.id === Number(button.dataset.modalEditRegister));
    const answers = await openModal({
      top: true,
      title: `Edit register · ${register.label || "register"}`,
      fields: [
        { name: "label", label: "Register label (e.g. HP)", value: register.label },
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
    } catch (error) { showAppError(error); }
    await refreshModalRegisters(meterId);
  }));
  $$("[data-modal-delete-register]").forEach((button) => button.addEventListener("click", async () => {
    if (!await confirmModal("Delete register", "Delete this register and its values?", "Delete", true)) return;
    try {
      await api(`/api/registers/${button.dataset.modalDeleteRegister}`, { method: "DELETE" });
    } catch (error) { showAppError(error); }
    await refreshModalRegisters(meterId);
  }));
  const addButton = $("[data-modal-add-register]");
  if (addButton) addButton.addEventListener("click", async () => {
    const answers = await openModal({
      top: true,
      title: "Add a register",
      submitLabel: "Add",
      fields: [
        { name: "label", label: "Register label (e.g. HP)", value: "" },
        { name: "initial_value", label: "Start value of the counter", type: "number", value: "" },
      ],
    });
    if (answers === null) return;
    try {
      await api(`/api/meters/${meterId}/registers`, { method: "POST", body: JSON.stringify({
        label: answers.label.trim(),
        initial_value: Number(answers.initial_value) || 0,
      }) });
    } catch (error) { showAppError(error); }
    await refreshModalRegisters(meterId);
  });
}

async function editMeter(meterId) {
  const meter = state.meters.find((item) => item.id === meterId);
  if (!meter) return;
  const promise = openModal({
    title: `Edit meter · ${meter.label || meter.kind}`,
    fields: [
      { name: "label", label: "Label", value: meter.label },
      { name: "unit", label: "Unit", value: meter.unit },
      { name: "monthly", label: "Monthly value (each entry is the consumption of the month, not a counter)", type: "checkbox", value: meter.monthly },
      { name: "active", label: "Active", type: "checkbox", value: meter.active },
      { type: "heading", label: "Registers" },
      { type: "html", html: `<div id="modal-registers">${registerRowsMarkup(meter)}</div>` },
    ],
  });
  wireModalRegisters(meterId);
  const answers = await promise;
  if (answers === null) return;
  try {
    await api(`/api/meters/${meterId}`, { method: "PUT", body: JSON.stringify({
      label: answers.label,
      unit: answers.unit,
      monthly: answers.monthly,
      active: answers.active,
    }) });
    await loadMeters();
  } catch (error) { showAppError(error); }
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

async function addMeter(event) {
  event.preventDefault();
  const registers = [
    { label: $("#register-one-label").value.trim(), initial_value: Number($("#register-one-initial").value) || 0 },
  ];
  try {
    await api("/api/meters", { method: "POST", body: JSON.stringify({
      house_id: state.houseId,
      kind: $("#meter-kind").value,
      label: $("#meter-label").value.trim(),
      unit: $("#meter-unit").value.trim(),
      monthly: $("#meter-monthly").checked,
      registers,
    }) });
    $("#meter-label").value = "";
    $("#meter-unit").value = "";
    $("#meter-monthly").checked = false;
    $("#meter-register-row").hidden = false;
    $("#register-one-label").value = "";
    $("#register-one-initial").value = "";
    await loadMeters();
  } catch (error) { showAppError(error); }
}

async function logout() {
  try { await api("/api/auth/logout", { method: "POST", body: "{}" }); } catch (_) {}
  location.reload();
}

function registerServiceWorker() {
  // Installable app: the service worker makes the shell cacheable offline.
  // Registered from here rather than an inline script, which the production
  // Content Security Policy (script-src 'self') blocks.
  if (!("serviceWorker" in navigator)) return;
  const build = (document.querySelector('meta[name="app-version"]') || {}).content || "";
  navigator.serviceWorker.register(`/sw.js?v=${encodeURIComponent(build)}`, { scope: "/" }).catch(() => {});
}

addEventListener("load", registerServiceWorker);

addEventListener("DOMContentLoaded", () => {
  $("#request-link-form").addEventListener("submit", requestLink);
  $("#btn-passkey").addEventListener("click", signInWithPasskey);
  $("#btn-logout").addEventListener("click", logout);
  $("#btn-add-passkey").addEventListener("click", registerPasskey);
  $("#reminder-toggle").addEventListener("change", async () => {
    const toggle = $("#reminder-toggle");
    try {
      await api("/api/me/reminders", { method: "POST", body: JSON.stringify({ house_id: state.houseId, enabled: toggle.checked }) });
    } catch (error) {
      toggle.checked = !toggle.checked;
      showAppError(error);
    }
  });
  $("#house-form").addEventListener("submit", addHouse);
  $("#user-form").addEventListener("submit", addUser);
  $("#meter-form").addEventListener("submit", addMeter);
  // A monthly meter has no counter: the start-value row would only mislead.
  $("#meter-monthly").addEventListener("change", () => {
    $("#meter-register-row").hidden = $("#meter-monthly").checked;
  });
  $("#house-btn").addEventListener("click", chooseHouse);
  $$("[data-sensor-days]").forEach((button) => button.addEventListener("click", () => {
    storeItem("usage-sensor-days", button.dataset.sensorDays);
    state.sensorOffset = 0;
    loadSensors();
  }));
  $("#sensor-earlier").addEventListener("click", () => { state.sensorOffset += 1; loadSensors(); });
  $("#sensor-later").addEventListener("click", () => {
    if (!state.sensorOffset) return;
    state.sensorOffset -= 1;
    loadSensors();
  });
  $("#sensor-celsius").addEventListener("change", () => {
    storeItem("usage-temp-unit", $("#sensor-celsius").checked ? "C" : "F");
    renderSensors();
  });
  $("#sensor-previous").addEventListener("change", () => {
    storeItem("usage-sensor-previous", $("#sensor-previous").checked ? "1" : "0");
    loadSensors();
  });
  // On narrow screens the version hides behind the info icon: a tap reveals it.
  $("#version").addEventListener("click", () => $("#version").classList.toggle("open"));
  $("#stats-show-tables").addEventListener("change", saveStatsPrefs);
  $("#stats-show-graphs").addEventListener("change", saveStatsPrefs);
  $("#stats-merge-graphs").addEventListener("change", saveStatsPrefs);
  wireYearSlider();
  $("#year-reset").addEventListener("click", () => {
    if (state.yearBounds) applyYearRange(state.yearBounds.min, state.yearBounds.max);
  });
  $("#reading-meter").addEventListener("change", renderValueInputs);
  $("#reading-photo").addEventListener("change", readPhoto);
  $("#reading-camera").addEventListener("change", cameraPhoto);
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
