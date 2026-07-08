// P2-11 修复：原 resize 事件直接调用图表重绘，高频 resize 密集触发导致性能问题。
// 添加 200ms 防抖，仅在 resize 停止后重绘一次。
let _resizeTimer = null;
window.addEventListener("resize", () => {
  if (_resizeTimer) window.clearTimeout(_resizeTimer);
  _resizeTimer = window.setTimeout(() => {
    if (state.trendCache && state.activePage === "overview") drawChart(document.getElementById("overviewChart"), state.trendCache.series, state.trendKeys);
    if (state.historyCache && state.activePage === "trends" && state.historyViewMode === "chart") {
      drawHistoryChart(document.getElementById("historyChart"), state.historyCache);
    }
  }, 200);
});

window.addEventListener("hashchange", async () => {
  const page = window.location.hash.slice(2);
  if (page && ["overview", "process", "processParams", "models", "plc", "data", "trends", "alarms", "settings"].includes(page)) {
    state.activePage = page;
    renderNav();
    await renderPage();
  }
});

boot().catch((err) => {
  document.getElementById("main").innerHTML = `<div class="panel"><div class="panel-body">系统启动失败：${htmlEscape(err.message)}</div></div>`;
});
