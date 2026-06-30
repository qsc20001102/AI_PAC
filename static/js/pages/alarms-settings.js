async function renderAlarms(main) {
  const rows = await api("/api/alarms?status=all");
  main.innerHTML = `
    <section class="panel alarm-page-panel">
      <div class="panel-header"><div class="panel-title">报警事件</div><button id="ackAllBtn" class="btn ghost" type="button">全部确认</button></div>
      <div class="panel-body alarm-table-body">
        <table class="table">
          <thead><tr><th>级别</th><th>标题</th><th>投加点/类别</th><th>时间</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>${rows.map((a) => `<tr><td><span class="severity-tag severity-${a.severity}">${severityName(a.severity)}</span></td><td>${htmlEscape(a.title)}<div class="muted">${htmlEscape(a.message)}</div></td><td>${htmlEscape(a.dosing_point_name || a.category)}</td><td>${dateMinute(a.event_time)}</td><td>${htmlEscape(a.status)}</td><td>${a.status === "active" ? `<button class="btn ghost" data-ack="${a.id}" type="button">确认</button>` : ""}</td></tr>`).join("")}</tbody>
        </table>
      </div>
    </section>
  `;
  document.getElementById("ackAllBtn").addEventListener("click", ackAll);
  document.querySelectorAll("[data-ack]").forEach((btn) => btn.addEventListener("click", async () => {
    await api(`/api/alarms/${btn.dataset.ack}/ack`, { method: "POST" });
    showToast("报警已确认");
    await refreshAll();
  }));
}

async function ackAll() {
  try {
    await api("/api/alarms/ack-all", { method: "POST" });
    showToast("活动报警已确认");
    await refreshAll();
  } catch (err) {
    showToast(`确认失败：${err.message}`);
  }
}

async function renderSettings(main) {
  const [settings, network] = await Promise.all([
    api("/api/settings"),
    api("/api/settings/network"),
  ]);
  state.settings = settings;
  const lanUrls = network.lan_urls || [];
  main.innerHTML = `
    <section class="panel settings-network-panel">
      <div class="panel-header"><div class="panel-title">访问地址</div></div>
      <div class="panel-body settings-network-body">
        <div class="settings-network-card">
          <div class="kv-label">当前访问</div>
          <div class="settings-url">${htmlEscape(network.current_url || "")}</div>
        </div>
        <div class="settings-network-card">
          <div class="kv-label">外部访问</div>
          <div class="settings-url-list">
            ${lanUrls.length ? lanUrls.map((url) => `<div class="settings-url">${htmlEscape(url)}</div>`).join("") : `<div class="muted">未检测到可用的本机 IPv4 地址</div>`}
          </div>
        </div>
        <div class="settings-network-card">
          <div class="kv-label">监听方式</div>
          <div><code>${htmlEscape(network.bind_host || "0.0.0.0")}:${htmlEscape(String(network.port || 8000))}</code><div class="muted">同一局域网设备可使用上面的 IP 地址加端口访问；如仍无法访问，请检查 Windows 防火墙是否放行该端口。</div></div>
        </div>
      </div>
    </section>
    <section class="panel">
      <div class="panel-header"><div class="panel-title">系统设置</div><button id="backupBtn" class="btn ghost" type="button">立即备份数据库</button></div>
      <div class="panel-body">
        <table class="table">
          <thead><tr><th>键</th><th>值</th><th>更新时间</th><th>操作</th></tr></thead>
          <tbody>${state.settings.map((s) => `<tr><td>${htmlEscape(s.key)}</td><td><input class="setting-input" data-setting="${htmlEscape(s.key)}" value="${htmlEscape(s.value)}"></td><td>${dateMinute(s.updated_at)}</td><td><button class="btn ghost" data-save-setting="${htmlEscape(s.key)}" type="button">保存</button></td></tr>`).join("")}</tbody>
        </table>
      </div>
    </section>
  `;
  document.getElementById("backupBtn").addEventListener("click", async () => {
    const res = await api("/api/backup", { method: "POST" });
    showToast(`备份完成：${res.path}`);
  });
  document.querySelectorAll("[data-save-setting]").forEach((btn) => btn.addEventListener("click", async () => {
    const key = btn.dataset.saveSetting;
    const value = document.querySelector(`[data-setting="${CSS.escape(key)}"]`).value;
    await api(`/api/settings/${encodeURIComponent(key)}`, { method: "PUT", body: JSON.stringify({ value }) });
    showToast("设置已保存");
    await renderPage();
  }));
}
