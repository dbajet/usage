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
  sensorsHouseId: 0,
  sensorDays: 1,
  sensorOffset: 0,
  hiddenSensors: new Set(),
  hiddenPower: new Set(),
  // One pending timer per feed, each set from the wait the server named in
  // that feed's own last answer.
  realtimeTimers: {},
  realtimeAgeId: null,
  waterData: null,
  waterFeeds: null,
  powerData: null,
  enphaseFeeds: null,
  enphaseLocal: null,
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
  { label: "Forest", value: "#3d8f3d" },
  { label: "Amber", value: "#c98a1a" },
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
  // `quiet` is for the Realtime timers. They fire while a hand is still resting
  // on whatever was clicked last, and a background refresh has no business
  // greying out a button nobody pressed.
  const { quiet = false, ...request } = options;
  const busyButton = quiet ? null : beginButtonBusy();
  try {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(request.headers || {}) },
      ...request,
    });
    if (!response.ok) {
      let message = "The request failed.";
      try { message = (await response.json()).detail || message; } catch (_) {}
      throw new Error(message);
    }
    // Anything that writes can change the houses, meters or sensors the
    // dashboard carries: its cache goes, so the next reader refetches.
    if ((request.method || "GET").toUpperCase() !== "GET") invalidateDashboard();
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

function openModal({ title, message = "", fields = [], options = [], submitLabel = "Save", danger = false, remove = false, top = false, compact = false }) {
  return new Promise((resolve) => {
    // Two layers: the base modal, and one that can stack on top of it.
    const part = (name) => $(top ? `#modal2-${name}` : `#modal-${name}`);
    const backdrop = part("backdrop");
    part("title").textContent = title;
    const messageTarget = part("message");
    messageTarget.textContent = message;
    messageTarget.hidden = !message;
    part("fields").classList.toggle("compact-options", compact && options.length > 0);
    part("fields").innerHTML = options.length
      ? options.map((option) => `
          <button class="ghost option${option.active ? " active" : ""}${option.wide ? " wide" : ""}" type="button" data-modal-option="${esc(String(option.value))}">
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
    if (!state.me.is_admin && ["houses", "users", "water", "enphase"].includes(tab)) tab = "meters";
    showSettingsTab(tab);
    loadPasskeys();
    loadMeters();
    loadSensorSettings();
    loadWaterSettings();
    loadEnphaseSettings();
    loadReminder();
    if (state.me && state.me.is_admin) loadAdmin();
  }
  if (name === "entries") loadEntries();
  if (name === "stats") loadStats();
  // The feeds cannot be scheduled before they have answered: each one names
  // its own next wait, so the first load is what starts the clocks.
  if (name === "sensors") loadSensors();
  else stopRealtime();
}

async function chooseHouseView() {
  // After the house changes, a view or tab the new house cannot show falls
  // back. Returns the view to open, so the caller loads it exactly once.
  await ensureDashboard();
  if (currentView() === "sensors" && !houseHasRealtime()) return "stats";
  return currentView();
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

// Opening a view wakes several loaders at once and each wants the dashboard:
// they share one request, and a result a few seconds old is reused rather
// than fetched again. Any write invalidates it, so nothing goes stale.
const DASHBOARD_FRESH_MS = 5000;
let dashboardCache = { at: 0, request: null };

function invalidateDashboard() {
  dashboardCache = { at: 0, request: null };
}

function fetchDashboard() {
  if (state.dashboard && Date.now() - dashboardCache.at <= DASHBOARD_FRESH_MS) {
    return Promise.resolve(state.dashboard);
  }
  if (!dashboardCache.request) {
    const request = api("/api/dashboard");
    dashboardCache.request = request;
    request.then(
      () => { dashboardCache.at = Date.now(); dashboardCache.request = null; },
      () => { dashboardCache.request = null; },
    );
  }
  return dashboardCache.request;
}

async function ensureDashboard() {
  state.dashboard = await fetchDashboard();
  const houses = state.dashboard.houses || [];
  if (!state.houseId) state.houseId = Number(storedItem("usage-house", "0"));
  if (!houses.some((house) => house.id === state.houseId)) {
    state.houseId = houses.length ? houses[0].id : 0;
  }
  storeItem("usage-house", state.houseId);
  const current = houses.find((house) => house.id === state.houseId);
  $("#house-name").textContent = current ? current.name : "";
  $("#house-btn").hidden = houses.length < 2;
  // Each house says what it measures (Settings, Houses, Edit): the Realtime
  // nav item and the two settings tabs follow that, not the data.
  const hasSensors = Boolean(current && current.has_sensors);
  const hasWater = Boolean(current && current.has_water);
  const hasPower = Boolean(current && current.has_power);
  $('[data-nav="sensors"]').hidden = !hasSensors && !hasWater && !hasPower;
  $('[data-settings-tab="sensors"]').hidden = !hasSensors;
  // Every half is per house, and the two feeds are an admin's to set up.
  const admin = Boolean(state.me && state.me.is_admin);
  const showsWater = hasWater && admin;
  const showsPower = hasPower && admin;
  $('[data-settings-tab="water"]').hidden = !showsWater;
  $('[data-settings-tab="enphase"]').hidden = !showsPower;
  // A tab that has just been hidden cannot stay the selected one. This waits for
  // the dashboard on purpose: deciding earlier would answer "no" for every house,
  // and a restored Water tab would fall back to Meters on the way in.
  const tab = storedItem("usage-settings-tab", "meters");
  const gone = (tab === "sensors" && !hasSensors) || (tab === "water" && !showsWater)
    || (tab === "enphase" && !showsPower);
  if (gone && currentView() === "settings") showSettingsTab("meters");
}

function houseHasSensors() {
  const current = ((state.dashboard && state.dashboard.houses) || []).find((house) => house.id === state.houseId);
  return Boolean(current && current.has_sensors);
}

function houseHasWater() {
  const current = ((state.dashboard && state.dashboard.houses) || []).find((house) => house.id === state.houseId);
  return Boolean(current && current.has_water);
}

// What each half of the Realtime view is called, and how to ask whether this
// house has it. The controls above the view name the halves they serve.
const REALTIME_HALVES = {
  sensors: () => houseHasSensors(),
  water: () => houseHasWater(),
  power: () => houseHasPower(),
};

function houseHasPower() {
  const current = ((state.dashboard && state.dashboard.houses) || []).find((house) => house.id === state.houseId);
  return Boolean(current && current.has_power);
}

function houseHasRealtime() {
  return houseHasSensors() || houseHasWater() || houseHasPower();
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
  showView(await chooseHouseView());
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
// What a feed waits when the server declined to say - a feed that errored, or
// an older build answering mid-deploy.
const REALTIME_FALLBACK_MS = 5 * 60 * 1000;
// "5 min ago" is wrong a minute later whether or not a byte changed, so the
// words are retouched on their own clock. Text only: nothing is redrawn.
const REALTIME_AGE_MS = 60 * 1000;
const BATTERY_LOW_PERCENT = 20;
const ICON_CHEVRON_LEFT = '<svg class="msym" fill="currentColor" xmlns="http://www.w3.org/2000/svg" viewBox="0 -960 960 960"><path d="M560-240 320-480l240-240 56 56-184 184 184 184-56 56Z"/></svg>';
const ICON_REFRESH = '<svg class="msym" fill="currentColor" xmlns="http://www.w3.org/2000/svg" viewBox="0 -960 960 960"><path d="M480-160q-134 0-227-93t-93-227q0-134 93-227t227-93q69 0 132 28.5T720-690v-110h80v280H520v-80h168q-32-56-87.5-88T480-720q-100 0-170 70t-70 170q0 100 70 170t170 70q77 0 139-44t87-116h84q-28 106-114 173t-196 67Z"/></svg>';
const ICON_CHEVRON_RIGHT = '<svg class="msym" fill="currentColor" xmlns="http://www.w3.org/2000/svg" viewBox="0 -960 960 960"><path d="M504-480 320-664l56-56 240 240-240 240-56-56 184-184Z"/></svg>';
const LONG_PRESS_MS = 500;
const ICON_THERMOMETER = '<svg class="msym" fill="currentColor" xmlns="http://www.w3.org/2000/svg" viewBox="0 -960 960 960"><path d="M480-80q-83 0-141.5-58.5T280-280q0-48 21-89.5t59-70.5v-280q0-50 35-85t85-35q50 0 85 35t35 85v280q38 29 59 70.5t21 89.5q0 83-58.5 141.5T480-80Zm-40-440h80v-40h-40v-40h40v-80h-40v-40h40v-40q0-17-11.5-28.5T480-800q-17 0-28.5 11.5T440-760v240Z"/></svg>';
const ICON_DROP = '<svg class="msym" fill="currentColor" xmlns="http://www.w3.org/2000/svg" viewBox="0 -960 960 960"><path d="M480-80q-137 0-228.5-94T160-408q0-100 79.5-217.5T480-880q161 137 240.5 254.5T800-408q0 140-91.5 234T480-80Z"/></svg>';
const ICON_SUN = '<svg class="msym" fill="currentColor" xmlns="http://www.w3.org/2000/svg" viewBox="0 -960 960 960"><path d="M440-800v-120h80v120h-80Zm0 760v-120h80v120h-80Zm360-400v-80h120v80H800ZM40-440v-80h120v80H40Zm708-252-56-56 70-72 58 58-72 70Zm-580 580-58-58 72-70 56 56-70 72Zm622 0-70-72 56-56 72 70-58 58ZM168-692l-72-70 58-58 70 72-56 56Zm312 452q-100 0-170-70t-70-170q0-100 70-170t170-70q100 0 170 70t70 170q0 100-70 170t-170 70Z"/></svg>';

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

async function chooseColor(title, current) {
  // Named colours, the default, or any colour from the browser's own dialog.
  // Returns the hex value ("" for the default), or null when cancelled.
  const choice = await openModal({
    title,
    compact: true,
    options: [
      { value: "", label: "Default", active: !current, wide: true },
      ...METER_COLORS.map((color) => ({ ...color, color: color.value, active: current === color.value })),
      { value: "__custom", label: "Pick your own…", active: Boolean(current) && !METER_COLORS.some((color) => color.value === current), wide: true },
    ],
  });
  if (choice === null) return null;
  if (choice.value !== "__custom") return choice.value;
  const answers = await openModal({
    title,
    submitLabel: "Use",
    fields: [{ name: "color", label: "Colour", type: "color", value: current || "#2a78d6" }],
  });
  return answers === null ? null : String(answers.color || "").toLowerCase();
}

function wantsMetric() {
  // One switch for the whole view: Celsius with litres, or Fahrenheit with
  // gallons. Stored under the old key, so nobody's choice is lost.
  return storedItem("usage-temp-unit", "F") === "C";
}

function wantsPrevious() {
  return storedItem("usage-sensor-previous", "0") === "1";
}

function wantsThresholds() {
  return storedItem("usage-sensor-thresholds", "0") === "1";
}

function storeThresholds(show) {
  storeItem("usage-sensor-thresholds", show ? "1" : "0");
}

function setToggle(selector, on) {
  // Pressed is on, for the icon toggles that replaced the sliders: the state
  // has to reach the assistive label as well as the eye.
  const button = $(selector);
  button.classList.toggle("active", on);
  button.setAttribute("aria-pressed", on ? "true" : "false");
}

// The three feeds behind the view: a question it asks, an answer it keeps, and
// the card that answer draws. They used to go out together on one timer and be
// redrawn together whether or not a number had moved. Now each is asked only
// once the thing behind it could have answered - the gateway pushes every
// minute, the thermometers every ten, the water meter is pulled every quarter
// of an hour - and redrawn only when the answer differs from the one on screen.
const REALTIME_FEEDS = [
  { key: "sensors", store: "sensorData", path: "/api/sensors/series", has: () => houseHasSensors() },
  { key: "water", store: "waterData", path: "/api/water/series", has: () => houseHasWater() },
  { key: "power", store: "powerData", path: "/api/enphase/series", has: () => houseHasPower() },
];

function feedUrl(feed) {
  // Every feed follows the same range, offset and overlay, so the graphs of the
  // view always show one window however far apart their clocks are.
  return `${feed.path}?house_id=${state.houseId}&days=${state.sensorDays}`
    + `&previous=${wantsPrevious()}&offset=${state.sensorOffset}`;
}

function cancelFeed(feed) {
  // Both the timer and the note of it: forgetting one without the other leaves
  // a request armed that nobody is expecting, which is a second poll a moment
  // after the one that replaced it.
  clearTimeout(state.realtimeTimers[feed.key]);
  delete state.realtimeTimers[feed.key];
}

function scheduleFeed(feed, seconds) {
  // A timeout, not an interval: the wait is named afresh in every answer, so a
  // house whose gateway goes quiet slows down on its own rather than holding
  // the pace it happened to have when the view was opened.
  //
  // An earlier period is not scheduled at all. It cannot change - there the
  // arrows, not a timer, move the view.
  cancelFeed(feed);
  // A graph the house does not have, one the viewer has switched off, and an
  // earlier period are all asked for nothing at all.
  if (state.sensorOffset !== 0 || !feed.has() || !showsCard(feed.key)) return;
  const wait = Number(seconds) > 0 ? Number(seconds) * 1000 : REALTIME_FALLBACK_MS;
  state.realtimeTimers[feed.key] = setTimeout(() => refreshFeed(feed), wait);
}

async function refreshFeed(feed) {
  // The quiet half of the view's life: no wheel, no rebuild, and nothing at all
  // on screen unless this feed's answer differs from the one already drawn.
  // What counts as different is the server's word - it stamps everything the
  // card draws - and not a comparison of the replies, which carry the window's
  // own end and so are never twice the same.
  // Asked for by hand as well as by the clock - switching a graph back on asks
  // at once - so whatever was pending is dropped rather than left to fire.
  cancelFeed(feed);
  if ($("#view-sensors").hidden || state.sensorOffset !== 0 || state.sensorsHouseId !== state.houseId) return;
  const asked = feedUrl(feed);
  try {
    const data = await api(asked, { quiet: true });
    // A house, a range or a period changed while this was in flight: the answer
    // describes a window nobody is looking at any more, and the load that made
    // the change is bringing the right one. Dropping it is the whole of the fix.
    if (asked !== feedUrl(feed) || state.sensorsHouseId !== state.houseId) return;
    // An answer with no stamp at all is treated as new rather than as the same:
    // during a blue/green switch the other colour may still be replying, and a
    // card that quietly stopped redrawing would be the worse of the two errors.
    const changed = !data.stamp || (state[feed.store] || {}).stamp !== data.stamp;
    state[feed.store] = data;
    if (changed) renderRealtimeCard(feed.key);
    scheduleFeed(feed, data.next_poll_seconds);
  } catch (error) {
    // A feed that cannot answer is not worth a banner over a graph that is
    // still perfectly readable, and a flaky connection would raise one every
    // time. It is simply asked again at the fallback pace.
    scheduleFeed(feed, 0);
  }
}

function startRealtime() {
  // Called once each feed has answered, because the pace comes out of the
  // answer: there is nothing to schedule until the first one is in.
  REALTIME_FEEDS.forEach((feed) => scheduleFeed(feed, (state[feed.store] || {}).next_poll_seconds));
  clearInterval(state.realtimeAgeId);
  state.realtimeAgeId = setInterval(refreshAges, REALTIME_AGE_MS);
}

function stopRealtime() {
  Object.values(state.realtimeTimers).forEach((id) => clearTimeout(id));
  state.realtimeTimers = {};
  clearInterval(state.realtimeAgeId);
  state.realtimeAgeId = null;
}

function wireTileGestures(tile, solo, toggle) {
  // Plain click picks one, Ctrl/Cmd+click or a long press adds and removes.
  // Touch events rather than pointer events: Chrome cancels the pointer on a
  // long hold but keeps the touch sequence alive. The toggle re-renders the
  // tiles, so the click the browser fires afterwards lands on a new element:
  // a shared flag swallows it.
  let pressTimer = null;
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
}

function pickOne(keys, hidden, key) {
  // What a plain click means: this one alone, or everyone back when it already is.
  const visible = keys.filter((item) => !hidden.has(item));
  if (visible.length === 1 && visible[0] === key) return new Set();
  return new Set(keys.filter((item) => item !== key));
}

function toggleOne(keys, hidden, key) {
  // What Ctrl+click means: add or remove, and hiding the last brings all back.
  const visible = keys.filter((item) => !hidden.has(item));
  if (visible.length === keys.length) return new Set(keys.filter((item) => item !== key));
  const result = new Set(hidden);
  if (result.has(key)) result.delete(key);
  else result.add(key);
  return keys.every((item) => result.has(item)) ? new Set() : result;
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
  if (wantsMetric() && unit === "°F") return { value: ((value - 32) * 5) / 9, unit: "°C" };
  if (!wantsMetric() && unit === "°C") return { value: (value * 9) / 5 + 32, unit: "°F" };
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

// Twelve distinct defaults, so a dozen thermometers never share a colour:
// the six theme-aware series colours, then the picker's other six.
const SENSOR_DEFAULT_COLORS = [...VIZ_COLORS, ...METER_COLORS.slice(6).map((color) => color.value)];

function batteryMarkup(sensor) {
  // The charge of the thermometer itself, drawn as a battery filled to its level
  // in the corner under the reading: a glance is enough, and the number is there
  // for the exact charge.
  if (sensor.battery === null || sensor.battery === undefined) return "";
  const level = Math.max(0, Math.min(100, Math.round(sensor.battery)));
  const filled = (level / 100) * 10;
  const when = sensor.battery_at ? ` · ${fmtAgo(sensor.battery_at)}` : "";
  return `<span class="tile-battery${level <= BATTERY_LOW_PERCENT ? " low" : ""}"
    title="Battery ${level}%${esc(when)}" aria-label="Battery ${level} percent">
    <svg viewBox="0 0 16 9" width="16" height="9" aria-hidden="true">
      <rect class="shell" x="0.5" y="0.5" width="12" height="8" rx="1.5"></rect>
      <rect class="cap" x="13.5" y="2.5" width="2" height="4" rx="0.7"></rect>
      <rect class="level" x="1.5" y="1.5" width="${filled.toFixed(1)}" height="6" rx="0.6"></rect>
    </svg><span class="tile-battery-text">${level}%</span></span>`;
}

function heardFrom(sensor) {
  // What the tile counts from: when Home Assistant last heard this thermometer
  // confirm its reading, not when that reading last happened to move. A room
  // holding 19.4 all afternoon is not a thermometer that went quiet at lunch,
  // and an outdoor one that only resolves to a fifth of a degree can sit half
  // an hour on the same number while reporting every minute.
  //
  // Falls back to the reading's own instant, which is all there is to go on
  // until the Home Assistant template sends `reported_at` too.
  return sensor.reported_at || sensor.last_at;
}

function sensorColors(sensors) {
  // A sensor's own colour, else a default from its rank among the active ones:
  // tiles, lines and legend agree.
  return new Map(sensors.filter((sensor) => sensor.active).map((sensor, index) =>
    [sensor.id, sensor.color || SENSOR_DEFAULT_COLORS[index % SENSOR_DEFAULT_COLORS.length]]));
}

async function loadSensors(seriesOnly = false) {
  try {
    // Changing the period, the range or the overlay only moves the graph: the
    // house and the sensor list are already loaded, so one request goes out
    // instead of three. Entering the view, or switching house, reloads all.
    const reuse = seriesOnly && state.sensors !== null && state.sensorsHouseId === state.houseId;
    if (!reuse) {
      await ensureDashboard();
      if (!state.houseId) {
        $("#sensor-content").innerHTML = '<p class="meta">No house is linked to your account yet.</p>';
        return;
      }
      if (!houseHasRealtime()) { showView("stats"); return; }
    }
    state.sensorDays = Number(storedItem("usage-sensor-days", "1")) || 1;
    $("#sensor-units").checked = wantsMetric();
    setToggle("#sensor-previous", wantsPrevious());
    setToggle("#sensor-thresholds", wantsThresholds());
    // Each control is offered to the houses it can actually do something for.
    // The alert lines are the thermometers' alone, but the overlay redraws every
    // graph on the view and the unit switch governs volumes as well as degrees -
    // a water-only house was being denied both for no reason.
    $$("#view-sensors .sensor-controls [data-needs]").forEach((control) => {
      control.hidden = !control.dataset.needs.split(" ").some((half) => REALTIME_HALVES[half]());
    });
    $$("[data-sensor-days]").forEach((button) => button.classList.toggle("active", Number(button.dataset.sensorDays) === state.sensorDays));
    // A load asked for by hand - entering the view, changing the range, the
    // refresh button - is the only one that shows the wheel. The timers work in
    // silence, or the view would blink at every feed that had nothing to say.
    stopRealtime();
    showSensorsLoading();
    // Every feed leaves together here, so the whole view arrives in one window
    // rather than filling in a card at a time. Only afterwards do they part
    // ways and go each at their own pace.
    const [list, ...answers] = await Promise.all([
      reuse
        ? Promise.resolve({ sensors: state.sensors })
        : api(`/api/sensors?house_id=${state.houseId}`),
      ...REALTIME_FEEDS.map((feed) => (feed.has() ? api(feedUrl(feed)) : Promise.resolve(feedBlank(feed)))),
    ]);
    state.sensors = list.sensors || [];
    state.sensorsHouseId = state.houseId;
    REALTIME_FEEDS.forEach((feed, index) => { state[feed.store] = answers[index]; });
    renderSensors();
    startRealtime();
  } catch (error) {
    $("#sensor-content").classList.remove("loading");
    showAppError(error);
  }
}

function feedBlank(feed) {
  // What a house that does not have this half holds instead. The thermometers
  // answer with an empty period rather than nothing at all, because the period
  // bar is read off whichever series came back.
  return feed.key === "sensors" ? { days: state.sensorDays, bucket_minutes: 10, series: [] } : null;
}

function showSensorsLoading() {
  // A wheel on the graph while the data comes in: over the previous curves
  // when switching period or range, alone on the first load.
  const content = $("#sensor-content");
  if (!content.querySelector(".graph-card")) {
    content.innerHTML = '<div class="period-bar"><span class="period-label">&nbsp;</span></div><div class="card graph-card empty"></div>';
  }
  content.classList.add("loading");
}

function realtimeSensors() {
  // Who the thermometers are, crossed with what they last read. The two change
  // on entirely different clocks: a name, a colour and an order only move when
  // somebody edits them in Settings, while the reading on the tile moves with
  // every push - and so it travels with the graph rather than with the list,
  // which is why a tile used to sit on an hour-old value beside a line that had
  // just been redrawn.
  const latest = new Map(((state.sensorData || {}).latest || []).map((item) => [item.sensor_id, item]));
  return (state.sensors || []).map((sensor) => {
    const last = latest.get(sensor.id);
    if (!last) return sensor;
    return {
      ...sensor,
      last_value: last.value,
      last_at: last.at,
      battery: last.battery,
      battery_at: last.battery_at,
      reported_at: last.reported_at,
    };
  });
}

function realtimeFrame() {
  // Every graph of the view shares one window, so the period bar can be read off
  // whichever series came back - a solar-only house never asks for the water's.
  const data = state.sensorData || { series: [], days: state.sensorDays, bucket_minutes: 10 };
  const frame = ((state.sensors || []).length ? data : null) || state.waterData || state.powerData || data;
  const days = frame.days || state.sensorDays;
  const tMax = frame.until ? Date.parse(frame.until) : Date.now();
  return { data, days, tMax, tMin: tMax - days * 86400000 };
}

function thermometerCardMarkup() {
  const sensors = displaySensors(realtimeSensors());
  if (!sensors.length) return "";
  const { data, tMax } = realtimeFrame();
  const colors = sensorColors(sensors);
  const activeIds = sensors.filter((sensor) => sensor.active).map((sensor) => sensor.id);
  // Tiles are "selected" while some sensors are hidden: the visible ones.
  const selecting = activeIds.some((id) => state.hiddenSensors.has(id));
  const tiles = sensors
    .filter((sensor) => sensor.active && sensor.last_value !== null)
    .map((sensor) => {
      const heard = heardFrom(sensor);
      const stale = Date.now() - Date.parse(heard) > SENSOR_STALE_MS;
      const visible = !state.hiddenSensors.has(sensor.id);
      const classes = ["sensor-tile", stale ? "stale" : "", selecting && visible ? "selected" : "", selecting && !visible ? "dimmed" : ""];
      // The reading's own age is worth having, just not on the face of the tile:
      // it answers "how long has it been this warm", which is a different
      // question from the one the tile is asked at a glance.
      // A clock rather than an "ago": a title attribute is not retouched by the
      // minute, and a fixed instant cannot go quietly out of date the way a
      // count of minutes would.
      const held = sensor.reported_at && sensor.last_at && sensor.last_at !== sensor.reported_at
        ? `\nReading unchanged since ${fmtInstant(Date.parse(sensor.last_at), 1)}`
        : "";
      return `
        <div class="${classes.filter(Boolean).join(" ")}" data-sensor-tile="${sensor.id}" data-at="${esc(heard)}" role="button" tabindex="0"
          style="border-left-color:${colors.get(sensor.id)}"
          title="${esc(sensor.entity_id)} - click: only this sensor · Ctrl+click or long press: add or remove it${esc(held)}">
          <div class="tile-name">${esc(sensor.name)}</div>
          <div class="tile-value">${fmtTemp(sensor.last_value)}${sensor.unit ? ` <span class="meta">${esc(sensor.unit)}</span>` : ""}</div>
          <div class="tile-when"><span class="tile-ago">${agoMarkup(heard)}</span>${batteryMarkup(sensor)}</div>
        </div>`;
    }).join("");
  const allSeries = sensorSeries(colors);
  const visible = allSeries.filter((item) => !state.hiddenSensors.has(item.sensor_id));
  const thresholds = sensorThresholds(allSeries).filter((threshold) => !state.hiddenSensors.has(threshold.sensor_id));
  return `
    <div class="card graph-card">
      ${sensorChartMarkup(visible, data.days, data.bucket_minutes, tMax, thresholds) || '<p class="meta">No reading in this period.</p>'}
      <div class="sensor-tiles">${tiles || '<p class="meta">No reading received yet.</p>'}</div>
    </div>`;
}

function sensorSeries(colors) {
  const { data, tMax } = realtimeFrame();
  return splitPrevious(displaySeries(data.series || []), data.days, data.until ? Date.parse(data.until) : tMax)
    .map((item) => ({ ...item, color: colors.get(item.sensor_id) || SENSOR_DEFAULT_COLORS[0] }));
}

function wireSensorTiles(root) {
  const activeIds = realtimeSensors().filter((sensor) => sensor.active).map((sensor) => sensor.id);
  $$(`${root} [data-sensor-tile]`).forEach((tile) => {
    const sensorId = Number(tile.dataset.sensorTile);
    // The same rule the solar tiles follow, and written once for both. Hiding a
    // sensor is a question for this card alone, so this card alone is redrawn.
    const solo = () => { state.hiddenSensors = pickOne(activeIds, state.hiddenSensors, sensorId); renderRealtimeCard("sensors"); };
    const toggle = () => { state.hiddenSensors = toggleOne(activeIds, state.hiddenSensors, sensorId); renderRealtimeCard("sensors"); };
    wireTileGestures(tile, solo, toggle);
  });
}

function renderSensors() {
  // The whole view, rebuilt: entering it, changing house, range, period or
  // overlay, or turning a graph on and off. Everything that happens afterwards
  // goes through renderRealtimeCard and leaves the rest of the page alone.
  $("#sensor-content").classList.remove("loading");
  // Nothing collected at all is a different thing from everything turned off,
  // and only one of them is the house's fault.
  const collecting = (state.sensors || []).length || state.waterData || state.powerData;
  if (!collecting) {
    $("#sensor-content").innerHTML = `
      <div class="card">
        <p class="meta">No sensor yet. Once Home Assistant pushes readings with this house's sensor token
          (Settings, Houses), the thermometers appear here on their own.</p>
      </div>`;
    return;
  }
  // One slot per card, standing whether or not it has anything in it yet: a
  // feed answering on its own later needs somewhere of its own to land.
  const slots = REALTIME_CARDS.filter((card) => card.has() && showsCard(card.key));
  // The bar stays even with every card off, or there would be no way back.
  $("#sensor-content").innerHTML = periodBarMarkup() + (slots.length
    ? slots.map((card) => `<div data-card-slot="${card.key}"></div>`).join("")
    : `
    <div class="card">
      <p class="meta">Every graph is hidden. The icons above the date bring them back.</p>
    </div>`);
  wirePeriodBar();
  slots.forEach((card) => renderRealtimeCard(card.key));
}

function renderRealtimeCard(key) {
  // One card redrawn where it stands. The view around it is untouched, so the
  // period bar keeps the focus a click just gave it and the other two graphs
  // keep the pointer they were following.
  const selector = `[data-card-slot="${key}"]`;
  const slot = $(selector);
  const card = REALTIME_CARDS.find((item) => item.key === key);
  if (!slot || !card) return;
  slot.innerHTML = card.markup();
  card.wire(selector);
  // The window ends now, so its label moves with every answer that lands.
  refreshPeriodBar();
  refreshAges();
}

function refreshPeriodBar() {
  const label = $("#sensor-content .period-label");
  if (!label) return;
  label.textContent = periodRangeLabel();
  label.title = periodHint();
}

function refreshAges() {
  // Words, not markup: no card is rebuilt and no graph is touched, so this can
  // run on the clock without anything on screen moving but the text itself.
  // "5 min ago" stops being true a minute later whether or not a byte changed,
  // and a tile that has gone quiet has to be able to say so.
  $$("#sensor-content .ago").forEach((span) => { span.textContent = fmtAgo(span.dataset.ago); });
  $$("#sensor-content [data-sensor-tile]").forEach((tile) => {
    tile.classList.toggle("stale", Date.now() - Date.parse(tile.dataset.at) > SENSOR_STALE_MS);
  });
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

function sensorThresholds(seriesList) {
  // The alert range is the sensor's, in the thermometer's own unit: it takes the
  // viewer's unit and the curve's colour, so a line is read against its sensor.
  if (!wantsThresholds()) return [];
  const sensors = new Map((state.sensors || []).map((sensor) => [sensor.id, sensor]));
  return seriesList.flatMap((item) => {
    const sensor = sensors.get(item.sensor_id);
    if (!sensor) return [];
    return [["below", sensor.threshold_min], ["above", sensor.threshold_max]]
      .filter(([, bound]) => bound !== null && bound !== undefined)
      .map(([side, bound]) => {
        const shown = displayTemp(bound, sensor.unit);
        return {
          sensor_id: sensor.id,
          color: item.color,
          value: shown.value,
          label: `${sensor.name}: alert ${side} ${fmtTemp(shown.value)}${shown.unit ? ` ${shown.unit}` : ""}`,
        };
      });
  });
}

function sensorChartMarkup(seriesList, days, bucketMinutes, tMax, thresholds = []) {
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
  let low = Math.min(...points.map((point) => point.low), ...thresholds.map((threshold) => threshold.value));
  let high = Math.max(...points.map((point) => point.high), ...thresholds.map((threshold) => threshold.value));
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

  // The alert bounds, inside the scale since it was told to make room for them.
  const thresholdLines = thresholds.map((threshold) => {
    const y = yAt(threshold.value).toFixed(1);
    return `<line class="threshold" x1="${left}" y1="${y}" x2="${width - right}" y2="${y}" stroke="${threshold.color}"><title>${esc(threshold.label)}</title></line>`;
  }).join("");

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
        ${thresholdLines}
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
    const [data, alerts] = await Promise.all([
      api(`/api/sensors?house_id=${state.houseId}`),
      api(`/api/sensors/alerts?house_id=${state.houseId}`),
    ]);
    state.sensors = data.sensors || [];
    $("#sensor-alert-toggle").checked = Boolean(alerts.enabled);
    renderSensorSettings();
  } catch (error) { showAppError(error); }
}

// ---------- Water (EyeOnWater consumption) ----------

const WATER_COLOR = "var(--viz-2)";
const WATER_BUCKETS = { 15: "quarter-hour", 60: "hourly", 360: "6-hour", 1440: "daily" };
const WATER_PERIODS = { 1: "day", 7: "week", 30: "30 days", 365: "year" };

// The three halves of the view, and the icon that turns each one off. Pressed
// is showing: the eye is open, the card is there.
const REALTIME_CARDS = [
  {
    key: "sensors", label: "Thermometers", icon: ICON_THERMOMETER, has: () => houseHasSensors(),
    markup: () => thermometerCardMarkup(),
    wire: (root) => { wireSensorChartHover(root); wireSensorTiles(root); },
  },
  {
    key: "water", label: "Water", icon: ICON_DROP, has: () => houseHasWater(),
    markup: () => waterCardMarkup(state.waterData),
    // Its bars carry their own titles, so there is nothing here to wire.
    wire: () => {},
  },
  {
    key: "power", label: "Solar", icon: ICON_SUN, has: () => houseHasPower(),
    // The batteries are the solar feed's second graph and follow the same
    // switch: one feed, one slot, two cards.
    markup: () => powerCardMarkup(state.powerData) + batteryCardMarkup(state.powerData),
    wire: (root) => { wireSensorChartHover(root); wirePowerTiles(root); },
  },
];

function agoMarkup(iso) {
  // The one place a "5 min ago" is written, so the timer that keeps them honest
  // has a single thing to look for.
  if (!iso) return "";
  return `<span class="ago" data-ago="${esc(iso)}">${esc(fmtAgo(iso))}</span>`;
}

function hiddenCards() {
  // A viewer's choice, kept per browser like the unit switch: which of the
  // graphs are worth the screen today is not a fact about the house.
  return new Set((storedItem("usage-realtime-cards", "") || "").split(",").filter(Boolean));
}

function showsCard(key) {
  return !hiddenCards().has(key);
}

function toggleCard(key) {
  const hidden = hiddenCards();
  if (hidden.has(key)) hidden.delete(key);
  else hidden.add(key);
  storeItem("usage-realtime-cards", [...hidden].join(","));
  renderSensors();
  // A hidden graph is not asked for, so one switched off drops its pending
  // request and one switched back on is asked afresh rather than reappearing
  // at whatever it happened to say when it was put away.
  const feed = REALTIME_FEEDS.find((item) => item.key === key);
  if (!feed) return;
  if (showsCard(key) && feed.has()) refreshFeed(feed);
  else scheduleFeed(feed, 0);
}

function cardTogglesMarkup() {
  // Only for the halves this house actually has: a switch for a graph that
  // could never appear is just a puzzle.
  return REALTIME_CARDS.filter((card) => card.has()).map((card) => {
    const shown = showsCard(card.key);
    return `<button class="ghost compact icon-button${shown ? " active" : ""}" data-card-toggle="${card.key}"
      type="button" aria-pressed="${shown}" title="${esc(shown ? `Hide the ${card.label.toLowerCase()}` : `Show the ${card.label.toLowerCase()}`)}"
      aria-label="${esc(card.label)}">${card.icon}</button>`;
  }).join("");
}

function periodRangeLabel() {
  const { days, tMin, tMax } = realtimeFrame();
  return `${fmtPeriodEdge(tMin, days)} – ${fmtPeriodEdge(tMax, days)}`;
}

function periodHint() {
  const { data } = realtimeFrame();
  if (!(state.sensors || []).length || !showsCard("sensors")) {
    return "Click a tile for that series alone; the icons choose which graphs are on show.";
  }
  const previousLabel = { 1: "day", 7: "week", 30: "30 days", 365: "year" }[data.days] || "period";
  const bucketLabel = data.bucket_minutes >= 1440 ? "daily" : data.bucket_minutes >= 60 ? `${data.bucket_minutes / 60}-hour` : `${data.bucket_minutes}-minute`;
  const banded = data.bucket_minutes > 10 ? " with the low-high band" : "";
  const dotted = data.previous ? `; dotted: the previous ${previousLabel}` : "";
  // Whether any curve on show carries an alert range, which is all the hint
  // needs to know - the lines themselves are the chart's business.
  const drawn = new Set((data.series || []).map((item) => item.sensor_id));
  const bounded = (sensor) => sensor.threshold_min !== null || sensor.threshold_max !== null;
  const dashed = wantsThresholds() && (state.sensors || []).some((sensor) => drawn.has(sensor.id) && bounded(sensor))
    ? "; dashed: the alert range"
    : "";
  return `${bucketLabel} averages${banded}${dotted}${dashed}. Click a tile for that sensor alone.`;
}

function periodBarMarkup() {
  // Shared by every graph of the view: they all move together, and the icons
  // on the left say which of them are on show at all.
  return `
    <div class="period-bar">
      <span class="period-label" title="${esc(periodHint())}">${esc(periodRangeLabel())}</span>
      <span class="range-tabs card-toggles">${cardTogglesMarkup()}</span>
      <span class="range-tabs">
        <button id="sensor-earlier" class="ghost compact icon-button" type="button" title="Earlier period" aria-label="Earlier period">${ICON_CHEVRON_LEFT}</button>
        ${state.sensorOffset
          ? `<button id="sensor-later" class="ghost compact icon-button" type="button" title="Later period" aria-label="Later period">${ICON_CHEVRON_RIGHT}</button>`
          : `<button id="sensor-refresh" class="ghost compact icon-button" type="button" title="Refresh the readings" aria-label="Refresh the readings">${ICON_REFRESH}</button>`}
      </span>
    </div>`;
}

function wirePeriodBar() {
  $$("[data-card-toggle]").forEach((button) =>
    button.addEventListener("click", () => toggleCard(button.dataset.cardToggle)));
  $("#sensor-earlier").addEventListener("click", () => { state.sensorOffset += 1; loadSensors(true); });
  // On the current period there is nothing later to show: the arrow makes way
  // for a refresh, which reloads the readings and the tiles without touching
  // the range, the overlay, the unit or the sensors on show. Only the window's
  // own end moves, since it always finishes now.
  const later = $("#sensor-later");
  if (later) {
    later.addEventListener("click", () => {
      if (!state.sensorOffset) return;
      state.sensorOffset -= 1;
      loadSensors(true);
    });
  }
  const refresh = $("#sensor-refresh");
  if (refresh) {
    refresh.addEventListener("click", () => {
      showSensorsLoading();
      loadSensors();
    });
  }
}

const GALLONS_PER_M3 = 264.172052;

function volumeUnit(highest, axis = false) {
  // US reads everything in gallons. FR takes litres while the numbers are small
  // and cubic metres once they are not - an axis decides from its top so every
  // one of its labels lands in the same unit, since a ladder ending
  // "750 L, 1.00 m³" is arithmetic the reader should not have to do.
  if (!wantsMetric()) return "gal";
  return Math.abs(highest) < (axis ? 2 : 1) ? "L" : "m3";
}

function fmtVolume(value, unit = null) {
  // Everything is stored in cubic metres; this is only how it is shown.
  if (value === null || value === undefined) return "—";
  const shown = unit || volumeUnit(value);
  if (shown === "gal") {
    const gallons = value * GALLONS_PER_M3;
    // A tenth of a gallon is worth showing for one bucket, never for a round
    // rung of an axis: "0.0 gal" beside "20 gal" only looks like a mistake.
    const rounded = Math.abs(gallons - Math.round(gallons)) < 0.05;
    return `${gallons < 10 && !rounded ? gallons.toFixed(1) : Math.round(gallons).toLocaleString("en-US")} gal`;
  }
  if (shown === "L") return `${Math.round(value * 1000)} L`;
  return `${value.toFixed(value < 10 ? 2 : 1)} m³`;
}

function waterStamp(time) {
  // One shape whatever the range: MM/DD hh:mm, in the viewer's own time zone. A
  // stamp that drops the date on the day view, or the clock on the year view,
  // leaves the two lines of an overlay tooltip with nothing to tell them apart.
  const moment = new Date(time);
  const two = (value) => String(value).padStart(2, "0");
  return `${two(moment.getMonth() + 1)}/${two(moment.getDate())} ${two(moment.getHours())}:${two(moment.getMinutes())}`;
}

function waterChartMarkup(current, earlier, days, bucketMinutes, tMax) {
  // Bars, not a curve: each one is the water drawn in its bucket, so the scale
  // starts at zero and an empty bucket is an honest gap rather than a dip.
  const tMin = tMax - days * 86400000;
  if (!current.length && !earlier.length) return "";
  const width = 720;
  const height = 200;
  const left = 52;
  const right = 16;
  const top = 12;
  const bottom = 28;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const high = Math.max(...[...current, ...earlier].map((point) => point.volume), 0);
  // The ladder is built in the unit it will be read in, not in the cubic metres
  // everything is stored as: a step that is round in m3 lands on 26 and 53 gal.
  const unit = volumeUnit(high, true);
  const perCubicMetre = unit === "gal" ? GALLONS_PER_M3 : unit === "L" ? 1000 : 1;
  const stepShown = sensorStep(Math.max(high * perCubicMetre, 1) / 4);
  const topShown = Math.max(stepShown, Math.ceil((high * perCubicMetre) / stepShown) * stepShown);
  const yMax = topShown / perCubicMetre;
  const xAt = (time) => left + ((time - tMin) / (tMax - tMin)) * plotWidth;
  const yAt = (value) => top + plotHeight - (value / yMax) * plotHeight;

  const gridLines = [];
  const yLabels = [];
  for (let shown = 0; shown <= topShown + stepShown / 2; shown += stepShown) {
    const y = yAt(shown / perCubicMetre);
    gridLines.push(`<line x1="${left}" y1="${y.toFixed(1)}" x2="${width - right}" y2="${y.toFixed(1)}"></line>`);
    yLabels.push(`<text x="${left - 6}" y="${(y + 4).toFixed(1)}" text-anchor="end">${esc(fmtVolume(shown / perCubicMetre, unit))}</text>`);
  }
  const xLabels = sensorTicks(tMin, tMax, days).map((tick) =>
    `<text x="${xAt(tick.time).toFixed(1)}" y="${height - 8}" text-anchor="middle">${esc(tick.label)}</text>`);

  const bucketMs = bucketMinutes * 60000;
  const barWidth = Math.max(1, (plotWidth * bucketMs) / (tMax - tMin) - 1);
  // A bucket is drawn twice when the overlay is on, and the point of the overlay
  // is the comparison: both bars carry both readings, each under its own date,
  // so whichever one the pointer lands on answers the same question.
  const currentAt = new Map(current.map((point) => [point.time, point]));
  const earlierAt = new Map(earlier.map((point) => [point.time, point]));
  const titleAt = (time) => {
    const now = currentAt.get(time);
    const before = earlierAt.get(time);
    const lines = [`${waterStamp(time)} · ${fmtVolume(now ? now.volume : 0)}`];
    if (earlier.length) {
      lines.push(`${waterStamp(before ? before.actual : time - days * 86400000)} · ${fmtVolume(before ? before.volume : 0)}`);
    }
    return lines.join("\n");
  };
  const barsOf = (timed, className) => timed.map((point) => {
    const y = yAt(point.volume);
    const barHeight = Math.max(point.volume > 0 ? 1 : 0, top + plotHeight - y);
    if (!barHeight) return "";
    return `<rect class="${className}" x="${xAt(point.time).toFixed(1)}" y="${(top + plotHeight - barHeight).toFixed(1)}" width="${barWidth.toFixed(1)}" height="${barHeight.toFixed(1)}" fill="${WATER_COLOR}"><title>${esc(titleAt(point.time))}</title></rect>`;
  }).join("");
  return `
    <div class="viz-holder">
      <svg class="viz-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Water consumption">
        <g class="grid">${gridLines.join("")}</g>
        <g class="axis">${yLabels.join("")}${xLabels.join("")}</g>
        <g class="bars">${barsOf(earlier, "previous")}${barsOf(current, "")}</g>
      </svg>
    </div>`;
}

function waterLimitMarkup(alert) {
  // A limit nobody set says nothing at all. One that is set is worth seeing
  // beside the total, and one currently broken is worth seeing loudly - the
  // email announces the crossing, but the page is where it is looked into.
  if (!alert || !alert.daily_max) return "";
  if (alert.over) {
    return ` <span class="meta warn">· over the ${esc(fmtVolume(alert.daily_max))} daily limit</span>`;
  }
  return ` <span class="meta">· alert above ${esc(fmtVolume(alert.daily_max))} a day</span>`;
}

function waterCardMarkup(data) {
  if (!data) return "";
  const points = data.points || [];
  const latest = data.latest || {};
  if (!points.length && !latest.at) return "";
  const tMax = data.until ? Date.parse(data.until) : Date.now();
  // The server sends both periods in one flat list when the overlay is on; the
  // earlier one is shifted forward by the range so it lines up under the shown
  // one, exactly as the thermometers' curves are.
  const span = data.days * 86400000;
  const current = [];
  const earlier = [];
  for (const point of points) {
    const time = Date.parse(point.at);
    if (time >= tMax - span) current.push({ time, volume: point.volume });
    else if (data.previous) earlier.push({ time: time + span, actual: time, volume: point.volume });
  }
  const total = current.reduce((sum, point) => sum + point.volume, 0);
  const bucket = WATER_BUCKETS[data.bucket_minutes] || `${data.bucket_minutes}-minute`;
  const reading = latest.reading === null || latest.reading === undefined ? "" : ` · meter at ${fmtVolume(latest.reading)}`;
  // EyeOnWater publishes in batches, so the freshest bar is usually hours old:
  // saying when the last reading landed stops that looking like a dry house.
  const freshness = latest.at ? `Last reading ${agoMarkup(latest.at)}${esc(reading)}.` : "Nothing collected yet.";
  const overlay = earlier.length ? ` Pale bars: the previous ${WATER_PERIODS[data.days] || "period"}.` : "";
  return `
    <div class="card graph-card">
      <h3>Water <span class="meta">· ${esc(fmtVolume(total))} over the period</span>${waterLimitMarkup(data.alert)}</h3>
      ${waterChartMarkup(current, earlier, data.days, data.bucket_minutes, tMax) || '<p class="meta">No reading in this period.</p>'}
      <p class="meta">${esc(bucket)} totals from the water meter. ${freshness}${esc(overlay)}</p>
    </div>`;
}

function limitUnit() {
  // The limit is typed in whatever the viewer reads volumes in, and stored in
  // cubic metres like every other volume here. Litres and gallons rather than
  // the axis's sliding choice: a threshold wants one fixed unit to mean.
  return wantsMetric() ? "L" : "gal";
}

function limitFromCubic(cubic) {
  if (cubic === null || cubic === undefined) return "";
  return Math.round(cubic * (wantsMetric() ? 1000 : GALLONS_PER_M3));
}

function limitToCubic(typed) {
  const value = Number(typed);
  if (typed === "" || typed === null || typed === undefined || !Number.isFinite(value)) return null;
  return value / (wantsMetric() ? 1000 : GALLONS_PER_M3);
}

async function loadWaterSettings() {
  try {
    await ensureDashboard();
    const houses = state.dashboard.houses || [];
    const current = houses.find((house) => house.id === state.houseId);
    $("#water-house-name").textContent = current ? current.name : "";
    $("#water-feed-form").hidden = !state.houseId;
    $("#water-alert-toggle").disabled = !state.houseId;
    if (!state.me || !state.me.is_admin || !state.houseId) return;
    const [data, alerts] = await Promise.all([
      api(`/api/water/feeds?house_id=${state.houseId}`),
      api(`/api/water/alerts?house_id=${state.houseId}`),
    ]);
    state.waterFeeds = data.feeds || [];
    $("#water-alert-toggle").checked = Boolean(alerts.enabled);
    renderWaterFeeds();
  } catch (error) { showAppError(error); }
}

function waterFeedStatus(feed) {
  const bits = [feed.points ? `${feed.points.toLocaleString()} readings` : "nothing collected yet"];
  if (feed.first_point_at) bits.push(`from ${new Date(feed.first_point_at).toLocaleDateString()}`);
  // Until the walk ends, how far back it has reached says more than a percentage
  // nobody can compute: how deep the utility keeps its history is unknown.
  bits.push(feed.backfill_done ? "history complete" : `still walking back${feed.backfill_from ? ` (at ${feed.backfill_from})` : ""}`);
  if (feed.last_point_at) bits.push(`last reading ${fmtAgo(feed.last_point_at)}`);
  // Before the first check there is nothing to show but the wait itself, and a
  // feed with nothing in it and nothing said about it reads as a broken one.
  bits.push(feed.last_sync_at ? `checked ${fmtAgo(feed.last_sync_at)}` : "first check due within a minute");
  // A limit nobody set is the ordinary case, and saying so every time would be noise.
  if (feed.daily_max) bits.push(`alert above ${fmtVolume(feed.daily_max)} a day`);
  return bits.join(" · ");
}

function renderWaterFeeds() {
  const feeds = state.waterFeeds || [];
  $("#water-feed-list").innerHTML = feeds.map((feed) => `
    <div class="mini-row wrap-row${feed.active ? "" : " inactive"}">
      <span>
        <strong>${esc(feed.username)}</strong> · ${esc(feed.hostname)}${feed.active ? "" : ' <span class="badge">paused</span>'}
        <br>
        <span class="meta">meter ${esc(feed.meter_uuid)} · ${esc(waterFeedStatus(feed))}</span>
        ${feed.last_error ? `<br><span class="meta warn">${esc(feed.last_error)}</span>` : ""}
      </span>
      <span class="icon-actions">
        <button class="ghost compact" data-edit-water="${feed.id}" type="button">Edit</button>
        <button class="ghost compact" data-backfill-water="${feed.id}" type="button"
          title="Walk the whole history again, a month at a time">Import history</button>
        <button class="ghost compact" data-delete-water="${feed.id}" type="button">Delete</button>
      </span>
    </div>`).join("") || '<p class="meta">No water feed yet.</p>';
  $$("[data-edit-water]").forEach((button) => button.addEventListener("click", async () => {
    const feed = feeds.find((item) => item.id === Number(button.dataset.editWater));
    const answers = await openModal({
      title: `Edit water feed · ${feed.username}`,
      message: "Leave the password empty to keep the one already stored.",
      fields: [
        { name: "hostname", label: "Host", type: "select", options: ["eyeonwater.com", "eyeonwater.ca"], value: feed.hostname },
        { name: "username", label: "Username", value: feed.username },
        { name: "password", label: "New password", type: "password", value: "" },
        { name: "meter_uuid", label: "Meter uuid", value: feed.meter_uuid },
        { name: "daily_max", label: `Alert above (${limitUnit()} in any 24 hours)`, type: "number", value: limitFromCubic(feed.daily_max) },
        { name: "active", label: "Collecting", type: "checkbox", value: feed.active },
      ],
    });
    if (answers === null) return;
    try {
      await api(`/api/water/feeds/${feed.id}`, { method: "PUT", body: JSON.stringify({
        ...answers,
        daily_max: limitToCubic(answers.daily_max),
      }) });
      await loadWaterSettings();
    } catch (error) { showAppError(error); }
  }));
  $$("[data-backfill-water]").forEach((button) => button.addEventListener("click", async () => {
    const feed = feeds.find((item) => item.id === Number(button.dataset.backfillWater));
    if (!await confirmModal("Import the history again", `Walk ${feed.username}'s history back from today. Readings already stored are kept and refreshed.`, "Import")) return;
    try {
      await api(`/api/water/feeds/${feed.id}/backfill`, { method: "POST" });
      await loadWaterSettings();
    } catch (error) { showAppError(error); }
  }));
  $$("[data-delete-water]").forEach((button) => button.addEventListener("click", async () => {
    const feed = feeds.find((item) => item.id === Number(button.dataset.deleteWater));
    if (!await confirmModal("Delete this water feed", `Everything collected for ${feed.username} goes with it. The history would have to be imported again.`)) return;
    try {
      await api(`/api/water/feeds/${feed.id}`, { method: "DELETE" });
      invalidateDashboard();
      await loadWaterSettings();
    } catch (error) { showAppError(error); }
  }));
}

async function addWaterFeed(event) {
  event.preventDefault();
  try {
    // The server signs in and asks for a day before storing anything, so a wrong
    // password or uuid is refused here rather than hours later in the log.
    await api("/api/water/feeds", { method: "POST", body: JSON.stringify({
      house_id: state.houseId,
      hostname: $("#water-hostname").value,
      username: $("#water-username").value.trim(),
      password: $("#water-password").value,
      meter_uuid: $("#water-meter-uuid").value.trim(),
    }) });
    $("#water-username").value = "";
    $("#water-password").value = "";
    $("#water-meter-uuid").value = "";
    invalidateDashboard();
    await loadWaterSettings();
  } catch (error) { showAppError(error); }
}

// ---------- Solar (Enphase production, consumption and batteries) ----------

const PRODUCTION_COLOR = "var(--viz-3)";
const CONSUMPTION_COLOR = "var(--viz-4)";
const POWER_COLORS = { production: "var(--viz-3)", consumption: "var(--viz-4)" };
const BATTERY_COLOR = "var(--viz-5)";
const WATT_HOURS_PER_KWH = 1000;
const POWER_PERIODS = { 1: "day", 7: "week", 30: "30 days", 365: "year" };
// A push every minute off the gateway goes stale in minutes, not hours: past
// this the tiles stop claiming to be live and fall back to the last interval.
const LIVE_STALE_MS = 15 * 60 * 1000;
const WATTS_PER_KW = 1000;
// The two halves of the solar graph, which the tiles turn on and off.
const POWER_SERIES = ["production", "consumption"];

function fmtPower(watts) {
  // What the panels are doing this second, which is the whole point of a local
  // feed: watts while they are small, kilowatts once they are not.
  if (watts === null || watts === undefined) return "—";
  if (Math.abs(watts) < WATTS_PER_KW) return `${Math.round(watts)} W`;
  return `${(watts / WATTS_PER_KW).toFixed(2)} kW`;
}

function liveReading(data) {
  // Present, and recent enough to still be true.
  const live = data && data.live;
  if (!live || !live.at) return null;
  return Date.now() - Date.parse(live.at) < LIVE_STALE_MS ? live : null;
}

function energyUnit(highest, axis = false) {
  // Watt-hours while the numbers are small, kilowatt-hours once they are not.
  // An axis decides from its top so every rung lands in the same unit: a ladder
  // reading "750 Wh, 1.0 kWh" is arithmetic the reader should not have to do.
  return Math.abs(highest) < (axis ? 2 : 1) ? "Wh" : "kWh";
}

function fmtEnergy(value, unit = null) {
  // Everything is stored in kilowatt-hours; this is only how it is shown.
  if (value === null || value === undefined) return "—";
  const shown = unit || energyUnit(value);
  if (shown === "Wh") return `${Math.round(value * WATT_HOURS_PER_KWH).toLocaleString("en-US")} Wh`;
  return `${value.toFixed(value < 10 ? 2 : 1)} kWh`;
}

function fmtPercent(value) {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value)}%`;
}

function splitPower(data) {
  // The server sends both periods in one flat list when the overlay is on; the
  // earlier one is shifted forward by the range so it lines up under the shown
  // one, exactly as the thermometers' curves and the water's bars are.
  const tMax = data.until ? Date.parse(data.until) : Date.now();
  const span = data.days * 86400000;
  const current = [];
  const earlier = [];
  for (const point of data.points || []) {
    const time = Date.parse(point.at);
    const values = {
      production: point.production || 0,
      consumption: point.consumption || 0,
      battery: point.battery_level,
    };
    if (time >= tMax - span) current.push({ time, ...values });
    else if (data.previous) earlier.push({ time: time + span, actual: time, ...values });
  }
  return { tMax, current, earlier };
}

function powerChartMarkup(current, earlier, days, bucketMinutes, tMax, hidden = new Set()) {
  const shown = POWER_SERIES.filter((field) => !hidden.has(field));
  if (!shown.length) return "";
  // Two counters drawn as paired bars: what the panels made and what the house
  // drew, in the same bucket and on the same scale, because the whole question a
  // solar owner asks is which of the two was bigger at that moment.
  const tMin = tMax - days * 86400000;
  if (!current.length && !earlier.length) return "";
  const width = 720;
  const height = 200;
  const left = 52;
  const right = 16;
  const top = 12;
  const bottom = 28;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const all = [...current, ...earlier];
  const high = Math.max(...all.map((point) => Math.max(...shown.map((field) => point[field]))), 0);
  const unit = energyUnit(high, true);
  const perKwh = unit === "Wh" ? WATT_HOURS_PER_KWH : 1;
  const stepShown = sensorStep(Math.max(high * perKwh, 1) / 4);
  const topShown = Math.max(stepShown, Math.ceil((high * perKwh) / stepShown) * stepShown);
  const yMax = topShown / perKwh;
  const xAt = (time) => left + ((time - tMin) / (tMax - tMin)) * plotWidth;
  const yAt = (value) => top + plotHeight - (value / yMax) * plotHeight;

  const gridLines = [];
  const yLabels = [];
  for (let shown = 0; shown <= topShown + stepShown / 2; shown += stepShown) {
    const y = yAt(shown / perKwh);
    gridLines.push(`<line x1="${left}" y1="${y.toFixed(1)}" x2="${width - right}" y2="${y.toFixed(1)}"></line>`);
    yLabels.push(`<text x="${left - 6}" y="${(y + 4).toFixed(1)}" text-anchor="end">${esc(fmtEnergy(shown / perKwh, unit))}</text>`);
  }
  const xLabels = sensorTicks(tMin, tMax, days).map((tick) =>
    `<text x="${xAt(tick.time).toFixed(1)}" y="${height - 8}" text-anchor="middle">${esc(tick.label)}</text>`);

  const bucketMs = bucketMinutes * 60000;
  const full = Math.max(1, (plotWidth * bucketMs) / (tMax - tMin) - 1);
  // Made and drawn sit side by side inside their bucket; the overlay sits behind
  // them at full width, so four bar sets never fight over the same pixels.
  const half = Math.max(1, full / 2);
  const currentAt = new Map(current.map((point) => [point.time, point]));
  const earlierAt = new Map(earlier.map((point) => [point.time, point]));
  const titleAt = (time) => {
    const now = currentAt.get(time);
    const before = earlierAt.get(time);
    const said = (point) => shown
      .map((field) => `${field === "production" ? "made" : "drew"} ${fmtEnergy(point ? point[field] : 0)}`)
      .join(" · ");
    const lines = [`${waterStamp(time)} · ${said(now)}`];
    if (earlier.length) {
      lines.push(`${waterStamp(before ? before.actual : time - days * 86400000)} · ${said(before)}`);
    }
    return lines.join("\n");
  };
  // One series on its own gets the whole bucket; two share it side by side.
  const slot = shown.length > 1 ? half : full;
  const barsOf = (timed, field, color, className, barWidth, offset) => timed.map((point) => {
    const value = point[field];
    const y = yAt(value);
    const barHeight = Math.max(value > 0 ? 1 : 0, top + plotHeight - y);
    if (!barHeight) return "";
    return `<rect class="${className}" x="${(xAt(point.time) + offset).toFixed(1)}" y="${(top + plotHeight - barHeight).toFixed(1)}"
      width="${barWidth.toFixed(1)}" height="${barHeight.toFixed(1)}" fill="${color}"><title>${esc(titleAt(point.time))}</title></rect>`;
  }).join("");
  return `
    <div class="viz-holder">
      <svg class="viz-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Solar production and consumption">
        <g class="grid">${gridLines.join("")}</g>
        <g class="axis">${yLabels.join("")}${xLabels.join("")}</g>
        <g class="bars">
          ${shown.map((field) => barsOf(earlier, field, POWER_COLORS[field], "previous", full, 0)).join("")}
          ${shown.map((field, index) => barsOf(current, field, POWER_COLORS[field], "", slot, index * slot)).join("")}
        </g>
      </svg>
    </div>`;
}

function powerCardMarkup(data) {
  if (!data) return "";
  const { tMax, current, earlier } = splitPower(data);
  const latest = data.latest || {};
  if (!current.length && !earlier.length && !latest.at) return "";
  const made = current.reduce((sum, point) => sum + point.production, 0);
  const drew = current.reduce((sum, point) => sum + point.consumption, 0);
  const showing = POWER_SERIES.filter((field) => !state.hiddenPower.has(field));
  const totals = [
    showing.includes("production") ? `made ${fmtEnergy(made)}` : "",
    showing.includes("consumption") ? `drew ${fmtEnergy(drew)}` : "",
  ].filter(Boolean).join(" · ");
  // What the panels covered is the number an owner actually watches, and it is
  // only honest when both halves of it were reported over the same period.
  const covered = drew > 0 ? ` · ${Math.round(Math.min(100, (made / drew) * 100))}% of what the house drew` : "";
  const bucket = data.daily ? "daily" : WATER_BUCKETS[data.bucket_minutes] || `${data.bucket_minutes}-minute`;
  const live = liveReading(data);
  const freshness = live
    ? `Live from the gateway, ${agoMarkup(live.at)}.`
    : latest.at ? `Last reading ${agoMarkup(latest.at)}.` : "Nothing collected yet.";
  // Beyond the fortnight of quarter-hourly telemetry the graph is drawn from the
  // daily totals, which is the only resolution the whole history fits in.
  const source = data.daily ? " Daily totals, from the whole life of the system." : "";
  const overlay = earlier.length ? ` Pale bars: the previous ${POWER_PERIODS[data.days] || "period"}.` : "";
  return `
    <div class="card graph-card">
      <h3>Solar <span class="meta">· ${esc(totals)}${esc(showing.length > 1 ? covered : "")}</span></h3>
      ${powerChartMarkup(current, earlier, data.days, data.bucket_minutes, tMax, state.hiddenPower) || '<p class="meta">No reading in this period.</p>'}
      ${powerTilesMarkup(data, latest)}
      <p class="meta">${esc(bucket)} totals from the Enphase system. ${freshness}${esc(source)}${esc(overlay)}</p>
    </div>`;
}

function powerTilesMarkup(data, latest) {
  // Home Assistant reads the gateway every minute, so where there is a live
  // push the tiles show power - what the panels are doing this second. Without
  // one they show the last interval's energy, which is the best the cloud API
  // can honestly offer at four hours behind.
  //
  // They are the graph's legend and its switch as well, like the thermometers':
  // a click leaves one series on the chart, Ctrl+click or a long press adds and
  // removes it.
  const live = liveReading(data);
  const when = live ? live.at : latest.at;
  const ago = agoMarkup(when);
  const selecting = POWER_SERIES.some((field) => state.hiddenPower.has(field));
  const names = { production: "Production", consumption: "Consumption" };
  const doing = { production: "the panels are making", consumption: "the house is drawing" };
  const made = { production: "the panels made", consumption: "the house drew" };
  const tiles = POWER_SERIES.map((field) => {
    const visible = !state.hiddenPower.has(field);
    const value = live ? fmtPower(live[`${field}_power`]) : fmtEnergy(latest[field]);
    const hint = live
      ? `What ${doing[field]} right now, off the gateway`
      : `What ${made[field]} in the last interval reported`;
    const classes = ["sensor-tile", selecting && visible ? "selected" : "", selecting && !visible ? "dimmed" : ""];
    return `
        <div class="${classes.filter(Boolean).join(" ")}" data-power-tile="${field}" role="button" tabindex="0"
          style="border-left-color:${POWER_COLORS[field]}"
          title="${esc(hint)} - click: only this one · Ctrl+click or long press: add or remove it">
          <div class="tile-name">${esc(names[field])}</div>
          <div class="tile-value">${esc(value)}</div>
          <div class="tile-when"><span class="tile-ago">${ago}</span></div>
        </div>`;
  }).join("");
  return `<div class="sensor-tiles">${tiles}</div>`;
}

function wirePowerTiles(root) {
  $$(`${root} [data-power-tile]`).forEach((tile) => {
    const field = tile.dataset.powerTile;
    // Which half of the solar is on show is a question for the solar card
    // alone, so the thermometers and the water are left where they are.
    wireTileGestures(
      tile,
      () => { state.hiddenPower = pickOne(POWER_SERIES, state.hiddenPower, field); renderRealtimeCard("power"); },
      () => { state.hiddenPower = toggleOne(POWER_SERIES, state.hiddenPower, field); renderRealtimeCard("power"); },
    );
  });
}

function batteryChartMarkup(current, earlier, days, bucketMinutes, tMax) {
  // A level, not a counter: a line between nothing and full, on a scale that is
  // always the whole 0-100 so a flat week does not look like a cliff.
  //
  // It is built on the same holder the thermometers use, so the pointer gets
  // the same circle on the curve and the same label beside it - one hover to
  // maintain rather than two that drift apart.
  const tMin = tMax - days * 86400000;
  const charged = (timed) => timed.filter((point) => point.battery !== null && point.battery !== undefined);
  const shown = charged(current);
  const before = charged(earlier);
  if (!shown.length && !before.length) return "";
  const width = 720;
  const height = 150;
  const left = 44;
  const right = 16;
  const top = 12;
  const bottom = 28;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const yMin = 0;
  const yMax = 100;
  const xAt = (time) => left + ((time - tMin) / (tMax - tMin)) * plotWidth;
  const yAt = (value) => top + plotHeight - ((value - yMin) / (yMax - yMin)) * plotHeight;

  const gridLines = [];
  const yLabels = [];
  for (let percent = yMin; percent <= yMax; percent += 25) {
    const y = yAt(percent);
    gridLines.push(`<line x1="${left}" y1="${y.toFixed(1)}" x2="${width - right}" y2="${y.toFixed(1)}"></line>`);
    yLabels.push(`<text x="${left - 6}" y="${(y + 4).toFixed(1)}" text-anchor="end">${percent}%</text>`);
  }
  const xLabels = sensorTicks(tMin, tMax, days).map((tick) =>
    `<text x="${xAt(tick.time).toFixed(1)}" y="${height - 8}" text-anchor="middle">${esc(tick.label)}</text>`);
  const lineOf = (timed) => timed.map((point, index) =>
    `${index === 0 ? "M" : "L"}${xAt(point.time).toFixed(1)},${yAt(point.battery).toFixed(1)}`).join(" ");
  const previousPath = before.length > 1
    ? `<path class="previous" d="${lineOf(before)}" stroke="${BATTERY_COLOR}"></path>`
    : "";
  const path = shown.length > 1 ? `<path d="${lineOf(shown)}" stroke="${BATTERY_COLOR}"></path>` : "";

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
    series: [{
      name: "Batteries",
      unit: "%",
      color: BATTERY_COLOR,
      // low and high repeat the value: a level has no band to draw.
      points: shown.map((point) => [point.time, point.battery, point.battery, point.battery]),
      previous: before.map((point) => [point.time, point.battery, point.battery, point.battery]),
    }],
  };
  return `
    <div class="viz-holder" data-sensor-chart="${esc(JSON.stringify(config))}">
      <svg class="viz-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Battery charge">
        <g class="grid">${gridLines.join("")}</g>
        <g class="axis">${yLabels.join("")}${xLabels.join("")}</g>
        <g class="series">${previousPath}${path}</g>
        <g class="viz-hover" hidden>
          <g class="hov-dots"></g>
        </g>
      </svg>
      <div class="viz-tip" hidden></div>
    </div>`;
}

function batteryCardMarkup(data) {
  if (!data) return "";
  const { tMax, current, earlier } = splitPower(data);
  const chart = batteryChartMarkup(current, earlier, data.days, data.bucket_minutes, tMax);
  const live = liveReading(data);
  const latest = live && live.battery_level !== null && live.battery_level !== undefined
    ? live.battery_level
    : (data.latest || {}).battery_level;
  // A system with no batteries never answers the third call, and a month or a
  // year is drawn from daily totals that carry no charge at all: in both cases
  // the honest thing is no card rather than an empty one.
  if (!chart && (latest === null || latest === undefined)) return "";
  const level = latest === null || latest === undefined ? "" : ` <span class="meta">· ${esc(fmtPercent(latest))} now</span>`;
  const shallow = data.daily
    ? "The charge is only collected quarter-hourly, so it does not reach back over this range."
    : "Average charge per bucket.";
  return `
    <div class="card graph-card">
      <h3>Batteries${level}</h3>
      ${chart || `<p class="meta">${esc(shallow)}</p>`}
      ${chart ? `<p class="meta">${esc(shallow)}${earlier.length ? " Pale line: the previous period." : ""}</p>` : ""}
    </div>`;
}

async function loadEnphaseSettings() {
  try {
    await ensureDashboard();
    const houses = state.dashboard.houses || [];
    const current = houses.find((house) => house.id === state.houseId);
    $("#enphase-house-name").textContent = current ? current.name : "";
    $("#enphase-feed-form").hidden = !state.houseId;
    if (!state.me || !state.me.is_admin || !state.houseId || !houseHasPower()) return;
    const data = await api(`/api/enphase/feeds?house_id=${state.houseId}`);
    state.enphaseFeeds = data.feeds || [];
    state.enphaseLocal = { live: data.live || {}, local: data.local || {} };
    renderEnphaseFeeds();
  } catch (error) { showAppError(error); }
}

function enphaseFeedStatus(feed) {
  const bits = [feed.points ? `${feed.points.toLocaleString()} readings` : "nothing collected yet"];
  if (feed.first_point_at) bits.push(`from ${new Date(feed.first_point_at).toLocaleDateString()}`);
  bits.push(feed.backfill_done ? "daily history complete" : "daily history pending");
  // The fortnight of quarter-hourly history is the expensive half, so how far it
  // has reached is worth saying while it is still walking.
  bits.push(feed.fine_done ? "quarter-hours complete" : `quarter-hours still walking back${feed.fine_from ? ` (at ${feed.fine_from})` : ""}`);
  if (feed.last_point_at) bits.push(`last reading ${fmtAgo(feed.last_point_at)}`);
  bits.push(feed.last_sync_at ? `checked ${fmtAgo(feed.last_sync_at)}` : "first check due within a minute");
  // The allowance is the thing that decides how often this feed may ask at all.
  bits.push(`${feed.calls_used.toLocaleString()} of ${feed.calls_budget.toLocaleString()} calls used this month`);
  return bits.join(" · ");
}

function localFeedMarkup() {
  // The push feed has nothing to configure, but somebody setting Home Assistant
  // up needs to see whether anything is arriving - otherwise a silent typo in
  // the automation looks exactly like a working one.
  const state_ = state.enphaseLocal || { live: {}, local: {} };
  const live = state_.live || {};
  const local = state_.local || {};
  if (!local.points && !live.at) {
    return `<div class="mini-row wrap-row"><span>
      <strong>Home Assistant</strong> <span class="badge">not pushing</span><br>
      <span class="meta">Nothing has arrived on this house's sensor token yet.
        The Envoy block in <code>deploy/home-assistant.yaml</code> is what sends it.</span>
    </span></div>`;
  }
  const bits = [local.points ? `${local.points.toLocaleString()} intervals` : "no interval yet"];
  if (local.first_point_at) bits.push(`from ${new Date(local.first_point_at).toLocaleDateString()}`);
  bits.push(live.at ? `last push ${fmtAgo(live.at)}` : "no push yet");
  if (live.production_power !== null && live.production_power !== undefined) {
    bits.push(`making ${fmtPower(live.production_power)}`);
  }
  if (live.battery_level !== null && live.battery_level !== undefined) {
    bits.push(`batteries ${fmtPercent(live.battery_level)}`);
  }
  return `<div class="mini-row wrap-row"><span>
    <strong>Home Assistant</strong> <span class="badge">live</span><br>
    <span class="meta">${esc(bits.join(" · "))}</span>
  </span></div>`;
}

function renderEnphaseFeeds() {
  const feeds = state.enphaseFeeds || [];
  $("#enphase-feed-list").innerHTML = feeds.map((feed) => `
    <div class="mini-row wrap-row${feed.active ? "" : " inactive"}">
      <span>
        <strong>system ${esc(feed.system_id)}</strong>${feed.active ? "" : ' <span class="badge">paused</span>'}
        <br>
        <span class="meta">${esc(enphaseFeedStatus(feed))}</span>
        ${feed.last_error ? `<br><span class="meta warn">${esc(feed.last_error)}</span>` : ""}
      </span>
      <span class="icon-actions">
        <button class="ghost compact" data-edit-enphase="${feed.id}" type="button">Edit</button>
        <button class="ghost compact" data-backfill-enphase="${feed.id}" type="button"
          title="Walk both histories again">Import history</button>
        <button class="ghost compact" data-delete-enphase="${feed.id}" type="button">Delete</button>
      </span>
    </div>`).join("") + localFeedMarkup();
  $$("[data-edit-enphase]").forEach((button) => button.addEventListener("click", async () => {
    const feed = feeds.find((item) => item.id === Number(button.dataset.editEnphase));
    const answers = await openModal({
      title: `Edit solar feed · system ${feed.system_id}`,
      message: "Leave the secret, the key and the code empty to keep what is already stored. "
        + "A fresh code is only needed when the authorisation has lapsed - a refresh token lasts about a month.",
      fields: [
        { name: "client_id", label: "Client id", value: feed.client_id },
        { name: "client_secret", label: "New client secret", type: "password", value: "" },
        { name: "api_key", label: "New API key", type: "password", value: "" },
        { name: "code", label: "New authorisation code", value: "" },
        { name: "system_id", label: "System id", value: feed.system_id },
        { name: "calls_budget", label: "Calls per month", type: "number", value: feed.calls_budget },
        { name: "active", label: "Collecting", type: "checkbox", value: feed.active },
      ],
    });
    if (answers === null) return;
    try {
      await api(`/api/enphase/feeds/${feed.id}`, { method: "PUT", body: JSON.stringify({
        ...answers,
        calls_budget: Number(answers.calls_budget) || 0,
      }) });
      await loadEnphaseSettings();
    } catch (error) { showAppError(error); }
  }));
  $$("[data-backfill-enphase]").forEach((button) => button.addEventListener("click", async () => {
    const feed = feeds.find((item) => item.id === Number(button.dataset.backfillEnphase));
    if (!await confirmModal("Import the history again",
      `Walk system ${feed.system_id}'s history again. Readings already stored are kept and refreshed, `
      + "and the walk costs calls out of this month's allowance.", "Import")) return;
    try {
      await api(`/api/enphase/feeds/${feed.id}/backfill`, { method: "POST" });
      await loadEnphaseSettings();
    } catch (error) { showAppError(error); }
  }));
  $$("[data-delete-enphase]").forEach((button) => button.addEventListener("click", async () => {
    const feed = feeds.find((item) => item.id === Number(button.dataset.deleteEnphase));
    if (!await confirmModal("Delete this solar feed",
      `Everything collected for system ${feed.system_id} goes with it. The history would have to be imported again.`)) return;
    try {
      await api(`/api/enphase/feeds/${feed.id}`, { method: "DELETE" });
      invalidateDashboard();
      await loadEnphaseSettings();
    } catch (error) { showAppError(error); }
  }));
}

async function openEnphaseAuthorization() {
  // Enphase wants a person in a browser, once. The window is opened before the
  // await so the click is still what opened it: a popup blocker would eat a
  // window opened after a round trip to our own server.
  const clientId = $("#enphase-client-id").value.trim();
  const opened = window.open("", "_blank");
  try {
    const data = await api(`/api/enphase/authorize-url?client_id=${encodeURIComponent(clientId)}`);
    if (opened) opened.location = data.url;
    else window.location.href = data.url;
  } catch (error) {
    if (opened) opened.close();
    showAppError(error);
  }
}

async function addEnphaseFeed(event) {
  event.preventDefault();
  try {
    // The server exchanges the code, asks the account for its systems and reads a
    // day before storing anything, so a stale code or a wrong key is refused here
    // rather than hours later in the log.
    await api("/api/enphase/feeds", { method: "POST", body: JSON.stringify({
      house_id: state.houseId,
      client_id: $("#enphase-client-id").value.trim(),
      client_secret: $("#enphase-client-secret").value,
      api_key: $("#enphase-api-key").value,
      code: $("#enphase-code").value.trim(),
      system_id: $("#enphase-system-id").value.trim(),
      calls_budget: Number($("#enphase-calls-budget").value) || 0,
    }) });
    ["client-secret", "api-key", "code", "system-id"].forEach((field) => { $(`#enphase-${field}`).value = ""; });
    invalidateDashboard();
    await loadEnphaseSettings();
  } catch (error) { showAppError(error); }
}

function sensorPayload(sensor) {
  // Every sensor write sends the whole sensor: a partial one would clear the rest.
  return {
    name: sensor.name,
    unit: sensor.unit,
    color: sensor.color,
    active: sensor.active,
    threshold_min: sensor.threshold_min,
    threshold_max: sensor.threshold_max,
  };
}

function sensorRangeLabel(sensor) {
  const unit = sensor.unit ? ` ${sensor.unit}` : "";
  const below = sensor.threshold_min == null ? "" : `below ${fmtTemp(sensor.threshold_min)}${unit}`;
  const above = sensor.threshold_max == null ? "" : `above ${fmtTemp(sensor.threshold_max)}${unit}`;
  if (below && above) return `alert ${below} or ${above}`;
  return below || above ? `alert ${below || above}` : "";
}

function renderSensorSettings() {
  const sensors = state.sensors || [];
  $("#sensor-list").innerHTML = sensors.map((sensor, index) => `
    <div class="mini-row wrap-row${sensor.active ? "" : " inactive"}">
      <span>
        <strong>${esc(sensor.name)}</strong>${sensor.unit ? ` · ${esc(sensor.unit)}` : ""}${sensor.active ? "" : ' <span class="badge">hidden</span>'}
        <br>
        <span class="meta">${esc(sensor.entity_id)}${sensor.last_value === null ? "" : ` · ${fmtTemp(sensor.last_value)} ${esc(sensor.unit)} ${esc(fmtAgo(sensor.last_at))}`}${sensorRangeLabel(sensor) ? ` · ${esc(sensorRangeLabel(sensor))}` : ""}</span>
      </span>
      <span class="icon-actions">
        <button class="ghost compact icon-only" data-color-sensor="${sensor.id}" type="button" title="Choose the colour">
          <span class="swatch" style="background:${esc(sensor.color || "var(--muted)")}"></span>
        </button>
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
  $$("[data-color-sensor]").forEach((button) => button.addEventListener("click", async () => {
    // The colour is the house's, like the order: everyone sees the same lines.
    const sensor = state.sensors.find((item) => item.id === Number(button.dataset.colorSensor));
    const color = await chooseColor(`Colour of ${sensor.name}`, sensor.color);
    if (color === null) return;
    try {
      await api(`/api/sensors/${sensor.id}`, { method: "PUT", body: JSON.stringify({
        ...sensorPayload(sensor),
        color,
      }) });
      await loadSensorSettings();
    } catch (error) { showAppError(error); }
  }));
  $$("[data-edit-sensor]").forEach((button) => button.addEventListener("click", async () => {
    const sensor = state.sensors.find((item) => item.id === Number(button.dataset.editSensor));
    let draft = { ...sensor, threshold_min: sensor.threshold_min ?? "", threshold_max: sensor.threshold_max ?? "" };
    let complaint = "";
    // An impossible range brings the dialog back with what was typed in it:
    // closing it would throw a whole edit away over one of the two numbers.
    for (;;) {
      const answers = await openModal({
        title: `Edit sensor · ${sensor.name}`,
        message: complaint || sensor.entity_id,
        fields: [
          { name: "name", label: "Name", value: draft.name },
          { name: "unit", label: "Unit", value: draft.unit },
          { name: "active", label: "Shown in the graphs", type: "checkbox", value: draft.active },
          { type: "heading", label: "Alert range - leave a side empty for no bound" },
          { name: "threshold_min", label: `Alert below${draft.unit ? ` (${draft.unit})` : ""}`, type: "number", value: draft.threshold_min },
          { name: "threshold_max", label: `Alert above${draft.unit ? ` (${draft.unit})` : ""}`, type: "number", value: draft.threshold_max },
        ],
      });
      if (answers === null) return;
      draft = answers;
      const minimum = answers.threshold_min === "" ? null : Number(answers.threshold_min);
      const maximum = answers.threshold_max === "" ? null : Number(answers.threshold_max);
      if (minimum !== null && maximum !== null && minimum >= maximum) {
        complaint = "The alert minimum must be lower than the maximum.";
        continue;
      }
      try {
        await api(`/api/sensors/${sensor.id}`, { method: "PUT", body: JSON.stringify({
          ...sensorPayload(sensor),
          name: answers.name,
          unit: answers.unit,
          active: answers.active,
          threshold_min: minimum,
          threshold_max: maximum,
        }) });
        await loadSensorSettings();
      } catch (error) { showAppError(error); }
      return;
    }
  }));
  $$("[data-toggle-sensor]").forEach((button) => button.addEventListener("click", async () => {
    // Hidden sensors keep collecting; deleting one would only bring it back on the next push.
    const sensor = state.sensors.find((item) => item.id === Number(button.dataset.toggleSensor));
    try {
      await api(`/api/sensors/${sensor.id}`, { method: "PUT", body: JSON.stringify({
        ...sensorPayload(sensor),
        active: !sensor.active,
      }) });
      await loadSensorSettings();
    } catch (error) { showAppError(error); }
  }));
}

async function issueSensorToken(house, top = false) {
  // `top` stacks it above the house dialog it is opened from, which stays put.
  const warning = house.has_sensor_token
    ? "This house already has a sensor token. Generating a new one stops the previous one at once: update Home Assistant with the new token."
    : "The token lets Home Assistant push the thermometers' readings into this house. It is shown once.";
  if (!await openModal({ title: `Sensor token · ${house.name}`, message: warning, submitLabel: "Generate", top })) return false;
  try {
    const data = await api(`/api/houses/${house.id}/sensor-token`, { method: "POST", body: "{}" });
    await openModal({
      title: `Sensor token · ${house.name}`,
      message: "Copy it now into Home Assistant's secrets.yaml (see deploy/home-assistant.yaml); it will not be shown again.",
      submitLabel: "Done",
      fields: [{ type: "html", html: `<div class="token-box">${esc(data.token)}</div>` }],
      top,
    });
    await loadAdmin();
    return true;
  } catch (error) { showAppError(error); }
  return false;
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

function houseMeasures(house) {
  return [
    house.shows_sensors ? "thermometers" : "",
    house.shows_water ? "water" : "",
    house.shows_power ? "solar" : "",
  ].filter(Boolean).join(", ");
}

function renderHouses() {
  $("#house-list").innerHTML = (state.admin.houses || []).map((house) => `
    <div class="mini-row">
      <span><strong>${esc(house.name)}</strong> <span class="meta">· ${esc(house.timezone || "")}${
        houseMeasures(house) ? ` · ${houseMeasures(house)}` : ""}</span></span>
      <span>
        <button class="ghost compact" data-rename-house="${house.id}" type="button">Edit</button>
        <button class="ghost compact danger" data-delete-house="${house.id}" type="button">Delete</button>
      </span>
    </div>`).join("") || '<p class="meta">No house yet.</p>';
  $$("[data-rename-house]").forEach((button) => button.addEventListener("click", async () => {
    const house = (state.admin.houses || []).find((item) => item.id === Number(button.dataset.renameHouse));
    const dialog = openModal({
      title: `Edit house · ${house.name}`,
      fields: [
        { name: "name", label: "House name", value: house.name },
        // The reminder email goes out at 06:15 in the house's own time zone.
        { name: "timezone", label: "Time zone", type: "select", value: house.timezone, options: timezoneOptions() },
        { type: "heading", label: "Realtime - what this house measures" },
        { name: "shows_sensors", label: "Thermometers (Home Assistant)", type: "checkbox", value: house.shows_sensors },
        { type: "html", html: `<button class="ghost compact modal-action" data-issue-token type="button"
          title="${house.has_sensor_token ? "Replace the Home Assistant sensor token" : "Create the Home Assistant sensor token"}">
          Sensor token${house.has_sensor_token ? ' <span class="badge">set</span>' : ""}</button>` },
        { name: "shows_water", label: "Water meter (EyeOnWater)", type: "checkbox", value: house.shows_water },
        { name: "shows_power", label: "Solar panels and batteries (Enphase)", type: "checkbox", value: house.shows_power },
      ],
    });
    // The token is what Home Assistant pushes with, so it belongs beside that
    // switch rather than in the row. openModal builds its fields before it
    // resolves, so the button is already there to be wired.
    const tokenButton = $("#modal-fields [data-issue-token]");
    if (tokenButton) {
      tokenButton.addEventListener("click", async () => {
        if (!await issueSensorToken(house, true)) return;
        house.has_sensor_token = true;
        tokenButton.innerHTML = 'Sensor token <span class="badge">set</span>';
      });
    }
    const answers = await dialog;
    if (answers === null || !answers.name.trim()) return;
    try {
      await api(`/api/houses/${house.id}`, { method: "PUT", body: JSON.stringify({
        name: answers.name.trim(),
        timezone: answers.timezone,
        shows_sensors: answers.shows_sensors,
        shows_water: answers.shows_water,
        shows_power: answers.shows_power,
      }) });
      // The switches decide a nav item and two settings tabs: the cached
      // dashboard would keep showing yesterday's answer.
      invalidateDashboard();
      await loadAdmin();
      await ensureDashboard();
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
    const color = await chooseColor(`Colour of ${meter.label || meter.kind}`, meter.color);
    if (color === null) return;
    try {
      await api("/api/me/meter-color", { method: "POST", body: JSON.stringify({ meter_id: meter.id, color }) });
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
    // The header's house label owns #house-name: this is the add-house field.
    await api("/api/houses", { method: "POST", body: JSON.stringify({ name: $("#new-house-name").value.trim() }) });
    $("#new-house-name").value = "";
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
  $("#water-feed-form").addEventListener("submit", addWaterFeed);
  $("#enphase-feed-form").addEventListener("submit", addEnphaseFeed);
  $("#enphase-authorize").addEventListener("click", openEnphaseAuthorization);
  // A monthly meter has no counter: the start-value row would only mislead.
  $("#meter-monthly").addEventListener("change", () => {
    $("#meter-register-row").hidden = $("#meter-monthly").checked;
  });
  $("#house-btn").addEventListener("click", chooseHouse);
  $$("[data-sensor-days]").forEach((button) => button.addEventListener("click", () => {
    storeItem("usage-sensor-days", button.dataset.sensorDays);
    state.sensorOffset = 0;
    loadSensors(true);
  }));
  $("#sensor-alert-toggle").addEventListener("change", async () => {
    const toggle = $("#sensor-alert-toggle");
    try {
      await api("/api/sensors/alerts", {
        method: "POST",
        body: JSON.stringify({ house_id: state.houseId, enabled: toggle.checked }),
      });
    } catch (error) {
      toggle.checked = !toggle.checked;
      showAppError(error);
    }
  });
  $("#water-alert-toggle").addEventListener("change", async () => {
    const toggle = $("#water-alert-toggle");
    try {
      await api("/api/water/alerts", {
        method: "POST",
        body: JSON.stringify({ house_id: state.houseId, enabled: toggle.checked }),
      });
    } catch (error) {
      toggle.checked = !toggle.checked;
      showAppError(error);
    }
  });
  $("#sensor-units").addEventListener("change", () => {
    storeItem("usage-temp-unit", $("#sensor-units").checked ? "C" : "F");
    renderSensors();
  });
  $("#sensor-previous").addEventListener("click", () => {
    const on = !wantsPrevious();
    storeItem("usage-sensor-previous", on ? "1" : "0");
    setToggle("#sensor-previous", on);
    // The overlay is a second period from the server, not a redraw of this one.
    loadSensors(true);
  });
  $("#sensor-thresholds").addEventListener("click", () => {
    const on = !wantsThresholds();
    storeThresholds(on);
    setToggle("#sensor-thresholds", on);
    // The alert range is drawn on the thermometers and nowhere else.
    renderRealtimeCard("sensors");
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
