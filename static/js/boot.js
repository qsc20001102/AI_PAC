async function boot() {
  renderNav();
  tickClock();
  window.setInterval(tickClock, 1000);
  await refreshAll();
  window.setInterval(refreshDashboardOnly, 30000);
  window.setInterval(refreshCollectionRealtime, 2000);
}

async function refreshAll() {
  const [dashboard, points] = await Promise.all([api("/api/dashboard"), api("/api/dosing-points")]);
  state.dashboard = dashboard;
  state.points = points;
  if ((!state.selectedPointId || !points.some((p) => p.id === state.selectedPointId)) && points[0]) {
    state.selectedPointId = points[0].id;
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

function renderNav() {
  document.getElementById("nav").innerHTML = navItems.map(([id, label, ico, extra]) => `
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

async function renderPage() {
  if (state.modelRefreshTimer) {
    window.clearTimeout(state.modelRefreshTimer);
    state.modelRefreshTimer = null;
  }
  const main = document.getElementById("main");
  if (!state.dashboard || !state.points.length) {
    main.innerHTML = `<div class="empty">正在加载系统数据</div>`;
    return;
  }
  if (state.activePage === "overview") return renderOverview(main);
  if (state.activePage === "process") return renderProcess(main);
  if (state.activePage === "processParams") return renderProcessParams(main);
  if (state.activePage === "data") return renderData(main);
  if (state.activePage === "trends") return renderTrends(main);
  if (state.activePage === "models") return renderModels(main);
  if (state.activePage === "plc") return renderPlc(main);
  if (state.activePage === "alarms") return renderAlarms(main);
  if (state.activePage === "settings") return renderSettings(main);
  state.activePage = "overview";
  renderNav();
  return renderOverview(main);
}
