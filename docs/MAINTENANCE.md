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

- `requirements.txt` 是否有变更；若有，必须说明新增依赖原因。
- API 路径、请求字段、返回字段是否保持兼容。
- 数据库结构是否保持兼容，`ensure_runtime_schema()` 是否仍能处理旧库。
- 前端核心页面是否能打开并刷新。
- 系统设置页是否显示外部访问地址。
- 工艺参数页单耗曲线是否可新增、删除、拖动和输入关键点。
- 新库首次启动后，投加点、工艺参数组、模型项目和 PLC 设备应为空；工艺配置、工艺参数、模型管理和 PLC 通讯页必须显示可操作的空状态。
- 模型训练、CSV 导入、实时记录、样本删除、训练、下载、投用是否可用。
- 投用 TP 模型后是否只显示预测 TP。
- 投用加药流量模型后投加点是否进入正常模式。
- 加药流量模型推荐解释中是否说明 `TP_OUT` 已由当前值替换为目标 TP。
- PLC 连接失败时是否有可读错误信息。
- `POST /api/backup` 是否能成功生成备份文件。

## 重点页面回归

- 总览：推荐卡片、推荐解释、预测 TP、报警、PLC 摘要（含协议列）、模型摘要。
- 总览趋势：出水TP趋势、加药流量趋势、节省加药流量三个面板大小一致、时间切换按钮在右上角。
- 总览节省加药流量：时间范围选择器（datetime-local）、累计节省值显示、差值曲线含零线、正负值颜色区分。
- 工艺配置：投加点新增、编辑、删除，投加点卡片名称/编码/启用状态布局，采集来源绑定。
- 工艺参数：参数组新增、编辑、删除，目标 TP、上下限、PAC 密度、计算周期，单耗曲线编辑器。
- 数据采集：公共采集点、投加点采集点、PLC 地址配置、手动轮询。
- 历史数据：采集点选择、曲线、表格、历史清理。
- 模型管理：新建模型、参数配置、参数分组折叠/展开、metric 多选、tooltip 显示、实时记录、CSV 导入、训练、投用、停用、下载模型文件。
- PLC 通讯：新增设备、编辑设备、连接、断开、事件记录，设备列表显示名称/协议/IP/状态四列。
- 报警事件：单条确认、全部确认。
- 系统设置：访问地址展示、设置保存、数据库备份。

## 常用运维接口

健康检查：

```text
GET /api/health
```

后端状态：

```text
GET /api/backend/status
```

系统访问地址：

```text
GET /api/settings/network
```

数据库备份：

```text
POST /api/backup
```

采集手动轮询：

```text
POST /api/collection/poll
```

历史清理：

```text
POST /api/history-data/purge
```

模型实时记录：

```text
POST /api/models/{model_id}/samples/record
POST /api/models/{model_id}/recording/start
POST /api/models/{model_id}/recording/stop
```

趋势数据：

```text
GET /api/trends?dosing_point_id=1&hours=3
```

节省加药流量：

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

## PLC 排障

检查顺序：

1. PLC 页面确认设备已启用。
2. 确认 IP、端口、Rack、Slot。
3. 确认现场 PLC 启用 PUT/GET。
4. 确认网络能访问 PLC 的 102 端口。
5. 确认采集点地址格式，如 `M1.0`、`DB2.1186.0`、`I0.0`、`Q4.0`。
6. 确认数据类型为 `REAL`、`BOOL` 或 `INT`。
7. 查看 PLC 事件表和页面错误信息。

常见现象：

- `python-snap7` 不可用：确认依赖安装和运行环境。
- 连接失败：优先查网络、PUT/GET、Rack/Slot。
- 读取失败：优先查地址、DB 块权限、数据类型。
- 数据质量超时：确认采集周期、历史存储周期和后台采集任务是否运行。

## 模型维护

模型训练依赖 `model_projects` 和 `model_training_samples`。

当前支持两类模型：

- `tp_out_response`：预测下一次出水 TP 检测数据；投用后只展示预测 TP。
- `pac_flow_predict`：预测实际加药流量；投用后进入正常模式。

推荐流程：

1. 创建模型项目并选择模型类型和投加点。
2. 在“模型参数配置”中确认输入字段、目标列、LightGBM 参数和单调约束。
3. 手动记录实时样本、开启实时记录或导入 CSV 样本。
4. 检查样本数量、输入字段和目标列。
5. 训练模型。
6. 检查 R2、MAE、样本数和有效特征数。
7. 投用模型。
8. 观察总览推荐结果、预测 TP 和推荐解释。

注意事项：

- 少于 2 条包含目标值的样本无法训练。
- CSV 导入支持 `utf-8-sig`、`utf-8`、`gb18030`、`gbk`。
- CSV 时间支持 `2026/5/20  0:00:00` 等斜杠格式。
- 投用同一投加点、同一模型类型的新模型会将旧投用模型置为 ready。
- TP 预测模型和加药流量预测模型是不同类型，可以分别投用。
- 加药流量模型推理时会用目标 TP 覆盖模型输入中的 `TP_OUT`。
- 若调整目标 TP 后推荐值不变，优先检查模型是否在该 TP 区间有分裂阈值；树模型可能在一个区间内输出同一个叶子值。
- 训练失败时不要先清空样本，应先检查字段映射、目标列、样本覆盖范围和训练参数。

## 历史数据维护

历史数据主要在 `sensor_samples`。

清理策略：

- 使用页面或 `POST /api/history-data/purge` 清理。
- 不建议直接 SQL 删除，避免误删当前诊断所需样本。
- 清理前执行备份。

## 日志和审计

项目会写入：

- `logs/` 下的服务日志。
- `data/server.stdout.log` 和 `data/server.stderr.log` 等本地运行日志。
- 数据库 `audit_logs` 表中的用户操作审计。
- 数据库 `plc_device_events` 表中的 PLC 连接事件。

排障时优先看：

1. 页面 toast 或接口返回错误。
2. `GET /api/backend/status`。
3. `plc_device_events`。
4. 服务日志。
5. `audit_logs`。

## 文件体量和拆分计划

当前仍需关注：

- `app/services/recommendation.py`：包含数据读取、模型推理、推荐计算、持久化和回放刷新，后续可按职责拆分。
- `app/database.py`：包含 schema 和历史兼容逻辑，体量较大但拆分风险高。
- `static/styles.css`：样式集中，后续若继续增长可按页面拆分。

拆分原则：

- 每次只拆一个业务域。
- 拆分前后运行验证命令。
- 不改变接口和 DOM 行为。
- 不把文档修复、样式重构和模块拆分混在同一次变更里。
- 保留历史兼容逻辑，并在变更说明中标注。

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
- 前端当前为无构建多脚本结构，必须验证脚本加载顺序。
- 局域网访问依赖现场防火墙、网段和路由策略。
