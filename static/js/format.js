function icon(id) {
  return `<svg aria-hidden="true"><use href="#${id}"></use></svg>`;
}

function fmt(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return Number(value).toLocaleString("zh-CN", { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

function fmtCompact(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return Number(value).toLocaleString("zh-CN", { maximumFractionDigits: digits });
}

function htmlEscape(value) {
  // P2-15 修复：补充单引号转义，防止在单引号属性上下文中产生 XSS
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function pad2(value) {
  return String(value).padStart(2, "0");
}

function dateMinute(value) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}

function dateSecond(value) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
}

function showToast(message) {
  const node = document.getElementById("toast");
  node.textContent = message;
  node.classList.add("show");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => node.classList.remove("show"), 2600);
}

// P2-6 修复：overview.js 的 drawChart/drawSavingsChart 与 data.js 的 drawHistoryChart
// 的 Canvas DPR 设置代码块完全重复，抽取公共函数。
function setupChartCanvas(canvas, opts) {
  const { minW = 1, minH = 1, round = true } = opts || {};
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const rawW = rect.width * dpr;
  const rawH = rect.height * dpr;
  canvas.width = round ? Math.max(minW, Math.round(rawW)) : Math.max(minW, rawW);
  canvas.height = round ? Math.max(minH, Math.round(rawH)) : Math.max(minH, rawH);
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  const w = canvas.width / dpr;
  const h = canvas.height / dpr;
  ctx.clearRect(0, 0, w, h);
  return { ctx, w, h };
}

// P2-6 修复：overview.js wireChartTooltip 与 data.js wireHistoryTooltip 逻辑几乎一致，
// 抽取公共函数，通过 labelFor 回调适配不同的标签来源。
function wireChartTooltip(canvas, tooltipId, chartPoints, labelFor) {
  const tooltip = document.getElementById(tooltipId);
  if (!canvas || !tooltip) return;
  canvas.onmousemove = (event) => {
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    let nearest = null;
    let best = 13;
    chartPoints.forEach((point) => {
      const distance = Math.hypot(point.x - x, point.y - y);
      if (distance < best) {
        best = distance;
        nearest = point;
      }
    });
    if (!nearest) {
      tooltip.classList.remove("show");
      return;
    }
    const label = labelFor ? labelFor(nearest) : (nearest.label || nearest.key || nearest.tag || "");
    tooltip.innerHTML = `<b>${htmlEscape(label)}</b><br>${dateMinute(nearest.time)}<br>${fmtCompact(nearest.value, 4)}`;
    tooltip.style.left = `${Math.min(x + 12, rect.width - 170)}px`;
    tooltip.style.top = `${Math.max(y - 62, 6)}px`;
    tooltip.classList.add("show");
  };
  canvas.onmouseleave = () => tooltip.classList.remove("show");
}
