"use strict";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

let state = {
  me: null,
  admin: null,
  dashboard: null,
  entriesHouseId: 0,
  entriesPage: 1,
  readingSource: "manual",
  statsHouseId: 0,
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

function showView(name) {
  $$(".app-nav button").forEach((item) => item.classList.toggle("active", item.dataset.nav === name));
  $$(".app-main > section").forEach((section) => { section.hidden = section.id !== `view-${name}`; });
  if (name === "settings") {
    loadPasskeys();
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
    .then((data) => { $("#version").textContent = `v${data.version}` + (data.build ? ` · ${data.build}` : ""); })
    .catch(() => {});
  showView("stats");
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

async function loadEntries() {
  try {
    state.dashboard = await api("/api/dashboard");
    const houses = state.dashboard.houses || [];
    const select = $("#entries-house");
    select.innerHTML = houses.map((house) => `<option value="${house.id}">${esc(house.name)}</option>`).join("");
    if (!houses.some((house) => house.id === state.entriesHouseId)) {
      state.entriesHouseId = houses.length ? houses[0].id : 0;
    }
    select.value = String(state.entriesHouseId);
    renderReadingForm();
    await loadReadings(state.entriesPage);
  } catch (error) { showAppError(error); }
}

function houseMeters() {
  return (state.dashboard.meters || []).filter((meter) => meter.house_id === state.entriesHouseId);
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

async function addReading(event) {
  event.preventDefault();
  const meter = selectedMeter();
  if (!meter) { showAppError(new Error("Add a meter first.")); return; }
  const values = $$("#reading-values [data-register-value]").map((input) => ({
    register_id: Number(input.dataset.registerValue),
    value: Number(input.value),
  }));
  try {
    await api("/api/readings", { method: "POST", body: JSON.stringify({
      meter_id: meter.id,
      read_on: $("#reading-date").value,
      source: state.readingSource,
      values,
    }) });
    $("#reading-photo").value = "";
    renderValueInputs();
    await loadReadings(1);
  } catch (error) { showAppError(error); }
}

async function loadReadings(page) {
  if (!state.entriesHouseId) {
    $("#reading-list").innerHTML = '<p class="meta">No house is linked to your account yet.</p>';
    $("#reading-pager").innerHTML = "";
    return;
  }
  try {
    const data = await api(`/api/readings?house_id=${state.entriesHouseId}&page=${page}`);
    state.entriesPage = data.page;
    renderReadings(data);
  } catch (error) { showAppError(error); }
}

function renderReadings(data) {
  $("#reading-list").innerHTML = (data.readings || []).map((reading) => `
    <div class="mini-row wrap-row">
      <span>
        <strong>${esc(reading.read_on)}</strong> · ${esc(reading.meter_label || reading.kind)}
        · ${reading.values.map((value) => `${value.label ? `${esc(value.label)}: ` : ""}${value.value}`).join(" / ")}
        ${reading.unit ? ` ${esc(reading.unit)}` : ""}
        <span class="badge">${esc(reading.source)}</span>
      </span>
      <span>
        <button class="ghost compact" data-edit-reading="${reading.id}" type="button">Edit</button>
        <button class="ghost compact danger" data-delete-reading="${reading.id}" type="button">Delete</button>
      </span>
    </div>`).join("") || '<p class="meta">No reading yet.</p>';
  const pager = [];
  if (data.page > 1) pager.push(`<button class="ghost compact" data-page="${data.page - 1}" type="button">← Previous</button>`);
  pager.push(`<span class="meta">Page ${data.page} / ${data.pages} · ${data.total} readings</span>`);
  if (data.page < data.pages) pager.push(`<button class="ghost compact" data-page="${data.page + 1}" type="button">Next →</button>`);
  $("#reading-pager").innerHTML = pager.join(" ");
  $$("[data-page]").forEach((button) => button.addEventListener("click", () => loadReadings(Number(button.dataset.page))));
  $$("[data-edit-reading]").forEach((button) => button.addEventListener("click", () => editReading(Number(button.dataset.editReading), data)));
  $$("[data-delete-reading]").forEach((button) => button.addEventListener("click", async () => {
    if (!confirm("Delete this reading?")) return;
    try {
      await api(`/api/readings/${button.dataset.deleteReading}`, { method: "DELETE" });
      await loadReadings(state.entriesPage);
    } catch (error) { showAppError(error); }
  }));
}

async function editReading(readingId, data) {
  const reading = (data.readings || []).find((item) => item.id === readingId);
  const readOn = prompt("Date (YYYY-MM-DD):", reading.read_on);
  if (readOn === null) return;
  const values = [];
  for (const value of reading.values) {
    const answer = prompt(`${value.label || "Counter"}:`, String(value.value));
    if (answer === null) return;
    values.push({ register_id: value.register_id, value: Number(answer) });
  }
  try {
    await api(`/api/readings/${readingId}`, { method: "PUT", body: JSON.stringify({ read_on: readOn, values }) });
    await loadReadings(state.entriesPage);
  } catch (error) { showAppError(error); }
}

async function loadStats() {
  try {
    state.dashboard = await api("/api/dashboard");
    const houses = state.dashboard.houses || [];
    const select = $("#stats-house");
    select.innerHTML = houses.map((house) => `<option value="${house.id}">${esc(house.name)}</option>`).join("");
    if (!houses.some((house) => house.id === state.statsHouseId)) {
      state.statsHouseId = houses.length ? houses[0].id : 0;
    }
    select.value = String(state.statsHouseId);
    if (!state.statsHouseId) {
      $("#stats-content").innerHTML = '<p class="meta">No house is linked to your account yet.</p>';
      return;
    }
    const tables = await api(`/api/stats/tables?house_id=${state.statsHouseId}`);
    const series = await api(`/api/stats/series?house_id=${state.statsHouseId}`);
    renderStats(tables, series);
  } catch (error) { showAppError(error); }
}

function renderStats(tables, series) {
  const kinds = tables.kinds || [];
  if (!kinds.length) {
    $("#stats-content").innerHTML = '<p class="meta">No reading yet - add measurements in Entries first.</p>';
    return;
  }
  $("#stats-content").innerHTML = kinds.map((kind) => {
    const kindSeries = (series.series || []).filter((item) => item.kind === kind.kind);
    const title = kind.kind.charAt(0).toUpperCase() + kind.kind.slice(1);
    return `
      <div class="card">
        <h3>${esc(title)}${kind.unit ? ` <span class="meta">(${esc(kind.unit)} per month)</span>` : ""}</h3>
        <div class="table-wrap">${statsTable(kind)}</div>
        ${chartMarkup(kindSeries)}
        ${kindSeries.length > 1 ? `
          <div class="viz-legend">
            ${kindSeries.map((item, index) => `<span><i style="background:${VIZ_COLORS[index % VIZ_COLORS.length]}"></i>${esc(item.label)}</span>`).join("")}
          </div>` : ""}
      </div>`;
  }).join("");
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

function chartMarkup(seriesList) {
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
    const dots = item.points.map((point) => {
      const tooltip = `<title>${esc(item.label)} · ${esc(point.month)} · ${fmtValue(point.value)}${item.unit ? ` ${esc(item.unit)}` : ""}</title>`;
      const dot = showDots
        ? `<circle class="dot" cx="${xAt(point.month).toFixed(1)}" cy="${yAt(point.value).toFixed(1)}" r="3" fill="${color}"></circle>`
        : "";
      return `${dot}<circle class="hit" cx="${xAt(point.month).toFixed(1)}" cy="${yAt(point.value).toFixed(1)}" r="9">${tooltip}</circle>`;
    }).join("");
    return `<g class="series"><path d="${path}" stroke="${color}"></path>${dots}</g>`;
  });

  return `
    <svg class="viz-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Monthly consumption trend">
      <g class="grid">${gridLines.join("")}</g>
      <g class="axis">${yLabels.join("")}${xLabels.join("")}</g>
      ${paths.join("")}
    </svg>`;
}

async function loadAdmin() {
  try {
    state.admin = await api("/api/admin/overview");
    $$("#settings-tabs button").forEach((button) => { button.hidden = false; });
    renderHouses();
    renderUsers();
    renderMeters();
  } catch (error) { showAppError(error); }
}

function showSettingsTab(name) {
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
    const name = prompt("House name:", houseName(Number(button.dataset.renameHouse)));
    if (!name) return;
    try {
      await api(`/api/houses/${button.dataset.renameHouse}`, { method: "PUT", body: JSON.stringify({ name }) });
      await loadAdmin();
    } catch (error) { showAppError(error); }
  }));
  $$("[data-delete-house]").forEach((button) => button.addEventListener("click", async () => {
    if (!confirm("Delete this house, its meters and all their readings?")) return;
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
    const name = prompt("Name:", user.name);
    if (name === null) return;
    const isAdmin = confirm("Should this user be an admin? OK = yes, Cancel = no.");
    try {
      await api(`/api/users/${user.id}`, { method: "PUT", body: JSON.stringify({ name, is_admin: isAdmin }) });
      await loadAdmin();
    } catch (error) { showAppError(error); }
  }));
  $$("[data-delete-user]").forEach((button) => button.addEventListener("click", async () => {
    if (!confirm("Delete this user?")) return;
    try {
      await api(`/api/users/${button.dataset.deleteUser}`, { method: "DELETE" });
      await loadAdmin();
    } catch (error) { showAppError(error); }
  }));
}

function renderMeters() {
  const houses = state.admin.houses || [];
  $("#meter-house").innerHTML = houses.map((house) => `<option value="${house.id}">${esc(house.name)}</option>`).join("");
  $("#meter-list").innerHTML = (state.admin.meters || []).map((meter) => `
    <div class="mini-row wrap-row${meter.active ? "" : " inactive"}">
      <span>
        <strong>${esc(meter.label || meter.kind)}</strong> · ${esc(meter.kind)} · ${esc(houseName(meter.house_id))}
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
    const meter = state.admin.meters.find((item) => item.id === Number(button.dataset.editMeter));
    const label = prompt("Label:", meter.label);
    if (label === null) return;
    const unit = prompt("Unit:", meter.unit);
    if (unit === null) return;
    const active = confirm("Should this meter stay active? OK = yes, Cancel = no.");
    try {
      await api(`/api/meters/${meter.id}`, { method: "PUT", body: JSON.stringify({ label, unit, active }) });
      await loadAdmin();
    } catch (error) { showAppError(error); }
  }));
  $$("[data-delete-meter]").forEach((button) => button.addEventListener("click", async () => {
    if (!confirm("Delete this meter and all its readings?")) return;
    try {
      await api(`/api/meters/${button.dataset.deleteMeter}`, { method: "DELETE" });
      await loadAdmin();
    } catch (error) { showAppError(error); }
  }));
  $$("[data-add-register]").forEach((button) => button.addEventListener("click", async () => {
    const label = prompt("Register label (e.g. HP):", "");
    if (label === null) return;
    const initial = prompt("Start value of the counter:", "0");
    if (initial === null) return;
    try {
      await api(`/api/meters/${button.dataset.addRegister}/registers`, { method: "POST", body: JSON.stringify({
        label,
        initial_value: Number(initial) || 0,
      }) });
      await loadAdmin();
    } catch (error) { showAppError(error); }
  }));
  $$("[data-edit-register]").forEach((button) => button.addEventListener("click", async () => {
    const register = state.admin.meters.flatMap((meter) => meter.registers)
      .find((item) => item.id === Number(button.dataset.editRegister));
    const label = prompt("Register label:", register.label);
    if (label === null) return;
    const initial = prompt("Start value of the counter:", String(register.initial_value));
    if (initial === null) return;
    const active = confirm("Should this register stay active? OK = yes, Cancel = no.");
    try {
      await api(`/api/registers/${register.id}`, { method: "PUT", body: JSON.stringify({
        label,
        initial_value: Number(initial) || 0,
        active,
      }) });
      await loadAdmin();
    } catch (error) { showAppError(error); }
  }));
  $$("[data-delete-register]").forEach((button) => button.addEventListener("click", async () => {
    if (!confirm("Delete this register?")) return;
    try {
      await api(`/api/registers/${button.dataset.deleteRegister}`, { method: "DELETE" });
      await loadAdmin();
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
      house_id: Number($("#meter-house").value),
      kind: $("#meter-kind").value,
      label: $("#meter-label").value.trim(),
      unit: $("#meter-unit").value.trim(),
      registers,
    }) });
    $("#meter-label").value = "";
    $("#meter-unit").value = "";
    $("#meter-dual").checked = false;
    toggleDualRegisters();
    await loadAdmin();
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
  $("#entries-house").addEventListener("change", () => {
    state.entriesHouseId = Number($("#entries-house").value);
    state.entriesPage = 1;
    renderReadingForm();
    loadReadings(1);
  });
  $("#reading-meter").addEventListener("change", renderValueInputs);
  $("#btn-read-photo").addEventListener("click", readPhoto);
  $("#reading-form").addEventListener("submit", addReading);
  $("#stats-house").addEventListener("change", () => {
    state.statsHouseId = Number($("#stats-house").value);
    loadStats();
  });
  const themeApp = $("#theme-btn-app");
  if (themeApp) themeApp.addEventListener("click", toggleTheme);
  $$(".app-nav button").forEach((button) => button.addEventListener("click", () => showView(button.dataset.nav)));
  $$("#settings-tabs button").forEach((button) => button.addEventListener("click", () => showSettingsTab(button.dataset.settingsTab)));
  load();
});
