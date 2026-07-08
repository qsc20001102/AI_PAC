// P2-9/P2-10 修复：原代码 for(i=1;i<99999;i++) clearInterval/clearTimeout 是极端 hack，
// 且 setInterval 返回值未保存，无法在页面切换或重新启动时精确清理。
// 改为维护已注册的定时器 ID 列表，清理时遍历该列表精确清除。
const _registeredTimers = [];

function registerInterval(fn, ms) {
  const id = window.setInterval(fn, ms);
  _registeredTimers.push(id);
  return id;
}

function clearRegisteredTimers() {
  while (_registeredTimers.length) {
    const id = _registeredTimers.pop();
    window.clearInterval(id);
  }
}

async function boot() {
  // 清理上一轮 boot 注册的定时器（如热重载场景），避免重复触发
  clearRegisteredTimers();
  await initAuth();
  const hashPage = window.location.hash.slice(2);
  if (hashPage && ["overview", "process", "processParams", "models", "plc", "data", "trends", "alarms", "settings"].includes(hashPage)) {
    state.activePage = hashPage;
  }
  renderNav();
  renderUserArea();
  tickClock();
  registerInterval(tickClock, 1000);
  await refreshAll();
  registerInterval(refreshDashboardOnly, 30000);
  registerInterval(refreshCollectionRealtime, 2000);
}

async function initAuth() {
  try {
    const data = await api("/api/auth/me");
    if (data.authenticated) {
      state.user = data.user;
    } else {
      state.user = null;
      localStorage.removeItem("token");
    }
  } catch (_) {
    state.user = null;
    localStorage.removeItem("token");
  }
}

async function refreshAll() {
  const [dashboard, points] = await Promise.all([api("/api/dashboard"), api("/api/dosing-points")]);
  state.dashboard = dashboard;
  state.points = points;
  if ((!state.selectedPointId || !points.some((p) => p.id === state.selectedPointId)) && points[0]) {
    state.selectedPointId = points[0].id;
  } else if (!points.length) {
    state.selectedPointId = null;
  }
  await renderPage();
}

async function refreshDashboardOnly() {
  try {
    state.dashboard = await api("/api/dashboard");
    if (state.activePage === "overview") await renderPage();
  } catch (err) {
    showToast(`刷新失败：${err.message}`);
  }
}

function tickClock() {
  const d = new Date();
  document.getElementById("clockText").textContent = `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
}

function userRole() {
  return state.user?.role || "guest";
}

function navAllowed(role) {
  if (role === "admin") return true;
  const allowed = ["process", "data", "plc", "models", "alarms", "settings"];
  return allowed.includes(role);
}

function visibleNavItems() {
  const role = userRole();
  return navItems.filter(([id]) => {
    if (role === "admin") return true;
    return ["overview", "processParams", "trends", "plc", "models", "alarms", "settings"].includes(id);
  });
}

function renderNav() {
  const role = userRole();
  const items = visibleNavItems();
  document.getElementById("nav").innerHTML = items.map(([id, label, ico, extra]) => `
    <button class="nav-button ${state.activePage === id ? "active" : ""} ${extra || ""}" type="button" data-page="${id}">
      ${icon(ico)}<span>${label}</span>
    </button>
  `).join("");
  document.querySelectorAll(".nav-button").forEach((btn) => {
    btn.addEventListener("click", async () => {
      state.activePage = btn.dataset.page;
      renderNav();
      await renderPage();
    });
  });
}

function renderUserArea() {
  const area = document.getElementById("userArea");
  if (!area) return;
  if (state.user) {
    area.innerHTML = `
      <span class="user-name">${htmlEscape(state.user.username)}</span>
      <span class="user-role">${roleLabel(state.user.role)}</span>
      <button class="btn ghost" id="logoutBtn" type="button">退出</button>
    `;
    document.getElementById("logoutBtn")?.addEventListener("click", async () => {
      try { await api("/api/auth/logout", { method: "POST" }); } catch (_) {}
      localStorage.removeItem("token");
      state.user = null;
      state.activePage = "overview";
      renderUserArea();
      renderNav();
      await renderPage();
    });
  } else {
    area.innerHTML = `<button class="btn ghost" id="loginBtn" type="button">登录</button>`;
    document.getElementById("loginBtn")?.addEventListener("click", showLoginModal);
  }
}

function roleLabel(role) {
  return role === "admin" ? "管理员" : role === "user" ? "普通用户" : "访客";
}

function showLoginModal() {
  let modal = document.getElementById("loginModal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "loginModal";
    modal.className = "modal";
    modal.innerHTML = `
      <div class="modal-backdrop"></div>
      <div class="modal-box">
        <div class="modal-header">
          <div class="modal-title">用户登录</div>
          <button class="btn icon" id="loginClose" type="button">&#x2715;</button>
        </div>
        <div class="modal-body">
          <form id="loginForm" class="form">
            <div class="field">
              <label>用户名</label>
              <input type="text" id="loginUsername" placeholder="请输入用户名" required autocomplete="username">
            </div>
            <div class="field">
              <label>密码</label>
              <input type="password" id="loginPassword" placeholder="请输入密码" required autocomplete="current-password">
            </div>
            <div class="actions">
              <button class="btn primary" type="submit">登录</button>
            </div>
          </form>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    document.getElementById("loginClose")?.addEventListener("click", hideLoginModal);
    document.getElementById("loginForm")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const username = document.getElementById("loginUsername").value.trim();
      const password = document.getElementById("loginPassword").value;
      try {
        const data = await api("/api/auth/login", {
          method: "POST",
          body: JSON.stringify({ username, password }),
        });
        if (data.ok) {
          localStorage.setItem("token", data.token);
          state.user = data.user;
          hideLoginModal();
          renderUserArea();
          renderNav();
          await renderPage();
          showToast("登录成功");
        } else {
          showToast(data.detail || "登录失败");
        }
      } catch (err) {
        showToast(`登录失败：${err.message}`);
      }
    });
  }
  modal.classList.add("show");
  document.getElementById("loginUsername")?.focus();
}

function hideLoginModal() {
  document.getElementById("loginModal")?.classList.remove("show");
}

async function renderPage() {
  if (state.modelRefreshTimer) {
    window.clearTimeout(state.modelRefreshTimer);
    state.modelRefreshTimer = null;
  }
  const main = document.getElementById("main");
  if (!state.dashboard) {
    main.innerHTML = `<div class="empty">正在加载系统数据</div>`;
    return;
  }
  const role = userRole();
  const allowed = ["overview", "processParams", "trends", "plc", "models", "alarms", "settings"];
  if (role !== "admin" && !allowed.includes(state.activePage)) {
    state.activePage = "overview";
    renderNav();
  }
  if (state.activePage === "overview") await renderOverview(main);
  else if (state.activePage === "process") await renderProcess(main);
  else if (state.activePage === "processParams") await renderProcessParams(main);
  else if (state.activePage === "data") await renderData(main);
  else if (state.activePage === "trends") await renderTrends(main);
  else if (state.activePage === "models") await renderModels(main);
  else if (state.activePage === "plc") await renderPlc(main);
  else if (state.activePage === "alarms") await renderAlarms(main);
  else if (state.activePage === "settings") await renderSettings(main);
  else {
    state.activePage = "overview";
    renderNav();
    await renderOverview(main);
  }
  applyPagePermissions();
}

function applyPagePermissions() {
  const main = document.getElementById("main");
  if (!main) return;
  if (userRole() === "guest") {
    main.classList.add("guest-mode");
  } else {
    main.classList.remove("guest-mode");
  }
}
