"use strict";

const $ = (selector) => document.querySelector(selector);
const state = { token: null, user: null, company: null, page: 0, size: 10, hasNext: false, editId: null, requests: [], epoch: 0, busy: false };
const labels = { company: ["公司资料", "查看和维护当前账号所属公司的基本信息。"], departments: ["部门管理", "查看组织结构，管理当前公司的部门。"], requests: ["请求记录", "查看本次操作的接口状态与响应时间。"] };
const admin = () => state.user?.role === "admin";
const dateText = (date) => new Date(date).toLocaleString("zh-CN", { hour12: false });

function notice(message, error = false) {
  const element = $("#notice");
  element.textContent = message;
  element.classList.toggle("error", error);
  element.classList.toggle("hidden", !message);
}

function detailText(data) {
  if (typeof data?.detail === "string") return data.detail;
  if (Array.isArray(data?.detail)) return data.detail.map((item) => `${item.loc?.slice(1).join(".") || "参数"}：${item.msg}`).join("；");
  return "请求失败，请查看后端终端的错误信息。";
}

function logRequest(method, path, status, start, message) {
  state.requests.unshift({ time: new Date(), method, path, status, duration: Math.round(performance.now() - start), message });
  state.requests = state.requests.slice(0, 50);
  renderRequests();
}

async function request(path, { method = "GET", body, authenticated = true } = {}) {
  const start = performance.now();
  const headers = { Accept: "application/json" };
  if (authenticated && state.token) headers.Authorization = `Bearer ${state.token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let response;
  try {
    response = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(15000) });
  } catch (error) {
    const message = error.name === "TimeoutError" ? "请求超时，请检查后端服务。" : "无法连接服务，请确认后端已启动，并通过后端地址打开此页面。";
    logRequest(method, path, "未连接", start, message);
    throw new Error(message);
  }
  const data = await response.json().catch(() => null);
  const message = response.ok ? "成功" : detailText(data);
  logRequest(method, path, response.status, start, message);
  if (!response.ok) {
    if (response.status === 401 && authenticated) resetSession();
    throw new Error(`${response.status} · ${message}`);
  }
  return data;
}

function renderRequests() {
  $("#request-count").textContent = state.requests.length;
  $("#request-empty").classList.toggle("hidden", state.requests.length > 0);
  const rows = state.requests.map((item) => {
    const row = document.createElement("tr");
    [item.time.toLocaleTimeString("zh-CN", { hour12: false }), `${item.method} ${item.path}`, String(item.status), `${item.duration} ms`, item.message].forEach((value) => {
      const cell = document.createElement("td"); cell.textContent = value; row.append(cell);
    });
    return row;
  });
  $("#request-rows").replaceChildren(...rows);
}

function renderSession() {
  const user = state.user;
  $("#identity").textContent = user ? (admin() ? "管理员" : "HR 账号") : "尚未登录";
  $("#identity-detail").textContent = user ? `公司标识：${user.tenant_id}` : "登录后查看本公司的资料与部门";
  $("#avatar").textContent = user ? (admin() ? "A" : "H") : "U";
  $("#role-badge").textContent = admin() ? "管理员" : "HR";
  $("#role-badge").classList.toggle("hidden", !user);
  $("#login-button").classList.toggle("hidden", !!user);
  $("#logout-button").classList.toggle("hidden", !user);
  document.querySelectorAll("[data-auth]").forEach((element) => { element.disabled = !user; });
  $("#add-department").disabled = !admin();
  $("#save-company").disabled = !admin();
  $("#company-permission").textContent = admin() ? "修改仅影响当前公司" : "当前为只读模式，仅管理员可以修改";
  syncPagination();
}

function syncPagination() {
  $("#previous-page").disabled = !state.user || state.page === 0;
  $("#next-page").disabled = !state.user || !state.hasNext;
}

function resetSession() {
  state.epoch += 1;
  state.token = null; state.user = null; state.company = null; state.page = 0; state.hasNext = false;
  $("#company-form").reset();
  $("#company-form").classList.add("hidden"); $("#company-empty").classList.remove("hidden");
  $("#department-rows").replaceChildren();
  $("#department-empty").classList.remove("hidden");
  $("#department-empty h3").textContent = "登录后查看部门";
  $("#department-empty p").textContent = "这里会显示当前公司的真实部门数据。";
  $("#department-count").textContent = "—"; $("#page-label").textContent = "第 1 页";
  $("#department-dialog").close();
  renderSession();
}

async function health() {
  $("#check-health").disabled = true;
  try {
    await request("/health", { authenticated: false });
    $("#health-text").textContent = "后端已连接";
    $("#health-dot").className = "dot";
  } catch {
    $("#health-text").textContent = "后端未连接";
    $("#health-dot").className = "dot offline";
  } finally { $("#check-health").disabled = false; }
}

async function loadCompany() {
  if (!state.user) return;
  const epoch = state.epoch;
  const company = await request("/api/v1/companies/current");
  if (epoch !== state.epoch) return;
  state.company = company;
  const form = $("#company-form");
  for (const name of ["name", "short_name", "address", "description"]) {
    form.elements[name].value = company[name] || "";
    form.elements[name].disabled = !admin();
  }
  $("#company-empty").classList.add("hidden"); form.classList.remove("hidden");
}

async function loadDepartments() {
  if (!state.user) return;
  const epoch = state.epoch;
  const filter = $("#department-filter").value;
  const params = new URLSearchParams({ limit: state.size, offset: state.page * state.size });
  if (filter) params.set("is_active", filter);
  const departments = await request(`/api/v1/departments?${params}`);
  if (epoch !== state.epoch) return;
  const rows = departments.map((department) => {
    const row = document.createElement("tr");
    for (const value of [department.name, department.description || "—"]) {
      const cell = document.createElement("td"); cell.textContent = value; row.append(cell);
    }
    const status = document.createElement("td"); const badge = document.createElement("span");
    badge.className = `badge${department.is_active ? "" : " inactive"}`;
    badge.textContent = department.is_active ? "启用中" : "已停用"; status.append(badge); row.append(status);
    const date = document.createElement("td"); date.textContent = dateText(department.updated_at); row.append(date);
    const actions = document.createElement("td"); const group = document.createElement("div"); group.className = "row-actions";
    const edit = document.createElement("button"); edit.className = "text-button"; edit.textContent = "编辑"; edit.disabled = !admin();
    edit.addEventListener("click", () => run(edit, async () => {
      const current = await request(`/api/v1/departments/${department.id}`);
      if (epoch !== state.epoch) return;
      openDepartment(current);
    }));
    const toggle = document.createElement("button"); toggle.className = "text-button warn";
    toggle.textContent = department.is_active ? "停用" : "启用"; toggle.disabled = !admin();
    toggle.addEventListener("click", () => {
      const action = department.is_active ? "停用" : "启用";
      if (!confirm(`确定${action}「${department.name}」吗？`)) return;
      run(toggle, async () => {
        await request(`/api/v1/departments/${department.id}`, { method: "PATCH", body: { is_active: !department.is_active } });
        notice(`部门已${action}`); await loadDepartments();
      });
    });
    group.append(edit, toggle); actions.append(group); row.append(actions); return row;
  });
  $("#department-rows").replaceChildren(...rows);
  $("#department-count").textContent = `本页 ${departments.length}`;
  $("#department-empty").classList.toggle("hidden", departments.length > 0);
  $("#department-empty h3").textContent = "暂无部门";
  $("#department-empty p").textContent = "当前筛选下没有部门记录，管理员可以新增部门。";
  $("#page-label").textContent = `第 ${state.page + 1} 页`;
  state.hasNext = departments.length === state.size;
  syncPagination();
}

function openDepartment(department = null) {
  state.editId = department?.id || null;
  $("#department-form").reset(); $("#department-error").textContent = "";
  $("#department-dialog-title").textContent = department ? "编辑部门" : "新增部门";
  if (department) {
    $("#department-form").elements.name.value = department.name;
    $("#department-form").elements.description.value = department.description || "";
  }
  $("#department-dialog").showModal();
}

async function run(button, action, errorTarget = null) {
  if (state.busy) return;
  state.busy = true;
  const wasDisabled = button.disabled; button.disabled = true;
  try { await action(); }
  catch (error) {
    if (errorTarget) errorTarget.textContent = error.message;
    else notice(error.message, true);
  } finally {
    state.busy = false;
    button.disabled = wasDisabled;
    document.querySelectorAll("[data-auth]").forEach((element) => { element.disabled = !state.user; });
    $("#add-department").disabled = !admin();
    $("#save-company").disabled = !admin();
    syncPagination();
  }
}

document.querySelectorAll("[data-tab]").forEach((button) => button.addEventListener("click", () => {
  const tab = button.dataset.tab;
  document.querySelectorAll(".nav").forEach((item) => item.classList.toggle("active", item === button));
  document.querySelectorAll(".panel").forEach((panel) => panel.classList.toggle("hidden", panel.id !== `${tab}-panel`));
  $("#page-title").textContent = labels[tab][0]; $("#breadcrumb").textContent = labels[tab][0]; $("#page-subtitle").textContent = labels[tab][1];
}));

function openLogin() { $("#login-error").textContent = ""; $("#login-dialog").showModal(); }
$("#login-button").addEventListener("click", openLogin);
document.querySelectorAll("[data-open-login]").forEach((button) => button.addEventListener("click", openLogin));
document.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", () => $("#" + button.dataset.close).close()));
$("#login-dialog").addEventListener("close", () => { $("#login-form").elements.password.value = ""; });
$("#logout-button").addEventListener("click", () => { resetSession(); notice("已退出登录，登录凭证已从页面清除。"); });

$("#login-form").addEventListener("submit", (event) => {
  event.preventDefault(); const form = event.currentTarget; $("#login-error").textContent = "";
  run(form.querySelector('[type="submit"]'), async () => {
    const result = await request("/api/v1/auth/login", { method: "POST", body: { username: form.elements.username.value.trim(), password: form.elements.password.value }, authenticated: false });
    state.token = result.access_token;
    try { state.user = await request("/api/v1/auth/me"); }
    catch (error) { resetSession(); throw error; }
    state.epoch += 1; state.page = 0; renderSession(); $("#login-dialog").close(); notice("登录成功，已验证当前账号身份。");
    const results = await Promise.allSettled([loadCompany(), loadDepartments()]);
    const errors = results.filter((result) => result.status === "rejected");
    if (errors.length) notice(errors.map((result) => result.reason.message).join("；"), true);
  }, $("#login-error"));
});

$("#company-form").addEventListener("submit", (event) => {
  event.preventDefault(); if (!admin()) return; const form = event.currentTarget;
  run($("#save-company"), async () => {
    const body = Object.fromEntries(["name", "short_name", "address", "description"].map((key) => [key, form.elements[key].value.trim() || null]));
    await request("/api/v1/companies/current", { method: "PATCH", body });
    await loadCompany(); notice("公司资料已保存。");
  });
});

$("#department-form").addEventListener("submit", (event) => {
  event.preventDefault(); if (!admin()) return; const form = event.currentTarget; $("#department-error").textContent = "";
  run(form.querySelector('[type="submit"]'), async () => {
    const body = { name: form.elements.name.value.trim(), description: form.elements.description.value.trim() || null };
    await request(state.editId ? `/api/v1/departments/${state.editId}` : "/api/v1/departments", { method: state.editId ? "PATCH" : "POST", body });
    $("#department-dialog").close(); state.page = 0; notice("部门已保存。"); await loadDepartments();
  }, $("#department-error"));
});

$("#add-department").addEventListener("click", () => openDepartment());
$("#reload-company").addEventListener("click", () => run($("#reload-company"), loadCompany));
$("#reload-departments").addEventListener("click", () => run($("#reload-departments"), loadDepartments));
$("#department-filter").addEventListener("change", () => { if (state.busy) return; state.page = 0; run($("#reload-departments"), loadDepartments); });
$("#previous-page").addEventListener("click", () => { if (state.busy) return; state.page = Math.max(0, state.page - 1); run($("#previous-page"), loadDepartments); });
$("#next-page").addEventListener("click", () => { if (state.busy) return; state.page += 1; run($("#next-page"), loadDepartments); });
$("#clear-requests").addEventListener("click", () => { state.requests = []; renderRequests(); });
$("#check-health").addEventListener("click", health);
$("#server-address").textContent = location.origin;
renderSession(); renderRequests(); health();
