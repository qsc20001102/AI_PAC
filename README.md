# AI PAC 智能除磷加药平台

本项目是一个本地部署的 PAC 除磷智能加药系统。系统提供 FastAPI 后端、SQLite WAL 数据库、PAC 加药推荐、数据采集、历史趋势、报警、模型训练/投用、S7-1500 PLC 通讯配置和系统访问地址展示。

## 功能范围

- 投加点管理：维护投加点、工艺参数组、采集点来源和 PLC 关联。
- 工艺参数：维护目标 TP、出水 TP 上限、PAC 密度、加药流量上下限、计算周期和单耗配置曲线。
- 单耗曲线：在工艺参数页以折线曲线方式配置关键点，支持新增、删除、拖动和手动输入 X/Y。
- 推荐计算：保守模式按实时出水 TP 查单耗曲线并计算 PAC 加药流量；加药流量预测模型投用后进入正常模式。
- 模型管理：支持下次出水 TP 预测模型和加药流量预测模型，支持参数配置、实时记录训练样本、CSV 导入、训练、下载、投用和停用。
- 模型展示：出水 TP 预测模型投用后只展示预测 TP；加药流量预测模型投用后驱动投加点进入正常模式。
- 数据采集：支持 API/CSV 写入、手动轮询和 S7-1500 PLC 读取采集点。
- 历史数据：展示采集点历史曲线和表格，支持按天数清理。
- 报警事件：记录并确认数据质量、PLC 等报警。
- 系统设置：支持数据库备份、运行设置维护，并显示本机外部访问地址。

## 推荐与模型逻辑

### 保守模式

未投用加药流量预测模型时，推荐值按以下逻辑计算：

```text
参考流量 × 单耗曲线(实时出水TP) / PAC密度 / 1000
```

如果关键实时数据异常，系统会保留上一次推荐值并产生数据质量报警。若保守模式下实时出水 TP 高于上限，则直接输出最大加药流量。

### 下次出水 TP 预测模型

- 模型类型：`tp_out_response`
- 输入字段：参考流量、进水 TP、进水 PH、出水 TP、回流流量1、回流流量2、生化池 A 东 ORP1、生化池 A 东 ORP2、生化池 A 西 ORP1、生化池 A 西 ORP2、生化池 MLSS1、生化池 MLSS2。
- 输出字段：下一次出水 TP 检测数据。
- 投用效果：只在总览和推荐解释中展示预测 TP，不直接替代加药流量推荐。

### 加药流量预测模型

- 模型类型：`pac_flow_predict`
- 输入字段：与下次出水 TP 预测模型一致。
- 输出字段：实际加药流量。
- 投用效果：投加点进入正常模式，模型预测的加药流量作为推荐值，并按工艺参数中的最小/最大 L/h 限幅。
- 推理规则：推荐时会把模型输入中的 `TP_OUT` 从当前出水 TP 临时替换为工艺参数的目标 TP，用于估算目标 TP 对应的加药流量。

示例推荐解释：

```text
正常模式：投用加药流量预测模型，将模型输入中的出水TP由当前值 0.196 mg/L 替换为目标TP 0.15 mg/L，预测目标TP对应加药流量 20.28 L/h
```

## 模型训练参数

模型管理页支持配置：

- `target_column`
- `feature_columns`
- `prediction_step`，允许为 `0`，表示直接预测当前条数据
- `valid_ratio`
- `split_method`
- `objective`
- `learning_rate`
- `num_boost_round`
- `early_stopping_rounds`
- `num_leaves`
- `max_depth`
- `min_data_in_leaf`
- `lambda_l2`
- `feature_fraction`
- `bagging_fraction`
- `bagging_freq`
- `monotone_constraints`
- `sample_weight_rule`

参数项支持鼠标悬停查看建议默认值和调整建议。训练样本可手动记录，也可开启实时记录并设置记录周期。

CSV 样本导入支持 `utf-8-sig`、`utf-8`、`gb18030`、`gbk` 编码，时间格式支持：

- `2026/5/20  0:00:00`
- `2026/5/20 0:00`
- `2026/5/20`
- `2026-05-20 00:00:00`
- `2026-05-20T00:00:00`

## 技术栈

- 后端：FastAPI
- 数据库：SQLite，启用 WAL
- 模型：LightGBM
- PLC：python-snap7，S7comm/PUT-GET
- 前端：原生 HTML/CSS/JavaScript，无构建步骤

## 项目结构

```text
app/
  main.py                    # FastAPI 入口、生命周期、静态挂载和 router include
  api/
    common.py                # API 通用行转换工具
    health.py                # /api/health、/api/backend/status
    alarms.py                # /api/alarms*
    collection.py            # /api/collection*、历史数据
    dashboard.py             # /api/dashboard
    dosing_points.py         # /api/dosing-points*
    ingest.py                # /api/ingest*、/api/import/csv
    models.py                # /api/models*
    plc.py                   # /api/plc*
    process_groups.py        # /api/process-lines、工艺参数组
    settings.py              # /api/settings、/api/settings/network、/api/backup、导出
    trends.py                # /api/trends
  schemas/
    config.py                # 工艺参数组、设置请求模型
    dosing.py                # 投加点、采集、历史、导入请求模型
    model.py                 # 模型管理请求模型
    plc.py                   # PLC 请求模型
  database.py                # SQLite 连接、schema、运行期兼容和数据库工具
  services/
    audit.py                 # 审计日志写入
    collection_data.py       # 采集质量、采集写入、本地模拟样本刷新
    collection_runtime.py    # 采集轮询、采集点校验
    model_training.py        # 模型样本记录、实时记录、CSV 导入、训练
    recommendation.py        # 推荐计算核心逻辑
    plc.py                   # PLC 连接、地址解析和读值
    plc_devices.py           # PLC 设备运行态、设备列表和事件写入
    seed.py                  # 演示数据初始化
static/
  index.html                 # 单页应用入口
  app.js                     # 兼容性语法检查入口
  js/                        # 无构建前端脚本
  styles.css                 # 页面样式
tests/
  test_recommendation.py     # 推荐计算、采集、模型样本相关测试
data/
  ai_pac.sqlite              # 运行时数据库，首次启动自动创建
docs/
  CODING_STANDARDS.md        # 代码组织和拆分规范
  MAINTENANCE.md             # 运维、发布、排障和回归测试文档
```

## 快速启动

```powershell
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

访问：

```text
http://<本机IP>:8000/
```

也可以在本机使用：

```text
http://127.0.0.1:8000/
```

系统设置页会显示当前检测到的外部访问地址。若局域网设备无法访问，请检查 Windows 防火墙是否放行 TCP 8000 端口。

首次启动会自动创建 `data/ai_pac.sqlite`，初始化数据库 schema，并写入演示水厂、投加点、采集点、历史样本、报警和模型数据。

## 验证命令

```powershell
python -m unittest -q
python -m compileall -q app tests
node --check static/app.js
Get-ChildItem static/js -Recurse -Filter *.js | ForEach-Object { node --check $_.FullName }
```

如已安装 pytest，也可运行：

```powershell
python -m pytest -q
```

## 常用接口

### 健康检查

```text
GET /api/health
```

### 后端状态

```text
GET /api/backend/status
```

返回数据库路径、表记录数、数据源状态和最新样本。

### 仪表盘数据

```text
GET /api/dashboard
```

返回推荐结果、报警、PLC、模型和数据质量摘要。

### 系统访问地址

```text
GET /api/settings/network
```

返回监听地址、端口、本机 IPv4 地址列表和推荐启动命令。

### 外部采集写入

```powershell
$body = @{
  source_name = "外部采集 API"
  recalculate = $true
  samples = @(
    @{ tag_code = "PAC1_Q"; value = 1235; sample_time = "2026-06-25T10:00:00"; quality = "good"; source = "s7comm" },
    @{ tag_code = "PAC1_TP_OUT"; value = 0.18; sample_time = "2026-06-25T10:00:00"; quality = "good"; source = "s7comm" }
  )
} | ConvertTo-Json -Depth 4

Invoke-RestMethod -Method Post `
  -Uri http://<本机IP>:8000/api/ingest/samples `
  -Body $body `
  -ContentType "application/json"
```

### CSV 导入历史样本

```text
POST /api/import/csv

tag_code,value,sample_time,quality,source
PAC1_Q,1235,2026-06-25T10:00:00,good,s7comm
PAC1_TP_OUT,0.18,2026-06-25T10:00:00,good,s7comm
```

### 模型样本与训练

```text
POST /api/models/{model_id}/samples/record
POST /api/models/{model_id}/recording/start
POST /api/models/{model_id}/recording/stop
POST /api/models/{model_id}/samples/import
POST /api/models/{model_id}/train
POST /api/models/{model_id}/deploy
GET  /api/models/{model_id}/artifact
```

### 数据库备份

```text
POST /api/backup
```

备份文件会写入 `backup/`。

## PLC 使用说明

PLC 页面使用 `plc_devices` 和 `plc_device_events` 表保存设备配置和连接事件。

当前支持：

- 协议：`s7_1500`
- 默认端口：`102`
- 默认超时：`5000ms`
- 地址范围：`M`、`DB`、`I`、`Q`
- 数据类型：`REAL`、`BOOL`、`INT`

现场 PLC 侧需要启用 PUT/GET 通讯，并确保 DB 块访问方式、地址规划和采集点配置一致。当前系统只执行读取和模拟写入测试，不写泵启停、频率、手自动模式、联锁旁路或控制强制值。

## 数据和兼容说明

- `data/ai_pac.sqlite` 是本地运行数据库，不建议提交到版本库。
- `app.database.ensure_runtime_schema()` 包含历史库兼容和补列逻辑，不应随意删除。
- `forecast_horizon_minutes`、旧版 `dose_predict` 等历史字段/状态仍保留兼容，不代表当前业务入口仍使用这些概念。
- 若不需要内置演示刷新，可在系统设置中将 `demo_live_refresh` 改为 `false`。

## 代码规范和维护

- 分文件编写规范见 [docs/CODING_STANDARDS.md](docs/CODING_STANDARDS.md)。
- 日常维护、发布和排障见 [docs/MAINTENANCE.md](docs/MAINTENANCE.md)。
