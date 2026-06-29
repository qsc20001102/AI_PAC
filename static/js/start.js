window.addEventListener("resize", () => {
  if (state.trendCache && state.activePage === "overview") drawChart(document.getElementById("overviewChart"), state.trendCache.series, state.trendKeys);
  if (state.historyCache && state.activePage === "trends" && state.historyViewMode === "chart") {
    drawHistoryChart(document.getElementById("historyChart"), state.historyCache);
  }
});

boot().catch((err) => {
  document.getElementById("main").innerHTML = `<div class="panel"><div class="panel-body">系统启动失败：${htmlEscape(err.message)}</div></div>`;
});
