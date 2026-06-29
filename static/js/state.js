const state = {
  activePage: "overview",
  dashboard: null,
  points: [],
  selectedPointId: 1,
  selectedCollectionGroupId: "public",
  overviewQualityGroupId: "public",
  selectedChemicalGroupId: null,
  selectedProcessParameterGroupId: null,
  editingNewPoint: false,
  trendHours: 3,
  trendCache: null,
  models: [],
  selectedModelId: null,
  editingNewModel: false,
  modelRefreshTimer: null,
  modelSampleStart: null,
  modelSampleEnd: null,
  modelSelectedSampleIds: [],
  settings: [],
  selectedPlcDeviceId: null,
  editingNewPlcDevice: false,
  historySelectedTagIds: [],
  historyViewMode: "chart",
  historyStart: null,
  historyEnd: null,
  historyPurgeDays: 30,
  historyCache: { series: [] },
  historyColors: {},
  historyChartPoints: [],
  overviewChartPoints: [],
  trendKeys: [],
};

const PUBLIC_COLLECTION_GROUP_ID = "public";

const navItems = [
  ["overview", "总览", "i-home"],
  ["process", "工艺配置", "i-gear"],
  ["processParams", "工艺参数", "i-gear"],
  ["chemical", "药剂参数", "i-flask"],
  ["models", "模型管理", "i-cube"],
  ["plc", "PLC通讯", "i-plc"],
  ["data", "数据采集", "i-data"],
  ["trends", "历史数据", "i-chart"],
  ["alarms", "报警事件", "i-bell", "warn"],
  ["settings", "系统设置", "i-gear"],
];

const modeText = {
  normal: "正常",
  conservative: "保守",
  manual: "手动",
  simulation: "模拟",
  stale: "延迟",
  degraded: "降级",
};

const seriesStyle = {
  Q: { color: "#1f66e5", label: "参与流量 (m3/h)" },
  IN_Q: { color: "#2563eb", label: "进水流量 (m3/h)" },
  PO4_P: { color: "#12a9bf", label: "正磷酸盐 (mg/L)" },
  TP_BEFORE: { color: "#7b4dff", label: "进水TP (mg/L)" },
  OUT_Q: { color: "#0f766e", label: "出水流量 (m3/h)" },
  TP_OUT: { color: "#d64545", label: "出水TP (mg/L)" },
  ZONE_Q: { color: "#b21f66", label: "分区流量 (m3/h)" },
  REFLUX_Q1: { color: "#4f6f00", label: "回流流量1 (m3/h)" },
  REFLUX_Q2: { color: "#7c3f00", label: "回流流量2 (m3/h)" },
  PAC_SUGGEST: { color: "#ff8b18", label: "PAC建议 (L/h)" },
  PAC_ACTUAL: { color: "#16a34a", label: "加药流量 (L/h)" },
  PH: { color: "#64748b", label: "pH" },
};

const statusText = {
  fresh: "正常",
  delayed: "延迟",
  stale: "超时",
  bad: "异常",
  manual: "手动",
  unknown: "未读取",
  connected: "已连接",
  disconnected: "未连接",
  error: "异常",
  published: "已发布",
  candidate: "候选",
  shadow: "影子",
  training: "训练中",
  draft: "草稿",
};

function localizedStatus(value) {
  return statusText[value] || modeText[value] || value || "—";
}

const processSourceFields = [
  ["in_flow_tag_id", "进水流量来源"],
  ["in_tp_tag_id", "进水TP来源"],
  ["out_flow_tag_id", "出水流量来源"],
  ["out_tp_tag_id", "出水TP来源"],
  ["zone_flow_tag_id", "分区流量来源"],
  ["reflux_flow_1_tag_id", "回流流量1来源"],
  ["reflux_flow_2_tag_id", "回流流量2来源"],
  ["po4_tag_id", "正磷酸盐来源"],
  ["pac_flow_tag_id", "加药流量来源"],
];
