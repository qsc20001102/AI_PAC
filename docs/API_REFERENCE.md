# AI PAC 智能除磷加药系统 — API 参考

> 全部路由前缀为 `/api`，以下表格中路径均省略该前缀。
> 服务器默认监听地址与端口见系统设置中的 `network` 模块。
> 认证通过 `X-Token` header 携带 session token，有效期 7 天。

---

## 目录

1. [health — 健康检查](#1-health--健康检查)
2. [auth — 认证](#2-auth--认证)
3. [alarms — 告警](#3-alarms--告警)
4. [process_groups — 工艺线与参数组](#4-process_groups--工艺线与参数组)
5. [settings — 系统设置](#5-settings--系统设置)
6. [models — 模型管理](#6-models--模型管理)
7. [dashboard — 仪表盘](#7-dashboard--仪表盘)
8. [dosing_points — 投加点](#8-dosing_points--投加点)
9. [plc — PLC 设备](#9-plc--plc-设备)
10. [collection — 数据采集与历史](#10-collection--数据采集与历史)
11. [ingest — 数据导入](#11-ingest--数据导入)
12. [trends — 趋势分析](#12-trends--趋势分析)

---

## 1. health — 健康检查

| 方法 | 路径 | 说明 | 查询参数 / 请求体 | 返回值 |
|------|------|------|-------------------|--------|
| GET | `/api/health` | 健康检查 | — | `{ "ok": true, "journal_mode": "wal", "dosing_points": N, "time": "2026-07-09T14:30:00" }` |
| GET | `/api/backend/status` | 后端状态（数据库文件名、各表记录数、数据源状态、最新样本） | — | 包含 `database`(file_name/journal_mode/exists)、`table_counts`、`data_sources`、`latest_samples`、`server_time` 的状态对象 |

---

## 2. auth — 认证

| 方法 | 路径 | 说明 | 请求体 | 返回值 |
|------|------|------|--------|--------|
| POST | `/api/auth/login` | 用户登录 | `{ "username": "emen", "password": "emen@1234" }` | `{ "ok": true, "user": { "id": 1, "username": "emen", "role": "admin" }, "token": "<session_token>" }` |
| GET | `/api/auth/me` | 获取当前用户（需 `X-Token` header） | — | `{ "authenticated": true, "user": { "id": 1, "username": "emen", "role": "admin" } }` 或 `{ "authenticated": false, "role": "guest" }` |
| POST | `/api/auth/logout` | 退出登录（需 `X-Token` header） | — | `{ "ok": true }` |
| PUT | `/api/auth/password` | 修改密码（需 `X-Token` header） | `{ "old_password": "...", "new_password": "..." }` | `{ "ok": true }` 或 `401`/`400` |

**说明**：
- 登录成功后返回随机 session token（`secrets.token_urlsafe(32)`），前端存入 `localStorage`
- token 有效期 7 天，存入 `user_sessions` 表
- 验证 token 时从 `request.headers` 读取 `x-token` / `X-Token`
- 修改密码后自动清除该用户所有 session，需重新登录
- 密码存储使用 PBKDF2-HMAC-SHA256 + 随机 salt，100000 轮迭代，纯 Python 标准库实现

---

## 3. alarms — 告警

| 方法 | 路径 | 说明 | 查询参数 / 请求体 | 返回值 |
|------|------|------|-------------------|--------|
| GET | `/api/alarms` | 告警列表 | `status`（默认 `active`）、`severity`（可选 `high`/`medium`/`low`）、`limit`（默认 `20`） | 告警数组，每条含 `id`、`severity`、`title`、`category`、`message`、`dosing_point_id`、`dosing_point_name`、`status`、`event_time`、`acknowledged_at`、`acknowledged_by` |
| POST | `/api/alarms/{alarm_id}/ack` | 确认单条告警 | — | 已确认的告警对象 |
| POST | `/api/alarms/ack-all` | 确认全部活动告警 | — | `{ "ok": true, "updated": N }` |

**自动告警逻辑**：
- `severity=high` 条件：关键实时数据（出水TP/参考流量）异常、保守模式下出水TP高于上限
- 条件恢复时自动清除（`status` → `cleared`）
- 通过 `upsert_alarm`/`clear_alarm` 实现去重

---

## 4. process_groups — 工艺线与参数组

| 方法 | 路径 | 说明 | 查询参数 / 请求体 | 返回值 |
|------|------|------|-------------------|--------|
| GET | `/api/process-lines` | 工艺线列表 | — | 工艺线数组，每条含 `id`、`area_id`、`name`、`line_code`、`design_flow_m3_h` |
| GET | `/api/process-parameter-groups` | 工艺参数组列表 | — | 参数组数组 |
| POST | `/api/process-parameter-groups` | 创建工艺参数组 | 请求体：`name`(必填唯一)、`tp_target_mg_l`、`tp_limit_mg_l`、`tp_upper_mg_l`(默认0.3)、`pac_min_l_h`、`pac_max_l_h`、`pac_density_kg_l`(默认1.2)、`unit_dose_curve_json`、`calculation_interval_seconds`(默认60)、`tp_forecast_coefficient`(默认1.0)、`pac_flow_coefficient`(默认1.0) 等 | 新创建的参数组对象 |
| PUT | `/api/process-parameter-groups/{group_id}` | 更新工艺参数组 | 请求体：需要更新的字段 | 更新后的参数组对象 |
| DELETE | `/api/process-parameter-groups/{group_id}` | 删除工艺参数组 | — | 操作结果 |

**工艺参数组关键字段**：
- `tp_target_mg_l`：目标出水TP
- `tp_upper_mg_l`：出水TP上限（高于此值紧急处理）
- `pac_min_l_h`/`pac_max_l_h`：PAC 加药流量限幅范围
- `unit_dose_curve_json`：单耗曲线（至少 2 个关键点的 JSON 数组）
- `pac_density_kg_l`：药剂密度
- `calculation_interval_seconds`：推荐计算周期（默认 60 秒）
- `tp_forecast_coefficient`：TP 预测修正系数（默认 1.0）
- `pac_flow_coefficient`：PAC 流量修正系数（默认 1.0）

---

## 5. settings — 系统设置

| 方法 | 路径 | 说明 | 查询参数 / 请求体 | 返回值 |
|------|------|------|-------------------|--------|
| GET | `/api/settings` | 获取全部设置 | — | 键值对对象，包含所有系统配置项（`listen_port`、`plc_auto_connect_enabled` 等） |
| GET | `/api/settings/network` | 获取网络信息 | — | `{ "listen_address": "0.0.0.0", "port": 8000, "local_ipv4": ["192.168.1.100", ...] }` |
| PUT | `/api/settings/{key}` | 更新单个设置项 | `{ "value": ... }` | 更新后的设置项 |
| POST | `/api/backup` | 触发数据库备份 | — | `{ "ok": true, "path": "backup/ai_pac_20260709_143000.sqlite" }` |
| GET | `/api/export/recommendations.csv` | 导出建议记录为 CSV | — | CSV 文件（Content-Type: `text/csv`） |

---

## 6. models — 模型管理

### 双任务模型（`ai_pac_dual_task`）

当前唯一支持的模型类型，同时训练两个 LightGBM 回归模型：
- **任务1**：PAC 加药量预测（target = `pac_dosage`）
- **任务2**：出水TP变化量预测（target = `tp_delta` = 未来TP - 当前TP）

旧单任务模型（`tp_out_response`、`pac_flow_predict`）已标记 DEPRECATED，保留兼容。

### 端点列表

| 方法 | 路径 | 说明 | 查询参数 / 请求体 | 返回值 |
|------|------|------|-------------------|--------|
| GET | `/api/models` | 模型列表 | — | 模型数组，每条含 `id`、`name`、`model_kind`、`status`、`dosing_point_id`、`trained_at`、`published_at` 等 |
| POST | `/api/models` | 创建模型项目（draft 状态） | `{ "name": "...", "model_kind": "ai_pac_dual_task", "dosing_point_id": 1, "training_config": {...} }` | 新创建的模型对象 |
| GET | `/api/models/{model_id}` | 获取模型详情 | — | 完整模型信息（含 `training_config_json`、`metrics_json`、`artifact_json`、样本数等） |
| PUT | `/api/models/{model_id}` | 更新模型配置 | `{ "name": "...", "training_config": {...} }` | 更新后的模型对象 |
| DELETE | `/api/models/{model_id}` | 删除模型 | — | 操作结果 |
| DELETE | `/api/models/{model_id}/samples/{sample_id}` | 删除单条训练样本 | — | 操作结果 |
| POST | `/api/models/{model_id}/samples/bulk-delete` | 批量删除训练样本 | `{ "sample_ids": [1, 2, 3] }` | `{ "ok": true, "deleted": 3 }` |
| DELETE | `/api/models/{model_id}/samples` | 清空所有训练样本 | — | 操作结果 |
| POST | `/api/models/{model_id}/samples/record` | 手动记录当前实时样本 | — | `{ "ok": true, "sample_id": 42 }` |
| POST | `/api/models/{model_id}/recording/start` | 开启实时记录 | `{ "interval_minutes": 5 }` | 操作结果 |
| POST | `/api/models/{model_id}/recording/stop` | 停止实时记录 | — | 操作结果 |
| POST | `/api/models/{model_id}/samples/import` | 导入 CSV 训练样本 | 请求体：`{ "csv_text": "...列名见下...", "encoding": "utf-8-sig" }` 或 `{ "csv_base64": "..." }` | `{ "ok": true, "imported": N }` |
| GET | `/api/models/{model_id}/samples.csv` | 导出训练样本为 CSV | — | CSV 文件（Content-Type: `text/csv`） |
| GET | `/api/models/{model_id}/features.csv` | 导出双任务模型处理后的特征 ZIP | — | ZIP 文件（内含 task1_features.csv + task2_features.csv + labels.csv） |
| POST | `/api/models/{model_id}/train` | 触发模型训练 | — | `{ "ok": true, "status": "success", "metrics": {...}, "sample_count": N }` |
| POST | `/api/models/{model_id}/deploy` | 投用/停用模型 | `{ "enabled": true/false, "actor": "emen" }` | 部署结果 |
| GET | `/api/models/{model_id}/artifact` | 下载模型 artifact JSON | — | JSON 文件（Content-Type: `application/json`） |

### CSV 样本导入格式

CSV 必须包含以下列（支持 `utf-8-sig`、`utf-8`、`gb18030`、`gbk` 编码）：

```text
sample_time,inflow_flow,inflow_tp,inflow_ph,outflow_tp,high_density_a1_return,high_density_a2_return,orp_east_1,orp_east_2,orp_west_1,orp_west_2,mlss_east,mlss_west,pac_dosage
2026-05-20 00:00:00,1234.5,3.21,7.12,0.35,200.0,180.0,-85.0,-90.0,-78.0,-82.0,3500.0,3200.0,95.0
```

也支持中英文混合列名自动映射：
- `进水流量` → `inflow_flow`
- `进水TP` → `inflow_tp`
- `出水TP` → `outflow_tp`
- `PAC1加药流量过程值` → `pac_dosage`

时间格式支持：
- `2026/5/20  0:00:00`
- `2026/5/20 0:00`
- `2026/5/20`
- `2026-05-20 00:00:00`
- `2026-05-20T00:00:00`

### 模型生命周期

```
draft → recording(实时记录中) → trained(训练完成, ready) → published(已投用) → archived(已归档)
                                                                         ↓ (停用)
                                                                    draft
```

投用同一投加点的新模型会将旧投用模型自动置为 `draft` 状态。

---

## 7. dashboard — 仪表盘

| 方法 | 路径 | 说明 | 查询参数 / 请求体 | 返回值 |
|------|------|------|-------------------|--------|
| GET | `/api/dashboard` | 仪表盘数据聚合（60 秒 TTL 缓存） | — | `{ "recommendations": [...], "alarms": [...], "plc": [...], "training_models": [...], "data_quality": [...], "server_time": "..." }` |

**`recommendations` 数组每项结构**：
```json
{
  "dosing_point_name": "PAC1",
  "mode": "dual_task_ai",
  "base_l_h": 80.5,
  "raw_l_h": 95.2,
  "limited_l_h": 95.2,
  "final_l_h": 95.2,
  "quality": "good",
  "reasons": ["..."],
  "tp_forecast": {
    "model_id": 1,
    "model_name": "双任务模型v2",
    "predicted_tp_out": 0.298,
    "target_label": "下次出水TP预测",
    "detail": { "pac_dosage_prediction": 95.2, "next_outflow_tp_prediction": 0.298, ... }
  }
}
```

---

## 8. dosing_points — 投加点

| 方法 | 路径 | 说明 | 查询参数 / 请求体 | 返回值 |
|------|------|------|-------------------|--------|
| GET | `/api/dosing-points` | 投加点列表 | — | 投加点数组，每条含 `id`、`name`、`code`、`enabled`、`flow_source`、`process_line_id`、关联 tag_id 字段、`tp_model_id`、`pac_flow_model_id`、`dual_model_id`、`process_parameter_group_id` |
| POST | `/api/dosing-points` | 创建投加点（自动创建 14 个物理采集点 + 2 个虚拟采集点标签） | `{ "name": "PAC1", "code": "PAC1", "process_line_id": 1, ... }` | 新创建的投加点对象 |
| PUT | `/api/dosing-points/{point_id}` | 更新投加点（自动触发重算） | 请求体：需要更新的字段 | 更新后的投加点对象 |
| DELETE | `/api/dosing-points/{point_id}` | 删除投加点 | — | 操作结果 |
| GET | `/api/dosing-points/{point_id}/config` | 获取投加点完整配置 | — | `{ "dosing_point": {...}, "process_parameter_group": {...}, "tags": [...], "latest_data": {...} }` |

**虚拟采集点标签**（创建投加点时自动生成）：
- `PREDICT_TP`（tag_type: `PREDICT_TP`）：预测出水 TP，推荐计算后写入
- `RECOMMEND_PAC`（tag_type: `RECOMMEND_PAC`）：推荐 PAC 加药流量，推荐计算后写入

---

## 9. plc — PLC 设备

| 方法 | 路径 | 说明 | 查询参数 / 请求体 | 返回值 |
|------|------|------|-------------------|--------|
| GET | `/api/plc` | PLC 设备列表（含事件日志摘要） | — | `{ "devices": [...], "events": [...] }` |
| POST | `/api/plc/devices` | 创建 PLC 设备 | `{ "name": "...", "protocol": "s7_1500"/"modbus_tcp", "ip_address": "192.168.1.10", "port": 102/502, "rack": 0, "slot": 0, "timeout_ms": 5000, "byte_order": "ABCD", "unit_id": 1 }` | 新创建的 PLC 设备对象 |
| PUT | `/api/plc/devices/{device_id}` | 更新 PLC 设备 | 请求体：需要更新的字段 | 更新后的 PLC 设备对象 |
| DELETE | `/api/plc/devices/{device_id}` | 删除 PLC 设备 | — | 操作结果 |
| POST | `/api/plc/devices/{device_id}/connect` | 连接 PLC 设备 | — | 连接结果 |
| POST | `/api/plc/devices/{device_id}/disconnect` | 断开 PLC 设备 | — | 断开结果 |

**支持协议**：
- `s7_1500`：python-snap7，地址格式 `M1.0`、`DB2.1186.0`、`I0.0`、`Q4.0`
- `modbus_tcp`：pymodbus，地址格式 `40001`/`30001` 或 `H1000`/`I1000`/`C1000`/`D1000`

---

## 10. collection — 数据采集与历史

| 方法 | 路径 | 说明 | 查询参数 / 请求体 | 返回值 |
|------|------|------|-------------------|--------|
| GET | `/api/samples/latest` | 最新采样数据（所有标签的实时值） | — | 标签最新值数组（从 `sensor_tags.last_value_text` 读取） |
| GET | `/api/collection` | 采集概览 | `scope`（`public`/`point`）或 `dosing_point_id` | 采集概览对象（含标签列表、最近采集时间、数据质量等） |
| POST | `/api/collection/public/tags` | 添加公共采集标签 | `{ "tag_code": "...", "tag_type": "...", "name": "...", "data_type": "REAL", "data_address": "DB2.1186.0", "plc_device_id": 1, ... }` | 新创建的标签对象 |
| POST | `/api/collection/points/{point_id}/tags` | 为指定投加点添加采集标签 | 同上 | 新创建的标签对象 |
| PUT | `/api/collection/tags/{tag_id}` | 更新采集标签 | 请求体：需要更新的字段 | 更新后的标签对象 |
| DELETE | `/api/collection/tags/{tag_id}` | 删除采集标签 | — | 操作结果 |
| POST | `/api/collection/poll` | 手动触发所有到期标签的采集轮询 | — | 轮询结果（含成功/失败数） |
| GET | `/api/samples/history` | 采样历史数据 | `dosing_point_id`、`start`、`end`、`limit` | 采样历史数组 |
| GET | `/api/history-data` | 历史数据查询 | `tag_ids`(逗号分隔)、`start`、`end` | 历史数据数组（按标签和时间索引） |
| POST | `/api/history-data/purge` | 清理历史数据 | `{ "tag_ids": [1,2,3], "days": 30 }` | `{ "ok": true, "deleted": N }` |

**采集标签关键字段**：
- `tag_code`：全局唯一编码
- `tag_type`：`Q`/`TP_BEFORE`/`TP_OUT`/`PH`/`PAC_ACTUAL`/`BIO_ORP1~4`/`BIO_MLSS1~2`/`REFLUX_Q1~2`/`PREDICT_TP`(虚拟)/`RECOMMEND_PAC`(虚拟)
- `data_type`：`REAL`/`BOOL`/`INT`/`DINT`/`UINT`
- `poll_interval_seconds`：轮询间隔（默认 5 秒）
- `history_interval_minutes`：历史记录间隔（默认 5 分钟）
- `last_quality`：`good`/`bad`/`unknown`

---

## 11. ingest — 数据导入

| 方法 | 路径 | 说明 | 查询参数 / 请求体 | 返回值 |
|------|------|------|-------------------|--------|
| GET | `/api/data-sources` | 数据源列表 | — | `{ "sources": [{"id": 1, "name": "...", "source_type": "...", "status": "idle/running", ...}] }` |
| POST | `/api/ingest/samples` | 批量导入采样数据 | `{ "source_name": "外部采集 API", "recalculate": true, "samples": [{ "tag_code": "PAC1_Q", "value": 1235, "sample_time": "2026-06-25T10:00:00", "quality": "good", "source": "s7comm" }, ...] }` | `{ "ok": true, "written": N, "samples_count": N, "recalculated": true }` |
| POST | `/api/import/csv` | 导入 CSV 文本数据 | `{ "csv_text": "tag_code,value,sample_time,quality,source\n...", "source": "csv_import", "recalculate": true }` | `{ "ok": true, "written": N }` |
| POST | `/api/collector/demo-poll` | 演示轮询（生成正弦波动的模拟数据） | — | 模拟数据写入结果 |

**`samples` 每项字段**：
- `tag_code`（必填）：对应 `sensor_tags.tag_code`
- `value`（必填）：数值
- `sample_time`（可选，默认当前时间）：ISO 时间字符串
- `quality`（可选，默认 `good`）：`good`/`bad`/`unknown`
- `source`（可选，默认 `api`）：数据来源标记
- `unit`（可选，不填则用标签默认单位）

---

## 12. trends — 趋势分析

| 方法 | 路径 | 说明 | 查询参数 / 请求体 | 返回值 |
|------|------|------|-------------------|--------|
| GET | `/api/trends` | 获取指定投加点和时间范围的趋势序列 | `dosing_point_id`(int, 必填)、`hours`(int, 默认 3) | 按系列名分组的趋势数据对象：`{ "Q": [{ "time": "...", "value": 1234 }], "TP_OUT": [...], "PREDICT_TP": [...], "PAC_ACTUAL": [...], "RECOMMEND_PAC": [...], "PAC_SUGGEST": [...], "TP_BEFORE": [...], "PH": [...], "ORP": [...], "MLSS": [...] }` |
| GET | `/api/savings` | 节省加药流量统计 | `dosing_point_id`(int, 必填)、`start`(ISO 时间字符串)、`end`(ISO 时间字符串) | `{ "total_savings": 123.45 (L), "points": [{ "time": "...", "value": -2.5 }, ...] }`，其中 `value = 实际流量 - 推荐流量` |

**趋势数据说明**：
- `PREDICT_TP` 和 `RECOMMEND_PAC` 来自虚拟采集点（推荐计算时写入 `sensor_samples`）
- `PAC_SUGGEST` 来自 `recommendations` 表
- 普通过程变量来自 `sensor_samples` 表
- `value` 为负值时，在节省图中表示节省（实际流量 < 推荐流量）

---

## 路由统计

| 模块 | 路由数 | 说明 |
|------|--------|------|
| health | 2 | `/api/health` + `/api/backend/status` |
| auth | 4 | login / me / logout / password |
| alarms | 3 | 列表 / 单条确认 / 全部确认 |
| process_groups | 5 | 工艺线 / 参数组 CRUD |
| settings | 5 | 设置 GET/PUT + network + backup + export |
| models | 16 | CRUD + 样本操作(record/recording/import/export) + 训练/部署 + 特征下载 + artifact |
| dashboard | 1 | `/api/dashboard` |
| dosing_points | 5 | CRUD + config |
| plc | 6 | 列表 + 设备 CRUD + 连接/断开 |
| collection | 10 | 采集概览 + 标签 CRUD + 轮询 + 历史查询/清理 |
| ingest | 4 | 数据源列表 + 批量导入 + CSV导入 + 演示轮询 |
| trends | 2 | 趋势 + 节省统计 |
| **合计** | **63** | |

> 注：`GET /api/settings` 和 `GET /api/settings/network` 为独立端点，`PUT /api/settings/{key}` 为通配路由。