// 协议参数配置定义
const PROTOCOL_CONFIGS = {
  s7_1500: {
    label: "S7-1500",
    defaultPort: 102,
    params: [
      { name: "rack", label: "Rack", type: "number", default: 0 },
      { name: "slot", label: "Slot", type: "number", default: 0 },
    ],
    hint: "S7-1500 通过 S7comm/PUT-GET 读 DB 数据，PLC 侧需允许 PUT/GET 通讯。",
  },
  modbus_tcp: {
    label: "Modbus TCP",
    defaultPort: 502,
    params: [
      { name: "unit_id", label: "站号 (Unit ID)", type: "number", default: 1 },
      {
        name: "byte_order",
        label: "字节序/高低位",
        type: "select",
        options: [
          { value: "ABCD", label: "ABCD (大端)" },
          { value: "DCBA", label: "DCBA (小端)" },
          { value: "BADC", label: "BADC" },
          { value: "CDAB", label: "CDAB" },
        ],
        default: "ABCD",
      },
    ],
    hint: "Modbus TCP 通过 TCP 端口 502 通信。地址格式：40001~4xxxx(保持寄存器)、30001~3xxxx(输入寄存器)、00001~0xxxx(线圈)、10001~1xxxx(离散输入)。也可使用简写 H1000、I1000、C1000、D1000。",
  },
};

function plcProtocolLabel(protocol) {
  const config = PROTOCOL_CONFIGS[protocol];
  return config ? config.label : protocol;
}

function plcStatusLabel(status) {
  if (status === "connected") return "已连接";
  if (status === "error") return "连接失败";
  return "未连接";
}

function plcStatusClass(status) {
  if (status === "connected") return "fresh";
  if (status === "error") return "bad";
  return "manual";
}

function defaultPlcDevice(protocol = "s7_1500", index = 1) {
  const config = PROTOCOL_CONFIGS[protocol];
  const device = {
    name: `${config.label} 设备${index}`,
    protocol: protocol,
    ip_address: "192.168.1.10",
    port: config.defaultPort,
    timeout_ms: 5000,
    pdu_length: null,
    status: "disconnected",
    enabled: true,
    reconnect_enabled: false,
    reconnect_interval_seconds: 10,
  };
  // 根据协议添加特有参数的默认值
  for (const param of config.params) {
    device[param.name] = param.default;
  }
  return device;
}

function selectedPlcDevice(devices) {
  if (state.editingNewPlcDevice) {
    // 新建设备时，使用当前选中的协议（从state中获取，如果没有则默认s7_1500）
    const protocol = state.newPlcDeviceProtocol || "s7_1500";
    return defaultPlcDevice(protocol, devices.length + 1);
  }
  if (!devices.length) return null;
  const selected = devices.find((device) => device.id === state.selectedPlcDeviceId) || devices[0];
  state.selectedPlcDeviceId = selected.id;
  return selected;
}

function plcDevicePayload(form) {
  const payload = formObject(form);
  payload.name = String(payload.name || "").trim();
  payload.protocol = String(payload.protocol || "s7_1500");
  payload.ip_address = String(payload.ip_address || "").trim();
  payload.port = Number(payload.port || PROTOCOL_CONFIGS[payload.protocol].defaultPort);
  payload.timeout_ms = Number(payload.timeout_ms || 5000);
  payload.enabled = payload.enabled === true || payload.enabled === "true";
  payload.reconnect_enabled = payload.reconnect_enabled === true || payload.reconnect_enabled === "true";
  payload.reconnect_interval_seconds = Number(payload.reconnect_interval_seconds || 10);

  // 根据协议类型处理特有参数
  const config = PROTOCOL_CONFIGS[payload.protocol];
  if (payload.protocol === "s7_1500") {
    payload.rack = Number(payload.rack || 0);
    payload.slot = Number(payload.slot || 0);
    payload.unit_id = undefined; // S7-1500 不需要unit_id
    payload.byte_order = undefined; // S7-1500 不需要byte_order
  } else if (payload.protocol === "modbus_tcp") {
    payload.rack = undefined;
    payload.slot = undefined;
    payload.unit_id = Number(payload.unit_id || 1);
    payload.byte_order = String(payload.byte_order || "ABCD");
  }

  return payload;
}

async function renderPlc(main) {
  const data = await api("/api/plc");
  const devices = data.devices || [];
  const events = data.events || [];
  const protocols = data.supported_protocols || [{ value: "s7_1500", label: "S7-1500" }];
  const device = selectedPlcDevice(devices);
  const isNew = state.editingNewPlcDevice;
  const deviceRows = devices.length ? devices.map((item) => `
    <div class="list-card plc-device-card ${!state.editingNewPlcDevice && item.id === state.selectedPlcDeviceId ? "active" : ""}" data-plc-device-select="${item.id}">
      <div class="plc-card-name">${htmlEscape(item.name)}</div>
      <div class="plc-card-meta">
        <span>${htmlEscape(item.ip_address)}</span>
        <span>${plcProtocolLabel(item.protocol)}</span>
        <span class="status-tag status-${plcStatusClass(item.status)}">${plcStatusLabel(item.status)}</span>
      </div>
    </div>
  `).join("") : `<div class="empty">还没有 PLC 设备，右侧创建第一台 PLC 设备。</div>`;

  // 根据当前协议动态生成参数字段
  const protocol = device ? device.protocol : (state.newPlcDeviceProtocol || "s7_1500");
  const config = PROTOCOL_CONFIGS[protocol];

  // 动态参数区域HTML
  const protocolParamsHtml = config.params.map((param) => {
    if (param.type === "select") {
      return selectField(param.name, param.label, param.options, device ? device[param.name] : param.default);
    } else {
      return field(param.name, param.label, device ? device[param.name] : param.default, param.type);
    }
  }).join("");

  const protocolHint = config.hint;

  main.innerHTML = `
    <section class="page-grid plc-page-grid">
      <aside class="panel">
        <div class="panel-header">
          <div class="panel-title">PLC 设备</div>
          <button id="newPlcDeviceBtn" class="btn ghost" type="button">新增</button>
        </div>
        <div class="panel-body"><div class="plc-device-list">${deviceRows}</div></div>
      </aside>
      <div class="plc-right-stack">
      ${device ? `<article class="panel plc-config-panel">
        <div class="panel-header">
          <div class="panel-title">${isNew ? "新增 PLC 设备" : "PLC 设备配置"}</div>
          ${isNew ? "" : `<button id="deletePlcDeviceBtn" class="btn" type="button">删除设备</button>`}
        </div>
        <div class="panel-body">
          <form id="plcDeviceForm">
            <div class="form-grid">
              ${field("name", "设备名称", device.name, "text")}
              ${selectField("protocol", "协议", protocols, protocol)}
              ${field("ip_address", "IP 地址", device.ip_address, "text")}
              ${field("port", "端口号", device.port ?? config.defaultPort)}
              ${field("timeout_ms", "接收超时 ms", device.timeout_ms ?? 5000)}
              ${protocolParamsHtml}
              ${selectField("enabled", "启用状态", [{ value: "true", label: "启用" }, { value: "false", label: "停用" }], String(Boolean(device.enabled)))}
              ${selectField("reconnect_enabled", "断线重连", [{ value: "true", label: "开启" }, { value: "false", label: "关闭" }], String(Boolean(device.reconnect_enabled)))}
              ${field("reconnect_interval_seconds", "重连间隔 (秒)", device.reconnect_interval_seconds ?? 10)}
            </div>
            <div class="kv" style="margin-top:16px">
              <div class="kv-label">连接状态</div><div><span class="status-tag status-${plcStatusClass(device.status)}">${plcStatusLabel(device.status)}</span></div>
              <div class="kv-label">PDU</div><div>${device.pdu_length ? `${device.pdu_length} bytes` : "连接成功后自动获取"}</div>
              <div class="kv-label">最后连接</div><div>${dateMinute(device.last_connected_at)}</div>
              <div class="kv-label">最后断开</div><div>${dateMinute(device.last_disconnected_at)}</div>
              <div class="kv-label">错误信息</div><div>${htmlEscape(device.last_error || "无")}</div>
            </div>
            <div class="btn-row">
              <button class="btn primary" type="submit">${icon("i-save")}${isNew ? "创建设备" : "保存配置"}</button>
              ${isNew ? `<button id="cancelNewPlcDeviceBtn" class="btn" type="button">取消</button>` : `
                <button id="connectPlcDeviceBtn" class="btn ghost" type="button" ${device.status === "connected" ? "disabled" : ""}>${icon("i-plc")}连接</button>
                <button id="disconnectPlcDeviceBtn" class="btn" type="button" ${device.status !== "connected" ? "disabled" : ""}>断开</button>
              `}
              <span class="muted">${protocolHint}</span>
            </div>
          </form>
        </div>
      </article>` : `<article class="panel plc-config-panel"><div class="panel-header"><div class="panel-title">PLC 设备配置</div></div><div class="panel-body"><div class="empty">点击左侧"新增"创建第一台 PLC 设备。</div></div></article>`}
      <section class="panel plc-events-panel">
      <div class="panel-header"><div class="panel-title">连接事件</div></div>
      <div class="panel-body plc-events-body">
        <table class="table">
          <thead><tr><th>时间</th><th>设备</th><th>事件</th><th>状态</th><th>PDU</th><th>信息</th></tr></thead>
          <tbody>${events.length ? events.map((event) => `
            <tr>
              <td>${dateMinute(event.created_at)}</td>
              <td>${htmlEscape(event.device_name)}</td>
              <td>${htmlEscape(event.event_type)}</td>
              <td><span class="status-tag status-${plcStatusClass(event.status)}">${plcStatusLabel(event.status)}</span></td>
              <td>${event.pdu_length || "—"}</td>
              <td>${htmlEscape(event.message || "")}</td>
            </tr>
          `).join("") : `<tr><td colspan="6" class="muted">暂无事件</td></tr>`}</tbody>
        </table>
      </div>
    </section>
      </div>
    </section>
  `;

  document.getElementById("newPlcDeviceBtn").addEventListener("click", async () => {
    state.editingNewPlcDevice = true;
    state.newPlcDeviceProtocol = "s7_1500"; // 新建时默认S7-1500协议
    await renderPage();
  });
  document.getElementById("cancelNewPlcDeviceBtn")?.addEventListener("click", async () => {
    state.editingNewPlcDevice = false;
    state.newPlcDeviceProtocol = undefined;
    await renderPage();
  });
  document.querySelectorAll("[data-plc-device-select]").forEach((node) => node.addEventListener("click", async () => {
    state.selectedPlcDeviceId = Number(node.dataset.plcDeviceSelect);
    state.editingNewPlcDevice = false;
    state.newPlcDeviceProtocol = undefined;
    await renderPage();
  }));

  // 协议选择下拉框onchange事件：切换协议后重新渲染表单
  const protocolSelect = document.querySelector("select[name='protocol']");
  if (protocolSelect) {
    protocolSelect.addEventListener("change", async (event) => {
      const newProtocol = event.target.value;
      state.newPlcDeviceProtocol = newProtocol;
      // 如果是新建设备，需要更新端口号默认值
      if (isNew) {
        await renderPage();
      }
    });
  }

  document.getElementById("plcDeviceForm")?.addEventListener("submit", (event) => savePlcDevice(event, isNew, device.id));
  document.getElementById("deletePlcDeviceBtn")?.addEventListener("click", () => deletePlcDevice(device.id, device.name));
  document.getElementById("connectPlcDeviceBtn")?.addEventListener("click", () => connectPlcDevice(device.id));
  document.getElementById("disconnectPlcDeviceBtn")?.addEventListener("click", () => disconnectPlcDevice(device.id));
}

async function savePlcDevice(event, isNew, deviceId) {
  event.preventDefault();
  const payload = plcDevicePayload(event.currentTarget);
  try {
    if (isNew) {
      const res = await api("/api/plc/devices", { method: "POST", body: JSON.stringify(payload) });
      state.selectedPlcDeviceId = res.device.id;
      state.editingNewPlcDevice = false;
      state.newPlcDeviceProtocol = undefined;
      showToast("PLC 设备已创建并写入数据库");
    } else {
      await api(`/api/plc/devices/${deviceId}`, { method: "PUT", body: JSON.stringify(payload) });
      showToast("PLC 设备配置已保存");
    }
    await refreshAll();
  } catch (err) {
    showToast(`保存失败：${err.message}`);
  }
}

async function deletePlcDevice(deviceId, name) {
  if (!window.confirm(`确认删除「${name}」？该设备的连接事件会同步清理。`)) return;
  try {
    await api(`/api/plc/devices/${deviceId}`, { method: "DELETE" });
    state.selectedPlcDeviceId = null;
    state.editingNewPlcDevice = false;
    state.newPlcDeviceProtocol = undefined;
    showToast("PLC 设备已删除");
    await refreshAll();
  } catch (err) {
    showToast(`删除失败：${err.message}`);
  }
}

async function connectPlcDevice(deviceId) {
  try {
    const res = await api(`/api/plc/devices/${deviceId}/connect`, { method: "POST" });
    showToast(res.ok ? "PLC 已连接，PDU 已更新" : `连接失败：${res.message}`);
    await refreshAll();
  } catch (err) {
    showToast(`连接失败：${err.message}`);
  }
}

async function disconnectPlcDevice(deviceId) {
  try {
    const res = await api(`/api/plc/devices/${deviceId}/disconnect`, { method: "POST" });
    showToast(res.message);
    await refreshAll();
  } catch (err) {
    showToast(`断开失败：${err.message}`);
  }
}