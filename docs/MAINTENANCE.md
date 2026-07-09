# 维护文档

本文档面向日常开发、部署、回归测试和现场排障。

## 日常开发流程

1. 修改前先确认改动范围和现有接口。
2. 涉及接口时先记录接口路径、请求字段和返回字段。
3. 小步修改，避免同时混改后端、前端、数据库和文档。
4. 修改后运行验证命令。
5. 记录需要现场重点测试的页面或接口。

基础验证：

```powershell
python -m unittest -q
python -m compileall -q app tests
node --check static/app.js
Get-ChildItem static/js -Recurse -Filter *.js | ForEach-Object { node --check $_.FullName }
```

启动服务：

```powershell
python run_server.py
```

访问：

```text
http://<本机IP>:<系统配置端口>/
```

本机调试也可使用：

```text
http://127.0.0.1:<系统配置端口>/
```

## 发布前检查清单

### 基础功能
- [ ] `requirements.txt` 是否有变更；若有，必须说明新增依赖原因。
- [ ] API 路径、请求字段、返回字段是否保持兼容。
- [ ] 数据库结构是否保持兼容，`ensure_runtime_schema()` 是否仍能处理旧库。
- [ ] 前端核心页面是否能打开并刷新。
- [ ] 系统设置页是否显示外部访问地址。
- [ ] 工艺参数页单耗曲线是否可新增、删除、拖动和输入关键点。
- [ ] 新库首次启动后，投加点、工艺参数组、模型项目和 PLC 设备应为空；工艺配置、工艺参数、模型管理和 PLC 通讯页必须显示可操作的空状态。

### 模型管理
- [ ] 模型训练、CSV 导入、实时记录、样本删除、训练、下载、投用是否可用。
- [ ] 双任务模型训练后检查任务1/任务2的评估指标（RMSE、MAE、R²、MAPE）。
- [ ] 投用双任务模型后推荐模式是否为 `dual_task_ai`。
- [ ] 双任务模型推荐解释中是否包含 PAC 预测值和下次出水 TP 预测值。
- [ ] 旧单任务模型（`tp_out_response`、`pac_flow_predict`）是否仍能正常加载和推理（兼容性）。
- [ ] 虚拟采集点 `PREDICT_TP` 和 `RECOMMEND_PAC` 是否正常写入 `sensor_samples`。
- [ ] 趋势图中 `PREDICT_TP` 和 `RECOMMEND_PAC` 是否正常显示。
- [ ] 模型停止投用后是否回退到保守模式。

### 数据采集
- [ ] PLC 连接失败时是否有可读错误信息。
- [ ] `POST /api/backup` 是否能成功生成备份文件。
- [ ] `POST /api/collection/poll` 手动轮询是否正常。
- [ ] `POST /api/history-data/purge` 历史清理是否正常。
- [ ] 模拟数据生成（demo-poll）是否正常。

### 前端&权限
- [ ] 总览：推荐卡片、推荐解释、预测TP、报警、PLC摘要（含协议列）、模型摘要。
- [ ] 右上角：未登录时显示登录按钮，登录后显示用户名+角色标签+退出按钮。
- [ ] 登录弹窗：用户名/密码输入，错误提示，登录成功后自动刷新页面并恢复导航。
- [ ] 权限控制：访客模式下按钮隐藏、输入框禁用；普通用户可编辑但看不到工艺配置和模型管理；管理员无限制。
- [ ] 刷新保持登录：登录后刷新浏览器，右上角仍显示已登录用户。
- [ ] 总览趋势：出水TP趋势、加药流量趋势、节省加药流量三个面板大小一致、时间切换按钮在右上角。
- [ ] 总览节省加药流量：时间范围选择器（datetime-local）、累计节省值显示、差值曲线含零线、正负值颜色区分。
- [ ] 工艺配置：投加点新增、编辑、删除，投加点卡片名称/编码/启用状态布局，采集来源绑定（仅管理员可见）。
- [ ] 工艺参数：参数组新增、编辑、删除，目标TP、上下限、PAC密度、计算周期、TP预测系数、PAC流量系数，单耗曲线编辑器。
- [ ] 历史数据：采集点选择、曲线、表格、历史清理。
- [ ] 模型管理：新建模型、参数配置、参数分组折叠/展开、metric多选、tooltip显示、实时记录、CSV导入、训练、投用、停用、下载模型文件（仅管理员可见）。
- [ ] PLC通讯：新增设备、编辑设备、连接、断开、事件记录，设备列表显示名称/协议/IP/状态四列。
- [ ] 报警事件：单条确认、全部确认。
- [ ] 系统设置：访问地址展示、设置保存、数据库备份、密码修改（旧密码验证+新密码确认）。

## 重点页面回归

- **总览**：推荐卡片、推荐解释、预测TP、报警、PLC摘要（含协议列）、模型摘要。
- **总览趋势**：出水TP趋势、加药流量趋势、节省加药流量三个面板大小一致、时间切换按钮在右上角。
- **总览节省加药流量**：时间范围选择器（datetime-local）、累计节省值显示、差值曲线含零线、正负值颜色区分。
- **右上角**：未登录时显示登录按钮，登录后显示用户名+角色标签+退出按钮。
- **登录弹窗**：用户名/密码输入，错误提示，登录成功后自动刷新页面并恢复导航。
- **权限控制**：访客模式下按钮隐藏、输入框禁用；普通用户可编辑但看不到工艺配置和模型管理；管理员无限制。
- **刷新保持登录**：登录后刷新浏览器，右上角仍显示已登录用户。
- **工艺配置**：投加点新增、编辑、删除，投加点卡片名称/编码/启用状态布局，采集来源绑定（仅管理员可见）。
- **工艺参数**：参数组新增、编辑、删除，目标TP、上下限、PAC密度、计算周期、单耗曲线编辑器、TP预测系数、PAC流量系数。
- **历史数据**：采集点选择、曲线、表格、历史清理。
- **模型管理**：新建模型、参数配置、参数分组折叠/展开、metric多选、tooltip显示、实时记录、CSV导入、训练、投用、停用、下载模型文件（仅管理员可见）。
- **PLC通讯**：新增设备、编辑设备、连接、断开、事件记录，设备列表显示名称/协议/IP/状态四列。
- **报警事件**：单条确认、全部确认。
- **系统设置**：访问地址展示、设置保存、数据库备份、密码修改（旧密码验证+新密码确认）。

## 常用运维接口

**认证**：
```text
POST /api/auth/login
GET  /api/auth/me
POST /api/auth/logout
PUT  /api/auth/password
```

**健康检查**：
```text
GET /api/health
```

**后端状态**：
```text
GET /api/backend/status
```

**系统访问地址**：
```text
GET /api/settings/network
```

**数据库备份**：
```text
POST /api/backup
```

**采集手动轮询**：
```text
POST /api/collection/poll
```

**历史清理**：
```text
POST /api/history-data/purge
```

**模型实时记录**：
```text
POST /api/models/{model_id}/samples/record
POST /api/models/{model_id}/recording/start
POST /api/models/{model_id}/recording/stop
```

**趋势数据**：
```text
GET /api/trends?dosing_point_id=1&hours=3
```

**节省加药流量**：
```text
GET /api/savings?dosing_point_id=1&start=2026-07-02T11:00:00&end=2026-07-02T14:00:00
```

## 外部访问排障

服务必须监听所有网卡。系统配置端口默认是 8000，可在系统设置页修改，修改后重启生效：

```powershell
python run_server.py
```

确认监听：

```powershell
Get-NetTCPConnection -LocalPort <系统配置端口> -State Listen
```

期望 `LocalAddress` 为 `0.0.0.0`。

查看本机 IPv4：

```powershell
Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254*' } |
  Select-Object IPAddress,InterfaceAlias,AddressState
```

若局域网设备仍无法访问：

1. 优先使用 WLAN/以太网地址，不要优先使用 VMware、虚拟网卡或隧道网卡地址。
2. 确认客户端和服务器在同一网段或路由可达。
3. 检查 Windows 防火墙是否放行系统配置的 TCP 端口。
4. 检查安全软件或网络策略是否阻断入站连接。
5. 在服务器本机打开 `http://127.0.0.1:<系统配置端口>/api/health` 确认服务本身正常。

## 数据库维护

默认数据库：

```text
data/ai_pac.sqlite
```

备份目录：

```text
backup/
```

注意事项：

- 生产或现场数据操作前先调用 `POST /api/backup`。
- 不要直接删除 `data/ai_pac.sqlite`，除非确认只需要重建空业务库。
- `data/ai_pac.db`、日志文件和旧数据库文件可能是历史遗留，处理前先确认运行配置实际使用的是 `DB_PATH`。
- SQLite WAL 运行时可能产生 `-wal` 和 `-shm` 文件，停止服务后再做文件级备份更稳妥。
- 启动迁移保持非破坏性：已停用旧表如 `pac_configs`、`control_configs`、`model_versions`、`model_shadow_results`、`plc_connections`、`plc_tag_mappings`、`plc_write_tests`、`simulation_runs` 会保留；只允许补列、回填等兼容动作。任何删表或清库必须先备份并由人确认。
- `ensure_runtime_schema()` 启动时会将 `status='recording'` 的模型恢复为正确的状态（`published` 或 `draft`），因为 recording 是运行时活动状态，不是模型生命周期状态。

## PLC 排障

检查顺序：

1. PLC 页面确认设备已启用。
2. 确认 IP、端口、Rack、Slot。
3. 确认现场 PLC 启用 PUT/GET（S7）或启用 Modbus TCP Server（Modbus）。
4. 确认网络能访问 PLC 的对应端口（S7: 102, Modbus: 502）。
5. 确认采集点地址格式（S7：`M1.0`、`DB2.1186.0`、`I0.0`、`Q4.0`；Modbus：`40001`、`H1000`）。
6. 确认数据类型为 `REAL`、`BOOL`、`INT`、`DINT` 或 `UINT`。
7. 确认字节序（Modbus：`ABCD` 大端 / `DCBA` 小端 / `BADC` / `CDAB`）。
8. 查看 PLC 事件表和页面错误信息。

常见现象：

- `python-snap7` 不可用：确认依赖安装和运行环境。
- 连接失败：优先查网络、PUT/GET、Rack/Slot。
- 读取失败：优先查地址、DB 块权限、数据类型、字节序。
- 数据质量超时：确认采集周期、历史存储周期和后台采集任务是否运行。
- Modbus 连接失败：确认 unit_id、端口和 TCP 连接。

## 模型维护

### 双任务模型（当前主流，`ai_pac_dual_task`）

训练流程：

1. 创建模型项目，选择模型类型为 `ai_pac_dual_task` 并关联投加点。
2. 在"模型参数配置"中分别配置任务1和任务2的 LightGBM 参数。
3. 配置数据切分比例（train_ratio/val_ratio）、HRT 模式（fixed_hrt/auto_detected）、采样间隔。
4. 手动记录实时样本、开启实时记录或导入 CSV 样本。
5. 检查样本数量（至少 40 条）、特征工程后每个任务至少 20 条。
6. 训练模型。
7. 检查任务1/任务2的评估指标（RMSE、MAE、R²、MAPE）。
8. 投用模型。
9. 观察总览推荐结果、预测 TP 和推荐解释。

注意事项：

- 少于 40 条原始样本无法训练。
- 特征工程后每个任务至少 20 条有效样本。
- 任务2使用更小的树（leaves=31, depth=6）和更强的正则化（l1=0.5, l2=2.0），因为 TP 变化量预测更困难。
- 采样间隔自动推断：通过 timestamp 中位数差推断，映射到最近的常见间隔（1/2/3/4/5/6/10/12/15/20/30/60 分钟），默认 5 分钟。
- CSV 导入支持 `utf-8-sig`、`utf-8`、`gb18030`、`gbk`，支持中英文列名自动映射。
- 投用同一投加点的新模型会将旧投用模型置为 `draft` 状态。
- 推理需至少 36 条历史数据（最近 72 小时），否则回退到保守模式。
- artifact 格式：`ai_pac_dual_task_v1` / `ai_pac_dual_task_v2`，存储在 `model_projects.artifact_json`。

### 旧单任务模型（DEPRECATED，保留兼容）

- `tp_out_response`：预测下一次出水 TP 检测数据；投用后只展示预测 TP。
- `pac_flow_predict`：预测实际加药流量；投用后进入正常模式。
- 推理时会将模型输入中的 `TP_OUT` 从当前出水 TP 临时替换为目标 TP（针对 `pac_flow_predict`）。
- 旧模型 artifact 格式：`ai_pac_tp_forecast_v1` / `ai_pac_tp_forecast_v2` / `ai_pac_tp_forecast_v3`。
- 新训练的模型只使用 `ai_pac_dual_task_v2` 格式。

### 推荐流程

```
1. 检查实时数据质量 → 异常 → 保留上次推荐 + 产生告警
2. 检查双任务 AI 模型 → 存在且历史数据≥36条 → 推理：
   └─ 任务1预测PAC加药量 × pac_flow_coefficient = raw
   └─ 任务2预测TP变化量 + 当前TP = 下次出水TP预测
   └─ mode = "dual_task_ai"
3. 回退保守模式 → 单耗曲线插值 × 流量 / 密度 = base
   └─ mode = "conservative"
4. 限幅 → clamp(raw, pac_min_l_h, pac_max_l_h)
5. 持久化 → recommendations表 + 虚拟采集点(PREDICT_TP, RECOMMEND_PAC)
```

### 反向优化（二分搜索）

`optimize_pac_for_target_tp_dual()` 基于任务2模型实现反向优化：给定目标 TP，在 [min, max] 区间二分搜索 20 次，找到最小 PAC 加药量。该函数当前已定义但未被主推荐流程直接调用，可作为实验性功能单独测试。

## 历史数据维护

历史数据主要在 `sensor_samples`。

清理策略：

- 使用页面或 `POST /api/history-data/purge` 清理。
- 不建议直接 SQL 删除，避免误删当前诊断所需样本。
- 清理前执行备份。

## 日志和审计

项目会写入：

- `logs/` 下的服务日志（包括 uvicorn 日志和 server 日志）。
- 数据库 `audit_logs` 表中的用户操作审计。
- 数据库 `plc_device_events` 表中的 PLC 连接事件。

排障时优先看：

1. 页面 toast 或接口返回错误。
2. `GET /api/backend/status`。
3. `plc_device_events`。
4. 服务日志（`logs/` 目录）。
5. `audit_logs`。

## 文件体量和拆分计划

当前仍需关注：

- `app/services/recommendation.py`：包含数据读取、模型推理、推荐计算、持久化和回放刷新，后续可按职责拆分（如 `recommendation_core.py`、`recommendation_persistence.py`）。
- `app/database.py`：包含 schema 和历史兼容逻辑，体量较大但拆分风险高（需谨慎处理迁移顺序）。
- `static/styles.css`：样式集中，后续若继续增长可按页面拆分。
- `app/services/wwtp_ai_engine.py`：包含四个类（DataImporter/FeatureEngineer/ModelTrainer/InferencePipeline），体量较大但各模块间耦合紧密，拆分需谨慎。

拆分原则：

- 每次只拆一个业务域。
- 拆分前后运行验证命令。
- 不改变接口和 DOM 行为。
- 不把文档修复、样式重构和模块拆分混在同一次变更里。
- 保留历史兼容逻辑，并在变更说明中标注。
- 拆分 `database.py` 时注意 `ensure_runtime_schema()` 中的函数调用顺序。

## 回滚建议

如果发布后出现问题：

1. 先停止服务。
2. 保留现场数据库和日志。
3. 使用最近的 `backup/` 数据库恢复。
4. 回退代码改动。
5. 运行基础验证。
6. 再启动服务。

如果只是前端异常，优先检查：

```powershell
node --check static/app.js
Get-ChildItem static/js -Recurse -Filter *.js | ForEach-Object { node --check $_.FullName }
```

如果只是后端无法启动，优先检查：

```powershell
python -m compileall -q app tests
python run_server.py
```

## 不确定风险记录

- PLC 真机通讯无法只靠本地测试完全覆盖，涉及现场网络和 PLC 配置。
- 数据库历史兼容逻辑只做必要补列和回填，不自动删除停用旧表；删除或移动前必须用旧库验证并确认备份可恢复。
- 前端当前为无构建多脚本结构，必须验证脚本加载顺序（`state.js` → `format.js` → `api.js` → `boot.js` → `start.js` + page 文件）。
- 局域网访问依赖现场防火墙、网段和路由策略。
- 双任务模型推理依赖历史数据质量（至少 36 条有效数据），如果 sensor_samples 数据不足或质量不佳，会回退到保守模式。
- 标签构建（任务2）的 HRT 参数在不同工艺场景下需要调整，auto_detected 模式依赖互相关分析，可能在某些场景下失效。
- 前端图表使用 Canvas 2D 手绘，在大量数据点（>5000）时可能出现性能问题，需要考虑数据降采样或分页。

## 性能考虑

- 前端的趋势图（Canvas 2D）在数据点超过 5000 时需考虑降采样。
- `GET /api/dashboard` 有 60 秒 TTL 缓存，避免频繁计算。
- `recalculate_all()` 内部按投加点有 `calculation_interval_seconds` 缓存，避免重复计算。
- 采集循环 1 秒轮询，但每个标签有独立的 `poll_interval_seconds`，避免频繁查询。
- 历史数据清理时建议分批执行，避免长时间锁表。