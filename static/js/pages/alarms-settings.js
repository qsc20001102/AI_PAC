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
  const configuredPort = network.configured_port || network.port || 8000;
  const currentPort = network.current_port || configuredPort;
  const systemSettings = state.settings.filter((item) => item.key !== "listen_port");
  main.innerHTML = `
    <section class="panel settings-network-panel">
      <div class="panel-header"><div class="panel-title">访问地址</div></div>
      <div class="panel-body settings-network-body">
        <div class="settings-network-card">
          <div class="kv-label">本机访问</div>
          <div id="configuredCurrentUrl" class="settings-url"></div>
          <div class="muted">按 Web端口配置生成。</div>
        </div>
        <div class="settings-network-card">
          <div class="kv-label">外部访问</div>
          <div id="configuredLanUrls" class="settings-url-list"></div>
        </div>
        <div class="settings-network-card">
          <div class="kv-label">Web端口</div>
          <div>
            <div class="settings-port-row">
              <input id="listenPortInput" class="setting-input settings-port-input" type="number" min="1" max="65535" step="1" value="${htmlEscape(configuredPort)}">
              <button id="saveListenPortBtn" class="btn ghost" type="button">保存端口</button>
            </div>
            <div class="muted">项目 Web 服务监听端口，修改后需要重启服务生效。</div>
            <div id="portStatusText" class="muted"></div>
            <div id="restartStatusText"></div>
          </div>
        </div>
        <div class="settings-network-card">
          <div class="kv-label">启动命令</div>
          <div>
            <code>${htmlEscape(network.recommended_command || "python run_server.py")}</code>
            <div class="muted">也可使用：<code id="uvicornCommand"></code></div>
          </div>
        </div>
      </div>
    </section>
    <section class="panel">
      <div class="panel-header"><div class="panel-title">系统设置</div><button id="backupBtn" class="btn ghost" type="button">立即备份数据库</button></div>
      <div class="panel-body">
        <table class="table">
          <thead><tr><th>参数</th><th>中文说明</th><th>值</th><th>更新时间</th><th>操作</th></tr></thead>
          <tbody>${systemSettings.length ? systemSettings.map(renderSettingRow).join("") : `<tr><td colspan="5" class="empty">暂无其他可配置参数</td></tr>`}</tbody>
        </table>
      </div>
    </section>
    <section class="panel" id="passwordPanel">
      <div class="panel-header"><div class="panel-title">修改密码</div></div>
      <div class="panel-body">
        <form id="passwordForm" class="form">
          <div class="field"><label>旧密码</label><input type="password" id="oldPassword" required></div>
          <div class="field"><label>新密码</label><input type="password" id="newPassword" required minlength="6"></div>
          <div class="field"><label>确认新密码</label><input type="password" id="confirmPassword" required minlength="6"></div>
          <div class="actions"><button class="btn primary" type="submit">修改密码</button></div>
        </form>
      </div>
    </section>
  `;
  updateNetworkPreview(network);
  document.getElementById("backupBtn").addEventListener("click", async () => {
    const res = await api("/api/backup", { method: "POST" });
    showToast(`备份完成：${res.path}`);
  });
  document.getElementById("saveListenPortBtn")?.addEventListener("click", saveListenPort);
  document.getElementById("listenPortInput")?.addEventListener("input", () => updateNetworkPreview(network));
  document.querySelectorAll("[data-save-setting]").forEach((btn) => btn.addEventListener("click", async () => {
    const key = btn.dataset.saveSetting;
    const value = document.querySelector(`[data-setting="${CSS.escape(key)}"]`).value;
    await api(`/api/settings/${encodeURIComponent(key)}`, { method: "PUT", body: JSON.stringify({ value }) });
    showToast("设置已保存");
    await renderPage();
  }));
  document.getElementById("passwordForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const oldPassword = document.getElementById("oldPassword").value;
    const newPassword = document.getElementById("newPassword").value;
    const confirmPassword = document.getElementById("confirmPassword").value;
    if (newPassword !== confirmPassword) {
      showToast("两次输入的新密码不一致");
      return;
    }
    try {
      const res = await api("/api/auth/password", { method: "PUT", body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }) });
      if (res.ok) {
        showToast("密码修改成功，请重新登录");
        localStorage.removeItem("token");
        state.user = null;
        renderUserArea();
        renderNav();
        await renderPage();
      } else {
        showToast(res.detail || "密码修改失败");
      }
    } catch (err) {
      showToast(`密码修改失败：${err.message}`);
    }
  });
}

function renderSettingRow(s) {
  const input = s.value_type === "boolean"
    ? `<select class="setting-input" data-setting="${htmlEscape(s.key)}">
        <option value="true" ${String(s.value).toLowerCase() === "true" ? "selected" : ""}>开启</option>
        <option value="false" ${String(s.value).toLowerCase() === "false" ? "selected" : ""}>关闭</option>
      </select>`
    : `<input class="setting-input" data-setting="${htmlEscape(s.key)}" value="${htmlEscape(s.value)}">`;
  return `<tr>
    <td>${htmlEscape(s.label || s.key)}</td>
    <td class="muted">${htmlEscape(s.description || "")}</td>
    <td>${input}</td>
    <td>${dateMinute(s.updated_at)}</td>
    <td><button class="btn ghost" data-save-setting="${htmlEscape(s.key)}" type="button">保存</button></td>
  </tr>`;
}

function updateNetworkPreview(network) {
  const portText = String(document.getElementById("listenPortInput")?.value || network.configured_port || network.port || 8000).trim();
  const port = Number(portText);
  const validPort = Number.isInteger(port) && port >= 1 && port <= 65535 ? port : (network.configured_port || network.port || 8000);
  const scheme = network.scheme || "http";
  const hostname = network.hostname || "127.0.0.1";
  const ips = network.local_ips || [];
  const currentPort = network.current_port || validPort;
  const configuredCurrentUrl = `${scheme}://${hostname}:${validPort}`;
  const configuredLanUrls = ips.map((ip) => `${scheme}://${ip}:${validPort}/`);
  const restartRequired = validPort !== currentPort;
  const currentNode = document.getElementById("configuredCurrentUrl");
  const lanNode = document.getElementById("configuredLanUrls");
  const portStatusNode = document.getElementById("portStatusText");
  const restartNode = document.getElementById("restartStatusText");
  const commandNode = document.getElementById("uvicornCommand");
  if (currentNode) currentNode.textContent = configuredCurrentUrl;
  if (lanNode) {
    lanNode.innerHTML = configuredLanUrls.length
      ? configuredLanUrls.map((url) => `<div class="settings-url">${htmlEscape(url)}</div>`).join("")
      : `<div class="muted">未检测到可用的本机 IPv4 地址</div>`;
  }
  if (portStatusNode) portStatusNode.textContent = `当前运行端口：${currentPort}；Web端口配置：${validPort}。`;
  if (restartNode) {
    restartNode.className = restartRequired ? "error-text" : "muted";
    restartNode.textContent = restartRequired ? "当前服务尚未运行在 Web端口配置上，请重启后访问。" : "当前服务已运行在 Web端口配置上。";
  }
  if (commandNode) commandNode.textContent = `python -m uvicorn app.main:app --host 0.0.0.0 --port ${validPort}`;
}

async function saveListenPort() {
  const value = String(document.getElementById("listenPortInput")?.value || "").trim();
  try {
    await api("/api/settings/listen_port", { method: "PUT", body: JSON.stringify({ value }) });
    showToast("监听端口已保存，重启服务后生效");
    await renderPage();
  } catch (err) {
    showToast(`保存失败：${err.message}`);
  }
}
