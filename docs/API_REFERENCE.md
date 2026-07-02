# AI PAC 智能除磷加药系统 — API 参考

> 全部路由前缀为 `/api`，以下表格中路径均省略该前缀。
> 服务器默认监听地址与端口见系统设置中的 `network` 模块。

---

## 目录

1. [health — 健康检查](#1-health--健康检查)
2. [alarms — 告警](#2-alarms--告警)
3. [process_groups — 工艺线与参数组](#3-process_groups--工艺线与参数组)
4. [settings — 系统设置](#4-settings--系统设置)
5. [models — 模型管理](#5-models--模型管理)
6. [dashboard — 仪表盘](#6-dashboard--仪表盘)
7. [dosing_points — 投加点](#7-dosing_points--投加点)
8. [plc — PLC 设备](#8-plc--plc-设备)
9. [collection — 数据采集与历史](#9-collection--数据采集与历史)
10. [ingest — 数据导入](#10-ingest--数据导入)
11. [trends — 趋势分析](#11-trends--趋势分析)

---

## 1. health — 健康检查

| 方法 | 路径 | 说明 | 查询参数 / 请求体 | 返回值 |
|------|------|------|-------------------|--------|
| GET | `/api/health` | 健康检查 | — | `{ "status": "ok" }` |
| GET | `/api/backend/status` | 后端状态（数据库路径、表记录数、数据源状态、最新样本） | — | 包含 `db_path`、`table_counts`、`data_source_status`、`latest_sample` 等字段的状态对象 |

---

## 2. alarms — 告警

| 方法 | 路径 | 说明 | 查询参数 / 请求体 | 返回值 |
|------|------|------|-------------------|--------|
| GET | `/api/alarms` | 告警列表 | `status`（默认 `active`）、`severity`、`limit`（默认 `20`） | 告警数组，每条含 `alarm_id`、`severity`、`message`、`status`、`timestamp` 等 |
| POST | `/api/alarms/{alarm_id}/ack` | 确认单条告警 | — | 已确认的告警对象 |
| POST | `/api/alarms/ack-all` | 确认全部告警 | — | 操作结果 |

---

## 3. process_groups — 工艺线与参数组

| 方法 | 路径 | 说明 | 查询参数 / 请求体 | 返回值 |
|------|------|------|-------------------|--------|
| GET | `/api/process-lines` | 工艺线列表 | — | 工艺线数组，每条含 `id`、`name` 等 |
| GET | `/api/process-parameter-groups` | 工艺参数组列表 | — | 参数组数组 |
| POST | `/api/process-parameter-groups` | 创建工艺参数组 | 请求体：参数组定义（名称、关联工艺线、参数列表等） | 新创建的参数组对象 |
| PUT | `/api/process-parameter-groups/{group_id}` | 更新工艺参数组 | 请求体：需要更新的字段 | 更新后的参数组对象 |
| DELETE | `/api/process-parameter-groups/{group_id}` | 删除工艺参数组 | — | 操作结果（删除成功/未找到） |

---

## 4. settings — 系统设置

| 方法 | 路径 | 说明 | 查询参数 / 请求体 | 返回值 |
|------|------|------|-------------------|--------|
| GET | `/api/settings` | 获取全部设置 | — | 键值对对象，包含所有系统配置项 |
| GET | `/api/settings/network` | 获取网络设置 | — | 包含 `listen_address`、`port`、`local_ipv4`（本机 IPv4 列表） |
| PUT | `/api/settings/{key}` | 更新单个设置项 | 请求体：`{ "value": ... }` | 更新后的设置项 |
| POST | `/api/backup` | 触发数据库备份，备份到 `backup/` 目录 | — | 操作结果（备份文件路径等） |
| GET | `/api/export/recommendations.csv` | 导出建议记录为 CSV | — | CSV 文件（Content-Type: `text/csv`） |

---

## 5. models — 模型管理

| 方法 | 路径 | 说明 | 查询参数 / 请求体 | 返回值 |
|------|------|------|-------------------|--------|
| GET | `/api/models` | 模型列表 | — | 模型数组，每条含 `model_id`、`name`、`model_kind`、`status` 等 |
| POST | `/api/models` | 创建模型 | 请求体：`name`、`model_kind`（`tp_out_response` / `pac_flow_predict`）、`dosing_point_id` | 新创建的模型对象 |
| GET | `/api/models/{model_id}` | 获取模型详情 | — | 模型详情，含 `training_config`、`metrics`、`artifact` 等完整信息 |
| PUT | `/api/models/{model_id}` | 更新模型 | 请求体：需要更新的字段 | 更新后的模型对象 |
| DELETE | `/api/models/{model_id}` | 删除模型 | — | 操作结果 |
| DELETE | `/api/models/{model_id}/samples/{sample_id}` | 删除单条训练样本 | — | 操作结果 |
| POST | `/api/models/{model_id}/samples/bulk-delete` | 批量删除训练样本 | 请求体：`sample_ids` 数组 | 操作结果（含删除计数） |
| DELETE | `/api/models/{model_id}/samples` | 清空训练样本 | — | 操作结果 |
| POST | `/api/models/{model_id}/samples/import` | 导入 CSV 训练样本 | 请求体：`Content-Type: multipart/form-data`，包含 CSV 文件 | 导入结果（成功/失败条数） |
| GET | `/api/models/{model_id}/samples.csv` | 导出训练样本为 CSV | — | CSV 文件（Content-Type: `text/csv`） |
| POST | `/api/models/{model_id}/train` | 训练模型 | — | 训练任务结果（含训练状态、metrics 等） |
| POST | `/api/models/{model_id}/deploy` | 部署模型 | — | 部署结果（含部署状态） |
| GET | `/api/models/{model_id}/artifact` | 下载模型文件 | — | 模型文件（二进制流） |

---

## 6. dashboard — 仪表盘

| 方法 | 路径 | 说明 | 查询参数 / 请求体 | 返回值 |
|------|------|------|-------------------|--------|
| GET | `/api/dashboard` | 仪表盘数据聚合 | — | 包含 `recommendations`、`alarms`、`plc`、`training_models`、`data_quality`、`server_time` 的聚合对象 |

---

## 7. dosing_points — 投加点

| 方法 | 路径 | 说明 | 查询参数 / 请求体 | 返回值 |
|------|------|------|-------------------|--------|
| GET | `/api/dosing-points` | 投加点列表 | — | 投加点数组，每条含 `point_id`、`name`、`description` 等 |
| POST | `/api/dosing-points` | 创建投加点 | 请求体：`name`、`description` 等投加点定义 | 新创建的投加点对象 |
| PUT | `/api/dosing-points/{point_id}` | 更新投加点 | 请求体：需要更新的字段 | 更新后的投加点对象 |
| DELETE | `/api/dosing-points/{point_id}` | 删除投加点 | — | 操作结果 |
| GET | `/api/dosing-points/{point_id}/config` | 获取投加点配置（含工艺参数） | — | 配置对象，含关联的工艺参数列表 |

---

## 8. plc — PLC 设备

| 方法 | 路径 | 说明 | 查询参数 / 请求体 | 返回值 |
|------|------|------|-------------------|--------|
| GET | `/api/plc` | PLC 设备列表 | — | PLC 设备数组，每条含 `device_id`、`name`、`connection_status` 等 |
| POST | `/api/plc/devices` | 创建 PLC 设备 | 请求体：`name`、`protocol`、`host`、`port` 等连接参数 | 新创建的 PLC 设备对象 |
| PUT | `/api/plc/devices/{device_id}` | 更新 PLC 设备 | 请求体：需要更新的字段 | 更新后的 PLC 设备对象 |
| DELETE | `/api/plc/devices/{device_id}` | 删除 PLC 设备 | — | 操作结果 |
| POST | `/api/plc/devices/{device_id}/connect` | 连接 PLC 设备 | — | 连接结果（含连接状态） |
| POST | `/api/plc/devices/{device_id}/disconnect` | 断开 PLC 设备 | — | 断开结果（含连接状态） |

---

## 9. collection — 数据采集与历史

| 方法 | 路径 | 说明 | 查询参数 / 请求体 | 返回值 |
|------|------|------|-------------------|--------|
| GET | `/api/samples/latest` | 最新采样数据 | — | 最新采样数据对象 |
| GET | `/api/collection` | 采集概览 | `scope`（默认 `public`）或 `dosing_point_id` | 采集概览对象（含标签列表、最近采集时间等） |
| POST | `/api/collection/public/tags` | 添加公共标签 | 请求体：`name`、`address`、`data_type` 等标签定义 | 新创建的标签对象 |
| POST | `/api/collection/points/{point_id}/tags` | 添加投加点标签 | 请求体：`name`、`address`、`data_type` 等标签定义 | 新创建的标签对象 |
| PUT | `/api/collection/tags/{tag_id}` | 更新标签 | 请求体：需要更新的字段 | 更新后的标签对象 |
| DELETE | `/api/collection/tags/{tag_id}` | 删除标签 | — | 操作结果 |
| POST | `/api/collection/poll` | 手动触发采集轮询 | — | 轮询结果（含采集到的数据点） |
| GET | `/api/samples/history` | 采样历史数据 | `dosing_point_id`、时间范围等查询参数 | 采样历史数组 |
| GET | `/api/history-data` | 历史数据查询 | `tag_ids`、`start`、`end` 等查询参数 | 历史数据数组（按标签和时间索引） |
| POST | `/api/history-data/purge` | 清理历史数据 | 请求体：`tag_ids`（数组）、`days`（默认 `30`） | 清理结果（含删除的记录数） |

---

## 10. ingest — 数据导入

| 方法 | 路径 | 说明 | 查询参数 / 请求体 | 返回值 |
|------|------|------|-------------------|--------|
| GET | `/api/data-sources` | 数据源列表 | — | 数据源数组，每条含 `id`、`name`、`type`、`status` 等 |
| POST | `/api/ingest/samples` | 导入采样数据 | 请求体：`source_name`、`recalculate`（布尔）、`samples`（数组，每条含时间戳与各参数值） | 导入结果（含成功/失败条数） |
| POST | `/api/import/csv` | 导入 CSV 数据 | 请求体：`Content-Type: multipart/form-data`，包含 CSV 文件 | 导入结果（含解析与写入计数） |
| POST | `/api/collector/demo-poll` | 演示轮询（生成模拟数据） | — | 轮询结果（含生成的模拟数据点） |

---

## 11. trends — 趋势分析

| 方法 | 路径 | 说明 | 查询参数 / 请求体 | 返回值 |
|------|------|------|-------------------|--------|
| GET | `/api/trends` | 趋势数据 | `dosing_point_id`（int）、`hours`（int，默认 `3`） | 趋势数据对象（含时间序列与各指标值） |
| GET | `/api/savings` | 节省加药流量统计 | `dosing_point_id`（int）、`start`（ISO 时间）、`end`（ISO 时间） | `{ "total_savings": float (L), "points": [{ "time": string, "value": float }] }`，其中 `value = 实际流量 - 推荐流量` |

---

## 路由统计

| 模块 | 路由数 |
|------|--------|
| health | 2 |
| alarms | 3 |
| process_groups | 5 |
| settings | 5 |
| models | 14 |
| dashboard | 1 |
| dosing_points | 5 |
| plc | 6 |
| collection | 10 |
| ingest | 4 |
| trends | 2 |
| **合计** | **57** |

> 注：上表中 `GET /api/settings` 同时出现在 settings 模块的通用设置和 network 子模块中，实际独立路由为 56 条，`GET /api/settings/network` 作为 `/api/settings/{key}` 的特例在代码中有独立端点实现，因此路由端点共 57 个（56 条独立路由逻辑）。
