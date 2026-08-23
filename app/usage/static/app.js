"use strict";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

let state = { me: null, admin: null };

function esc(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function api(path, options = {}) {
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
  showView("entries");
}

async function requestLink(event) {
  event.preventDefault();
  try {
    const email = $("#login-email").value.trim();
    const data = await api("/api/auth/request-link", { method: "POST", body: JSON.stringify({ email }) });
    if (data.dev_link) {
      showLoginNotice(`Development mode — sign-in link: ${data.dev_link}`);
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

async function loadAdmin() {
  try {
    state.admin = await api("/api/admin/overview");
    $("#admin-panels").hidden = false;
    renderHouses();
    renderUsers();
    renderMeters();
  } catch (error) { showAppError(error); }
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
  const themeApp = $("#theme-btn-app");
  if (themeApp) themeApp.addEventListener("click", toggleTheme);
  $$(".app-nav button").forEach((button) => button.addEventListener("click", () => showView(button.dataset.nav)));
  load();
});
